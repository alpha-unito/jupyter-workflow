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
        self._parent_headers: MutableMapping[str, MutableMapping] = {}
        self.cell_id: ContextVar[str] = ContextVar('cell_id', default='')
        self.register_hook(partial(add_cell_id_hook, cell_id=self.cell_id))

    def delete_parent(self, parent):
        if 'workflow' in parent['content']:
            self.set_cell_id(parent['content']['workflow'].get('cell_id', ''))
        del self.parent_header

    @property
    def parent_header(self):
        return self._parent_headers[self.cell_id.get()]

    @parent_header.setter
    def parent_header(self, header: MutableMapping):
        self._parent_headers[self.cell_id.get()] = header

    @parent_header.deleter
    def parent_header(self):
        del self._parent_headers[self.cell_id.get()]

    def set_cell_id(self, cell_id: str):
        self.cell_id.set(cell_id)

    def set_parent(self, parent):
        if 'workflow' in parent['content']:
            self.set_cell_id(parent['content']['workflow'].get('cell_id', ''))
        super().set_parent(parent)


class StreamFlowShellDisplayHook(ZMQShellDisplayHook):

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self._parent_headers: MutableMapping[str, MutableMapping] = {}
        self.cell_id: ContextVar[str] = ContextVar('cell_id', default='')

    def delete_parent(self, parent):
        if 'workflow' in parent['content']:
            self.set_cell_id(parent['content']['workflow'].get('cell_id', ''))
        del self.parent_header

    @property
    def parent_header(self):
        return self._parent_headers[self.cell_id.get()]

    @parent_header.setter
    def parent_header(self, header: MutableMapping):
        self._parent_headers[self.cell_id.get()] = header

    @parent_header.deleter
    def parent_header(self):
        del self._parent_headers[self.cell_id.get()]

    def set_cell_id(self, cell_id: str):
        self.cell_id.set(cell_id)

    def set_parent(self, parent):
        if 'workflow' in parent['content']:
            self.set_cell_id(parent['content']['workflow'].get('cell_id', ''))
        super().set_parent(parent)

    def write_format_data(self, format_dict, md_dict=None):
        if not md_dict:
            md_dict = {}
        md_dict['cell_id'] = self.cell_id.get()
        super().write_format_data(format_dict, md_dict)
