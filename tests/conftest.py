import os
from functools import partial
from pathlib import Path

from testbook import testbook

from jupyter_workflow.client.client import WorkflowKernelManager, on_cell_execute


def get_file(filename):
    return os.path.join(Path(__file__).parent, "testdata", filename)


class testflow(testbook):
    def __init__(
        self,
        nb,
        execute=None,
        timeout=60,
        kernel_name="jupyter-workflow",
        allow_errors=False,
        **kwargs
    ):
        super().__init__(nb, execute, timeout, kernel_name, allow_errors, **kwargs)
        self.client.on_cell_execute = partial(on_cell_execute, client=self.client)
        self.client.kernel_manager_class = WorkflowKernelManager
