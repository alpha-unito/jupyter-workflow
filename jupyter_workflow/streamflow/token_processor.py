import asyncio
import builtins
import os
from typing import Any, Set, Text, Optional, MutableMapping

import dill
from IPython.core.compilerop import CachingCompiler
from streamflow.core.utils import get_path_processor
from streamflow.core.workflow import Job, Token, Port
from streamflow.data import remotepath
from streamflow.workflow.port import DefaultTokenProcessor

from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.command import JupyterCommandOutput


class ControlTokenProcessor(DefaultTokenProcessor):

    def __init__(self,
                 port: Port,
                 name: Text):
        super().__init__(port)
        self.name: Text = name

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        return Token(name=self.port.name, value=None, job=job.name)


class FileTokenProcessor(DefaultTokenProcessor):

    def __init__(self,
                 port: Port,
                 name: Optional[Text] = None,
                 value: Optional[Text] = None,
                 value_from: Optional[Text] = None):
        super().__init__(port)
        self.name: Optional[Text] = name
        self.value: Optional[Text] = value
        self.value_from: Optional[Text] = value_from

    async def collect_output(self, token: Token, output_dir: Text) -> Token:
        context = self.port.step.context
        path_processor = get_path_processor(self.port.step)
        src_job = context.scheduler.get_job(token.job)
        src_path = token.value['src']
        if not path_processor.isabs(src_path):
            src_path = path_processor.join(src_job.output_directory, src_path)
        dest_path = os.path.join(output_dir, path_processor.basename(src_path))
        # Transfer file to local destination
        await self.port.step.context.data_manager.transfer_data(
            src=src_path,
            src_job=src_job,
            dst=dest_path,
            dst_job=None,
            writable=True)
        # Update token
        return token.update({**token.value, **{'dst': dest_path}})

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        token_value = {
            'name': self.name,
            'type': 'file',
            'src': (self.value if self.value is not None else
                    command_output.user_ns.get(self.value_from))
        }
        return Token(name=self.port.name, value=token_value, job=job.name)

    async def _register_data(self, job: Job, path: Text):
        connector = job.step.get_connector()
        resources = job.get_resources() or [None]
        if resources:
            register_path_tasks = []
            for resource in resources:
                register_path_tasks.append(asyncio.create_task(
                    self.port.step.context.data_manager.register_path(connector, resource, path)))
            await asyncio.gather(*register_path_tasks)
        else:
            await self.port.step.context.data_manager.register_path(connector, None, path)

    def get_related_resources(self, token: Token) -> Set[Text]:
        context = self.port.step.context
        resources = set(context.scheduler.get_job(token.job).get_resources())
        data_locations = set()
        for resource in resources:
            data_locations.update(context.data_manager.get_data_locations(resource, token.value))
        resources.update({l.resource for l in data_locations})
        return resources

    async def update_token(self, job: Job, token: Token) -> Token:
        filepath = token.value['src']
        path_processor = get_path_processor(self.port.step)
        dest_path = path_processor.join(job.input_directory, os.path.basename(filepath))
        await self.port.step.context.data_manager.transfer_data(
            src=filepath,
            src_job=None,
            dst=dest_path,
            dst_job=job)
        return token.update({**token.value, **{'dst': dill.dumps(dest_path)}})

    async def weight_token(self, job: Job, token_value: Any) -> int:
        if job is not None and job.get_resources():
            connector = job.step.get_connector()
            for resource in job.get_resources():
                return await remotepath.size(connector, resource, token_value)
            return 0
        else:
            return await remotepath.size(None, None, token_value) if token_value is not None else 0


class NameTokenProcessor(DefaultTokenProcessor):

    def __init__(self,
                 port: Port,
                 name: Text,
                 token_type: Text,
                 compiler: CachingCompiler,
                 serializer: MutableMapping[Text, Any] = None,
                 value: Optional[Text] = None,
                 value_from: Optional[Text] = None):
        super().__init__(port)
        self.name: Text = name
        self.token_type: Text = token_type
        self.compiler: CachingCompiler = compiler
        self.serializer: MutableMapping[Text, Any] = serializer
        self.value: Optional[Text] = value
        self.value_from: Optional[Text] = value_from

    async def collect_output(self, token: Token, output_dir: Text) -> Token:
        return token.update({
            'name': self.name,
            'type': self.token_type,
            'serializer': self.serializer,
            'value': executor.postload(
                compiler=self.compiler,
                name=self.name,
                value=dill.loads(token.value['value']),
                serializer=self.serializer)})

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        token_value = {
            'name': self.name,
            'type': self.token_type,
            'value': dill.dumps(executor.predump(
                compiler=self.compiler,
                name=self.name,
                value=(self.value if self.value is not None else
                       command_output.user_ns[self.value_from] if self.value_from in command_output.user_ns else
                       builtins.__dict__.get(self.value_from)),
                serializer=self.serializer), recurse=True)
        }
        if self.serializer is not None:
            token_value['serializer'] = self.serializer
        return Token(name=self.port.name, value=token_value, job=job.name)
