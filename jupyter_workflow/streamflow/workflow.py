from __future__ import annotations

from typing import Any
from collections.abc import MutableMapping

from streamflow.core.context import StreamFlowContext
from streamflow.core.workflow import Workflow


class JupyterWorkflow(Workflow):
    def __init__(
        self,
        context: StreamFlowContext,
        config: MutableMapping[str, Any],
        name: str = None,
    ):
        super().__init__(context, config, name)
        self.type: str = "jupyter"
