import ast
import asyncio
import os
import posixpath
import sys
from contextlib import redirect_stderr, redirect_stdout
from contextvars import ContextVar
from typing import MutableMapping, Any, List, Tuple, MutableSequence

import IPython
import dill
from IPython.core.error import InputRejected
from IPython.core.interactiveshell import softspace, ExecutionResult
from ipykernel.zmqshell import ZMQInteractiveShell
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.data import LOCAL_LOCATION
from streamflow.core.exception import WorkflowDefinitionException
from streamflow.core.utils import get_token_value
from streamflow.core.workflow import Workflow, Token
from streamflow.data.data_manager import DefaultDataManager
from streamflow.deployment.deployment_manager import DefaultDeploymentManager
from streamflow.recovery.checkpoint_manager import DummyCheckpointManager
from streamflow.recovery.failure_manager import DummyFailureManager
from streamflow.scheduling.policy import DataLocalityPolicy
from streamflow.scheduling.scheduler import DefaultScheduler
from streamflow.workflow.executor import StreamFlowExecutor
from streamflow.workflow.step import DeployStep
from traitlets import observe
from typing_extensions import Text

from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.translator import JupyterCell, JupyterNotebookTranslator, JupyterNotebook
from jupyter_workflow.streamflow.utils import get_stdout


def build_context() -> StreamFlowContext:
    context: StreamFlowContext = StreamFlowContext(os.getcwd())
    context.checkpoint_manager = DummyCheckpointManager(context)
    context.data_manager = DefaultDataManager(context)
    context.deployment_manager = DefaultDeploymentManager(os.getcwd())
    context.failure_manager = DummyFailureManager(context)
    context.scheduler = DefaultScheduler(context, DataLocalityPolicy())
    return context


async def _get_outputs(workflow: Workflow) -> MutableMapping[str, Token]:
    output_tasks = {posixpath.split(name)[0]: asyncio.create_task(port.get(utils.random_name()))
                    for name, port in workflow.get_output_ports().items()
                    if posixpath.split(name)[1] == executor.CELL_OUTPUT}
    return dict(zip(output_tasks.keys(), await asyncio.gather(*output_tasks.values())))


class StreamFlowInteractiveShell(ZMQInteractiveShell):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.context: StreamFlowContext = build_context()
        self.context.data_manager.register_path(
            deployment=LOCAL_LOCATION,
            location=os.path.join(executor.__file__),
            path=os.path.join(executor.__file__),
            relpath=os.path.basename(executor.__file__))
        self.deployment_map: MutableMapping[str, DeployStep] = {}
        self.wf_cell_config: ContextVar[MutableMapping[Text, Any]] = ContextVar('wf_cell_config', default={})
        self.sys_excepthook = None

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
        # Create a notebook with a single cell
        notebook = JupyterNotebook(
            cells=[cell],
            autoawait=self.autoawait)
        # Translate notebook into workflow
        translator = JupyterNotebookTranslator(
            context=self.context,
            deployment_map=self.deployment_map,
            user_ns=self.user_ns)
        workflow = await translator.translate(notebook=notebook)
        try:
            # Execute workflow
            await StreamFlowExecutor(workflow).run()
            # Retrieve outputs and update namespaces
            output_tasks = {posixpath.split(name)[0]: asyncio.create_task(port.get(utils.random_name()))
                            for name, port in workflow.get_output_ports().items()
                            if posixpath.split(name)[1] != executor.CELL_OUTPUT}
            self.user_ns.update(dict(zip(output_tasks.keys(), [
                [dill.loads(v) for v in get_token_value(t)] if isinstance(get_token_value(t), MutableSequence)
                else dill.loads(get_token_value(t)) for t in await asyncio.gather(*output_tasks.values())])))
        finally:
            # Print output log
            if output := next(iter((await _get_outputs(workflow)).values())):
                print(get_stdout(get_token_value(output)))

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
                translator = JupyterNotebookTranslator(
                    context=self.context,
                    deployment_map=self.deployment_map,
                    user_ns=self.user_ns)
                workflow = await translator.translate(
                    notebook=JupyterNotebook(
                        cells=jupyter_cells,
                        autoawait=self.autoawait,
                        metadata=notebook.get('metadata')))
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
            try:
                with open(os.devnull, 'w') as devnull:
                    with redirect_stdout(devnull), redirect_stderr(devnull):
                        await StreamFlowExecutor(workflow).run()
                        # Print output logs
                        result.result = {}
                        outputs = await _get_outputs(workflow)
                        for cell_name, token in outputs:
                            if token_value := get_token_value(token):
                                result.result[cell_name] = get_stdout(token_value)
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
