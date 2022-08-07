import ast
from typing import Any, MutableMapping, MutableSequence

from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.utils import get_token_value
from streamflow.core.workflow import Token, Workflow
from streamflow.workflow.token import ListToken
from streamflow.workflow.transformer import OneToOneTransformer


def _flatten_list(token_list: MutableSequence[Token],
                  buffer: MutableSequence[Token]) -> MutableSequence[Token]:
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
            raise WorkflowExecutionException(self.name + " step must receive a list input.")

    async def transform(self, inputs: MutableMapping[str, Token]) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.values())))}


class MakeListTransformer(OneToOneTransformer):

    def __init__(self,
                 name: str,
                 split_size: int,
                 split_type: str,
                 workflow: Workflow):
        super().__init__(name, workflow)
        self.split_type: str = split_type
        self.split_size: int = split_size

    def _split(self, token_value: MutableSequence[Any], tag: str):
        size = len(token_value)
        if self.split_type == 'size':
            for i in range(0, size, self.split_size):
                yield Token(
                    tag=tag,
                    value=token_value[i:max(i + self.split_size, size)])
        else:
            d, r = divmod(size, self.split_size)
            for i in range(self.split_size):
                si = (d + 1) * (i if i < r else r) + d * (0 if i < r else i - r)
                yield Token(
                    tag=tag,
                    value=token_value[si:si+(d+1 if i < r else d)])

    def _transform(self, token: Token):
        return ListToken(
            tag=token.tag,
            value=list(self._split(get_token_value(token), token.tag)))

    async def transform(self, inputs: MutableMapping[str, Token]) -> MutableMapping[str, Token]:
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
                    value="[{}]".format(', '.join([str(v) for v in output])))
            else:
                return Token(
                    tag=token.tag,
                    value='\n'.join([str(v) for v in output if str(v) != '']))
        else:
            raise WorkflowExecutionException(self.name + " step must receive a list input.")

    async def transform(self, inputs: MutableMapping[str, Token]) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.values())))}
