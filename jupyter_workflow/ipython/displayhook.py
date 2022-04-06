from contextvars import ContextVar
from functools import partial
from typing import MutableMapping

from ipykernel.displayhook import ZMQShellDisplayHook
from ipykernel.zmqshell import ZMQDisplayPublisher


def add_cell_id_hook(msg: MutableMapping, cell_id: ContextVar):
    msg["content"]["metadata"]["cell_id"] = cell_id.get()
    return msg


class StreamFlowDisplayPublisher(ZMQDisplayPublisher):

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.cell_id: ContextVar[str] = ContextVar('cell_id', default='')
        self.register_hook(partial(add_cell_id_hook, cell_id=self.cell_id))

    def set_cell_id(self, cell_id: str):
        self.cell_id.set(cell_id)


class StreamFlowShellDisplayHook(ZMQShellDisplayHook):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.cell_id: ContextVar[str] = ContextVar('cell_id', default='')

    def write_format_data(self, format_dict, md_dict=None):
        if not md_dict:
            md_dict = {}
        md_dict['cell_id'] = self.cell_id.get()
        super().write_format_data(format_dict, md_dict)

    def set_cell_id(self, cell_id: str):
        self.cell_id.set(cell_id)
