from typing import Any, MutableMapping, Optional

from streamflow.core.workflow import Port, Token
from streamflow.workflow.token import TerminationToken


class ProgramContextPort(Port):

    async def get_context(self, consumer: str) -> Optional[MutableMapping[str, Any]]:
        token = await self.get(consumer)
        if isinstance(token, TerminationToken):
            return None
        else:
            return token.value

    def put_context(self, context: MutableMapping[str, Any]):
        self.put(Token(value=context))
