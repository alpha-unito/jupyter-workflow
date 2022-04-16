import ast
import asyncio
import os
import posixpath
import tempfile
from io import StringIO
from pathlib import Path
from typing import Any, MutableMapping, MutableSequence, Union

import pytest
from IPython.core.compilerop import CachingCompiler
from IPython.core.displaypub import DisplayPublisher
from streamflow.core.data import LOCAL_LOCATION
from streamflow.core.utils import get_token_value, random_name
from streamflow.workflow.executor import StreamFlowExecutor

from jupyter_workflow.config.validator import validate
from jupyter_workflow.ipython.shell import build_context
from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.translator import JupyterCell, JupyterNotebookTranslator


def build_cell(cell, compiler, mode) -> JupyterCell:
    code = ''.join(cell['source'])
    metadata = cell.get('metadata', {}).get('workflow', {})
    if metadata:
        validate(metadata)
    metadata['cell_id'] = random_name()
    cell_name = compiler.cache(code, number=1, raw_code=cell)
    code_ast = compiler.ast_parse(code, filename=cell_name)
    to_run = [(node, mode) for node in code_ast.body]
    return JupyterCell(
        name=cell_name,
        code=to_run,
        compiler=compiler,
        metadata=metadata)


@pytest.fixture
def compiler():
    return CachingCompiler()


@pytest.fixture()
def context():
    context = build_context()
    context.data_manager.register_path(
        deployment=LOCAL_LOCATION,
        location=os.path.join(executor.__file__),
        path=os.path.join(executor.__file__),
        relpath=os.path.basename(executor.__file__))
    return context


@pytest.fixture
def datadir():
    return os.path.join(Path(__file__).parent, 'testdata')


def get_from_file(filename):
    with open(os.path.join(Path(__file__).parent, 'testdata', filename), "r") as f:
        return f.readlines()


def get_output(outputs, name) -> Any:
    return ([v for v in outputs[name]] if isinstance(outputs[name], MutableSequence)
            else outputs[name])


def get_stdout(outputs) -> str:
    try:
        return str(ast.literal_eval(outputs[executor.CELL_OUTPUT]))
    except BaseException:
        return outputs[executor.CELL_OUTPUT]


def get_ipython_out(outputs):
    try:
        return ast.literal_eval(outputs['Out'])
    except BaseException:
        return outputs['Out']


async def run(notebook, translator, user_ns) -> MutableMapping[str, Any]:
    workflow = await translator.translate(notebook=notebook, user_ns=user_ns)
    await StreamFlowExecutor(workflow).run()
    output_tasks = {posixpath.split(name)[1]: asyncio.create_task(port.get(random_name()))
                    for name, port in workflow.get_output_ports().items()}
    return dict(zip(output_tasks.keys(), [get_token_value(t) for t in await asyncio.gather(*output_tasks.values())]))


def set_code(workflow_cell: MutableMapping[str, Any],
             code: MutableSequence[str]):
    workflow_cell['source'] = code


def set_inputs(workflow_cell: MutableMapping[str, Any],
               inputs: MutableSequence[Union[str, MutableMapping]]):
    workflow_cell['metadata']['workflow']['step']['in'] = inputs


def set_outputs(workflow_cell: MutableMapping[str, Any],
                outputs: MutableSequence[Union[str, MutableMapping]]):
    workflow_cell['metadata']['workflow']['step']['out'] = outputs


def set_scatter(workflow_cell: MutableMapping[str, Any],
                scatter: MutableMapping[str, Any]):
    workflow_cell['metadata']['workflow']['step']['scatter'] = scatter


@pytest.fixture
def translator(context):
    return JupyterNotebookTranslator(
        context=context,
        output_directory=tempfile.mkdtemp())


@pytest.fixture
def workflow_cell():
    return {
        'cell_type': 'code',
        'metadata': {
            'workflow': {
                'step': {
                    'in': [],
                    'out': []
                },
                'version': 'v1.0'
            }
        },
        'source': []
    }


class MockDisplayHook(object):

    def __init__(self, displayhook):
        self.displayhook = displayhook

    def __call__(self, *args, **kwargs):
        self.displayhook(*args, **kwargs)

    def set_cell_id(self, cell_id):
        pass


class MockDisplayPublisher(DisplayPublisher):

    def set_cell_id(self, cell_id):
        pass


class MockOutStream(StringIO):

    def set_cell_id(self, cell_id):
        pass

