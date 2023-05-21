import ast
import json
from typing import Any, MutableMapping, MutableSequence

from streamflow.core.context import StreamFlowContext
from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.persistence import DatabaseLoadingContext
from streamflow.core.workflow import Token, Workflow
from streamflow.workflow.token import ListToken
from streamflow.workflow.transformer import OneToOneTransformer
from streamflow.workflow.utils import get_token_value

from jupyter_workflow.config.config import SplitType
from jupyter_workflow.streamflow.token import JupyterToken


def _flatten_list(
    token_list: MutableSequence[Token], buffer: MutableSequence[Token]
) -> MutableSequence[Token]:
    for token in token_list:
        if isinstance(token, ListToken):
            return _flatten_list(token.value, buffer)
        else:
            buffer.append(token)
            return buffer


class ListJoinTransformer(OneToOneTransformer):
    def _transform(self, token: Token):
        if isinstance(token, ListToken):
            value = []
            for t in token.value:
                value.extend(t.value)
            return token.update(value)
        else:
            raise WorkflowExecutionException(
                self.name + " step must receive a list input."
            )

    async def transform(
        self, inputs: MutableMapping[str, Token]
    ) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.values())))}


class MakeListTransformer(OneToOneTransformer):
    def __init__(
        self, name: str, split_size: int, split_type: SplitType, workflow: Workflow
    ):
        super().__init__(name, workflow)
        self.split_type: SplitType = split_type
        self.split_size: int = split_size

    @classmethod
    async def _load(
        cls,
        context: StreamFlowContext,
        row: MutableMapping[str, Any],
        loading_context: DatabaseLoadingContext,
    ):
        params = json.loads(row["params"])
        return cls(
            name=row["name"],
            workflow=await loading_context.load_workflow(context, row["workflow"]),
            split_type=SplitType[params["split_type"]],
            split_size=params["split_size"],
        )

    async def _save_additional_params(
        self, context: StreamFlowContext
    ) -> MutableMapping[str, Any]:
        return {
            **await super()._save_additional_params(context),
            **{"split_type": self.split_type.name, "split_size": self.split_size},
        }

    def _transform(self, token: Token):
        token_list = []
        token_value = get_token_value(token)
        size = len(token_value)
        if self.split_type == SplitType.size:
            for i in range(0, size, self.split_size):
                token_list.append(
                    JupyterToken(
                        tag=token.tag,
                        value=token_value[i : min(i + self.split_size, size)],
                    )
                )
        else:
            d, r = divmod(size, self.split_size)
            for i in range(self.split_size):
                si = (d + 1) * (i if i < r else r) + d * (0 if i < r else i - r)
                token_list.append(
                    JupyterToken(
                        tag=token.tag,
                        value=token_value[si : si + (d + 1 if i < r else d)],
                    )
                )
        return ListToken(tag=token.tag, value=token_list)

    async def transform(
        self, inputs: MutableMapping[str, Token]
    ) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.values())))}


class OutputJoinTransformer(OneToOneTransformer):
    def _transform(self, token: Token):
        if isinstance(token, ListToken):
            output = []
            is_list = False
            for value in [t.value for t in token.value]:
                try:
                    value = ast.literal_eval(value)
                except BaseException:
                    pass
                if isinstance(value, MutableSequence):
                    is_list = True
                    output.extend(value)
                else:
                    output.append(value)
            if is_list:
                return Token(
                    tag=token.tag,
                    value="[{}]".format(", ".join([str(v) for v in output])),
                )
            else:
                return Token(
                    tag=token.tag,
                    value="\n".join([str(v) for v in output if str(v) != ""]),
                )
        else:
            raise WorkflowExecutionException(
                self.name + " step must receive a list input."
            )

    async def transform(
        self, inputs: MutableMapping[str, Token]
    ) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.values())))}
