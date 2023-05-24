from contextvars import ContextVar
from functools import partial
from io import StringIO
from typing import MutableMapping, cast

from ipykernel.iostream import IOPubThread, OutStream


def add_cell_id_hook(msg: MutableMapping, cell_id: ContextVar):
    msg["content"]["metadata"]["cell_id"] = cell_id.get()
    return msg


class CellAwareIOPubThreadWrapper:
    def __init__(self, pub_thread: IOPubThread, cell_id: ContextVar[str]):
        self.pub_thread: IOPubThread = pub_thread
        self.cell_id: ContextVar[str] = cell_id

    def schedule(self, f):
        if f.__name__ == "_flush":
            self.pub_thread.schedule(partial(f, cell_id=self.cell_id.get()))
        else:
            self.pub_thread.schedule(f)

    def __getattr__(self, item):
        return getattr(self.pub_thread, item)


class WorkflowOutStream(OutStream):
    def __init__(self, *args, **kwargs):
        self._buffer_dict: MutableMapping[str, StringIO] = {}
        self._parent_headers: MutableMapping[str, MutableMapping] = {}
        self.cell_id: ContextVar[str] = ContextVar("cell_id", default="")
        super().__init__(*args, **kwargs)
        self.pub_thread = CellAwareIOPubThreadWrapper(
            cast(IOPubThread, self.pub_thread), self.cell_id
        )
        self.register_hook(partial(add_cell_id_hook, cell_id=self.cell_id))

    @property
    def _buffer(self):
        return self._buffer_dict[self.cell_id.get()]

    @_buffer.setter
    def _buffer(self, stream: StringIO):
        self._buffer_dict[self.cell_id.get()] = stream

    @_buffer.deleter
    def _buffer(self):
        del self._buffer_dict[self.cell_id.get()]

    def _flush(self, cell_id: str = None):
        if cell_id:
            self.set_cell_id(cell_id)
        super()._flush()

    def delete_parent(self, parent):
        if "workflow" in parent["content"]:
            self.set_cell_id(parent["content"]["workflow"].get("cell_id", ""))
        del self.parent_header

    @property
    def parent_header(self):
        return self._parent_headers.get(self.cell_id.get(), {})

    @parent_header.setter
    def parent_header(self, header: MutableMapping):
        self._parent_headers[self.cell_id.get()] = header

    @parent_header.deleter
    def parent_header(self):
        self._parent_headers.pop(self.cell_id.get())

    def set_cell_id(self, cell_id: str):
        self.cell_id.set(cell_id)
        if cell_id not in self._buffer_dict:
            self._buffer_dict[cell_id] = StringIO()

    def set_parent(self, parent):
        if "workflow" in parent["content"]:
            self.set_cell_id(parent["content"]["workflow"].get("cell_id", ""))
        super().set_parent(parent)
