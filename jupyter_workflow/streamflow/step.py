import asyncio
from typing import Any, MutableMapping, Optional

import dill
from IPython.core.compilerop import CachingCompiler
from streamflow.core.exception import WorkflowDefinitionException
from streamflow.core.utils import get_path_processor, get_token_value
from streamflow.core.workflow import Job, Token, Workflow
from streamflow.workflow.port import JobPort
from streamflow.workflow.step import GatherStep, InputInjectorStep, ScatterStep, TransferStep
from streamflow.workflow.token import FileToken, ListToken

from jupyter_workflow.streamflow import utils


class JupyterFileInputInjectorStep(InputInjectorStep):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 job_port: JobPort,
                 user_ns: MutableMapping[str, Any],
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow, job_port)
        self.user_ns: MutableMapping[str, Any] = user_ns
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process_input(self, job: Job, token_value: Any):
        return await utils.get_file_token_from_ns(
            context=self.workflow.context,
            job=job,
            user_ns=self.user_ns,
            value=self.value,
            value_from=self.value_from)


class JupyterNameInputInjectorStep(InputInjectorStep):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 job_port: JobPort,
                 compiler: CachingCompiler,
                 user_ns: MutableMapping[str, Any],
                 serializer: Optional[MutableMapping[str, Any]] = None,
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow, job_port)
        self.compiler: CachingCompiler = compiler
        self.serializer: Optional[MutableMapping[str, Any]] = serializer
        self.user_ns: MutableMapping[str, Any] = user_ns
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process_input(self, job: Job, token_value: Any):
        return utils.get_token_from_ns(
            compiler=self.compiler,
            job=job,
            name=self.name,
            serializer=self.serializer,
            user_ns=self.user_ns,
            value=self.value,
            value_from=self.value_from)


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
            return token.update(dill.dumps(dst_path))
        else:
            return token
