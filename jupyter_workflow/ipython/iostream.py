import os
import sys
import threading
from contextvars import ContextVar
from functools import partial
from io import StringIO
from typing import MutableMapping

from ipykernel.iostream import OutStream


class WorkflowOutStream(OutStream):

    def __init__(self, *args, **kwargs):
        self._buffer_dict: MutableMapping[str, StringIO] = {}
        self._parent_headers: MutableMapping[str, MutableMapping] = {}
        self.cell_id: ContextVar[str] = ContextVar('cell_id', default='')
        super().__init__(*args, **kwargs)

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
        self._flush_pending = False
        self._subprocess_flush_pending = False

        if self.echo is not None:
            try:
                self.echo.flush()
            except OSError as e:
                if self.echo is not sys.__stderr__:
                    print(f"Flush failed: {e}", file=sys.__stderr__)

        if cell_id:
            self.set_cell_id(cell_id)

        data = self._flush_buffer()
        if data:
            self.session.pid = os.getpid()
            content = {"name": self.name, "metadata": {"cell_id": self.cell_id.get()}, "text": data}
            self.session.send(
                self.pub_thread,
                "stream",
                content=content,
                parent=self.parent_header,
                ident=self.topic)

    def _schedule_flush(self):
        if self._flush_pending:
            return
        self._flush_pending = True

        def _schedule_in_thread():
            self._io_loop.call_later(self.flush_interval, partial(self._flush, cell_id=self.cell_id.get()))

        self.pub_thread.schedule(_schedule_in_thread)

    def flush(self):
        if (
                self.pub_thread
                and self.pub_thread.thread is not None
                and self.pub_thread.thread.is_alive()
                and self.pub_thread.thread.ident != threading.current_thread().ident
        ):
            self.pub_thread.schedule(partial(self._flush, cell_id=self.cell_id.get()))
            evt = threading.Event()
            self.pub_thread.schedule(evt.set)
            if not evt.wait(self.flush_timeout):
                print("IOStream.flush timed out", file=sys.__stderr__)
        else:
            self._flush()

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
        if cell_id not in self._buffer_dict:
            self._buffer_dict[cell_id] = StringIO()

    def set_parent(self, parent):
        if 'workflow' in parent['content']:
            self.set_cell_id(parent['content']['workflow'].get('cell_id', ''))
        super().set_parent(parent)

    def write(self, string: str) -> int:
        if not isinstance(string, str):
            raise TypeError(f"write() argument must be str, not {type(string)}")
        if self.echo is not None:
            try:
                self.echo.write(string)
            except OSError as e:
                if self.echo is not sys.__stderr__:
                    print(f"Write failed: {e}", file=sys.__stderr__)
        if self.pub_thread is None:
            raise ValueError("I/O operation on closed file")
        else:
            is_child = not self._is_master_process()
            with self._buffer_lock:
                self._buffer.write(string)
            if is_child:
                if self._subprocess_flush_pending:
                    return
                self._subprocess_flush_pending = True
                self.pub_thread.schedule(partial(self._flush, cell_id=self.cell_id.get()))
            else:
                self._schedule_flush()
        return len(string)
