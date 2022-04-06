from typing import Optional

from streamflow.core.workflow import CommandOutputProcessor, Job, Token, Workflow

from jupyter_workflow.streamflow import utils
from jupyter_workflow.streamflow.command import JupyterCommandOutput


class JupyterFileCommandOutputProcessor(CommandOutputProcessor):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow)
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process(self, job: Job, command_output: JupyterCommandOutput) -> Optional[Token]:
        return await utils.get_file_token_from_ns(
            context=self.workflow.context,
            job=job,
            user_ns=command_output.user_ns,
            value=self.value,
            value_from=self.value_from)


class JupyterNameCommandOutputProcessor(CommandOutputProcessor):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 value: Optional[str] = None,
                 value_from: Optional[str] = None):
        super().__init__(name, workflow)
        self.value: Optional[str] = value
        self.value_from: Optional[str] = value_from

    async def process(self, job: Job, command_output: JupyterCommandOutput) -> Optional[Token]:
        return utils.get_token_from_ns(
            job=job,
            user_ns=command_output.user_ns,
            value=self.value,
            value_from=self.value_from)
