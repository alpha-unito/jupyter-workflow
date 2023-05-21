from typing import Any, MutableMapping, Optional

from streamflow.core.workflow import Port
from streamflow.workflow.token import TerminationToken

from jupyter_workflow.streamflow.token import ProgramContextToken


class ProgramContextPort(Port):
    async def get_context(self, consumer: str) -> Optional[MutableMapping[str, Any]]:
        token = await self.get(consumer)
        if isinstance(token, TerminationToken):
            return None
        else:
            return token.value

    def put_context(self, context: MutableMapping[str, Any]):
        self.put(ProgramContextToken(value=context))
