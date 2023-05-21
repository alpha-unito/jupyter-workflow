import asyncio
import builtins
import posixpath
from typing import Any, MutableMapping, MutableSequence

from streamflow.core import utils
from streamflow.core.context import StreamFlowContext
from streamflow.core.deployment import Connector, Location, Target
from streamflow.core.workflow import Job, Token, Workflow
from streamflow.data import remotepath
from streamflow.deployment.utils import get_path_processor
from streamflow.workflow.step import DeployStep
from streamflow.workflow.token import ListToken

from jupyter_workflow.streamflow.token import JupyterFileToken, JupyterToken


async def _register_path(context: StreamFlowContext, job: Job, path: str):
    connector = context.scheduler.get_connector(job.name)
    path_processor = get_path_processor(connector)
    locations = context.scheduler.get_locations(job.name)
    relpath = (
        path_processor.relpath(path, job.output_directory)
        if path.startswith(job.output_directory)
        else path_processor.basename(path)
    )
    for location in locations:
        if await remotepath.exists(connector, location, path):
            context.data_manager.register_path(
                location=location, path=path, relpath=relpath
            )


def get_deploy_step(
    deployment_map: MutableMapping[str, DeployStep], target: Target, workflow: Workflow
):
    if target.deployment.name not in deployment_map:
        deployment_map[target.deployment.name] = workflow.create_step(
            cls=DeployStep,
            name=posixpath.join("__deploy__", target.deployment.name),
            deployment_config=target.deployment,
        )
    return deployment_map[target.deployment.name]


async def get_file_token_from_ns(
    context: StreamFlowContext,
    connector: Connector,
    job: Job,
    locations: MutableSequence[Location],
    output_directory: str,
    user_ns: MutableMapping[str, Any],
    value: Any,
    value_from: str,
) -> Token:
    path_processor = get_path_processor(connector)
    if value is not None:
        pattern = (
            value
            if path_processor.isabs(value)
            else path_processor.join(output_directory, value)
        )
        value = utils.flatten_list(
            await asyncio.gather(
                *(
                    asyncio.create_task(
                        remotepath.resolve(
                            connector=connector, location=location, pattern=pattern
                        )
                    )
                    for location in locations
                )
            )
        )
        value = [
            v if path_processor.isabs(v) else path_processor.join(output_directory, v)
            for v in value
        ]
        await asyncio.gather(
            *(
                asyncio.create_task(_register_path(context=context, job=job, path=v))
                for v in value
            )
        )
        if len(value) == 1:
            value = value[0]
    else:
        value = user_ns.get(value_from)
        if not path_processor.isabs(value):
            value = path_processor.join(output_directory, value)
        await _register_path(context=context, job=job, path=value)
    if isinstance(value, MutableSequence):
        return ListToken(
            tag=utils.get_tag(job.inputs.values()),
            value=[JupyterFileToken(value=v) for v in value],
        )
    else:
        return JupyterFileToken(tag=utils.get_tag(job.inputs.values()), value=value)


def get_token_from_ns(
    job: Job, user_ns: MutableMapping[str, Any], value: Any, value_from: str
) -> Token:
    value = (
        value
        if value is not None
        else user_ns.get(value_from, builtins.__dict__.get(value_from))
    )
    if isinstance(value, MutableSequence):
        return ListToken(
            tag=utils.get_tag(job.inputs.values()),
            value=[JupyterToken(value=v) for v in value],
        )
    else:
        return JupyterToken(tag=utils.get_tag(job.inputs.values()), value=value)
