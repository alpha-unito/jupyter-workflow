import ast
import asyncio
import json
import os
import sys
from asyncio.subprocess import STDOUT
from tempfile import NamedTemporaryFile, TemporaryDirectory
from typing import MutableMapping, MutableSequence, Any, Tuple
from typing import Optional, List

import dill
from streamflow.core.utils import get_path_processor, random_name
from streamflow.core.workflow import Command, Status
from streamflow.core.workflow import Job, CommandOutput, Step
from streamflow.log_handler import logger
from typing_extensions import Text

from jupyter_workflow.ipython import executor


class JupyterCommandOutput(CommandOutput):

    def __init__(self,
                 value: Any,
                 status: Status,
                 user_ns: MutableMapping[Text, Any],
                 user_global_ns: Optional[MutableMapping[Text, Any]] = None):
        super().__init__(value, status)
        self.user_ns: MutableMapping[Text, Any] = user_ns
        self.user_global_ns: Optional[MutableMapping[Text, Any]] = user_global_ns


class JupyterCommand(Command):

    def __init__(self,
                 step: Step,
                 ast_nodes: List[Tuple[ast.AST, Text]],
                 environment: MutableMapping[Text, Text],
                 interpreter: Text,
                 input_names: MutableSequence[Text],
                 output_names: MutableSequence[Text],
                 user_ns: MutableMapping[Text, Any],
                 user_global_ns: MutableMapping[Text, Any],
                 autoawait: bool,
                 stderr: Optional[Text] = None,
                 stdin: Optional[Text] = None,
                 stdout: Optional[Text] = None):
        super().__init__(step)
        self.ast_nodes: List[Tuple[ast.AST, Text]] = ast_nodes
        self.environment: MutableMapping[Text, Text] = environment
        self.interpreter: Text = interpreter
        self.input_names: MutableSequence[Text] = input_names
        self.output_names: MutableSequence[Text] = output_names
        self.user_ns: MutableMapping[Text, Any] = user_ns
        self.user_global_ns: MutableMapping[Text, Any] = user_global_ns
        self.autoawait: bool = autoawait
        self.stderr: Optional[Text] = stderr
        self.stdin: Optional[Text] = stdin
        self.stdout: Optional[Text] = stdout

    async def _deserialize_namespace(self, job: Job, remote_path: Text) -> MutableMapping[Text, Any]:
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
                    return dill.load(f)
        else:
            return {}

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
            dst_job=job)
        return dest_path

    async def execute(self, job: Job) -> CommandOutput:
        connector = self.step.get_connector()
        # Transfer executor file to remote resource
        executor_path = await self._transfer_file(
            job,
            os.path.join(executor.__file__))
        # Modify code and namespaces according to inputs
        updated_names = {}
        for element in [t.value for t in job.inputs]:
            if 'name' in element:
                updated_names[element['name']] = element['dst']
            else:
                pass  # TODO: manipulate AST
        # Serialize AST nodes to remote resource
        code_path = await self._serialize_to_remote_file(job, self.ast_nodes)
        # Vonfigure output fiel path
        path_processor = get_path_processor(self.step)
        output_path = path_processor.join(job.output_directory, random_name())
        # Serialize namespaces to remote resource
        user_ns = {**self.user_ns, **updated_names}
        user_ns_path = await self._serialize_to_remote_file(
            job,
            {k: v for k, v in user_ns.items() if k in self.input_names})
        if self.user_global_ns != self.user_ns:
            user_global_ns = {**self.user_global_ns, **updated_names}
            user_global_ns_path = await self._serialize_to_remote_file(
                job,
                {k: v for k, v in user_global_ns.items() if k in self.input_names})
        else:
            user_global_ns_path = None
        # Parse command
        cmd = [self.interpreter, executor_path]
        if self.autoawait:
            cmd.append("--autoawait")
        cmd.extend(["--local-ns-file", user_ns_path])
        if user_global_ns_path is not None:
            cmd.extend(["--global-ns-file", user_global_ns_path])
        for name in self.output_names:
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
            parsed_env = self.environment
            if len(resources) > 1:
                available_resources = await connector.get_available_resources(self.step.target.service)
                hosts = {k: v.hostname for k, v in available_resources.items() if k in resources}
                parsed_env['STREAMFLOW_HOSTS'] = ','.join(hosts.values())
            # Configure standard streams
            stdin = self.stdin
            stdout = self.stdout if self.stdout is not None else STDOUT
            stderr = self.stderr if self.stderr is not None else stdout
            # Execute command
            result, exit_code = await connector.run(
                resources[0] if resources else None,
                cmd,
                environment=parsed_env,
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
            stdin = open(self.stdin, "rb") if self.stdin is not None else sys.stdin
            stdout = open(self.stdout, "wb") if self.stdout is not None else sys.stdout
            stderr = open(self.stderr, "wb") if self.stderr is not None else sys.stderr
            # Execute command
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                cwd=job.output_directory,
                env=self.environment,
                stdin=stdin,
                stdout=stdout,
                stderr=stderr
            )
            result, error = await proc.communicate()
            exit_code = proc.returncode
            # Close streams
            if stdin is not sys.stdin:
                stdin.close()
            if stdout is not sys.stderr:
                stdout.close()
            if stderr is not sys.stderr:
                stderr.close()
        # Infer status
        status = Status.COMPLETED if exit_code == 0 else Status.FAILED
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
        if status == Status.COMPLETED:
            command_stdout = json_output[executor.CELL_OUTPUT]
            if self.user_global_ns != self.user_ns:
                self.user_ns = {
                    **self.user_ns,
                    **await self._deserialize_namespace(job, json_output[executor.CELL_LOCAL_NS])}
                self.user_global_ns = {
                    **self.user_global_ns,
                    **(await self._deserialize_namespace(job, json_output[executor.CELL_GLOBAL_NS])
                       if executor.CELL_GLOBAL_NS in json_output else {})}
            else:
                self.user_global_ns = self.user_ns = {
                    **self.user_ns,
                    **await self._deserialize_namespace(job, json_output[executor.CELL_LOCAL_NS])}
        else:
            command_stdout = json_output[executor.CELL_OUTPUT]
        # Print the command stdout
        if command_stdout:
            print(command_stdout)
        # Return the command output object
        return JupyterCommandOutput(
            value=command_stdout,
            status=status,
            user_ns=self.user_ns,
            user_global_ns=self.user_global_ns)
