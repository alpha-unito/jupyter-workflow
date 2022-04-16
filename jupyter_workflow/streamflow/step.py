import ast
import asyncio
import sys
from abc import ABC, abstractmethod
from typing import Any, List, MutableMapping, Optional, Tuple, cast

from IPython.core.compilerop import CachingCompiler
from IPython.core.interactiveshell import softspace
from streamflow.core.exception import WorkflowDefinitionException, WorkflowExecutionException
from streamflow.core.utils import check_termination, get_path_processor, get_token_value
from streamflow.core.workflow import CommandOutput, CommandOutputProcessor, Job, Port, Status, Token, Workflow
from streamflow.log_handler import logger
from streamflow.workflow.port import JobPort
from streamflow.workflow.step import BaseStep, DefaultCommandOutputProcessor, ScatterStep, TransferStep
from streamflow.workflow.token import FileToken, ListToken

from jupyter_workflow.ipython.displayhook import StreamFlowDisplayPublisher, StreamFlowShellDisplayHook
from jupyter_workflow.ipython.iostream import WorkflowOutStream
from jupyter_workflow.streamflow import executor, utils
from jupyter_workflow.streamflow.port import ProgramContextPort


class JupyterInputInjectorStep(BaseStep, ABC):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 context_port: ProgramContextPort,
                 job_port: JobPort):
        super().__init__(name, workflow)
        self.add_input_port("__job__", job_port)
        self.add_input_port("__context__", context_port)

    def add_output_port(self, name: str, port: Port) -> None:
        if not self.output_ports or port.name in self.output_ports:
            super().add_output_port(name, port)
        else:
            raise WorkflowDefinitionException("{} step must contain a single output port.".format(self.name))

    async def run(self):
        input_ports = {k: v for k, v in self.get_input_ports().items() if k not in ['__context__', '__job__']}
        if len(input_ports) != 1:
            raise WorkflowDefinitionException("{} step must contain a single input port.".format(self.name))
        if len(self.output_ports) != 1:
            raise WorkflowDefinitionException("{} step must contain a single output port.".format(self.name))
        if input_ports:
            while True:
                # Retrieve input token
                token = next(iter((await self._get_inputs(input_ports)).values()))
                # Check for termination
                if check_termination(token):
                    break
                # Retrieve job
                job = await cast(JobPort, self.get_input_port("__job__")).get_job(self.name)
                if job is None:
                    raise WorkflowExecutionException("Step {} received a null job".format(self.name))
                # Retrieve context
                user_ns = await cast(ProgramContextPort, self.get_input_port("__context__")).get_context(self.name)
                if user_ns is None:
                    raise WorkflowExecutionException("Step {} received a null program context".format(self.name))
                # Process value and inject token in the output port
                self.get_output_port().put(await self.process_input(job, user_ns, token.value))
        # Terminate step
        self.terminate(Status.SKIPPED if self.get_output_port().empty() else Status.COMPLETED)

    @abstractmethod
    async def process_input(self,
                            job: Job,
                            user_ns: MutableMapping[str, Any],
                            token_value: Any) -> Token:
        ...


class JupyterFileInputInjectorStep(JupyterInputInjectorStep):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 context_port: ProgramContextPort,
                 job_port: JobPort,
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow, context_port, job_port)
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process_input(self,
                            job: Job,
                            user_ns: MutableMapping[str, Any],
                            token_value: Any):
        return await utils.get_file_token_from_ns(
            context=self.workflow.context,
            job=job,
            user_ns=user_ns,
            value=self.value,
            value_from=self.value_from)


class JupyterNameInputInjectorStep(JupyterInputInjectorStep):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 context_port: ProgramContextPort,
                 job_port: JobPort,
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow, context_port, job_port)
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process_input(self,
                            job: Job,
                            user_ns: MutableMapping[str, Any],
                            token_value: Any):
        return utils.get_token_from_ns(
            job=job,
            user_ns=user_ns,
            value=self.value,
            value_from=self.value_from)


class JupyterNotebookStep(BaseStep):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 ast_nodes: List[Tuple[ast.AST, str]],
                 autoawait: bool,
                 compiler: CachingCompiler,
                 context_port: ProgramContextPort):
        super().__init__(name, workflow)
        self.ast_nodes: List[Tuple[ast.AST, str]] = ast_nodes
        self.autoawait: bool = autoawait
        self.compiler: CachingCompiler = compiler
        self.output_processors: MutableMapping[str, CommandOutputProcessor] = {}
        self.add_input_port('__context__', context_port)
        self.add_output_port('__context__', workflow.create_port(cls=ProgramContextPort))

    async def _retrieve_output(self,
                               job: Job,
                               output_name: str,
                               output_port: Port,
                               command_output: CommandOutput) -> None:
        if (token := await self.output_processors[output_name].process(job, command_output)) is not None:
            output_port.put(token)

    async def _run_ast_nodes(self, inputs: MutableMapping[str, Token]):
        logger.info("Executing cell {} on notebook's context".format(self.name))
        # Update context
        user_ns = await cast(ProgramContextPort, self.get_input_port('__context__')).get_context(self.name)
        if user_ns is None:
            raise WorkflowExecutionException("Step {} received a null program context".format(self.name))
        user_ns.update({k: get_token_value(v) for k, v in inputs.items()})
        # Set cell name in stdout and stderr
        cast(WorkflowOutStream, sys.stdout).set_cell_id(self.name)
        cast(WorkflowOutStream, sys.stderr).set_cell_id(self.name)
        # Set cell name in displayhook
        cast(StreamFlowShellDisplayHook, sys.displayhook).set_cell_id(self.name)
        # Set cell name in display publisher
        cast(StreamFlowDisplayPublisher, user_ns['get_ipython']().display_pub).set_cell_id(self.name)
        # Run code locally
        await executor.run_ast_nodes(
            ast_nodes=self.ast_nodes,
            autoawait=self.autoawait,
            compiler=self.compiler,
            user_ns=user_ns)
        # Flush softspace
        if softspace(sys.stdout, 0):
            print()
        # Propagate the new context
        self.get_output_context_port().put_context(user_ns)

    def add_output_port(self,
                        name: str,
                        port: Port,
                        output_processor: CommandOutputProcessor = None) -> None:
        super().add_output_port(name, port)
        self.output_processors[name] = output_processor or DefaultCommandOutputProcessor(name, self.workflow)

    def get_output_context_port(self) -> ProgramContextPort:
        return cast(ProgramContextPort, self.get_output_port('__context__'))

    async def run(self):
        input_ports = {k: v for k, v in self.get_input_ports().items() if k != '__context__'}
        # If there are input ports create jobs until termination token are received
        if input_ports:
            while True:
                # Retrieve input tokens
                inputs = await self._get_inputs(input_ports)
                # Check for termination
                if check_termination(inputs.values()):
                    break
                # Run code locally
                await self._run_ast_nodes(inputs)
        # Otherwise simply run job
        else:
            # Run code locally
            await self._run_ast_nodes({})
        # Terminate step
        self.terminate(Status.SKIPPED if self.get_output_context_port().empty() else Status.COMPLETED)


class JupyterScatterStep(ScatterStep):

    def _scatter(self, token: Token):
        if isinstance(token.value, Token):
            self._scatter(token.value)
        elif isinstance(token, ListToken):
            output_port = self.get_output_port()
            for i, t in enumerate(token.value):
                t = t.retag(token.tag + '.' + str(i))
                output_port.put(t.update([t.value]))
        else:
            raise WorkflowDefinitionException("Scatter ports require iterable inputs")


class JupyterTransferStep(TransferStep):

    async def _transfer(self,
                        job: Job,
                        path: str):
        dst_connector = self.workflow.context.scheduler.get_connector(job.name)
        dst_path_processor = get_path_processor(dst_connector)
        dst_locations = self.workflow.context.scheduler.get_locations(job.name)
        source_location = self.workflow.context.data_manager.get_source_location(
            path=path,
            dst_deployment=dst_connector.deployment_name)
        src_connector = self.workflow.context.deployment_manager.get_connector(source_location.deployment)
        dst_path = dst_path_processor.join(job.input_directory, source_location.relpath)
        logger.error(source_location.path)
        logger.error(dst_path)
        await self.workflow.context.data_manager.transfer_data(
            src_deployment=src_connector.deployment_name,
            src_locations=[source_location.location],
            src_path=source_location.path,
            dst_deployment=dst_connector.deployment_name,
            dst_locations=dst_locations,
            dst_path=dst_path)
        return dst_path

    async def transfer(self, job: Job, token: Token) -> Token:
        if isinstance(token, ListToken):
            return token.update(await asyncio.gather(*(asyncio.create_task(
                self.transfer(job, t)) for t in token.value)))
        elif isinstance(token, FileToken):
            token_value = get_token_value(token)
            dst_path = await self._transfer(job, token_value)
            return token.update(dst_path)
        else:
            return token
