from __future__ import annotations

from streamflow.core.command import CommandOutputProcessor
from streamflow.core.deployment import Connector, Target
from streamflow.core.workflow import Job, Token, Workflow

from jupyter_workflow.streamflow import utils
from jupyter_workflow.streamflow.command import JupyterCommandOutput


class JupyterFileCommandOutputProcessor(CommandOutputProcessor):
    def __init__(
        self,
        name: str,
        workflow: Workflow,
        target: Target | None = None,
        value: str | None = None,
        value_from: str | None = None,
    ):
        super().__init__(name, workflow, target)
        self.value: str | None = value
        self.value_from: str | None = value_from

    async def process(
        self,
        job: Job,
        command_output: JupyterCommandOutput,
        connector: Connector | None = None,
    ) -> Token | None:
        return await utils.get_file_token_from_ns(
            context=self.workflow.context,
            connector=self._get_connector(connector, job),
            job=job,
            locations=await self._get_locations(connector, job),
            output_directory=(
                self.target.workdir if self.target else job.output_directory
            ),
            user_ns=command_output.user_ns,
            value=self.value,
            value_from=self.value_from,
        )


class JupyterNameCommandOutputProcessor(CommandOutputProcessor):
    def __init__(
        self,
        name: str,
        workflow: Workflow,
        value: str | None = None,
        value_from: str | None = None,
    ):
        super().__init__(name, workflow)
        self.value: str | None = value
        self.value_from: str | None = value_from

    async def process(
        self,
        job: Job,
        command_output: JupyterCommandOutput,
        connector: Connector | None = None,
    ) -> Token | None:
        return utils.get_token_from_ns(
            job=job,
            user_ns=command_output.user_ns,
            value=self.value,
            value_from=self.value_from,
        )
