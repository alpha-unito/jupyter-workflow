import sys

import streamflow
import traitlets
from ipykernel.ipkernel import IPythonKernel
from ipython_genutils.py3compat import PY3

from jupyter_workflow.config.validator import validate
from jupyter_workflow.ipython.shell import StreamFlowInteractiveShell


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
        super().finish_metadata(parent, metadata, reply_content)
