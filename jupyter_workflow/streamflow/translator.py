import ast
import asyncio
import hashlib
import json
from collections import OrderedDict
from itertools import islice
from typing import MutableSequence, Text, Any, MutableMapping, Optional, Tuple, List, Set

from IPython.core.compilerop import CachingCompiler
from IPython.utils.text import DollarFormatter
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import ModelConfig
from streamflow.core.workflow import Workflow, Target, Step, InputCombinator
from streamflow.workflow.combinator import DotProductInputCombinator, CartesianProductInputCombinator
from streamflow.workflow.port import DefaultOutputPort, DefaultInputPort, ScatterInputPort, GatherOutputPort
from streamflow.workflow.step import BaseStep

from jupyter_workflow.streamflow.command import JupyterCommand, JupyterCommandToken
from jupyter_workflow.streamflow.token_processor import FileTokenProcessor, NameTokenProcessor, ControlTokenProcessor


def _build_dependencies(workflow: Workflow) -> None:
    input_deps = {step_name: list(step.input_ports.keys()) for step_name, step in workflow.steps.items()}
    return_values = {step_name: list(step.output_ports.keys()) for step_name, step in workflow.steps.items()}

    for i, (in_step, in_names) in enumerate(input_deps.values()):
        available_names = {k: return_values[k] for k in reversed(list(islice(return_values, i)))}
        for in_name in in_names:
            for out_step, out_names in available_names.items():
                if in_name in out_names:
                    input_port = workflow.steps[in_step].input_ports[in_name]
                    output_port = workflow.steps[out_step].output_ports[in_name]
                    input_port.dependee = output_port
                    break


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


def _extract_dependencies(cell_name: Text,
                          compiler: CachingCompiler,
                          ast_nodes: List[Tuple[ast.AST, Text]]) -> MutableSequence[Text]:
    visitor = DependenciesRetriever(cell_name, compiler)
    for node, _ in ast_nodes:
        visitor.visit(node)
    return list(visitor.deps)


def _get_input_combinator(step: Step, scatter_inputs: Optional[Set[Text]] = None) -> InputCombinator:
    scatter_inputs = scatter_inputs or set()
    # If there are no scatter ports in this step, create a single DotProduct combinator
    if not [n for n in scatter_inputs]:
        input_combinator = DotProductInputCombinator(utils.random_name())
        for port in step.input_ports.values():
            input_combinator.ports[port.name] = port
        return input_combinator
    # If there are scatter ports
    else:
        other_ports = dict(step.input_ports)
        cartesian_combinator = CartesianProductInputCombinator(utils.random_name())
        # Separate scatter ports from the other ones
        scatter_ports = {}
        for port_name, port in step.input_ports.items():
            if port_name in scatter_inputs:
                scatter_ports[port_name] = port
                del other_ports[port_name]
        scatter_name = utils.random_name()
        scatter_combinator = CartesianProductInputCombinator(scatter_name)
        scatter_combinator.ports = scatter_ports
        cartesian_combinator.ports[scatter_name] = scatter_combinator
        # Create a CartesianProduct combinator between the scatter ports and the DotProduct of the others
        if other_ports:
            dotproduct_name = utils.random_name()
            dotproduct_combinator = DotProductInputCombinator(dotproduct_name)
            dotproduct_combinator.ports = other_ports
            cartesian_combinator.ports[dotproduct_name] = dotproduct_combinator
        return cartesian_combinator


class NamesStack(object):

    def __init__(self):
        self.stack: List[Set] = [set()]

    def add_scope(self):
        self.stack.append(set())

    def add_name(self, name: Text):
        self.stack[-1].add(name)

    def delete_scope(self):
        self.stack.pop()

    def delete_name(self, name: Text):
        self.stack[-1].remove(name)

    def __contains__(self, name: Text) -> bool:
        for scope in self.stack:
            if name in scope:
                return True
        return False


class DependenciesRetriever(ast.NodeVisitor):

    def __init__(self,
                 cell_name: Text,
                 compiler: CachingCompiler):
        super().__init__()
        self.cell_name: Text = cell_name
        self.compiler: CachingCompiler = compiler
        self.deps: Set[Text] = set()
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
        for item in fields['generators']:
            if isinstance(item, ast.AST):
                self.visit(item)
        del fields['generators']
        # Visit the other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def _visit_FunctionDef(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add name to the context
        self.names.add_name(fields['name'])
        del fields['name']
        # Add local context
        self.names.add_scope()
        # Visit arguments
        self.visit(fields['args'])
        del fields['args']
        # Visit other fields
        self._visit_fields(fields)
        # Remove local context
        self.names.delete_scope()

    def visit_alias(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # If alias is defined add alias, otherwise, add name
        self.names.add_name(fields['asname'] or fields['name'])

    def visit_arg(self, node: ast.arg):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add arg to context
        self.names.add_name(fields['arg'])
        del fields['arg']
        # Fisit other fields
        self._visit_fields(fields)

    def visit_AsyncFunctionDef(self, node):
        self._visit_FunctionDef(node)

    def visit_Call(self, node) -> Any:
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Check if is a call to `run_cell_magic`
        if isinstance(fields['func'], ast.Attribute) and fields['func'].attr == 'run_cell_magic':
            for _, name, _, _ in DollarFormatter().parse(fields['args'][1].value):
                if name is not None:
                    self.deps.add(name)
        # Visit other fields
        self._visit_fields(fields)

    def visit_ClassDef(self, node):
        # Extract fields
        fields = {f: v for f, v in ast.iter_fields(node)}
        # Add name to the context
        self.names.add_name(fields['name'])
        del fields['name']
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
        if fields['name'] is not None:
            self.names.add_name(fields['name'])
        del fields['name']
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
            if node.id != 'get_ipython':
                self.deps.add(node.id)
        elif isinstance(node.ctx, ast.Store):
            self.names.add_name(node.id)
        self.generic_visit(node)

    def visit_SetComp(self, node):
        self._visit_Comp(node)


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

    def __init__(self, context: StreamFlowContext):
        self.context: StreamFlowContext = context

    async def translate_cell(self,
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
        step.workdir = metadata['step'].get('workdir')
        # Process cell inputs
        cell_inputs = metadata['step'].get('in', [])
        input_tokens = {}
        scatter_inputs = set()
        gather = False
        for element in cell_inputs:
            # If is a string, it refers to the name of a variable
            if isinstance(element, Text):
                element = {
                    'type': 'name',
                    'name': element
                }
            # Otherwise it must be a dictionary
            if isinstance(element, MutableMapping):
                # Create input port
                name = element.get('name') or element.get('valueFrom')
                if 'scatter' in element:
                    port = ScatterInputPort(name=name, step=step)
                    scatter_inputs.add(name)
                    gather = True
                else:
                    port = DefaultInputPort(name=name, step=step)
                # Get serializer if present
                serializer = (metadata['serializers'][element['serializer']]
                              if isinstance(element['serializer'], Text)
                              else element['serializer']) if 'serializer' in element else None
                # Process port type
                element_type = element['type']
                # If type is equal to `file`, it refers to a file path in the local resource
                if element_type == 'file':
                    port.token_processor = FileTokenProcessor(
                        port=port,
                        value=element.get('value'),
                        value_from=element.get('valueFrom'))
                # If type is equal to `name` or `env`, it refers to a variable
                elif element_type in ['name', 'env']:
                    port.token_processor = NameTokenProcessor(
                        port=port,
                        serializer=serializer,
                        compiler=cell.compiler,
                        value=element.get('value'),
                        value_from=element.get('valueFrom', name))
                # If type is equal to `control`, simply add an empty dependency
                elif element_type == 'control':
                    port.token_processor = ControlTokenProcessor(port=port)
                # Add command token
                input_tokens[name] = JupyterCommandToken(
                    name=name,
                    token_type=element_type,
                    serializer=serializer)
                # Register step port
                step.input_ports[port.name] = port
        # Retrieve inputs automatically if necessary
        if metadata['step'].get('autoin', True):
            input_names = _extract_dependencies(cell.name, cell.compiler, cell.code)
            for name in input_names:
                if name not in step.input_ports:
                    port = DefaultInputPort(name=name, step=step)
                    port.token_processor = NameTokenProcessor(
                        port=port,
                        compiler=cell.compiler,
                        value_from=name)
                    input_tokens[name] = JupyterCommandToken(name=name, token_type='name')
                    step.input_ports[port.name] = port
        # If outputs are defined for the current cell
        output_tokens = {}
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
                    # Create port
                    name = element.get('name') or element.get('valueFrom')
                    if gather:
                        output_port = GatherOutputPort(name=name, step=step)
                    else:
                        output_port = DefaultOutputPort(name=name, step=step)
                    # Get serializer if present
                    serializer = (metadata['serializers'][element['serializer']]
                                  if isinstance(element['serializer'], Text)
                                  else element['serializer']) if 'serializer' in element else None
                    # Process port type
                    element_type = element['type']
                    # If type is equal to `file`, it refers to a file path in the remote resource
                    if element_type == 'file':
                        output_port.token_processor = FileTokenProcessor(
                            port=output_port,
                            value=element.get('value'),
                            value_from=element.get('valueFrom'))
                    # If type is equal to `name` or `env`, it refers to a variable
                    elif element_type in ['name', 'env']:
                        output_port.token_processor = NameTokenProcessor(
                            port=output_port,
                            compiler=cell.compiler,
                            serializer=serializer,
                            value_from=element.get('valueFrom', name))
                    # If type is equal to `control`, simply add an empty dependency
                    elif element_type == 'control':
                        output_port.token_processor = ControlTokenProcessor(port=output_port)
                    # Add command token
                    output_tokens[name] = JupyterCommandToken(
                        name=name,
                        token_type=element_type,
                        serializer=serializer)
                    # Register step port
                    step.output_ports[name] = output_port
        # Set input combinator for the step
        step.input_combinator = _get_input_combinator(step=step, scatter_inputs=scatter_inputs)
        # Create the command to be executed remotely
        step.command = JupyterCommand(
            step=step,
            ast_nodes=cell.code,
            compiler=cell.compiler,
            interpreter=interpreter,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
            autoawait=autoawait)
        return step

    async def translate(self, notebook: JupyterNotebook) -> Workflow:
        # Create workflow
        workflow = Workflow()
        # Parse single cells independently to derive workflow steps
        cell_tasks = {cell.name: asyncio.create_task(
            self.translate_cell(
                cell=cell,
                metadata={**cell.metadata, **notebook.metadata},
                autoawait=notebook.autoawait)
        ) for cell in notebook.cells}
        workflow.steps = OrderedDict(zip(cell_tasks.keys(), await asyncio.gather(*cell_tasks.values())))
        # Build dependency graph
        _build_dependencies(workflow)
        # Extract workflow outputs
        last_step = workflow.steps[notebook.cells[-1].name]
        for port_name, port in last_step.output_ports.items():
            workflow.output_ports[last_step.name] = port
        # Return the final workflow object
        return workflow
