from __future__ import annotations

from contextvars import ContextVar
from typing import Any

from jupyter_client import AsyncKernelClient, AsyncKernelManager
from jupyter_client.client import validate_string_dict
from nbclient import NotebookClient
from nbformat import NotebookNode
from traitlets import Type


async def on_cell_execute(
    client: NotebookClient, cell: NotebookNode, cell_index: int
) -> None:
    if isinstance(client.kc, WorkflowKernelClient):
        client.kc.metadata.set(
            {**cell.metadata.get("workflow", {}), **{"cell_id": cell.id}}
        )


class WorkflowKernelClient(AsyncKernelClient):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.metadata: ContextVar = ContextVar("metadata", default={})

    def execute(
        self,
        code: str,
        silent: bool = False,
        store_history: bool = True,
        user_expressions: dict[str, Any] | None = None,
        allow_stdin: bool | None = None,
        stop_on_error: bool = True,
    ) -> str:
        if user_expressions is None:
            user_expressions = {}
        if allow_stdin is None:
            allow_stdin = self.allow_stdin
        if not isinstance(code, str):
            raise ValueError("code %r must be a string" % code)
        validate_string_dict(user_expressions)
        content = {
            "code": code,
            "silent": silent,
            "store_history": store_history,
            "user_expressions": user_expressions,
            "allow_stdin": allow_stdin,
            "stop_on_error": stop_on_error,
            "workflow": self.metadata.get(),
        }
        msg = self.session.msg("execute_request", content)
        self.shell_channel.send(msg)
        return msg["header"]["msg_id"]


class WorkflowKernelManager(AsyncKernelManager):
    client_factory: Type = Type(
        klass="jupyter_workflow.client.client.WorkflowKernelClient"
    )
