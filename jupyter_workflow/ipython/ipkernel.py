import asyncio
import sys
import time

import streamflow
import traitlets
from ipykernel.ipkernel import IPythonKernel
from ipykernel.jsonutil import json_clean
from ipython_genutils.py3compat import PY3, safe_unicode
from tornado import gen

from jupyter_workflow.config.validator import validate
from jupyter_workflow.ipython.shell import StreamFlowInteractiveShell

try:
    # noinspection PyProtectedMember
    from IPython.core.interactiveshell import _asyncio_runner
except ImportError:
    _asyncio_runner = None


class WorkflowIPythonKernel(IPythonKernel):
    # Set StreamFlow shell
    shell_class = traitlets.Type(StreamFlowInteractiveShell)
    # Kernel info fields
    implementation = 'sf-ipython'
    implementation_version = streamflow.version.VERSION
    language_info = {
        'name': 'python',
        'version': sys.version.split()[0],
        'mimetype': 'text/x-python',
        'codemirror_mode': {
            'name': 'ipython',
            'version': sys.version_info[0]
        },
        'pygments_lexer': 'ipython%d' % (3 if PY3 else 2),
        'nbconvert_exporter': 'python',
        'file_extension': '.py'
    }

    msg_types = IPythonKernel.msg_types + ['workflow_request']

    def init_metadata(self, parent):
        # Call parent functionse
        metadata = super().init_metadata(parent)
        # If StreamFlow has been configured for this cell, store its configuration
        workflow_config = (parent['metadata'] if 'workflow' in parent['metadata'] else
                           parent['content'] if 'workflow' in parent['content'] else
                           None)
        if workflow_config is not None:
            try:
                validate(workflow_config['workflow'])
            except BaseException as e:
                self.log.error(str(e))
                return metadata
            metadata['sf_token'] = self.shell.wf_cell_config.set(
                {**workflow_config['workflow'], **{
                    'step_id': parent['msg_id']
                }})
        # Return metadata
        return metadata

    def finish_metadata(self, parent, metadata, reply_content):
        # Remove StreamFlow configuration from the `sf_cell_config` attribute if present
        if 'sf_token' in metadata:
            self.shell.wf_cell_config.reset(metadata['sf_token'])
            del metadata['sf_token']
        # Call parent function
        return super().finish_metadata(parent, metadata, reply_content)

    @gen.coroutine
    def workflow_request(self, stream, ident, parent):
        try:
            content = parent['content']
            notebook = content['notebook']
        except:
            self.log.error("Got bad msg: ")
            self.log.error("%s", parent)
            return
        metadata = self.init_metadata(parent)
        reply_content = yield gen.maybe_future(self.do_workflow(notebook))
        sys.stdout.flush()
        sys.stderr.flush()
        if self._execute_sleep:
            time.sleep(self._execute_sleep)
        # Send the reply.
        reply_content = json_clean(reply_content)
        metadata = self.finish_metadata(parent, metadata, reply_content)
        reply_msg = self.session.send(stream, 'workflow_reply',
                                      reply_content, parent, metadata=metadata,
                                      ident=ident)
        self.log.debug("%s", reply_msg)

    @gen.coroutine
    def do_workflow(self, notebook):
        shell = self.shell
        reply_content = {}
        if (
            _asyncio_runner
            and shell.loop_runner is _asyncio_runner
            and asyncio.get_event_loop().is_running()
        ):
            coro = shell.run_workflow(notebook)
            coro_future = asyncio.ensure_future(coro)

            with self._cancel_on_sigint(coro_future):
                try:
                    res = yield coro_future
                finally:
                    shell.events.trigger('post_execute')
        else:
            coro = shell.run_workflow(notebook)
            if shell.trio_runner:
                runner = shell.trio_runner
            else:
                runner = shell.loop_runner
            res = runner(coro)
        if res.error_before_exec is not None:
            err = res.error_before_exec
        else:
            err = res.error_in_exec
        if res.success:
            reply_content['status'] = 'ok'
        else:
            reply_content['status'] = 'error'
            # noinspection PyProtectedMember
            reply_content.update({
                'traceback': shell._last_traceback or [],
                'ename': str(type(err).__name__),
                'evalue': safe_unicode(err),
            })
        # Fix execution count to 0 for each cell
        reply_content['execution_count'] = 0,
        reply_content['payload'] = shell.payload_manager.read_payload()
        shell.payload_manager.clear_payload()
        return reply_content
