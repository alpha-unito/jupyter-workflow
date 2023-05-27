from __future__ import annotations

import os
from functools import partial
from pathlib import Path

import nbformat
from testbook import testbook

from jupyter_workflow.client.client import (
    WorkflowClient,
    WorkflowKernelManager,
    on_cell_execute,
)


def get_file(filename):
    return os.path.join(Path(__file__).parent, "testdata", filename)


class CoverageWorkflowKernelManager(WorkflowKernelManager):
    def format_kernel_cmd(self, extra_arguments: list[str] | None = None) -> list[str]:
        cmd = super().format_kernel_cmd(extra_arguments)
        if "COVERAGE_RUN" in os.environ:
            cmd = (
                cmd[0:1]
                + ["-m", "coverage", "run", "--concurrency=multiprocessing", "-p", "-m"]
                + cmd[2:]
            )
        return cmd


class testflow(testbook):
    def __init__(
        self,
        nb,
        execute=None,
        workflow=None,
        timeout=60,
        kernel_name="jupyter-workflow",
        allow_errors=False,
        **kwargs,
    ):
        super().__init__(nb, execute, timeout, kernel_name, allow_errors, **kwargs)
        self.client.on_cell_execute = partial(on_cell_execute, client=self.client)
        self.client.kernel_manager_class = CoverageWorkflowKernelManager
        self.workflow = workflow
        self.workflow_client = WorkflowClient(
            nb=(
                nbformat.read(nb, as_version=4)
                if not isinstance(nb, nbformat.NotebookNode)
                else nb
            ),
            timeout=timeout,
            allow_errors=allow_errors,
            kernel_name=kernel_name,
            **kwargs,
        )
        self.workflow_client.kernel_manager_class = CoverageWorkflowKernelManager

    def _prepare(self):
        if self.workflow is True:
            self.workflow_client.execute_workflow()
            self.client.nb = self.workflow_client.nb
        else:
            super()._prepare()
