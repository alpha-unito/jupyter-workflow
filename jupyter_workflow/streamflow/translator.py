import ast
import asyncio
import hashlib
import json
from typing import MutableSequence, Text, Any, MutableMapping, Optional, Tuple, List

from IPython.core.compilerop import CachingCompiler
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import ModelConfig
from streamflow.core.workflow import Workflow, Target, Step
from streamflow.workflow.combinator import DotProductInputCombinator
from streamflow.workflow.port import DefaultOutputPort, DefaultInputPort, ScatterInputPort, GatherOutputPort
from streamflow.workflow.step import BaseStep

from jupyter_workflow.streamflow.command import JupyterCommand
from jupyter_workflow.streamflow.token_processor import FileTokenProcessor, NameTokenProcessor


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
    return visitor.deps


class DependenciesRetriever(ast.NodeVisitor):

    def __init__(self,
                 cell_name: Text,
                 compiler: CachingCompiler):
        super().__init__()
        self.cell_name: Text = cell_name
        self.compiler: CachingCompiler = compiler
        self.deps: MutableSequence[Text] = []
        self.names: MutableSequence[Text] = []

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.names:
            # Skip the 'get_ipython' dependency as it is not serialisable
            if node.id != 'get_ipython':
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
        # Process cell inputs
        cell_inputs = metadata['step'].get('in', [])
        input_serializers = {}
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
                if element.get('scatter', False):
                    port = ScatterInputPort(name=name, step=step)
                    gather = True
                else:
                    port = DefaultInputPort(name=name, step=step)
                # Get serializer if present
                serializer = (metadata['serializers'][element['serializer']]
                              if isinstance(element['serializer'], Text)
                              else element['serializer']) if 'serializer' in element else None
                if serializer is not None:
                    input_serializers[name] = serializer
                # Process port type
                element_type = element['type']
                # If type is equal to `file`, it refers to a file path in the local resource
                if element_type == 'file':
                    port.token_processor = FileTokenProcessor(
                        port=port,
                        name=name,
                        value=element.get('value'),
                        value_from=element.get('valueFrom'))
                # If type is equal to `name`, it refers to a variable
                elif element_type == 'name':
                    port.token_processor = NameTokenProcessor(
                        port=port,
                        name=name,
                        token_type='name',
                        serializer=serializer,
                        compiler=cell.compiler,
                        value=element.get('value'),
                        value_from=element.get('valueFrom', name))
                # Put each additional dependency not related to variables as env variables
                elif element_type == 'env':
                    port.token_processor = NameTokenProcessor(
                        port=port,
                        name=name,
                        token_type='env',
                        compiler=cell.compiler,
                        serializer=serializer,
                        value=element.get('value'),
                        value_from=element.get('valueFrom'))
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
                        name=name,
                        token_type='name',
                        compiler=cell.compiler,
                        value_from=name)
                    step.input_ports[port.name] = port
        # If outputs are defined for the current cell
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
                    # Create port
                    name = element.get('name') or element.get('valueFrom')
                    port_name = name or utils.random_name()
                    if gather:
                        output_port = GatherOutputPort(name=port_name, step=step)
                    else:
                        output_port = DefaultOutputPort(name=port_name, step=step)
                    # Get serializer if present
                    serializer = (metadata['serializers'][element['serializer']]
                                  if isinstance(element['serializer'], Text)
                                  else element['serializer']) if 'serializer' in element else None
                    if serializer is not None:
                        output_serializers[name] = serializer
                    # Process port type
                    element_type = element['type']
                    # If type is equal to `file`, it refers to a file path in the remote resource
                    if element_type == 'file':
                        output_port.token_processor = FileTokenProcessor(
                            port=output_port,
                            name=name,
                            value_from=element.get('valueFrom'))
                    # If type is equal to `name`, it refers to a variable
                    elif element_type == 'name':
                        output_port.token_processor = NameTokenProcessor(
                            port=output_port,
                            name=name,
                            token_type='name',
                            compiler=cell.compiler,
                            serializer=serializer,
                            value_from=element.get('valueFrom', name))
                    # Register step port
                    step.output_ports[port_name] = output_port
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
            interpreter=interpreter,
            input_serializers=input_serializers,
            output_serializers=output_serializers,
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
        workflow.steps = dict(zip(cell_tasks.keys(), await asyncio.gather(*cell_tasks.values())))
        # Extract workflow outputs
        last_step = workflow.steps[notebook.cells[-1].name]
        for port_name, port in last_step.output_ports.items():
            workflow.output_ports[last_step.name] = port
        # Return the final workflow object
        return workflow
