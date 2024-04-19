import logging
import pathlib
import sys
from textwrap import dedent

import nbformat
import traitlets.config
from jupyter_core.application import JupyterApp

from jupyter_workflow.client.client import WorkflowClient
from jupyter_workflow.version import VERSION

aliases = {
    "timeout": "JupyterWorkflowApp.timeout",
    "startup_timeout": "JupyterWorkflowApp.startup_timeout",
}


class JupyterWorkflowApp(JupyterApp):
    """
    An application used to execute notebook files (``*.ipynb``) as distributed workflows
    """

    version = traitlets.Unicode(VERSION)
    name = "jupyter-workflow"
    aliases = aliases

    description = "An application used to execute notebook files (``*.ipynb``) as distributed workflows"
    notebooks = traitlets.List([], help="Path of notebooks to convert").tag(config=True)
    timeout = traitlets.Integer(
        None,
        allow_none=True,
        help=dedent(
            """
            The time to wait (in seconds) for output from executions.
            If workflow execution takes longer, a TimeoutError is raised.
            ``-1`` will disable the timeout.
            """
        ),
    ).tag(config=True)
    startup_timeout = traitlets.Integer(
        60,
        help=dedent(
            """
            The time to wait (in seconds) for the kernel to start.
            If kernel startup takes longer, a RuntimeError is
            raised.
            """
        ),
    ).tag(config=True)
    interactive = traitlets.Bool(
        False,
        help=dedent(
            """
            Simulates an interactive notebook execution, executing
            cells sequentially from beginning to end instead of
            constructing a DAG. Mainly used for testing purposes.
            """
        ),
    ).tag(config=True)

    @traitlets.default("log_level")
    def _log_level_default(self):
        return logging.INFO

    @traitlets.config.catch_config_error
    def initialize(self, argv=None):
        super().initialize(argv)
        self.notebooks = self.extra_args or self.notebooks
        if not self.notebooks:
            sys.exit(-1)
        [self.run_notebook(path) for path in self.notebooks]

    def run_notebook(self, notebook_path):
        self.log.info(f"Executing {notebook_path}")
        name = notebook_path.replace(".ipynb", "")
        path = pathlib.Path(notebook_path).parent.absolute()
        input_path = f"{name}.ipynb"
        with open(input_path) as f:
            nb = nbformat.read(f, as_version=4)
        client = WorkflowClient(
            nb,
            timeout=self.timeout,
            startup_timeout=self.startup_timeout,
            resources={"metadata": {"path": path}},
        )
        if self.interactive:
            client.execute()
        else:
            client.execute_workflow()


main = JupyterWorkflowApp.launch_instance
