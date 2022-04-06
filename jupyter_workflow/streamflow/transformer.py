import ast
from typing import MutableMapping, MutableSequence

from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.workflow import Token
from streamflow.workflow.token import ListToken
from streamflow.workflow.transformer import OneToOneTransformer


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

    def _transform(self, token: Token):
        if isinstance(token, ListToken):
            return token.update([self._transform(t) for t in token.value])
        else:
            return ListToken(tag=token.tag, value=[token])

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
