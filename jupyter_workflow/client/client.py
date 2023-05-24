from __future__ import annotations

from contextvars import ContextVar
from functools import partial
from typing import Any, MutableMapping, MutableSequence, cast

from jupyter_client import AsyncKernelClient, AsyncKernelManager, KernelManager
from jupyter_client.client import validate_string_dict
from jupyter_core.utils import run_sync, ensure_async
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

    def execute_workflow(
        self,
        cells: MutableSequence[NotebookNode],
        metadata: MutableMapping[str, Any],
    ) -> str:
        content = {"notebook": {"cells": cells, "metadata": metadata}}
        msg = self.session.msg("workflow_request", content)
        self.shell_channel.send(msg)
        return msg["header"]["msg_id"]


class WorkflowKernelManager(AsyncKernelManager):
    client_factory: Type = Type(
        klass="jupyter_workflow.client.client.WorkflowKernelClient"
    )


class WorkflowClient(NotebookClient):
    def __init__(self, nb: NotebookNode, **kw: Any):
        super().__init__(nb, **kw)
        self.kernel_manager_class = WorkflowKernelManager
        self.on_cell_execute = partial(on_cell_execute, client=self)

    async def async_execute_workflow(
        self, reset_kc: bool = False, **kwargs: Any
    ) -> NotebookNode:
        if reset_kc and self.owns_km:
            await self._async_cleanup_kernel()
        self.reset_execution_trackers()

        async with self.async_setup_kernel(**kwargs):
            assert self.kc is not None
            self.log.info("Executing notebook with kernel: %s" % self.kernel_name)
            msg_id = await ensure_async(self.kc.kernel_info())
            info_msg = await self.async_wait_for_reply(msg_id)
            if info_msg is not None:
                if "language_info" in info_msg["content"]:
                    self.nb.metadata["language_info"] = info_msg["content"][
                        "language_info"
                    ]
                else:
                    raise RuntimeError(
                        'Kernel info received message content has no "language_info" key. '
                        "Content is:\n" + str(info_msg["content"])
                    )

            cells = {}
            for index, cell in enumerate(self.nb.cells):
                if cell.cell_type != "code" or not cell.source.strip():
                    self.log.debug("Skipping non-executing cell %s", index)
                elif self.skip_cells_with_tag in cell.metadata.get("tags", []):
                    self.log.debug("Skipping tagged cell %s", index)
                else:
                    cells[index] = cell

            for cell in cells.values():
                if self.record_timing:
                    cell["metadata"]["execution"] = {}
                if "workflow" in cell["metadata"]:
                    cell["metadata"]["workflow"]["cell_id"] = cell.id

            parent_msg_id = await ensure_async(
                cast(WorkflowKernelClient, self.kc).execute_workflow(
                    cells=list(cells.values()), metadata=self.nb.metadata
                )
            )
            self.set_widgets_metadata()
        return self.nb

    execute = run_sync(async_execute_workflow)


def execute(
    nb: NotebookNode,
    cwd: str | None = None,
    km: KernelManager | None = None,
    **kwargs: Any,
) -> NotebookNode:
    resources = {}
    if cwd is not None:
        resources["metadata"] = {"path": cwd}
    return WorkflowClient(nb=nb, resources=resources, km=km, **kwargs).execute()
