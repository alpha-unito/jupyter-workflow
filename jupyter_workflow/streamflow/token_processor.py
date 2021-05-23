import asyncio
import builtins
import os
from typing import Any, Set, Text, Optional, MutableMapping, MutableSequence

import dill
from IPython.core.compilerop import CachingCompiler
from streamflow.core import utils
from streamflow.core.workflow import Job, Token, Port
from streamflow.data import remotepath
from streamflow.workflow.port import DefaultTokenProcessor

from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.command import JupyterCommandOutput


class ControlTokenProcessor(DefaultTokenProcessor):

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        return Token(
            name=self.port.name,
            value=None,
            tag=utils.get_tag(job.inputs),
            job=job.name)


class FileTokenProcessor(DefaultTokenProcessor):

    def __init__(self,
                 port: Port,
                 value: Optional[Text] = None,
                 value_from: Optional[Text] = None):
        super().__init__(port)
        self.value: Optional[Text] = value
        self.value_from: Optional[Text] = value_from

    async def collect_output(self, token: Token, output_dir: Text) -> Token:
        if isinstance(token.job, MutableSequence):
            return token.update(await asyncio.gather(*[asyncio.create_task(
                self.collect_output(t, output_dir)
            ) for t in token.value]))
        elif isinstance(token.value, MutableSequence):
            token_list = await asyncio.gather(*[asyncio.create_task(
                self.collect_output(token.update(t), output_dir)
            ) for t in token.value])
            return token.update([t.value for t in token_list])
        context = self.port.step.context
        path_processor = utils.get_path_processor(self.port.step)
        src_path = token.value
        src_job = context.scheduler.get_job(token.job)
        dest_path = os.path.join(output_dir, path_processor.basename(src_path))
        # Transfer file to local destination
        await self.port.step.context.data_manager.transfer_data(
            src=src_path,
            src_job=src_job,
            dst=dest_path,
            dst_job=None,
            writable=True)
        # Update token
        return token.update(dest_path)

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        path_processor = utils.get_path_processor(self.port.step)
        if self.value is not None:
            connector = job.step.get_connector() if job is not None else None
            resources = job.get_resources() or [None]
            if job.output_directory and not path_processor.isabs(self.value):
                pattern = path_processor.join(job.output_directory, self.value)
            else:
                pattern = self.value
            token_value = utils.flatten_list(await asyncio.gather(*[asyncio.create_task(
                remotepath.resolve(
                    connector=connector,
                    target=resource,
                    pattern=pattern
                )) for resource in resources]))
            if len(token_value) == 1:
                token_value = token_value[0]
        else:
            token_value = command_output.user_ns.get(self.value_from)
        if job.output_directory:
            if isinstance(token_value, MutableSequence):
                token_value = [path_processor.join(job.output_directory, t) if not path_processor.isabs(t) else t
                               for t in token_value]
            else:
                if not path_processor.isabs(token_value):
                    token_value = path_processor.join(job.output_directory, token_value)
        return Token(
            name=self.port.name,
            value=token_value,
            job=job.name,
            tag=utils.get_tag(job.inputs))

    async def _register_data(self, job: Job, path: Text):
        connector = job.step.get_connector()
        resources = job.get_resources() or [None]
        register_path_tasks = []
        for resource in resources:
            register_path_tasks.append(asyncio.create_task(
                self.port.step.context.data_manager.register_path(connector, resource, path)))
        await asyncio.gather(*register_path_tasks)

    def get_related_resources(self, token: Token) -> Set[Text]:
        if isinstance(token.job, MutableSequence) or isinstance(token.value, MutableSequence):
            resources = set()
            for t in token.value:
                resources.update(self.get_related_resources(
                    t if isinstance(token.job, MutableSequence) else token.update(t)))
        context = self.port.step.context
        src_job = context.scheduler.get_job(token.job)
        resources = set(src_job.get_resources() if src_job else [])
        data_locations = set()
        for resource in resources:
            data_locations.update(context.data_manager.get_data_locations(resource, token.value))
        resources.update({loc.resource for loc in data_locations})
        return resources

    async def update_token(self, job: Job, token: Token) -> Token:
        if isinstance(token.job, MutableSequence):
            return token.update(await asyncio.gather(*[asyncio.create_task(
                self.update_token(job, t)
            ) for t in token.value]))
        elif isinstance(token.value, MutableSequence):
            token_list = await asyncio.gather(*[asyncio.create_task(
                self.update_token(job, token.update(t))
            ) for t in token.value])
            return token.update([t.value for t in token_list])
        path_processor = utils.get_path_processor(self.port.step)
        token_value = dill.loads(token.value) if isinstance(token.value, bytes) else token.value
        dest_path = path_processor.join(job.input_directory, os.path.basename(token_value))
        await self.port.step.context.data_manager.transfer_data(
            src=token_value,
            src_job=None,
            dst=dest_path,
            dst_job=job)
        return token.update(dill.dumps(dest_path))

    async def weight_token(self, job: Job, token_value: Any) -> int:
        if isinstance(token_value, MutableSequence):
            return sum(await asyncio.gather(*[asyncio.create_task(
                self.weight_token(job, v)
            ) for v in token_value]))
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
                 compiler: CachingCompiler,
                 serializer: MutableMapping[Text, Any] = None,
                 value: Optional[Text] = None,
                 value_from: Optional[Text] = None):
        super().__init__(port)
        self.compiler: CachingCompiler = compiler
        self.serializer: MutableMapping[Text, Any] = serializer
        self.value: Optional[Text] = value
        self.value_from: Optional[Text] = value_from

    async def collect_output(self, token: Token, output_dir: Text) -> Token:
        if isinstance(token.job, MutableSequence):
            return await super().collect_output(token, output_dir)
        return token.update(executor.postload(
            compiler=self.compiler,
            name=self.port.name,
            value=([dill.loads(v) for v in token.value]
                   if isinstance(token.value, MutableSequence) else dill.loads(token.value)),
            serializer=self.serializer))

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        value = executor.predump(
            compiler=self.compiler,
            name=self.port.name,
            value=(self.value if self.value is not None else
                   command_output.user_ns[self.value_from] if self.value_from in command_output.user_ns else
                   builtins.__dict__.get(self.value_from)),
            serializer=self.serializer)
        token_value = ([dill.dumps(v, recurse=True) for v in value] if isinstance(value, MutableSequence) else
                       dill.dumps(value, recurse=True))
        return Token(
            name=self.port.name,
            value=token_value,
            job=job.name,
            tag=utils.get_tag(job.inputs))


class OutputLogTokenProcessor(DefaultTokenProcessor):

    async def compute_token(self, job: Job, command_output: JupyterCommandOutput) -> Token:
        return Token(
            name=self.port.name,
            value=command_output.value,
            job=job.name,
            tag=utils.get_tag(job.inputs))
