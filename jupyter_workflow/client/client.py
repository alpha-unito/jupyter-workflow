from __future__ import annotations

import asyncio
from contextvars import ContextVar
from functools import partial
from typing import Any, MutableMapping, MutableSequence, cast

import traitlets
from jupyter_client import AsyncKernelClient, AsyncKernelManager, KernelManager
from jupyter_client.client import validate_string_dict
from jupyter_core.utils import ensure_async, run_sync
from nbclient import NotebookClient
from nbclient.client import timestamp
from nbclient.exceptions import (
    CellControlSignal,
    CellExecutionComplete,
    DeadKernelError,
)
from nbformat import NotebookNode
from streamflow.core.exception import WorkflowExecutionException


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
        cells: MutableSequence[MutableMapping[str, Any]],
        metadata: MutableMapping[str, Any],
    ) -> str:
        content = {"notebook": {"cells": cells, "metadata": metadata}}
        msg = self.session.msg("workflow_request", content)
        self.shell_channel.send(msg)
        return msg["header"]["msg_id"]


class WorkflowKernelManager(AsyncKernelManager):
    client_factory: traitlets.Type = traitlets.Type(
        klass="jupyter_workflow.client.client.WorkflowKernelClient"
    )


class WorkflowClient(NotebookClient):
    def __init__(self, nb: NotebookNode, **kw: Any):
        super().__init__(nb, **kw)
        self.clear_before_next_output = False
        self.kernel_manager_class = WorkflowKernelManager
        self.on_cell_execute = partial(on_cell_execute, client=self)
        self.task_poll_for_reply: asyncio.Task | None = None

    async def _async_poll_for_workflow_reply(
        self,
        msg_id: str,
        cells: MutableSequence[NotebookNode],
        task_poll_output_msgs: asyncio.Future,
        task_poll_kernel_alive: asyncio.Future,
    ) -> dict:
        while True:
            msg = await ensure_async(self.kc.shell_channel.get_msg())
            if msg["parent_header"].get("msg_id") == msg_id:
                if self.record_timing:
                    for cell in cells:
                        cell["metadata"]["execution"]["shell.execute_reply"] = (
                            timestamp(msg)
                        )
                await asyncio.wait_for(task_poll_output_msgs, self.iopub_timeout)
                task_poll_kernel_alive.cancel()
                return msg

    async def _async_poll_output_msgs(
        self, parent_msg_id: str, cells: MutableMapping[str, (int, NotebookNode)]
    ) -> None:
        while True:
            msg = await ensure_async(self.kc.iopub_channel.get_msg(timeout=None))
            if msg["parent_header"].get("msg_id") == parent_msg_id:
                try:
                    if "cell_id" in msg["content"].get("metadata", {}):
                        cell = cells[msg["content"]["metadata"]["cell_id"]]
                        self.process_message(msg, cell[1], cell[0])
                    else:
                        for cell in cells.values():
                            self.process_message(msg, cell[1], cell[0])
                except CellExecutionComplete:
                    return

    async def async_execute_workflow(
        self, reset_kc: bool = False, **kwargs: Any
    ) -> NotebookNode:
        if reset_kc and self.owns_km:
            await self._async_cleanup_kernel()
        self.reset_execution_trackers()

        async with self.async_setup_kernel(**kwargs):
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
                else:
                    if self.record_timing:
                        cell["metadata"]["execution"] = {}
                    cell = {
                        "code": cell["source"],
                        "metadata": {
                            **cell["metadata"].get("workflow", {}),
                            **{"cell_id": cell.id},
                        },
                    }
                    cells[index] = cell

            parent_msg_id = await ensure_async(
                cast(WorkflowKernelClient, self.kc).execute_workflow(
                    cells=list(cells.values()), metadata=self.nb.metadata
                )
            )

            task_poll_kernel_alive = asyncio.ensure_future(
                self._async_poll_kernel_alive()
            )
            task_poll_output_msg = asyncio.ensure_future(
                self._async_poll_output_msgs(
                    parent_msg_id,
                    {
                        cell.id: (index, cell)
                        for index, cell in enumerate(self.nb.cells)
                        if index in cells
                    },
                )
            )
            self.task_poll_for_reply = asyncio.ensure_future(
                self._async_poll_for_workflow_reply(
                    parent_msg_id,
                    [
                        cell
                        for index, cell in enumerate(self.nb.cells)
                        if index in cells
                    ],
                    task_poll_output_msg,
                    task_poll_kernel_alive,
                )
            )
            try:
                exec_reply = await self.task_poll_for_reply
            except asyncio.CancelledError:
                # can only be cancelled by task_poll_kernel_alive when the kernel is dead
                task_poll_output_msg.cancel()
                raise DeadKernelError("Kernel died") from None
            except Exception as e:
                # Best effort to cancel request if it hasn't been resolved
                try:
                    # Check if the task_poll_output is doing the raising for us
                    if not isinstance(e, CellControlSignal):
                        task_poll_output_msg.cancel()
                finally:
                    raise
            if exec_reply["content"]["status"] == "error":
                raise WorkflowExecutionException(exec_reply["content"])
            for index, cell in enumerate(self.nb.cells):
                if index in cells:
                    cell["execution_count"] = 1
            self.set_widgets_metadata()
        return self.nb

    execute_workflow = run_sync(async_execute_workflow)


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
