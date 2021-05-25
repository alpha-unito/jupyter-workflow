import ast
import asyncio
import json
import os
import sys
import tempfile
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
from typing import MutableMapping, Any, List, Tuple, MutableSequence

import IPython
from IPython.core.error import InputRejected
from IPython.core.interactiveshell import softspace, ExecutionResult
from ipykernel.zmqshell import ZMQInteractiveShell
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.exception import WorkflowDefinitionException
from streamflow.core.workflow import Step, Job, Status, TerminationToken
from streamflow.data.data_manager import DefaultDataManager
from streamflow.deployment.deployment_manager import DefaultDeploymentManager
from streamflow.recovery.checkpoint_manager import DummyCheckpointManager
from streamflow.recovery.failure_manager import DummyFailureManager
from streamflow.scheduling.policy import DataLocalityPolicy
from streamflow.scheduling.scheduler import DefaultScheduler
from streamflow.workflow.executor import StreamFlowExecutor
from streamflow.workflow.port import DefaultOutputPort
from streamflow.workflow.step import BaseStep, BaseJob
from traitlets import observe
from typing_extensions import Text

from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.command import JupyterCommandOutput
from jupyter_workflow.streamflow.translator import JupyterCell, JupyterNotebookTranslator, JupyterNotebook


async def _get_output(step: Step, output_retriever: str, d: str) -> Text:
    token_processor = step.output_ports[executor.CELL_OUTPUT].token_processor
    token = await step.output_ports[executor.CELL_OUTPUT].get(output_retriever)
    token = await token_processor.collect_output(token, d)
    if isinstance(token.job, MutableSequence):
        return "\n".join([t for t in utils.flatten_list([t.value for t in token.value]) if t])
    else:
        return token.value


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
        # Print output log
        output_retriever = utils.random_name()
        d = tempfile.mkdtemp()
        output = await _get_output(
            step=step,
            output_retriever=output_retriever,
            d=d)
        if output:
            print(output)
        # Retrieve output tokens
        if step.status == Status.COMPLETED:
            output_names = {}
            for port_name, port in step.output_ports.items():
                if port_name != executor.CELL_OUTPUT:
                    token_processor = step.output_ports[port_name].token_processor
                    token = await step.output_ports[port_name].get(output_retriever)
                    token = await token_processor.collect_output(token, d)
                    if isinstance(token.job, MutableSequence):
                        output_names[token.name] = utils.flatten_list([t.value for t in token.value])
                    else:
                        output_names[token.name] = token.value
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

    async def run_workflow(self, notebook):
        result = ExecutionResult(None)

        def error_before_exec(val):
            result.error_before_exec = val
            self.last_execution_succeeded = False
            self.last_execution_result = result
            return result

        cells = [self.transform_cell(cell['code']) for cell in notebook['cells']]
        with self.builtin_trap, self.display_trap:
            try:
                # Extract cells code
                jupyter_cells = []
                for cell, metadata in zip(cells, [c.get('metadata', {'step': {}}) for c in notebook['cells']]):
                    cell_name = self.compile.cache(cell, self.execution_count, raw_code=cell)
                    code_ast = self.compile.ast_parse(cell, filename=cell_name)
                    code_ast = self.transform_ast(code_ast)
                    to_run = [(node, 'exec') for node in code_ast.body]
                    jupyter_cells.append(JupyterCell(
                        name=cell_name,
                        code=to_run,
                        compiler=self.compile,
                        metadata=metadata))
                # Build workflow
                translator = JupyterNotebookTranslator(context=self.context)
                workflow = await translator.translate(JupyterNotebook(
                    cells=jupyter_cells,
                    autoawait=self.autoawait,
                    metadata=notebook.get('metadata')))
                # Inject inputs
                input_injector = BaseJob(
                    name=utils.random_name(),
                    step=BaseStep(utils.random_name(), self.context),
                    inputs=[])
                for step in workflow.steps.values():
                    await self._inject_inputs(step=step, job=input_injector)
            except self.custom_exceptions as e:
                etype, value, tb = sys.exc_info()
                self.CustomTB(etype, value, tb)
                return error_before_exec(e)
            except (InputRejected, WorkflowDefinitionException) as e:
                self.showtraceback()
                return error_before_exec(e)
            except IndentationError as e:
                self.showindentationerror()
                return error_before_exec(e)
            except (OverflowError, SyntaxError, ValueError, TypeError,
                    MemoryError) as e:
                self.showsyntaxerror()
                return error_before_exec(e)
            self.displayhook.exec_result = result
            # Execute workflow
            d = tempfile.mkdtemp()
            try:
                with open(os.devnull, 'w') as devnull:
                    with redirect_stdout(devnull), redirect_stderr(devnull):
                        await StreamFlowExecutor(context=self.context, workflow=workflow).run(output_dir=d)
                        # Print output logs
                        output_retriever = utils.random_name()
                        d = tempfile.mkdtemp()
                        result.result = {}
                        for step in workflow.steps.values():
                            output = await _get_output(
                                step=step,
                                output_retriever=output_retriever,
                                d=d)
                            if output:
                                result.result[step.name] = output
            except:
                if result:
                    result.error_before_exec = sys.exc_info()[1]
                self.showtraceback()
        return result

    def should_run_async(self,
                         raw_cell: Text,
                         *,
                         transformed_cell=None,
                         preprocessing_exc_tuple=None) -> bool:
        # Since StreamFlow needs a real `asyncio loop` to execute tasks, the default `_pseudo_sync_runner` doesn't work
        return True
