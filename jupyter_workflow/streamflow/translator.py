from __future__ import annotations

import ast
import codeop
import hashlib
import json
import os
import posixpath
import string
from collections import deque
from collections.abc import MutableMapping, MutableSequence
from typing import (
    Any,
    cast,
)

from streamflow.core import utils
from streamflow.core.config import BindingConfig
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import DeploymentConfig, LocalTarget, Target
from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.workflow import Port, Step, Token, Workflow
from streamflow.cwl.transformer import (
    CartesianProductSizeTransformer,
    DotProductSizeTransformer,
)
from streamflow.workflow.combinator import (
    CartesianProductCombinator,
    DotProductCombinator,
)
from streamflow.workflow.step import (
    Combinator,
    CombinatorStep,
    DefaultCommandOutputProcessor,
    DeployStep,
    ExecuteStep,
    GatherStep,
    ScatterStep,
    ScheduleStep,
)
from streamflow.workflow.token import TerminationToken

from jupyter_workflow.config.config import SplitType
from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.command import JupyterCommand, JupyterCommandToken
from jupyter_workflow.streamflow.port import ProgramContextPort
from jupyter_workflow.streamflow.processor import (
    JupyterFileCommandOutputProcessor,
    JupyterNameCommandOutputProcessor,
)
from jupyter_workflow.streamflow.step import (
    JupyterFileInputInjectorStep,
    JupyterNameInputInjectorStep,
    JupyterNotebookStep,
    JupyterTransferStep,
)
from jupyter_workflow.streamflow.transformer import (
    ListJoinTransformer,
    MakeListTransformer,
    OutputJoinTransformer,
)
from jupyter_workflow.streamflow.utils import get_deploy_step
from jupyter_workflow.streamflow.workflow import JupyterWorkflow


def _add_gather_step(
    cell_id: str, name: str, port: Port, depth: int, size_port: Port, workflow: Workflow
):
    gather_step = workflow.create_step(
        cls=GatherStep,
        name=posixpath.join(cell_id, name, "__gather__"),
        size_port=size_port,
        depth=depth,
    )
    gather_step.add_input_port(name, port)
    gather_step.add_output_port(name, workflow.create_port())
    return gather_step.get_output_port()


def _add_scatter_step(
    cell_id: str,
    name: str,
    port: Port,
    split: MutableMapping[str, int],
    workflow: Workflow,
):
    # Add split step
    split_step = workflow.create_step(
        cls=MakeListTransformer,
        name=posixpath.join(cell_id, name, "__split__"),
        split_type=SplitType[next(iter(split.keys()))],
        split_size=int(next(iter(split.values()))),
    )
    split_step.add_input_port(name, port)
    split_step.add_output_port(name, workflow.create_port())
    # Add scatter step
    scatter_step = workflow.create_step(
        cls=ScatterStep, name=posixpath.join(cell_id, name, "__scatter__")
    )
    scatter_step.add_input_port(name, split_step.get_output_port())
    scatter_step.add_output_port(name, workflow.create_port())
    return scatter_step.get_output_port()


def _build_dependencies(workflow: Workflow, in_step: Step) -> None:
    in_names = list(in_step.input_ports.keys())
    return_values = {
        s_name: list(s.output_ports.keys())
        for s_name, s in reversed(list(workflow.steps.items()))
    }
    for in_name in in_names:
        for out_step, out_names in return_values.items():
            if in_name in out_names:
                input_port = in_step.input_ports[in_name]
                output_port = workflow.steps[out_step].output_ports[in_name]
                input_port.dependee = output_port
                break


def _build_target(
    deployment_name: str, step_target: MutableMapping[str, Any]
) -> Target:
    target_model = step_target["deployment"]
    return Target(
        deployment=DeploymentConfig(
            name=deployment_name,
            type=target_model["type"],
            config=target_model["config"],
            external=target_model.get("external", False),
        ),
        locations=step_target.get("locations", 1),
        service=step_target.get("service"),
        workdir=step_target.get("workdir"),
    )


def _delete_size_chain(root_size_port: Port, workflow: Workflow):
    size_ports = deque([root_size_port])
    while size_ports:
        size_port = size_ports.popleft()
        for step in size_port.get_output_steps():
            if isinstance(
                step, (CartesianProductSizeTransformer, DotProductSizeTransformer)
            ):
                for inner_size_port in step.get_output_ports().values():
                    size_ports.append(inner_size_port)
                del workflow.steps[step.name]
        del workflow.ports[size_port.name]


def _extract_dependencies(
    cell_name: str,
    compiler: codeop.Compile,
    command_formatter: string.Formatter | None,
    ast_nodes: list[tuple[ast.AST, str]],
) -> MutableSequence[str]:
    visitor = DependenciesRetriever(
        cell_name=cell_name, compiler=compiler, command_formatter=command_formatter
    )
    for node, _ in ast_nodes:
        visitor.visit(node)
    return list(visitor.deps)


def _get_gather_steps(scatter_step: ScatterStep) -> MutableSequence[Step]:
    gather_steps = []
    ports = [scatter_step.get_size_port()]
    while ports:
        for step in ports.pop().get_output_steps():
            if isinstance(
                step, (CartesianProductSizeTransformer, DotProductSizeTransformer)
            ):
                ports.append(step.get_output_port())
            elif isinstance(step, GatherStep):
                gather_steps.append(step)
    return gather_steps


def _get_scatter_inputs(
    scatter_schema: MutableMapping[str, Any] | None,
) -> MutableMapping[str, Any]:
    scatter_inputs = {}
    if scatter_schema:
        for entry in scatter_schema.get("items") or []:
            if isinstance(entry, str):
                scatter_inputs[entry] = {"size": 1}
            else:
                if "items" in entry:
                    scatter_inputs.update(_get_scatter_inputs(entry))
                else:
                    scatter_inputs[entry["name"]] = {
                        k: v for k, v in entry.items() if k != "name"
                    }
    return scatter_inputs


def _process_scatter_entries(
    entries: MutableSequence[str | MutableMapping[str, Any]],
    combinator: Combinator,
    input_ports: MutableMapping[str, Port],
    scatter_method: str,
    workflow: Workflow,
) -> None:
    for entry in entries:
        if isinstance(entry, str):
            combinator.add_item(entry)
        else:
            if scatter_method == "dotproduct":
                inner_combinator = DotProductCombinator(
                    workflow=workflow, name=utils.random_name()
                )
            else:
                inner_combinator = CartesianProductCombinator(
                    workflow=workflow, name=utils.random_name()
                )
            _process_scatter_entries(
                entries=entry["items"],
                combinator=inner_combinator,
                input_ports=input_ports,
                scatter_method=scatter_method,
                workflow=workflow,
            )
            combinator.add_combinator(
                inner_combinator, inner_combinator.get_items(recursive=True)
            )


class NamesStack:
    def __init__(self):
        self.stack: list[set] = [set()]

    def add_scope(self):
        self.stack.append(set())

    def add_name(self, name: str):
        self.stack[-1].add(name)

    def delete_scope(self):
        self.stack.pop()

    def delete_name(self, name: str):
        self.stack[-1].remove(name)

    def __contains__(self, name: str) -> bool:
        for scope in self.stack:
            if name in scope:
                return True
        return False


class DependenciesRetriever(ast.NodeVisitor):
    def __init__(
        self,
        cell_name: str,
        compiler: codeop.Compile,
        command_formatter: string.Formatter | None = None,
    ):
        super().__init__()
        self.cell_name: str = cell_name
        self.compiler: codeop.Compile = compiler
        self.command_formatter: string.Formatter | None = command_formatter
        self.deps: set[str] = set()
        self.names: NamesStack = NamesStack()

    def _visit_fields(self, fields):
        for value in fields.values():
            if isinstance(value, list):
                for item in value:
                    if isinstance(item, ast.AST):
                        self.visit(item)
            elif isinstance(value, ast.AST):
                self.visit(value)

    def _visit_Comp(self, node):
        # Add local context
        self.names.add_scope()
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Visit the generators field
        for item in fields["generators"]:
            if isinstance(item, ast.AST):
                self.visit(item)
        del fields["generators"]
        # Visit the other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def _visit_FunctionDef(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add name to the context
        self.names.add_name(fields["name"])
        del fields["name"]
        # Add local context
        self.names.add_scope()
        # Visit arguments
        self.visit(fields["args"])
        del fields["args"]
        # Visit other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def visit_alias(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # If alias is defined add alias, otherwise, add name
        self.names.add_name(fields["asname"] or fields["name"])

    def visit_arg(self, node: ast.arg):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add arg to context
        self.names.add_name(fields["arg"])
        del fields["arg"]
        # Visit other fields
        self._visit_fields(fields)

    def visit_Assign(self, node) -> Any:
        self.visit(node.value)
        for t in node.targets:
            self.visit(t)

    def visit_AsyncFunctionDef(self, node):
        self._visit_FunctionDef(node)

    def visit_Call(self, node) -> Any:
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Check if is a call to `run_cell_magic`
        if (
            isinstance(fields["func"], ast.Attribute)
            and fields["func"].attr == "run_cell_magic"
        ):
            if self.command_formatter is None:
                raise WorkflowExecutionException(
                    "Attribute `command_formatter` attribute not defined.:"
                )
            for _, name, _, _ in self.command_formatter.parse(fields["args"][1].value):
                if name is not None:
                    self.deps.add(name)
        # Visit other fields
        self._visit_fields(fields)

    def visit_ClassDef(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add name to the context
        self.names.add_name(fields["name"])
        del fields["name"]
        # Add local context
        self.names.add_scope()
        # Visit other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def visit_DictComp(self, node):
        self._visit_Comp(node)

    def visit_ExceptHandler(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add name to the context
        if fields["name"] is not None:
            self.names.add_name(fields["name"])
        del fields["name"]
        # Add local context
        self.names.add_scope()
        # Visit other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def visit_FunctionDef(self, node):
        self._visit_FunctionDef(node)

    def visit_GeneratorExp(self, node):
        self._visit_Comp(node)

    def visit_ListComp(self, node):
        self._visit_Comp(node)

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.names:
            # Skip the 'get_ipython' dependency as it is not serialisable
            if node.id != "get_ipython":
                self.deps.add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.names.add_name(node.id)
        self.generic_visit(node)

    def visit_SetComp(self, node):
        self._visit_Comp(node)


class JupyterCell:
    __slots__ = ("name", "code", "compiler", "command_formatter", "metadata")

    def __init__(
        self,
        name: str,
        code: list[tuple[ast.AST, str]],
        compiler: codeop.Compile,
        command_formatter: string.Formatter | None,
        metadata: MutableMapping[str, Any] | None = None,
    ):
        self.name: str = name
        self.code: list[tuple[ast.AST, str]] = code
        self.compiler: codeop.Compile = compiler
        self.command_formatter: string.Formatter | None = command_formatter
        self.metadata: MutableMapping[str, Any] | None = metadata or {}


class JupyterNotebook:
    __slots__ = ("cells", "autoawait", "metadata")

    def __init__(
        self,
        cells: list[JupyterCell],
        autoawait: bool = False,
        metadata: MutableMapping[str, Any] | None = None,
    ):
        self.cells: list[JupyterCell] = cells
        self.autoawait: bool = autoawait
        self.metadata: MutableMapping[str, Any] | None = metadata or {}


class JupyterNotebookTranslator:
    def __init__(self, context: StreamFlowContext, output_directory: str | None = None):
        self.context: StreamFlowContext = context
        self.deployment_map: MutableMapping[str, DeployStep] = {}
        self.output_directory: str = (
            output_directory if output_directory is not None else os.getcwd()
        )
        self.output_ports: MutableMapping[str, Any] = {}

    def _get_source_port(self, name: str, workflow: Workflow) -> Port:
        return (
            self.output_ports[name]
            if name in self.output_ports
            else workflow.create_port()
        )

    def _inject_inputs(
        self, cell: JupyterCell, context_port: ProgramContextPort, workflow: Workflow
    ):
        step = workflow.steps[posixpath.join(cell.metadata["cell_id"], "__schedule__")]
        input_ports = {
            k: v for k, v in step.get_input_ports().items() if k != "__connector__"
        }
        # Retrieve cell input types
        cell_inputs = {
            (v["name"] if isinstance(v, MutableMapping) else v): (
                v
                if isinstance(v, MutableMapping)
                else {"name": v, "type": "name", "valueFrom": v}
            )
            for v in cell.metadata["step"].get("in", [])
        }
        # Automatically set `valueFrom` to `name` when missing
        for v in cell_inputs.values():
            if "valueFrom" not in v:
                v["valueFrom"] = v["name"]
        # Expand automatic inputs
        for input_name in input_ports:
            if input_name not in cell_inputs:
                cell_inputs[input_name] = {
                    "name": input_name,
                    "type": "name",
                    "valueFrom": input_name,
                }
        # Retrieve a local DeployStep
        target = LocalTarget()
        deploy_step = get_deploy_step(
            deployment_map=self.deployment_map, target=target, workflow=workflow
        )
        for port_name, port in input_ports.items():
            # Check if there is a scatter step and, if yes, inject input into its port
            if split_step := workflow.steps.get(
                posixpath.join(cell.metadata["cell_id"], port_name, "__split__")
            ):
                port = split_step.get_input_port(port_name) or port
            # Otherwise, check for a combinator step and, if yes, inject input into its port
            elif combinator_step := workflow.steps.get(
                posixpath.join(cell.metadata["cell_id"], "__combinator__")
            ):
                port = combinator_step.get_input_port(port_name) or port
            # If the port has at least an input step, skip it
            if port.get_input_steps():
                continue
            # Create a schedule step and connect it to the local DeployStep
            schedule_step = workflow.create_step(
                cls=ScheduleStep,
                name=posixpath.join(
                    cell.metadata["cell_id"], port_name + "-injector", "__schedule__"
                ),
                connector_ports={target.deployment.name: deploy_step.get_output_port()},
                input_directory=os.getcwd(),
                output_directory=os.getcwd(),
                tmp_directory=os.getcwd(),
                binding_config=BindingConfig(targets=[target]),
            )
            # Create an InputInjector step to process the input if needed
            injector_step = None
            if cell_inputs[port_name]["type"] == "name":
                injector_step = workflow.create_step(
                    cls=JupyterNameInputInjectorStep,
                    name=posixpath.join(
                        cell.metadata["cell_id"], port_name + "-injector"
                    ),
                    context_port=context_port,
                    job_port=schedule_step.get_output_port(),
                    value=cell_inputs[port_name].get("value"),
                    value_from=cell_inputs[port_name].get("valueFrom"),
                )
            elif cell_inputs[port_name]["type"] == "file":
                injector_step = workflow.create_step(
                    cls=JupyterFileInputInjectorStep,
                    name=posixpath.join(step.name, port_name + "-injector"),
                    context_port=context_port,
                    job_port=schedule_step.get_output_port(),
                    value=cell_inputs[port_name].get("value"),
                    value_from=cell_inputs[port_name].get("valueFrom"),
                )
            # If there is an injector step, create an input port and inject values
            if injector_step:
                input_port = workflow.create_port()
                input_port.put(Token(value=None))
                input_port.put(TerminationToken())
                # Connect input and output ports to the injector step
                injector_step.add_input_port(port_name, input_port)
                injector_step.add_output_port(port_name, port)
            # Otherwise, simply inject the value into the original port
            else:
                port.put(Token(value=None))
                port.put(TerminationToken())

    def _optimize_scatter(self, workflow: Workflow):
        # Collect split steps
        split_steps = {
            s for s in workflow.steps.values() if s.name.endswith("__split__")
        }
        # Collect parent join and gather steps
        gather_steps = []
        join_steps = []
        for split_step in split_steps:
            input_steps = split_step.get_input_port().get_input_steps()
            for input_step in input_steps:
                if input_step.name.endswith("__join__"):
                    join_steps.append(input_step)
                    gather_steps.append(
                        next(iter(input_step.get_input_port().get_input_steps()))
                    )
        # Collect child split and scatter steps
        scatter_steps = []
        split_steps = []
        is_removable = [True for _ in range(len(join_steps))]
        for i, join_step in enumerate(join_steps):
            output_steps = join_step.get_output_port().get_output_steps()
            for output_step in output_steps:
                if output_step.name.endswith("__split__"):
                    split_steps.append(output_step)
                    scatter_steps.append(
                        next(iter(output_step.get_output_port().get_output_steps()))
                    )
                else:
                    is_removable[i] = False
        # Remove redundant steps
        for i in range(len(scatter_steps)):
            input_port = gather_steps[i].get_input_port()
            output_port = scatter_steps[i].get_output_port()
            # Fix `size` port of the orphan `gather` steps
            upper_size_port = cast(GatherStep, gather_steps[i]).get_size_port()
            for gather_step in _get_gather_steps(cast(ScatterStep, scatter_steps[i])):
                gather_step.add_input_port("__size__", upper_size_port)
            # Relink steps
            for step in output_port.get_output_steps():
                for port_name, port in step.get_input_ports().items():
                    if port.name == output_port.name:
                        step.add_input_port(port_name, input_port)
            # Remove steps and ports
            if is_removable[i]:
                del workflow.ports[gather_steps[i].get_output_port().name]
                del workflow.steps[gather_steps[i].name]
                for port_name, port in list(self.output_ports.items()):
                    if port.name == join_steps[i].get_output_port().name:
                        del self.output_ports[port_name]
                        break
                del workflow.ports[join_steps[i].get_output_port().name]
                del workflow.steps[join_steps[i].name]
            del workflow.ports[split_steps[i].get_output_port().name]
            del workflow.steps[split_steps[i].name]
            del workflow.ports[scatter_steps[i].get_output_port().name]
            _delete_size_chain(
                cast(ScatterStep, scatter_steps[i]).get_size_port(), workflow
            )
            del workflow.steps[scatter_steps[i].name]

    async def _translate_jupyter_cell(
        self,
        workflow: Workflow,
        cell: JupyterCell,
        autoawait: bool,
        context_port: ProgramContextPort,
    ):
        # Create a JupyterNotebookStep to execute the cell on the local context
        step = workflow.create_step(
            cls=JupyterNotebookStep,
            name=cell.metadata["cell_id"],
            ast_nodes=cell.code,
            autoawait=autoawait,
            compiler=cell.compiler,
            context_port=context_port,
        )
        # Use any active output port as input
        for port_name, port in self.output_ports.items():
            # Propagate output to JupyterNotebookStep
            step.add_input_port(port_name, port)
        # Return the new context port
        return step.get_output_context_port()

    async def _translate_streamflow_cell(
        self,
        workflow: Workflow,
        cell: JupyterCell,
        metadata: MutableMapping[str, Any] | None,
        autoawait: bool = False,
    ) -> Step:
        cell_id = metadata["cell_id"]
        # Build execution target
        target = metadata.get("target")
        if target is not None:
            if isinstance(target["deployment"], str):
                target |= {"deployment": metadata["deployments"][target["deployment"]]}
            deployment_name = hashlib.new(
                name="md5",
                data=json.dumps(
                    obj=target["deployment"],
                    sort_keys=True,
                    ensure_ascii=True,
                    default=str,
                ).encode("ascii"),
                usedforsecurity=False,
            ).hexdigest()
            target = _build_target(deployment_name, target)
        else:
            target = LocalTarget()
        # Extract Python interpreter from metadata
        interpreter = metadata.get("interpreter", "ipython")
        # Create DeployStep to initialise the execution environment
        deploy_step = get_deploy_step(
            deployment_map=self.deployment_map, target=target, workflow=workflow
        )
        # Create a schedule step and connect it to the DeployStep
        schedule_step = workflow.create_step(
            cls=ScheduleStep,
            name=posixpath.join(cell_id, "__schedule__"),
            job_prefix=cell_id,
            connector_ports={target.deployment.name: deploy_step.get_output_port()},
            binding_config=BindingConfig(targets=[target]),
        )
        # Create the ExecuteStep and connect it to the ScheduleStep
        step = workflow.create_step(
            cls=ExecuteStep,
            name=cell_id,
            job_port=schedule_step.get_output_port(),
        )
        # Process cell inputs
        cell_inputs = metadata["step"].get("in", [])
        scatter_inputs = _get_scatter_inputs(metadata["step"].get("scatter"))
        scatter_method = metadata["step"].get("scatter", {}).get("method", "cartesian")
        file_inputs = cast(MutableMapping[str, Any], {})
        input_ports = cast(MutableMapping[str, Port], {})
        input_tokens = cast(MutableMapping[str, JupyterCommandToken], {})
        for element in cell_inputs:
            # If is a string, it refers to the name of a variable
            if isinstance(element, str):
                element = {"type": "name", "name": element}
            # Otherwise it must be a dictionary
            if isinstance(element, MutableMapping):
                # Create input port
                name = element.get("name") or element.get("valueFrom")
                input_ports[name] = self._get_source_port(name, workflow)
                # Add scatter step if needed
                if name in scatter_inputs:
                    input_ports[name] = _add_scatter_step(
                        cell_id=cell_id,
                        name=name,
                        port=input_ports[name],
                        split=scatter_inputs[name],
                        workflow=workflow,
                    )
                # Get serializer if present
                serializer = (
                    (
                        metadata["serializers"][element["serializer"]]
                        if isinstance(element["serializer"], str)
                        else element["serializer"]
                    )
                    if "serializer" in element
                    else None
                )
                # Process port type
                element_type = element["type"]
                # If type is equal to `file`, it refers to a file path in the local resource
                if element_type == "file":
                    file_inputs[name] = element
                # Add command token
                input_tokens[name] = JupyterCommandToken(
                    name=name, token_type=element_type, serializer=serializer
                )
        # Retrieve inputs automatically if necessary
        if metadata["step"].get("autoin", True):
            input_names = _extract_dependencies(
                cell_name=cell.name,
                compiler=cell.compiler,
                command_formatter=cell.command_formatter,
                ast_nodes=cell.code,
            )
            for name in input_names:
                if name not in input_ports:
                    input_ports[name] = self._get_source_port(name, workflow)
                    # Add scatter step if needed
                    if name in scatter_inputs:
                        input_ports[name] = _add_scatter_step(
                            cell_id=cell_id,
                            name=name,
                            port=input_ports[name],
                            split=scatter_inputs[name],
                            workflow=workflow,
                        )
                    # Add name output processor to the execute step
                    step.output_processors[name] = JupyterNameCommandOutputProcessor(
                        name=name, workflow=workflow, value_from=name
                    )
                    # Add command token
                    input_tokens[name] = JupyterCommandToken(  # nosec
                        name=name, token_type="name"
                    )
        # Add scatter combinator if present
        scatter_combinator = None
        scatter_size_transformer = None
        size_port = None
        if len(scatter_inputs) > 1:
            if scatter_method == "dotproduct":
                scatter_combinator = DotProductCombinator(
                    workflow=workflow, name=cell_id + "-scatter-combinator"
                )
                scatter_size_transformer = workflow.create_step(
                    cls=DotProductSizeTransformer,
                    name=cell_id + "-scatter-size-transformer",
                )
            else:
                scatter_combinator = CartesianProductCombinator(
                    workflow=workflow, name=cell_id + "-scatter-combinator"
                )
                scatter_size_transformer = workflow.create_step(
                    cls=CartesianProductSizeTransformer,
                    name=cell_id + "-scatter-size-transformer",
                )
            _process_scatter_entries(
                entries=metadata["step"]["scatter"]["items"],
                combinator=scatter_combinator,
                input_ports=input_ports,
                scatter_method=scatter_method,
                workflow=workflow,
            )
        # If there are both scatter and non-scatter inputs
        if len(scatter_inputs) < len(input_ports):
            dot_product_combinator = DotProductCombinator(
                workflow=workflow, name=cell_id + "-dot-product-combinator"
            )
            if scatter_combinator:
                dot_product_combinator.add_combinator(
                    scatter_combinator, scatter_combinator.get_items(recursive=True)
                )
            else:
                for name in scatter_inputs:
                    dot_product_combinator.add_item(name)
            for port_name in input_ports:
                if port_name not in scatter_inputs:
                    dot_product_combinator.add_item(port_name)
            scatter_combinator = dot_product_combinator
        # If a scatter combinator has been defined, create a combinator step and add all input ports to it
        if scatter_combinator:
            combinator_step = workflow.create_step(
                cls=CombinatorStep,
                name=posixpath.join(cell_id, "__combinator__"),
                combinator=scatter_combinator,
            )
            for port_name, port in input_ports.items():
                combinator_step.add_input_port(port_name, port)
                combinator_step.add_output_port(port_name, workflow.create_port())
                input_ports[port_name] = combinator_step.get_output_port(port_name)
            if scatter_size_transformer:
                for name in scatter_inputs:
                    scatter_size_transformer.add_input_port(
                        name,
                        cast(
                            ScatterStep,
                            workflow.steps[
                                posixpath.join(cell_id, name, "__scatter__")
                            ],
                        ).get_size_port(),
                    )
                size_port = workflow.create_port()
                scatter_size_transformer.add_output_port("__size__", size_port)
        # Scatter on a single input
        if len(scatter_inputs) == 1:
            size_port = cast(
                ScatterStep,
                workflow.steps[
                    posixpath.join(cell_id, next(iter(scatter_inputs)), "__scatter__")
                ],
            ).get_size_port()
        # Add input ports to the schedule step
        for port_name, port in input_ports.items():
            schedule_step.add_input_port(port_name, port)
        # Process file inputs to transfer them
        for name in file_inputs:
            # Add transfer step
            transfer_step = workflow.create_step(
                cls=JupyterTransferStep,
                name=posixpath.join(cell_id, name, "__transfer__"),
                job_port=schedule_step.get_output_port(),
            )
            transfer_step.add_input_port(name, input_ports[name])
            input_ports[name] = workflow.create_port()
            transfer_step.add_output_port(name, input_ports[name])
        # Add input ports to the execute step
        for port_name, port in input_ports.items():
            step.add_input_port(port_name, port)
        # If outputs are defined for the current cell
        output_tokens = {}
        if "out" in metadata["step"]:
            for element in metadata["step"]["out"]:
                # If is a string, it refers to the name of a variable
                if isinstance(element, str):
                    element = {"type": "name", "name": element}
                # Otherwise it must be a dictionary
                if isinstance(element, MutableMapping):
                    # Create port
                    name = cast(str, element.get("name") or element.get("valueFrom"))
                    self.output_ports[name] = workflow.create_port()
                    step.add_output_port(name, self.output_ports[name])
                    # Get serializer if present
                    serializer = (
                        (
                            metadata["serializers"][element["serializer"]]
                            if isinstance(element["serializer"], str)
                            else element["serializer"]
                        )
                        if "serializer" in element
                        else None
                    )
                    # Process port type
                    element_type = element["type"]
                    # If type is equal to `file`, it refers to a file path in the remote resource
                    if element_type == "file":
                        # Add file output processor to the execute step
                        step.output_processors[name] = (
                            JupyterFileCommandOutputProcessor(
                                name=name,
                                workflow=workflow,
                                value=element.get("value"),
                                value_from=element.get("valueFrom"),
                            )
                        )
                    # If type is equal to `name` or `env`, it refers to a variable
                    elif element_type in ["name", "env"]:
                        # Add name output processor to the execute step
                        step.output_processors[name] = (
                            JupyterNameCommandOutputProcessor(
                                name=name,
                                workflow=workflow,
                                value=element.get("value"),
                                value_from=element.get("valueFrom", name),
                            )
                        )
                    # If type is equal to `control`, simply add an empty dependency
                    elif element_type == "control":
                        # Add default output processor to the execute step
                        step.output_processors[name] = DefaultCommandOutputProcessor(
                            name=name, workflow=workflow
                        )
                    # Add command token
                    output_tokens[name] = JupyterCommandToken(
                        name=name, token_type=element_type, serializer=serializer
                    )
                    # Add gather step if present
                    if scatter_inputs:
                        # Add gather step
                        self.output_ports[name] = _add_gather_step(
                            cell_id=cell_id,
                            name=name,
                            port=self.output_ports[name],
                            depth=(
                                len(scatter_inputs)
                                if scatter_method == "cartesian"
                                else 1
                            ),
                            size_port=size_port,
                            workflow=workflow,
                        )
                        # Add list join transformer
                        transformer_step = workflow.create_step(
                            cls=ListJoinTransformer,
                            name=posixpath.join(cell_id, name, "__join__"),
                        )
                        transformer_step.add_input_port(name, self.output_ports[name])
                        transformer_step.add_output_port(name, workflow.create_port())
                        self.output_ports[name] = transformer_step.get_output_port()
        # Add output log ports
        output_log_port = workflow.create_port()
        step.add_output_port(executor.CELL_OUTPUT, output_log_port)
        if "Out" not in step.output_ports:
            ipython_out_port = workflow.create_port()
            step.add_output_port(
                name="Out",
                port=ipython_out_port,
                output_processor=JupyterNameCommandOutputProcessor(
                    name="Out", workflow=workflow, value_from="Out"
                ),
            )
        else:
            ipython_out_port = step.get_output_port("Out")
        log_ports = cast(
            MutableMapping[str, Port],
            {executor.CELL_OUTPUT: output_log_port, "Out": ipython_out_port},
        )
        if scatter_inputs:
            for log_port_name in log_ports:
                # Add gather step
                gather_output_port = _add_gather_step(
                    cell_id=cell_id,
                    name=log_port_name,
                    port=step.get_output_port(log_port_name),
                    depth=len(scatter_inputs) if scatter_method == "cartesian" else 1,
                    size_port=size_port,
                    workflow=workflow,
                )
                # Add string join transformer
                transformer_step = workflow.create_step(
                    cls=OutputJoinTransformer,
                    name=posixpath.join(cell_id, log_port_name, "__join__"),
                )
                transformer_step.add_input_port(log_port_name, gather_output_port)
                transformer_step.add_output_port(log_port_name, workflow.create_port())
                log_ports[log_port_name] = transformer_step.get_output_port()
        output_log_name = posixpath.join(step.name, executor.CELL_OUTPUT)
        workflow.output_ports[output_log_name] = log_ports[executor.CELL_OUTPUT].name
        ipython_out_name = posixpath.join(step.name, "Out")
        workflow.output_ports[ipython_out_name] = log_ports["Out"].name
        # Create the command to be executed remotely
        step.command = JupyterCommand(
            step=step,
            ast_nodes=cell.code,
            compiler=cell.compiler,
            interpreter=interpreter,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            autoawait=autoawait,
        )
        return step

    async def translate(
        self, notebook: JupyterNotebook, user_ns: MutableMapping[str, Any]
    ) -> Workflow:
        # Create workflow
        workflow = JupyterWorkflow(
            context=self.context, config={}, name=utils.random_name()
        )
        # Add program context port with initial program context
        context_port = workflow.create_port(cls=ProgramContextPort)
        context_port.put_context(user_ns)
        # Parse single cells independently to derive workflow steps
        for cell in notebook.cells:
            if "step" in cell.metadata:
                await self._translate_streamflow_cell(
                    workflow=workflow,
                    cell=cell,
                    metadata=notebook.metadata | cell.metadata,
                    autoawait=notebook.autoawait,
                )
                # Inject inputs from program context
                self._inject_inputs(
                    cell=cell, context_port=context_port, workflow=workflow
                )
            else:
                context_port = await self._translate_jupyter_cell(
                    workflow=workflow,
                    cell=cell,
                    autoawait=notebook.autoawait,
                    context_port=context_port,
                )
                # Reset output ports dictionary
                self.output_ports = {}
        # Apply rewrite rules
        self._optimize_scatter(workflow)
        # Set workflow outputs
        for port_name, port in self.output_ports.items():
            step_name = next(
                iter(next(iter(s.name for s in port.get_input_steps())).split("/"))
            )
            workflow.output_ports[posixpath.join(step_name, port_name)] = port.name
        # Return the final workflow object
        return workflow
