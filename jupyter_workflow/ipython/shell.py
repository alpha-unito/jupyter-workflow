import ast
import asyncio
import os
import sys
import tempfile
from contextvars import ContextVar
from typing import MutableMapping, Any, Optional, MutableSequence, List, Tuple

import IPython
import dill
from IPython.core.interactiveshell import softspace
from ipykernel.zmqshell import ZMQInteractiveShell
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import ModelConfig
from streamflow.core.utils import random_name
from streamflow.core.workflow import Step, TerminationToken, Job
from streamflow.core.workflow import Target, Status
from streamflow.data.data_manager import DefaultDataManager
from streamflow.deployment.deployment_manager import DefaultDeploymentManager
from streamflow.recovery.checkpoint_manager import DummyCheckpointManager
from streamflow.recovery.failure_manager import DummyFailureManager
from streamflow.scheduling.policy import DataLocalityPolicy
from streamflow.scheduling.scheduler import DefaultScheduler
from streamflow.workflow.combinator import DotProductInputCombinator
from streamflow.workflow.port import DefaultInputPort, DefaultOutputPort
from streamflow.workflow.step import BaseStep, BaseJob
from traitlets import observe
from typing_extensions import Text

from jupyter_workflow.streamflow.command import JupyterCommand, JupyterCommandOutput
from jupyter_workflow.streamflow.token_processor import FileTokenProcessor


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


async def _collect_namespace(step: Step,
                             output_retriever: Step,
                             port_name: Text,
                             output_dir: Text) -> Optional[MutableMapping[Text, Any]]:
    ns_token = await step.output_ports[port_name].get(output_retriever)
    if ns_token.value is not None:
        token_processor = step.output_ports[port_name].token_processor
        ns_token = await token_processor.collect_output(ns_token, output_dir)
        with open(ns_token.value, mode="rb") as f:
            return dill.load(f, encoding="bytes")
    else:
        return None


class DependenciesRetriever(ast.NodeVisitor):

    def __init__(self,
                 cell_name: Text,
                 compiler,
                 user_ns: MutableMapping[Text, Any],
                 user_global_ns: MutableMapping[Text, Any]):
        super().__init__()
        self.cell_name: Text = cell_name
        self.compiler = compiler
        self.deps: MutableSequence[Text] = []
        self.names: MutableSequence[Text] = []
        self.user_ns: MutableMapping[Text, Any] = user_ns
        self.user_global_ns: MutableMapping[Text, Any] = user_global_ns

    def visit_Name(self, node):
        if isinstance(node.ctx, ast.Load) and node.id not in self.names:
            if node.id in self.user_ns or node.id in self.user_global_ns:
                self.deps.append(node.id)
        self.names.append(node.id)
        self.generic_visit(node)


class StreamFlowInteractiveShell(ZMQInteractiveShell):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.workflow_dir: Text = os.path.join(tempfile.gettempdir(), 'streamflow')
        self.config_dir: Text = os.path.join(self.workflow_dir, 'config')
        os.makedirs(self.config_dir, exist_ok=True)
        self.context: StreamFlowContext = StreamFlowContext(self.config_dir)
        self.context.checkpoint_manager = DummyCheckpointManager(self.context)
        self.context.data_manager = DefaultDataManager(self.context)
        self.context.deployment_manager = DefaultDeploymentManager(self.config_dir)
        self.context.failure_manager = DummyFailureManager(self.context)
        self.context.scheduler = DefaultScheduler(self.context, DataLocalityPolicy())
        self.wf_nb_config: MutableMapping[Text, Any] = {}
        self.wf_cell_config: ContextVar[MutableMapping[Text, Any]] = ContextVar('wf_cell_config', default={})
        self.sys_excepthook = None

    async def _build_file_port(self, job: Job, name: Text, step: Step, element: MutableMapping[Text, Text]):
        port_name = name or utils.random_name()
        output_port = DefaultOutputPort(name=port_name)
        output_port.step = job.step
        output_port.token_processor = FileTokenProcessor(
            port=output_port,
            name=name,
            value=element.get('value'),
            valueFrom=element.get('valueFrom'))
        command_output = JupyterCommandOutput(
            value=None,
            status=Status.COMPLETED,
            user_ns=self.user_ns,
            user_global_ns=self.user_global_ns)
        output_port.put(await output_port.token_processor.compute_token(job, command_output))
        output_port.put(TerminationToken(port_name))
        port = DefaultInputPort(name=port_name)
        port.step = step
        port.token_processor = FileTokenProcessor(
            port=port,
            name=name,
            value=element.get('value'),
            valueFrom=element.get('valueFrom'))
        port.dependee = output_port
        return port

    def _extract_dependencies(self,
                              cell_name: Text,
                              compiler,
                              ast_nodes: List[Tuple[ast.AST, Text]]) -> MutableSequence[Text]:
        visitor = DependenciesRetriever(cell_name, compiler, self.user_ns, self.user_global_ns)
        for node, _ in ast_nodes:
            visitor.visit(node)
        return visitor.deps

    async def _run_with_streamflow(self,
                                   cell_name: Text,
                                   compiler,
                                   ast_nodes: List[Tuple[ast.AST, Text]],
                                   cell_config: MutableMapping[Text, Any]):
        # Get StreamFlow config
        sf_config = {**self.wf_nb_config, **cell_config}  # TODO: validate cell_config from protocol schema
        # Build the step target from metadata
        target = _build_target(sf_config['model_name'], sf_config['target'])
        # Extract Python interpreter from metadata
        interpreter = sf_config.get('interpreter', 'python')
        # Create a step structure
        step = BaseStep(
            name=sf_config['step_id'],
            context=self.context,
            target=target)
        # Create dummy job for input tokens
        input_injector = BaseJob(
            name=utils.random_name(),
            step=BaseStep(utils.random_name(), self.context),
            inputs=[])
        # Process cell inputs
        cell_inputs = cell_config['step'].get('in', ['*'])
        environment = {}
        input_names = []
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
                    port = await self._build_file_port(
                        job=input_injector,
                        name=name,
                        step=step,
                        element=element)
                    step.input_ports[port.name] = port
                    if name is not None:
                        input_names.append(name)
                # If type is equal to `name`, it refers to a variable
                elif element_type == 'name':
                    if element['name'] == '*':
                        input_names.extend(self._extract_dependencies(cell_name, compiler, ast_nodes))
                    else:
                        input_names.append(element['name'])
                # Put each additional dependency not related to variables as env variables
                elif element_type == 'env':
                    environment[element['name']] = element['value']
        # If outputs are defined for the current cell
        output_names = []
        if 'out' in cell_config['step']:
            for element in cell_config['step']['out']:
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
                        port_name = name or random_name()
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
        # Set input combinator for the step
        input_combinator = DotProductInputCombinator(utils.random_name())
        for port in step.input_ports.values():
            input_combinator.ports[port.name] = port
        step.input_combinator = input_combinator
        # Create the command to be executed remotely
        step.command = JupyterCommand(
            step=step,
            ast_nodes=ast_nodes,
            environment=environment,
            interpreter=interpreter,
            input_names=input_names,
            output_names=output_names,
            user_ns=self.user_ns,
            user_global_ns=self.user_global_ns,
            autoawait=self.autoawait)
        # Execute the step
        await step.run()
        # Update namespaces
        if self.user_global_ns != self.user_ns:
            self.user_global_ns.update(step.command.user_global_ns)
        self.user_ns.update(step.command.user_ns)
        # Retrieve output
        output_retriever = BaseStep(utils.random_name(), self.context)
        updated_names = {}
        d = tempfile.mkdtemp()
        for port_name, port in step.output_ports.items():
            token_processor = step.output_ports[port_name].token_processor
            token = await step.output_ports[port_name].get(output_retriever)
            token = await token_processor.collect_output(token, d)
            if 'name' in token.value:
                updated_names[token.value['name']] = token.value['dst']
            else:
                pass  # TODO: manipulate AST
        # Update namespaces
        if self.user_global_ns != self.user_ns:
            self.user_global_ns.update(updated_names)
        self.user_ns.update(updated_names)

    @observe('exit_now')
    def _update_exit_now(self, change):
        print(str(change))
        # Undeploy all environments before exiting
        coro = self.context.deployment_manager.undeploy_all()
        asyncio.ensure_future(coro)
        # Call parent function
        super()._update_exit_now(change=change)

    # noinspection PyProtectedMember
    async def run_ast_nodes(self,
                            nodelist: List[ast.AST],
                            cell_name: str,
                            interactivity='last_expr',
                            compiler=compile,
                            result=None):
        cell_config = self.wf_cell_config.get() or {}
        if 'step' in cell_config:
            if not nodelist:
                return
            if interactivity == 'last_expr_or_assign':
                if isinstance(nodelist[-1], IPython.core.interactiveshell._assign_nodes):
                    asg = nodelist[-1]
                    if isinstance(asg, ast.Assign) and len(asg.targets) == 1:
                        target = asg.targets[0]
                    elif isinstance(asg, IPython.core.interactiveshell._single_targets_nodes):
                        target = asg.target
                    else:
                        target = None
                    if isinstance(target, ast.Name):
                        nnode = ast.Expr(ast.Name(target.id, ast.Load()))
                        ast.fix_missing_locations(nnode)
                        nodelist.append(nnode)
                interactivity = 'last_expr'

            _async = False
            if interactivity == 'last_expr':
                if isinstance(nodelist[-1], ast.Expr):
                    interactivity = "last"
                else:
                    interactivity = "none"

            if interactivity == 'none':
                to_run_exec, to_run_interactive = nodelist, []
            elif interactivity == 'last':
                to_run_exec, to_run_interactive = nodelist[:-1], nodelist[-1:]
            elif interactivity == 'all':
                to_run_exec, to_run_interactive = [], nodelist
            else:
                raise ValueError("Interactivity was %r" % interactivity)

            try:
                # refactor that to just change the mod constructor.
                to_run = []
                for node in to_run_exec:
                    to_run.append((node, 'exec'))

                for node in to_run_interactive:
                    to_run.append((node, 'single'))

                # Run AST nodes remotely
                await self._run_with_streamflow(
                    cell_name=cell_name,
                    compiler=compiler,
                    ast_nodes=to_run,
                    cell_config=cell_config)

                # Flush softspace
                if softspace(sys.stdout, 0):
                    print()
            except:
                if result:
                    result.error_before_exec = sys.exc_info()[1]
                self.showtraceback()
                return True
            return False
        else:
            return await super().run_ast_nodes(nodelist, cell_name, interactivity, compiler, result=None)

    def should_run_async(self,
                         raw_cell: Text,
                         *,
                         transformed_cell=None,
                         preprocessing_exc_tuple=None) -> bool:
        # Since StreamFlow needs a real `asyncio loop` to execute tasks, the default `_pseudo_sync_runner` doesn't work
        return True
