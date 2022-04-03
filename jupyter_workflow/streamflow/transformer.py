import ast
from typing import Any, MutableMapping, MutableSequence, Text, cast

import dill
from IPython.core.compilerop import CachingCompiler
from streamflow.core.exception import WorkflowExecutionException
from streamflow.core.utils import get_token_value
from streamflow.core.workflow import Token, Workflow
from streamflow.workflow.token import ListToken
from streamflow.workflow.transformer import OneToOneTransformer

from jupyter_workflow.streamflow import executor


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


class PostLoadTransformer(OneToOneTransformer):

    def __init__(self,
                 name: str,
                 workflow: Workflow,
                 compiler: CachingCompiler,
                 serializer: MutableMapping[Text, Any] = None):
        super().__init__(name, workflow)
        self.compiler: CachingCompiler = compiler
        self.serializer: MutableMapping[Text, Any] = serializer

    def _transform(self, name: str, token: Token):
        if isinstance(token, ListToken):
            return token.update([self._transform(name, t) for t in token.value])
        else:
            return token.update(executor.postload(
                compiler=self.compiler,
                name=name,
                value=(dill.loads(get_token_value(token))),
                serializer=self.serializer))

    async def transform(self, inputs: MutableMapping[str, Token]) -> MutableMapping[str, Token]:
        return {self.get_output_name(): self._transform(next(iter(inputs.keys())), next(iter(inputs.values())))}


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
