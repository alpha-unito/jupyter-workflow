import asyncio
import sys
import time
from functools import partial

import streamflow
import traitlets
from ipykernel.ipkernel import IPythonKernel
from ipykernel.jsonutil import json_clean
from ipython_genutils.py3compat import safe_unicode
from jupyter_client.session import extract_header
from streamflow.core.exception import WorkflowDefinitionException

from jupyter_workflow.config.validator import validate
from jupyter_workflow.ipython.shell import StreamFlowInteractiveShell


class WorkflowIPythonKernel(IPythonKernel):
    # Set StreamFlow shell
    shell_class = traitlets.Type(StreamFlowInteractiveShell)
    # Kernel info fields
    implementation = "sf-ipython"
    implementation_version = streamflow.version.VERSION
    language_info = {
        "name": "python",
        "version": sys.version.split()[0],
        "mimetype": "text/x-python",
        "codemirror_mode": {"name": "ipython", "version": sys.version_info[0]},
        "pygments_lexer": "ipython%d" % 3,
        "nbconvert_exporter": "python",
        "file_extension": ".py",
    }

    msg_types = IPythonKernel.msg_types + [
        "auto_inputs_request",
        "background_execute_request",
        "workflow_request",
    ]

    async def auto_inputs_request(self, stream, ident, parent):
        if code := parent.get("content", {}).get("code"):
            reply_content = await self.do_auto_inputs_request(code)
            # Send the reply.
            reply_content = json_clean(reply_content)
            reply_msg = self.session.msg(
                "auto_inputs_reply", reply_content, parent=parent
            )
            self.session.send(stream, reply_msg, ident=ident)
            self.log.debug("%s", reply_msg)
        else:
            self.log.error("Invalid workflow definition: %s", parent)
            return

    async def do_auto_inputs_request(self, code):
        shell = self.shell
        reply_content = {}
        res = await shell.retrieve_inputs(code)
        if res.error_before_exec is not None:
            err = res.error_before_exec
        else:
            err = res.error_in_exec
        if res.success:
            reply_content["inputs"] = res.inputs
            reply_content["status"] = "ok"
        else:
            reply_content["status"] = "error"
            # noinspection PyProtectedMember
            reply_content.update(
                {
                    "traceback": shell._last_traceback or [],
                    "ename": str(type(err).__name__),
                    "evalue": safe_unicode(err),
                }
            )
        shell.payload_manager.clear_payload()
        return reply_content

    async def background_execute_request(self, stream, ident, parent):
        # Fast-forward reply content
        try:
            content = parent["content"]
            user_expressions = content.get("user_expressions", {})
        except Exception:
            self.log.error("Got bad msg: ")
            self.log.error("%s", parent)
            return
        reply_content = {
            "status": "background",
            "execution_count": self.shell.execution_count - 1,
            "user_expressions": self.shell.user_expressions(user_expressions or {}),
            "payload": self.shell.payload_manager.read_payload(),
        }
        msg = self.session.msg("execute_reply", reply_content, parent=parent)
        self.session.send(stream, msg, ident=ident)
        # Call normal execute
        task = asyncio.create_task(self.execute_request(stream, ident, parent))
        task.add_done_callback(partial(self.shell.delete_parent, parent=parent))

    async def execute_request(self, stream, ident, parent):
        await super().execute_request(stream, ident, parent)
        self.shell.delete_parent(parent)

    def init_metadata(self, parent):
        # Call parent functionse
        metadata = super().init_metadata(parent)
        # If StreamFlow has been configured for this cell, store its configuration
        workflow_config = (
            parent["metadata"]
            if "workflow" in parent["metadata"]
            else parent["content"] if "workflow" in parent["content"] else None
        )
        if workflow_config is not None:
            try:
                validate(
                    {
                        k: v
                        for k, v in workflow_config["workflow"].items()
                        if k != "cell_id"
                    }
                )
            except WorkflowDefinitionException as e:
                self.log.error(str(e))
                return metadata
            metadata["sf_token"] = self.shell.wf_cell_config.set(
                workflow_config["workflow"]
            )
        # Return metadata
        return metadata

    def finish_metadata(self, parent, metadata, reply_content):
        # Remove StreamFlow configuration from the `sf_cell_config` attribute if present
        if "sf_token" in metadata:
            self.shell.wf_cell_config.reset(metadata["sf_token"])
            del metadata["sf_token"]
        # Call parent function
        return super().finish_metadata(parent, metadata, reply_content)

    async def workflow_request(self, stream, ident, parent):
        if notebook := parent.get("content", {}).get("notebook"):
            metadata = self.init_metadata(parent)
            reply_content = await self.do_workflow(notebook, ident, parent)
            sys.stdout.flush()
            sys.stderr.flush()
            if self._execute_sleep:
                time.sleep(self._execute_sleep)
            # Send the reply.
            reply_content = json_clean(reply_content)
            metadata = self.finish_metadata(parent, metadata, reply_content)
            reply_msg = self.session.msg(
                "execute_reply", reply_content, parent=parent, metadata=metadata
            )
            self.session.send(stream, reply_msg, ident=ident)
            self.log.debug("%s", reply_msg)
        else:
            self.log.error("Invalid workflow definition: %s", parent)
            return

    async def do_workflow(self, notebook, ident, parent):
        shell = self.shell
        reply_content = {}
        parent["content"]["workflow"] = {}
        for cell in notebook["cells"]:
            parent["content"]["workflow"]["cell_id"] = cell["metadata"]["cell_id"]
            self.set_parent(ident, parent)
        res = await shell.run_workflow(notebook)
        # Send stdout contents to cell streams
        for cell_name, content in res.stdout.items():
            content = {
                "name": "stdout",
                "metadata": {"cell_id": cell_name},
                "text": content,
            }
            msg = self.session.msg("stream", content, parent=extract_header(parent))
            self.session.send(self.iopub_thread, msg, ident=ident)
        # Send ipython out contents to cell streams
        for cell_name, content in res.out.items():
            content = {
                "execution_count": 1,
                "data": {"text/plain": repr(content)},
                "metadata": {"cell_id": cell_name},
            }
            msg = self.session.msg(
                "execute_result", content, parent=extract_header(parent)
            )
            self.session.send(self.iopub_thread, msg, ident=b"execute_result")
        # Send reply message
        if res.error_before_exec is not None:
            err = res.error_before_exec
        else:
            err = res.error_in_exec
        if res.success:
            reply_content["status"] = "ok"
        else:
            reply_content["status"] = "error"
            # noinspection PyProtectedMember
            reply_content.update(
                {
                    "traceback": shell._last_traceback or [],
                    "ename": str(type(err).__name__),
                    "evalue": safe_unicode(err),
                }
            )
        reply_content["execution_count"] = shell.execution_count - 1
        reply_content["payload"] = shell.payload_manager.read_payload()
        shell.payload_manager.clear_payload()
        return reply_content
