import asyncio
import os
import posixpath
import tempfile
from pathlib import Path
from typing import Any, MutableMapping, MutableSequence, Union

import dill
import pytest
from IPython.core.compilerop import CachingCompiler
from streamflow.core.data import LOCAL_LOCATION
from streamflow.core.utils import get_token_value, random_name
from streamflow.workflow.executor import StreamFlowExecutor

from jupyter_workflow.config.validator import validate
from jupyter_workflow.ipython.shell import build_context
from jupyter_workflow.streamflow import executor
from jupyter_workflow.streamflow.executor import prepare_ns
from jupyter_workflow.streamflow.translator import JupyterCell, JupyterNotebook, JupyterNotebookTranslator


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
    return ([dill.loads(v) for v in outputs[name]] if isinstance(outputs[name], MutableSequence)
            else dill.loads(outputs[name]))


async def run(notebook, translator) -> MutableMapping[str, Any]:
    workflow = await translator.translate(notebook=notebook)
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


def set_namespace(translator: JupyterNotebookTranslator,
                  names: MutableMapping[str, Any]):
    return translator.user_ns.update(names)


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
        deployment_map={},
        user_ns=prepare_ns({}))


@pytest.fixture
def workflow_cell(request):
    return {
        'cell_type': 'code',
        'metadata': {
            'workflow': {
                'step': {
                    'in': [],
                    'out': []
                },
                'outdir': tempfile.mkdtemp(),
                'version': 'v1.0'
            }
        },
        'source': []
    }
