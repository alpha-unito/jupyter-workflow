import ast
import asyncio
import os
import sys
import tempfile
from contextvars import ContextVar
from typing import MutableMapping, Any, List, Tuple

import IPython
from IPython.core.interactiveshell import softspace
from ipykernel.zmqshell import ZMQInteractiveShell
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.workflow import Step, Job, Status, TerminationToken
from streamflow.data.data_manager import DefaultDataManager
from streamflow.deployment.deployment_manager import DefaultDeploymentManager
from streamflow.recovery.checkpoint_manager import DummyCheckpointManager
from streamflow.recovery.failure_manager import DummyFailureManager
from streamflow.scheduling.policy import DataLocalityPolicy
from streamflow.scheduling.scheduler import DefaultScheduler
from streamflow.workflow.port import DefaultOutputPort
from streamflow.workflow.step import BaseStep, BaseJob
from traitlets import observe
from typing_extensions import Text

from jupyter_workflow.streamflow.command import JupyterCommandOutput
from jupyter_workflow.streamflow.translator import JupyterCell, JupyterNotebookTranslator


class StreamFlowInteractiveShell(ZMQInteractiveShell):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.context: StreamFlowContext = StreamFlowContext(os.getcwd())
        self.context.checkpoint_manager = DummyCheckpointManager(self.context)
        self.context.data_manager = DefaultDataManager(self.context)
        self.context.deployment_manager = DefaultDeploymentManager(os.getcwd())
        self.context.failure_manager = DummyFailureManager(self.context)
        self.context.scheduler = DefaultScheduler(self.context, DataLocalityPolicy())
        self.wf_cell_config: ContextVar[MutableMapping[Text, Any]] = ContextVar('wf_cell_config', default={})
        self.sys_excepthook = None

    async def _inject_inputs(self, step: Step, job: Job):
        for port_name, port in step.input_ports.items():
            if port.dependee is None:
                output_port = DefaultOutputPort(name=port_name)
                output_port.step = step
                output_port.token_processor = port.token_processor
                command_output = JupyterCommandOutput(
                    value=None,
                    status=Status.COMPLETED,
                    user_ns=self.user_ns)
                output_port.put(await output_port.token_processor.compute_token(job, command_output))
                output_port.put(TerminationToken(port_name))
                port.dependee = output_port

    async def _run_with_streamflow(self,
                                   cell_name: Text,
                                   compiler,
                                   ast_nodes: List[Tuple[ast.AST, Text]],
                                   cell_config: MutableMapping[Text, Any]):
        # Build the step target from metadata
        cell = JupyterCell(
            name=cell_name,
            code=ast_nodes,
            compiler=compiler,
            metadata=cell_config)
        translator = JupyterNotebookTranslator(context=self.context)
        step = await translator.translate_cell(
            cell=cell,
            autoawait=self.autoawait,
            metadata=cell_config)
        # Inject inputs
        input_injector = BaseJob(
            name=utils.random_name(),
            step=BaseStep(utils.random_name(), self.context),
            inputs=[])
        await self._inject_inputs(step=step, job=input_injector)
        # Execute the step
        await step.run()
        # Retrieve output
        output_retriever = utils.random_name()
        output_names = {}
        d = tempfile.mkdtemp()
        for port_name, port in step.output_ports.items():
            token_processor = step.output_ports[port_name].token_processor
            token = await step.output_ports[port_name].get(output_retriever)
            token = await token_processor.collect_output(token, d)
            token_type = token.value['type']
            if token_type == 'file':
                if 'name' in token.value:
                    output_names[token.value['name']] = token.value['dst']
                else:
                    pass  # TODO: manipulate AST
            elif token_type == 'name':
                output_names[token.value['name']] = token.value['value']
        # Update namespaces
        self.user_ns.update(output_names)

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
