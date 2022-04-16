from typing import MutableSequence

from streamflow.core.context import StreamFlowContext
from streamflow.core.data import DataType
from streamflow.core.utils import get_token_value
from streamflow.data import remotepath
from streamflow.workflow.token import FileToken


async def _get_file_token_weight(context: StreamFlowContext,
                                 paths: MutableSequence[str]):
    weight = 0
    for path in paths:
        data_locations = context.data_manager.get_data_locations(
            path=path,
            location_type=DataType.PRIMARY)
        if data_locations:
            connector = context.deployment_manager.get_connector(list(data_locations)[0].deployment)
            location = list(data_locations)[0].location
            real_path = await remotepath.follow_symlink(connector, location, path)
            weight += await remotepath.size(connector, location, real_path)
    return weight


class JupyterFileToken(FileToken):

    async def get_paths(self, context: StreamFlowContext) -> MutableSequence[str]:
        value = get_token_value(self)
        return [value]

    async def get_weight(self, context):
        return await _get_file_token_weight(context, await self.get_paths(context))
