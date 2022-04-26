import ast
import asyncio
import os
import posixpath
import sys
from contextvars import ContextVar
from io import FileIO, TextIOWrapper
from typing import Any, List, MutableMapping, Tuple, cast

import IPython
import streamflow.log_handler
from IPython.core.error import InputRejected
from IPython.core.interactiveshell import ExecutionResult, softspace
from ipykernel.zmqshell import ZMQInteractiveShell
from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.data import LOCAL_LOCATION
from streamflow.core.exception import WorkflowDefinitionException
from streamflow.core.utils import get_token_value
from streamflow.core.workflow import Token, Workflow
from streamflow.data.data_manager import DefaultDataManager
from streamflow.deployment.deployment_manager import DefaultDeploymentManager
from streamflow.recovery.checkpoint_manager import DummyCheckpointManager
from streamflow.recovery.failure_manager import DummyFailureManager
from streamflow.scheduling.policy import DataLocalityPolicy
from streamflow.scheduling.scheduler import DefaultScheduler
from streamflow.workflow.executor import StreamFlowExecutor
from traitlets import Type, observe
from typing_extensions import Text

from jupyter_workflow.ipython.displayhook import StreamFlowDisplayPublisher, StreamFlowShellDisplayHook
from jupyter_workflow.ipython.iostream import WorkflowOutStream
from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.translator import (
    DependenciesRetriever, JupyterCell, JupyterNotebook,
    JupyterNotebookTranslator
)

# Patch StreamFlow log to bypass IPython stderr
streamflow.log_handler.defaultStreamHandler.stream = TextIOWrapper(
    FileIO(os.dup(sys.stderr.fileno()), "w"))


def _classify_nodes(nodelist, interactivity):
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
    to_run = []
    for node in to_run_exec:
        to_run.append((node, 'exec'))
    for node in to_run_interactive:
        to_run.append((node, 'single'))
    return to_run


async def _get_outputs(workflow: Workflow, port_name: str) -> MutableMapping[str, Token]:
    output_tasks = {posixpath.split(name)[0]: asyncio.create_task(port.get(utils.random_name()))
                    for name, port in workflow.get_output_ports().items()
                    if posixpath.split(name)[1] == port_name}
    return dict(zip(output_tasks.keys(), await asyncio.gather(*output_tasks.values())))


def _get_stdout(token_value: Any):
    try:
        return str(ast.literal_eval(token_value))
    except (SyntaxError, ValueError):
        return token_value


def build_context() -> StreamFlowContext:
    context: StreamFlowContext = StreamFlowContext(os.getcwd())
    context.checkpoint_manager = DummyCheckpointManager(context)
    context.data_manager = DefaultDataManager(context)
    context.deployment_manager = DefaultDeploymentManager(os.getcwd())
    context.failure_manager = DummyFailureManager(context)
    context.scheduler = DefaultScheduler(context, DataLocalityPolicy())
    return context


class StreamFlowInteractiveShell(ZMQInteractiveShell):
    displayhook_class = Type(StreamFlowShellDisplayHook)
    display_pub_class = Type(StreamFlowDisplayPublisher)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.context: StreamFlowContext = build_context()
        self.context.data_manager.register_path(
            deployment=LOCAL_LOCATION,
            location=os.path.join(executor.__file__),
            path=os.path.join(executor.__file__),
            relpath=os.path.basename(executor.__file__))
        self.wf_cell_config: ContextVar[MutableMapping[Text, Any]] = ContextVar('wf_cell_config', default={})
        self.sys_excepthook = None

    def _error_before_exec(self, result, val):
        result.error_before_exec = val
        self.last_execution_succeeded = False
        self.last_execution_result = result
        return result

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
        notebook = JupyterNotebook([cell])
        # Translate notebook into workflow
        translator = JupyterNotebookTranslator(
            context=self.context)
        workflow = await translator.translate(notebook=notebook, user_ns=self.user_ns)
        try:
            # Execute workflow
            await StreamFlowExecutor(workflow).run()
            # Print output log
            output = next(iter((await _get_outputs(workflow, executor.CELL_OUTPUT)).values()))
            if output := _get_stdout(get_token_value(output)):
                print(output)
            # Retrieve outputs and update namespaces
            output_tasks = {posixpath.split(name)[1]: asyncio.create_task(port.get(utils.random_name()))
                            for name, port in workflow.get_output_ports().items()
                            if posixpath.split(name)[1] != executor.CELL_OUTPUT}
            outputs = dict(zip(
                output_tasks.keys(), [get_token_value(t) for t in await asyncio.gather(*output_tasks.values())]))
            # Update the 'Out' field
            ipython_out = outputs.pop('Out')
            try:
                ipython_out = ast.literal_eval(ipython_out)
            except (SyntaxError, ValueError):
                pass
            if ipython_out:
                self.user_ns['Out'][self.execution_count] = ipython_out
                self.displayhook(self.user_ns['Out'][self.execution_count])
            # Update the other variables
            self.user_ns.update(outputs)
        except BaseException:
            # Print output log
            output = next(iter((await _get_outputs(workflow, executor.CELL_OUTPUT)).values()))
            if output := _get_stdout(get_token_value(output)):
                print(output)
            # Propagate exception
            raise

    @observe('exit_now')
    def _update_exit_now(self, change):
        print(str(change))
        # Undeploy all environments before exiting
        coro = self.context.deployment_manager.undeploy_all()
        asyncio.ensure_future(coro)
        # Call parent function
        super()._update_exit_now(change=change)

    def delete_parent(self, parent):
        self.displayhook.delete_parent(parent)
        self.display_pub.delete_parent(parent)
        if hasattr(self, "_data_pub"):
            self.data_pub.set_parent(parent)
        try:
            cast(WorkflowOutStream, sys.stdout).delete_parent(parent)
        except AttributeError:
            pass
        try:
            cast(WorkflowOutStream, sys.stderr).delete_parent(parent)
        except AttributeError:
            pass

    async def retrieve_inputs(self, code):
        result = ExecutionResult(None)
        try:
            code = self.transform_cell(raw_cell=code)
            cell_name = self.compile.cache(code, self.execution_count, raw_code=code)
            code_ast = self.compile.ast_parse(code, filename=cell_name)
            code_ast = self.transform_ast(code_ast)
            visitor = DependenciesRetriever(cell_name, self.compile)
            for node in code_ast.body:
                visitor.visit(node)
            result.inputs = list(visitor.deps)
        except self.custom_exceptions as e:
            etype, value, tb = sys.exc_info()
            self.CustomTB(etype, value, tb)
            return self._error_before_exec(result, e)
        except (InputRejected, WorkflowDefinitionException) as e:
            self.showtraceback()
            return self._error_before_exec(result, e)
        except IndentationError as e:
            self.showindentationerror()
            return self._error_before_exec(result, e)
        except (OverflowError, SyntaxError, ValueError, TypeError,
                MemoryError) as e:
            self.showsyntaxerror()
            return self._error_before_exec(result, e)
        return result

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
            try:
                to_run = _classify_nodes(nodelist, interactivity)
                # Run AST nodes remotely
                await self._run_with_streamflow(
                    cell_name=cell_name,
                    compiler=compiler,
                    ast_nodes=to_run,
                    cell_config=cell_config)
                # Flush softspace
                if softspace(sys.stdout, 0):
                    print()
            except BaseException:
                if result:
                    result.error_before_exec = sys.exc_info()[1]
                self.showtraceback()
                return True
            return False
        else:
            return await super().run_ast_nodes(nodelist, cell_name, interactivity, compiler, result=None)

    async def run_workflow(self, notebook):
        result = ExecutionResult(None)
        result.stdout = {}
        result.out = {}
        cells = [self.transform_cell(cell['code']) for cell in notebook['cells']]
        with self.builtin_trap, self.display_trap:
            try:
                interactivity = self.ast_node_interactivity
                # Extract cells code
                jupyter_cells = []
                for cell, metadata in zip(cells, [c.get('metadata', {'step': {}}) for c in notebook['cells']]):
                    cell_name = self.compile.cache(cell, self.execution_count, raw_code=cell)
                    code_ast = self.compile.ast_parse(cell, filename=cell_name)
                    code_ast = self.transform_ast(code_ast)
                    to_run = _classify_nodes(code_ast.body, interactivity)
                    jupyter_cells.append(JupyterCell(
                        name=cell_name,
                        code=to_run,
                        compiler=self.compile,
                        metadata=metadata))
                # Build workflow
                translator = JupyterNotebookTranslator(context=self.context)
                workflow = await translator.translate(
                    notebook=JupyterNotebook(
                        cells=jupyter_cells,
                        metadata=notebook.get('metadata')),
                    user_ns=self.user_ns)
            except self.custom_exceptions as e:
                etype, value, tb = sys.exc_info()
                self.CustomTB(etype, value, tb)
                return self._error_before_exec(result, e)
            except (InputRejected, WorkflowDefinitionException) as e:
                self.showtraceback()
                return self._error_before_exec(result, e)
            except IndentationError as e:
                self.showindentationerror()
                return self._error_before_exec(result, e)
            except (OverflowError, SyntaxError, ValueError, TypeError,
                    MemoryError) as e:
                self.showsyntaxerror()
                return self._error_before_exec(result, e)
            self.displayhook.exec_result = result
            # Execute workflow
            try:
                await StreamFlowExecutor(workflow).run()
                # Capture output logs
                outputs = await _get_outputs(workflow, executor.CELL_OUTPUT)
                for cell_name, token in outputs.items():
                    if output := _get_stdout(get_token_value(token)):
                        result.stdout[cell_name] = output
                # Capture IPython 'Out' content
                ipython_outs = await _get_outputs(workflow, 'Out')
                for cell_name, token in ipython_outs.items():
                    try:
                        ipython_out = ast.literal_eval(get_token_value(token))
                    except (SyntaxError, ValueError):
                        ipython_out = get_token_value(token)
                    if ipython_out:
                        result.out[cell_name] = ipython_out
                # Capture other outputs and update namespace
                outputs = {posixpath.split(name)[1]: asyncio.create_task(port.get(utils.random_name()))
                           for name, port in workflow.get_output_ports().items()
                           if posixpath.split(name)[1] not in ['Out', executor.CELL_OUTPUT]}
                for out_name, out_value in zip(outputs.keys(), await asyncio.gather(*outputs.values())):
                    self.user_ns[out_name] = get_token_value(out_value)
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
