import json
from typing import Any, MutableMapping, MutableSequence

from cloudpickle import dumps, loads
from streamflow.core.context import StreamFlowContext
from streamflow.core.data import DataType
from streamflow.core.exception import UnrecoverableTokenException
from streamflow.core.persistence import DatabaseLoadingContext
from streamflow.core.workflow import Token
from streamflow.data import remotepath
from streamflow.workflow.token import FileToken
from streamflow.workflow.utils import get_token_value


async def _get_file_token_weight(
    context: StreamFlowContext, paths: MutableSequence[str]
):
    weight = 0
    for path in paths:
        data_locations = context.data_manager.get_data_locations(
            path=path, location_type=DataType.PRIMARY
        )
        if data_locations:
            connector = context.deployment_manager.get_connector(
                list(data_locations)[0].deployment
            )
            location = list(data_locations)[0]
            real_path = await remotepath.follow_symlink(
                context, connector, location, path
            )
            weight += await remotepath.size(connector, location, real_path)
    return weight


class JupyterFileToken(FileToken):
    async def get_paths(self, context: StreamFlowContext) -> MutableSequence[str]:
        value = get_token_value(self)
        return [value]

    async def get_weight(self, context):
        return await _get_file_token_weight(context, await self.get_paths(context))


class JupyterToken(Token):
    @classmethod
    async def _load(
        cls,
        context: StreamFlowContext,
        row: MutableMapping[str, Any],
        loading_context: DatabaseLoadingContext,
    ) -> Token:
        value = json.loads(row["value"])
        if isinstance(value, MutableMapping) and "token" in value:
            value = await loading_context.load_token(context, value["token"])
        else:
            value = loads(bytes.fromhex(value))
        return cls(tag=row["tag"], value=value)

    async def _save_value(self, context: StreamFlowContext):
        return (
            {"token": self.value.persistent_id}
            if isinstance(self.value, Token)
            else dumps(self.value).hex()
        )


class ProgramContextToken(Token):
    @classmethod
    async def _load(
        cls,
        context: StreamFlowContext,
        row: MutableMapping[str, Any],
        loading_context: DatabaseLoadingContext,
    ) -> Token:
        value = json.loads(row["value"])
        if isinstance(value, MutableMapping) and "token" in value:
            value = await loading_context.load_token(context, value["token"])
        else:
            names = globals()
            for name in value:
                if name in names:
                    value = names[name]
                else:
                    raise UnrecoverableTokenException(
                        f"Variable {name} cannot be restored from the current program context."
                    )
        return cls(tag=row["tag"], value=value)

    async def _save_value(self, context: StreamFlowContext):
        return list(self.value.keys())
