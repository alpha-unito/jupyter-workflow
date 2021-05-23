import ast
import asyncio
import json
import os
from asyncio.subprocess import STDOUT
from tempfile import NamedTemporaryFile, TemporaryDirectory, mkdtemp
from typing import MutableMapping, Any, Tuple, MutableSequence
from typing import Optional, List

import dill
from IPython.core.compilerop import CachingCompiler
from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.utils import get_path_processor, random_name
from streamflow.core.workflow import Command, Status
from streamflow.core.workflow import Job, CommandOutput, Step
from streamflow.log_handler import logger
from streamflow.workflow.port import ScatterInputPort
from typing_extensions import Text

from jupyter_workflow.streamflow import executor


class JupyterCommandOutput(CommandOutput):

    def __init__(self,
                 value: Any,
                 status: Status,
                 user_ns: MutableMapping[Text, Any]):
        super().__init__(value, status)
        self.user_ns: MutableMapping[Text, Any] = user_ns


class JupyterCommandToken(object):

    def __init__(self,
                 name: Text,
                 token_type: Text,
                 serializer: Optional[MutableMapping[Text, Any]] = None):
        self.name: Text = name
        self.token_type: Text = token_type
        self.serializer: Optional[MutableMapping[Text, Any]] = serializer


class JupyterCommand(Command):

    def __init__(self,
                 step: Step,
                 ast_nodes: List[Tuple[ast.AST, Text]],
                 compiler: CachingCompiler,
                 interpreter: Text,
                 input_tokens: MutableMapping[Text, JupyterCommandToken],
                 output_tokens: MutableMapping[Text, JupyterCommandToken],
                 autoawait: bool,
                 stderr: Optional[Text] = None,
                 stdin: Optional[Text] = None,
                 stdout: Optional[Text] = None):
        super().__init__(step)
        self.ast_nodes: List[Tuple[ast.AST, Text]] = ast_nodes
        self.compiler: CachingCompiler = compiler
        self.interpreter: Text = interpreter
        self.input_tokens: MutableMapping[Text, JupyterCommandToken] = input_tokens
        self.output_tokens: MutableMapping[Text, JupyterCommandToken] = output_tokens
        self.autoawait: bool = autoawait
        self.stderr: Optional[Text] = stderr
        self.stdin: Optional[Text] = stdin
        self.stdout: Optional[Text] = stdout

    async def _deserialize_namespace(self,
                                     job: Job,
                                     output_serializers: MutableMapping[Text, Any],
                                     remote_path: Text) -> MutableMapping[Text, Any]:
        if remote_path:
            with TemporaryDirectory() as d:
                path_processor = get_path_processor(self.step)
                dest_path = os.path.join(d, path_processor.basename(remote_path))
                await self.step.context.data_manager.transfer_data(
                    src=remote_path,
                    src_job=job,
                    dst=dest_path,
                    dst_job=None)
                with open(dest_path, 'rb') as f:
                    namespace = dill.load(f)
                for name, value in namespace.items():
                    if name in output_serializers:
                        intermediate_type = output_serializers[name].get('type', 'name')
                        if intermediate_type == 'file':
                            dest_path = os.path.join(mkdtemp(), path_processor.basename(namespace[name]))
                            await self.step.context.data_manager.transfer_data(
                                src=namespace[name],
                                src_job=job,
                                dst=dest_path,
                                dst_job=None)
                            namespace[name] = dest_path
                return {k: executor.postload(
                    compiler=self.compiler,
                    name=k,
                    value=v,
                    serializer=output_serializers.get(k)
                ) for k, v in namespace.items()}
        else:
            return {}

    async def _serialize_namespace(self,
                                   input_serializers: MutableMapping[Text, Any],
                                   job: Job,
                                   namespace: MutableMapping[Text, Any]) -> Text:
        for name, value in namespace.items():
            if name in input_serializers:
                intermediate_type = input_serializers[name].get('type', 'name')
                if intermediate_type == 'file':
                    namespace[name] = dill.dumps(await self._transfer_file(job, dill.loads(value)))
        try:
            return await self._serialize_to_remote_file(job, namespace)
        except BaseException:
            for k, v in namespace.items():
                if not dill.pickles(v, safe=True):
                    raise WorkflowExecutionException("Name {name} is not serializable".format(name=k))
            raise

    async def _serialize_to_remote_file(self, job: Job, element: Any) -> Text:
        with NamedTemporaryFile() as f:
            dill.dump(element, f, recurse=True)
            f.flush()
            return await self._transfer_file(job, f.name)

    async def _transfer_file(self, job: Job, path: Text) -> Text:
        path_processor = get_path_processor(self.step)
        dest_path = path_processor.join(job.input_directory, os.path.basename(path))
        await self.step.context.data_manager.transfer_data(
            src=path,
            src_job=None,
            dst=dest_path,
            dst_job=job,
            writable=True)
        return dest_path

    async def execute(self, job: Job) -> CommandOutput:
        connector = self.step.get_connector()
        # Transfer executor file to remote resource
        executor_path = await self._transfer_file(
            job,
            os.path.join(executor.__file__))
        # Modify code, environment and namespaces according to inputs
        input_names = {}
        environment = {}
        for token in job.inputs:
            if token.value is not None:
                command_token = self.input_tokens[token.name]
                token_value = ([token.value] if isinstance(self.step.input_ports[token.name], ScatterInputPort) else
                               token.value)
                if command_token.token_type == 'file':
                    input_names[token.name] = token_value
                elif command_token.token_type == 'name':
                    input_names[token.name] = token_value
                elif command_token.token_type == 'env':
                    environment[token.name] = token_value
        # List output names to be retrieved from remote context
        output_names = self.step.output_ports.keys()
        # Serialize AST nodes to remote resource
        code_path = await self._serialize_to_remote_file(job, self.ast_nodes)
        # Configure output fiel path
        path_processor = get_path_processor(self.step)
        output_path = path_processor.join(job.output_directory, random_name())
        # Extract serializers from command tokens
        input_serializers = {k: v.serializer for k, v in self.input_tokens.items() if v.serializer is not None}
        output_serializers = {k: v.serializer for k, v in self.output_tokens.items() if v.serializer is not None}
        # Serialize namespaces to remote resource
        user_ns_path = await self._serialize_namespace(
            input_serializers=input_serializers,
            job=job,
            namespace=input_names)
        # Create dictionaries of postload input serializers and predump output serializers
        postload_input_serializers = {k: {'postload': v['postload']}
                                      for k, v in input_serializers.items() if 'postload' in v}
        predump_output_serializers = {k: {'predump': v['predump']}
                                      for k, v in output_serializers.items() if 'predump' in v}
        # Parse command
        cmd = [self.interpreter, executor_path]
        if os.path.basename(self.interpreter) == 'ipython':
            cmd.append('--')
        if self.step.workdir:
            cmd.extend(["--workdir", self.step.workdir])
        if self.autoawait:
            cmd.append("--autoawait")
        cmd.extend(["--local-ns-file", user_ns_path])
        if postload_input_serializers:
            postload_serializers_path = await self._serialize_to_remote_file(job, postload_input_serializers)
            cmd.extend(["--postload-input-serializers", postload_serializers_path])
        if predump_output_serializers:
            predump_serializers_path = await self._serialize_to_remote_file(job, predump_output_serializers)
            cmd.extend(["--predump-output-serializers", predump_serializers_path])
        for name in output_names:
            cmd.extend(["--output-name", name])
        cmd.extend([code_path, output_path])
        # Execute command
        if connector is not None:
            resources = job.get_resources()
            logger.info('Executing job {job} on resource {resource} into directory {outdir}:\n{command}'.format(
                job=job.name,
                resource=resources[0] if resources else None,
                outdir=job.output_directory,
                command=' \\\n\t'.join(cmd),
            ))
            # If step is assigned to multiple resources, add the STREAMFLOW_HOSTS environment variable
            if len(resources) > 1:
                available_resources = await connector.get_available_resources(self.step.target.service)
                hosts = {k: v.hostname for k, v in available_resources.items() if k in resources}
                environment['STREAMFLOW_HOSTS'] = ','.join(hosts.values())
            # Configure standard streams
            stdin = self.stdin
            stdout = self.stdout if self.stdout is not None else STDOUT
            stderr = self.stderr if self.stderr is not None else stdout
            # Execute command
            result, exit_code = await connector.run(
                resources[0] if resources else None,
                cmd,
                environment=environment,
                workdir=job.output_directory,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr,
                capture_output=True,
                job_name=job.name)
        else:
            logger.info('Executing job {job} into directory {outdir}: \n{command}'.format(
                job=job.name,
                outdir=job.output_directory,
                command=' \\\n\t'.join(cmd)
            ))
            # Configure standard streams
            stdin = open(self.stdin, "rb") if self.stdin is not None else None
            stdout = open(self.stdout, "wb") if self.stdout is not None else None
            stderr = open(self.stderr, "wb") if self.stderr is not None else None
            # Execute command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=job.output_directory,
                env={**os.environ, **environment},
                stdin=stdin,
                stdout=stdout,
                stderr=stderr)
            result, error = await proc.communicate()
            exit_code = proc.returncode
            # Close streams
            if stdin is not None:
                stdin.close()
            if stdout is not None:
                stdout.close()
            if stderr is not None:
                stderr.close()
        # Retrieve outputs
        with TemporaryDirectory() as d:
            dest_path = os.path.join(d, path_processor.basename(output_path))
            await self.step.context.data_manager.transfer_data(
                src=output_path,
                src_job=job,
                dst=dest_path,
                dst_job=None)
            with open(dest_path, mode='r') as f:
                json_output = json.load(f)
        # Infer status
        status = Status[json_output[executor.CELL_STATUS]]
        if status == Status.COMPLETED:
            command_stdout = json_output[executor.CELL_OUTPUT]
            if isinstance(command_stdout, MutableSequence):  # TODO: understand why we obtain a list here
                command_stdout = command_stdout[0]
            user_ns = await self._deserialize_namespace(
                job=job,
                output_serializers=output_serializers,
                remote_path=json_output[executor.CELL_LOCAL_NS])
        else:
            command_stdout = json_output[executor.CELL_OUTPUT]
            user_ns = {}
        # Return the command output object
        return JupyterCommandOutput(
            value=command_stdout,
            status=status,
            user_ns=user_ns)
