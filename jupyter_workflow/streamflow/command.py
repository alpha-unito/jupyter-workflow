from __future__ import annotations

import ast
import asyncio
import codeop
import json
import logging
import os
import tempfile
import time
from asyncio.subprocess import STDOUT
from collections.abc import MutableMapping
from tempfile import TemporaryDirectory, mkdtemp
from typing import Any

import cloudpickle as pickle
from streamflow.core.command import Command, CommandOutput
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import ExecutionLocation, LocalTarget
from streamflow.core.utils import get_tag, random_name
from streamflow.core.workflow import Job, Status, Step
from streamflow.data.remotepath import StreamFlowPath
from streamflow.deployment.utils import get_path_processor
from streamflow.log_handler import logger
from streamflow.workflow.utils import get_token_value

from jupyter_workflow.streamflow import executor


async def _transfer_data(
    context: StreamFlowContext,
    location: ExecutionLocation,
    src: str,
    dst: str,
    relpath: str,
):
    if await StreamFlowPath(src, context=context, location=location).exists():
        context.data_manager.register_path(location=location, path=src, relpath=relpath)
    await context.data_manager.transfer_data(
        src_location=location,
        src_path=src,
        dst_locations=[
            ExecutionLocation(
                deployment=LocalTarget.deployment_name, local=True, name="__LOCAL__"
            )
        ],
        dst_path=dst,
    )


class JupyterCommandOutput(CommandOutput):
    def __init__(self, value: Any, status: Status, user_ns: MutableMapping[str, Any]):
        super().__init__(value, status)
        self.user_ns: MutableMapping[str, Any] = user_ns


class JupyterCommandToken:
    def __init__(
        self,
        name: str,
        token_type: str,
        serializer: MutableMapping[str, Any] | None = None,
    ):
        self.name: str = name
        self.token_type: str = token_type
        self.serializer: MutableMapping[str, Any] | None = serializer


class JupyterCommand(Command):
    def __init__(
        self,
        step: Step,
        ast_nodes: list[tuple[ast.AST, str]],
        compiler: codeop.Compile,
        interpreter: str,
        input_tokens: MutableMapping[str, JupyterCommandToken],
        output_tokens: MutableMapping[str, JupyterCommandToken],
        autoawait: bool,
        stderr: str | None = None,
        stdin: str | None = None,
        stdout: str | None = None,
    ):
        super().__init__(step)
        self.ast_nodes: list[tuple[ast.AST, str]] = ast_nodes
        self.compiler: codeop.Compile = compiler
        self.interpreter: str = interpreter
        self.input_tokens: MutableMapping[str, JupyterCommandToken] = input_tokens
        self.output_tokens: MutableMapping[str, JupyterCommandToken] = output_tokens
        self.autoawait: bool = autoawait
        self.stderr: str | None = stderr
        self.stdin: str | None = stdin
        self.stdout: str | None = stdout

    async def _deserialize_namespace(
        self, job: Job, output_serializers: MutableMapping[str, Any], src_path: str
    ) -> MutableMapping[str, Any]:
        if src_path:
            with TemporaryDirectory() as d:
                src_connector = self.step.workflow.context.scheduler.get_connector(
                    job.name
                )
                path_processor = get_path_processor(src_connector)
                dst_path = os.path.join(d, path_processor.basename(src_path))
                await asyncio.gather(
                    *(
                        asyncio.create_task(
                            self.step.workflow.context.data_manager.transfer_data(
                                src_location=location,
                                src_path=src_path,
                                dst_locations=[
                                    ExecutionLocation(
                                        deployment=LocalTarget.deployment_name,
                                        local=True,
                                        name="__LOCAL__",
                                    )
                                ],
                                dst_path=dst_path,
                            )
                        )
                        for location in self.step.workflow.context.scheduler.get_locations(
                            job.name
                        )
                    )
                )
                with open(dst_path, "rb") as f:
                    namespace = pickle.load(f)
                for name in namespace:
                    if name in output_serializers:
                        intermediate_type = output_serializers[name].get("type", "name")
                        if intermediate_type == "file":
                            dst_path = os.path.join(
                                mkdtemp(), path_processor.basename(namespace[name])
                            )
                            await asyncio.gather(
                                *(
                                    asyncio.create_task(
                                        self.step.workflow.context.data_manager.transfer_data(
                                            src_location=location,
                                            src_path=namespace[name],
                                            dst_locations=[
                                                ExecutionLocation(
                                                    deployment=LocalTarget.deployment_name,
                                                    local=True,
                                                    name="__LOCAL__",
                                                )
                                            ],
                                            dst_path=dst_path,
                                        )
                                    )
                                    for location in self.step.workflow.context.scheduler.get_locations(
                                        job.name
                                    )
                                )
                            )
                            namespace[name] = dst_path
                return {
                    k: executor.postload(
                        compiler=self.compiler,
                        name=k,
                        value=v,
                        serializer=output_serializers.get(k),
                    )
                    for k, v in namespace.items()
                }
        else:
            return {}

    async def _serialize_namespace(
        self,
        input_serializers: MutableMapping[str, Any],
        job: Job,
        namespace: MutableMapping[str, Any],
    ) -> str:
        for name, value in namespace.items():
            if name in input_serializers:
                value = executor.predump(
                    compiler=self.compiler,
                    name=name,
                    value=value,
                    serializer=input_serializers,
                )
                intermediate_type = input_serializers[name].get("type", "name")
                if intermediate_type == "file":
                    namespace[name] = await self._transfer_file(job, value)
        return await self._serialize_to_remote_file(job, namespace)

    async def _serialize_to_remote_file(self, job: Job, element: Any) -> str:
        fd, src_path = tempfile.mkstemp()
        with os.fdopen(fd, "wb") as f:
            pickle.dump(element, f)
            f.flush()
        self.step.workflow.context.data_manager.register_path(
            location=ExecutionLocation(
                deployment=LocalTarget.deployment_name, local=True, name="__LOCAL__"
            ),
            path=src_path,
            relpath=os.path.basename(src_path),
        )
        return await self._transfer_file(job, src_path)

    async def _transfer_file(self, job: Job, path: str) -> str:
        dst_connector = self.step.workflow.context.scheduler.get_connector(job.name)
        path_processor = get_path_processor(dst_connector)
        dst_path = path_processor.join(job.input_directory, os.path.basename(path))
        await self.step.workflow.context.data_manager.transfer_data(
            src_location=ExecutionLocation(
                deployment=LocalTarget.deployment_name, local=True, name="__LOCAL__"
            ),
            src_path=path,
            dst_locations=self.step.workflow.context.scheduler.get_locations(job.name),
            dst_path=dst_path,
            writable=True,
        )
        return dst_path

    async def execute(self, job: Job) -> CommandOutput:
        connector = self.step.workflow.context.scheduler.get_connector(job.name)
        locations = self.step.workflow.context.scheduler.get_locations(job.name)
        # Transfer executor file to remote resource
        executor_path = await self._transfer_file(job, os.path.join(executor.__file__))
        # Modify code, environment and namespaces according to inputs
        input_names = {}
        environment = {}
        for name, token in job.inputs.items():
            if (token_value := get_token_value(token)) is not None:
                command_token = self.input_tokens[name]
                if command_token.token_type in ["file", "name", "env"]:
                    input_names[name] = token_value
        # List output names to be retrieved from remote context
        output_names = [
            name
            for name, p in self.step.get_output_ports().items()
            if name != executor.CELL_OUTPUT
        ]
        # Serialize AST nodes to remote resource
        code_path = await self._serialize_to_remote_file(job, self.ast_nodes)
        # Configure output file path
        path_processor = get_path_processor(connector)
        output_name = random_name()
        output_path = path_processor.join(job.output_directory, output_name)
        # Extract serializers from command tokens
        input_serializers = {
            k: v.serializer
            for k, v in self.input_tokens.items()
            if v.serializer is not None
        }
        output_serializers = {
            k: v.serializer
            for k, v in self.output_tokens.items()
            if v.serializer is not None
        }
        # Serialize namespaces to remote resource
        user_ns_path = await self._serialize_namespace(
            input_serializers=input_serializers, job=job, namespace=input_names
        )
        # Create dictionaries of postload input serializers and predump output serializers
        postload_input_serializers = {
            k: {"postload": v["postload"]}
            for k, v in input_serializers.items()
            if "postload" in v
        }
        predump_output_serializers = {
            k: {"predump": v["predump"]}
            for k, v in output_serializers.items()
            if "predump" in v
        }
        # Parse command
        cmd = [self.interpreter, executor_path]
        if os.path.basename(self.interpreter) == "ipython":
            cmd.append("--")
        if self.autoawait:
            cmd.append("--autoawait")
        cmd.extend(["--local-ns-file", user_ns_path])
        if postload_input_serializers:
            postload_serializers_path = await self._serialize_to_remote_file(
                job, postload_input_serializers
            )
            cmd.extend(["--postload-input-serializers", postload_serializers_path])
        if predump_output_serializers:
            predump_serializers_path = await self._serialize_to_remote_file(
                job, predump_output_serializers
            )
            cmd.extend(["--predump-output-serializers", predump_serializers_path])
        for name in output_names:
            cmd.extend(["--output-name", name])
        cmd.extend(["--tmpdir", job.tmp_directory])
        cmd.extend([code_path, output_path])
        cmd_string = " \\\n\t".join(cmd)
        if logger.isEnabledFor(logging.INFO):
            logger.info(
                "EXECUTING step {step} (job {job}) {location} into directory {outdir}:\n{command}".format(
                    step=self.step.name,
                    job=job.name,
                    location=(
                        "locally"
                        if locations[0].local
                        else f"on location {locations[0]}"
                    ),
                    outdir=job.output_directory,
                    command=cmd_string,
                )
            )
        # Persist command
        execution_id = await self.step.workflow.context.database.add_execution(
            step_id=self.step.persistent_id,
            tag=get_tag(job.inputs.values()),
            cmd=cmd_string,
        )
        # If step is assigned to multiple locations, add the STREAMFLOW_HOSTS environment variable
        if len(locations) > 1:
            environment["STREAMFLOW_HOSTS"] = ",".join(
                [loc.hostname for loc in locations]
            )
        # Configure standard streams
        stdin = self.stdin
        stdout = self.stdout if self.stdout is not None else STDOUT
        stderr = self.stderr if self.stderr is not None else stdout
        # Execute command
        start_time = time.time_ns()
        result, exit_code = await connector.run(
            locations[0],
            cmd,
            environment=environment,
            workdir=job.output_directory,
            stdin=stdin,
            stdout=stdout,
            stderr=stderr,
            capture_output=True,
            job_name=job.name,
        )
        end_time = time.time_ns()
        # Handle exit codes
        if exit_code != 0:
            logger.error(
                f"Command {cmd_string} failed with exit code {exit_code}:\n{result}"
            )
            status = Status.FAILED
        else:
            status = Status.COMPLETED
        # Update command persistence
        await self.step.workflow.context.database.update_execution(
            execution_id,
            {
                "status": status.value,
                "start_time": start_time,
                "end_time": end_time,
            },
        )
        # Retrieve outputs
        dst_dir = tempfile.mkdtemp()
        dst_path = os.path.join(dst_dir, path_processor.basename(output_path))
        await asyncio.gather(
            *(
                asyncio.create_task(
                    _transfer_data(
                        context=self.step.workflow.context,
                        location=location,
                        src=output_path,
                        dst=dst_path,
                        relpath=output_name,
                    )
                )
                for location in locations
            )
        )
        with open(dst_path) as f:
            json_output = json.load(f)
        # Infer status
        status = Status[json_output[executor.CELL_STATUS]]
        user_ns = {}
        if status == Status.COMPLETED:
            command_stdout = json_output[executor.CELL_OUTPUT]
            if ns_path := json_output[executor.CELL_LOCAL_NS]:
                for location in locations:
                    sf_path = StreamFlowPath(
                        ns_path, context=self.step.workflow.context, location=location
                    )
                    if await sf_path.exists():
                        self.step.workflow.context.data_manager.register_path(
                            location=location,
                            path=str(sf_path),
                            relpath=sf_path.name,
                        )
                user_ns = await self._deserialize_namespace(
                    job=job, output_serializers=output_serializers, src_path=ns_path
                )
        else:
            command_stdout = json_output[executor.CELL_OUTPUT]
        # Return the command output object
        return JupyterCommandOutput(
            value=command_stdout, status=status, user_ns=user_ns
        )
