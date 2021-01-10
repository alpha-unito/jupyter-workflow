import ast
import asyncio
import hashlib
import json
from typing import MutableSequence, Text, Any, MutableMapping, Optional, Tuple, List

from IPython.core.compilerop import CachingCompiler
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import ModelConfig
from streamflow.core.workflow import Workflow, Target, Step, Status, TerminationToken, Job
from streamflow.workflow.combinator import DotProductInputCombinator
from streamflow.workflow.port import DefaultOutputPort, DefaultInputPort
from streamflow.workflow.step import BaseStep, BaseJob

from jupyter_workflow.streamflow.command import JupyterCommand, JupyterCommandOutput
from jupyter_workflow.streamflow.token_processor import FileTokenProcessor


async def _build_file_port(name: Text,
                           step: Step,
                           element: MutableMapping[Text, Text]):
    port_name = name or utils.random_name()
    port = DefaultInputPort(name=port_name)
    port.step = step
    port.token_processor = FileTokenProcessor(
        port=port,
        name=name,
        value=element.get('value'),
        valueFrom=element.get('valueFrom'))
    return port


def _build_target(model_name: Text, step_target: MutableMapping[Text, Any]) -> Target:
    target_model = step_target['model']
    return Target(
        model=ModelConfig(
            name=model_name,
            connector_type=target_model['type'],
            config=target_model['config'],
            external=target_model.get('external', False)
        ),
        resources=step_target.get('resources', 1),
        service=step_target.get('service')
    )


class DependenciesRetriever(ast.NodeVisitor):

    def __init__(self,
                 cell_name: Text,
                 compiler: CachingCompiler,
                 user_ns: MutableMapping[Text, Any],
                 user_global_ns: MutableMapping[Text, Any]):
        super().__init__()
        self.cell_name: Text = cell_name
        self.compiler: CachingCompiler = compiler
        self.deps: MutableSequence[Text] = []
        self.names: MutableSequence[Text] = []
        self.user_ns: MutableMapping[Text, Any] = user_ns
        self.user_global_ns: MutableMapping[Text, Any] = user_global_ns

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.names:
            # Skip the 'get_ipython' dependency as it is not serialisable
            if node.id != 'get_ipython' and (node.id in self.user_ns or node.id in self.user_global_ns):
                self.deps.append(node.id)
        self.names.append(node.id)
        self.generic_visit(node)


class JupyterCell(object):

    def __init__(self,
                 name: Text,
                 code: List[Tuple[ast.AST, Text]],
                 compiler: CachingCompiler,
                 metadata: Optional[MutableMapping[Text, Any]] = None):
        self.name: Text = name
        self.code: List[Tuple[ast.AST, Text]] = code
        self.compiler: CachingCompiler = compiler
        self.metadata: Optional[MutableMapping[Text, Any]] = metadata or {}


class JupyterNotebook(object):

    def __init__(self,
                 cells: List[JupyterCell],
                 autoawait: bool = False,
                 metadata: Optional[MutableMapping[Text, Any]] = None):
        self.cells: List[JupyterCell] = cells
        self.autoawait: bool = autoawait
        self.metadata: Optional[MutableMapping[Text, Any]] = metadata or {}


class JupyterNotebookTranslator(object):

    def __init__(self,
                 context: StreamFlowContext,
                 user_ns: MutableMapping[Text, Any],
                 user_global_ns: MutableMapping[Text, Any]):
        self.context: StreamFlowContext = context
        self.user_ns: MutableMapping[Text, Any] = user_ns
        self.user_global_ns: MutableMapping[Text, Any] = user_global_ns

    def _extract_dependencies(self,
                              cell_name: Text,
                              compiler,
                              ast_nodes: List[Tuple[ast.AST, Text]]) -> MutableSequence[Text]:
        visitor = DependenciesRetriever(cell_name, compiler, self.user_ns, self.user_global_ns)
        for node, _ in ast_nodes:
            visitor.visit(node)
        return visitor.deps

    async def _inject_inputs(self, step: Step, job: Job):
        for port_name, port in step.input_ports.items():
            if port.dependee is None:
                output_port = DefaultOutputPort(name=port_name)
                output_port.step = step
                output_port.token_processor = port.token_processor
                command_output = JupyterCommandOutput(
                    value=None,
                    status=Status.COMPLETED,
                    user_ns=self.user_ns,
                    user_global_ns=self.user_global_ns)
                output_port.put(await output_port.token_processor.compute_token(job, command_output))
                output_port.put(TerminationToken(port_name))
                port.dependee = output_port

    async def _translate_cell(self,
                              cell: JupyterCell,
                              metadata: Optional[MutableMapping[Text, Any]],
                              autoawait: bool = False) -> Step:
        # Build execution target
        target = metadata.get('target')
        if target is not None:
            if isinstance(target['model'], Text):
                target = {**target, **{'model': metadata['models'][target['model']]}}
            model_name = hashlib.md5(json.dumps(
                obj=target['model'],
                sort_keys=True,
                ensure_ascii=True,
                default=str).encode('ascii')).hexdigest()
            target = _build_target(model_name, target)
        # Extract Python interpreter from metadata
        interpreter = metadata.get('interpreter', 'ipython')
        # Create a step structure
        step = BaseStep(
            name=cell.name,
            context=self.context,
            target=target)
        # Process cell inputs
        cell_inputs = metadata['step'].get('in', [])
        autoin = metadata['step'].get('autoin', True)
        environment = {}
        input_names = self._extract_dependencies(cell.name, cell.compiler, cell.code) if autoin else []
        input_serializers = {}
        for element in cell_inputs:
            # If is a string, it refers to the name of a variable
            if isinstance(element, Text):
                element = {
                    'type': 'name',
                    'name': element
                }
            # Otherwise it must be a dictionary
            if isinstance(element, MutableMapping):
                element_type = element['type']
                # If type is equal to `file`, it refers to a file path in the local resource
                if element_type == 'file':
                    name = element.get('name') or element.get('valueFrom')
                    port = await _build_file_port(
                        name=name,
                        step=step,
                        element=element)
                    step.input_ports[port.name] = port
                    if name is not None:
                        input_names.append(name)
                # If type is equal to `name`, it refers to a variable
                elif element_type == 'name':
                    input_names.append(element['name'])
                # Put each additional dependency not related to variables as env variables
                elif element_type == 'env':
                    if 'value' in element:
                        environment[element['name']] = element['value']
                    else:
                        name = element['valueFrom']
                        environment[element['name']] = (self.user_ns[name] if name in self.user_ns else
                                                        self.user_global_ns[name])
                # Add serializer if present
                if 'serializer' in element:
                    name = element.get('name') or element.get('valueFrom')
                    input_serializers[name] = (metadata['serializers'][element['serializer']]
                                               if isinstance(element['serializer'], Text)
                                               else element['serializer'])
        # If outputs are defined for the current cell
        output_names = []
        output_serializers = {}
        if 'out' in metadata['step']:
            for element in metadata['step']['out']:
                # If is a string, it refers to the name of a variable
                if isinstance(element, Text):
                    element = {
                        'type': 'name',
                        'name': element
                    }
                # Otherwise it must be a dictionary
                if isinstance(element, MutableMapping):
                    element_type = element['type']
                    # If type is equal to `file`, it refers to a file path in the remote resource
                    if element_type == 'file':
                        name = element.get('name') or element.get('valueFrom')
                        port_name = name or utils.random_name()
                        output_port = DefaultOutputPort(name=port_name)
                        output_port.step = step
                        output_port.token_processor = FileTokenProcessor(
                            port=output_port,
                            name=name,
                            value=element.get('value'),
                            valueFrom=element.get('valueFrom'))
                        step.output_ports[port_name] = output_port
                        output_names.append(port_name)
                    # If type is equal to `name`, it refers to a variable
                    elif element_type == 'name':
                        output_names.append(element['name'])
                # Add serializer if present
                if 'serializer' in element:
                    name = element.get('name') or element.get('valueFrom')
                    output_serializers[name] = (metadata['serializers'][element['serializer']]
                                                if isinstance(element['serializer'], Text)
                                                else element['serializer'])
        # Set input combinator for the step
        input_combinator = DotProductInputCombinator(utils.random_name())
        for port in step.input_ports.values():
            input_combinator.ports[port.name] = port
        step.input_combinator = input_combinator
        # Create the command to be executed remotely
        step.command = JupyterCommand(
            step=step,
            ast_nodes=cell.code,
            compiler=cell.compiler,
            environment=environment,
            interpreter=interpreter,
            input_names=input_names,
            input_serializers=input_serializers,
            output_names=output_names,
            output_serializers=output_serializers,
            user_ns=self.user_ns,
            user_global_ns=self.user_global_ns,
            autoawait=autoawait)
        return step

    async def translate(self, notebook: JupyterNotebook) -> Workflow:
        # Create workflow
        workflow = Workflow()
        # Parse single cells independently to derive workflow steps
        cell_tasks = {cell.name: asyncio.create_task(
            self._translate_cell(
                cell=cell,
                metadata={**cell.metadata, **notebook.metadata},
                autoawait=notebook.autoawait)
        ) for cell in notebook.cells}
        workflow.steps = dict(zip(cell_tasks.keys(), await asyncio.gather(*cell_tasks.values())))
        # Inject initial inputs
        input_injector = BaseJob(
            name=utils.random_name(),
            step=BaseStep(utils.random_name(), self.context),
            inputs=[])
        for step in workflow.steps.values():
            await self._inject_inputs(step, input_injector)
        # Extract workflow outputs
        last_step = workflow.steps[notebook.cells[-1].name]
        for port_name, port in last_step.output_ports.items():
            workflow.output_ports[last_step.name] = port
        # Return the final workflow object
        return workflow

    async def translate_cell(self,
                             cell: JupyterCell,
                             metadata: Optional[MutableMapping[Text, Any]],
                             autoawait: bool = False):
        step = await self._translate_cell(
            cell=cell,
            metadata=metadata,
            autoawait=autoawait)
        # Inject initial inputs
        input_injector = BaseJob(
            name=utils.random_name(),
            step=BaseStep(utils.random_name(), self.context),
            inputs=[])
        await self._inject_inputs(step, input_injector)
        # Return the step for the translated cell
        return step

