import copy
import io
import sys
from contextlib import redirect_stderr, redirect_stdout
from typing import Any, MutableMapping

import IPython
from IPython import InteractiveShell

from jupyter_workflow.streamflow.executor import prepare_ns
from jupyter_workflow.streamflow.translator import JupyterNotebook
from tests import conftest
from tests.conftest import (
    MockDisplayHook, MockDisplayPublisher, MockOutStream, build_cell, get_from_file, get_ipython_out, get_stdout,
    set_code, set_outputs,
    set_scatter
)


async def run(cells, compiler, translator, user_ns) -> MutableMapping[str, Any]:
    return await conftest.run(
        notebook=JupyterNotebook(
            cells=[build_cell(c, compiler, 'single') for c in cells],
            autoawait=True),
        translator=translator,
        user_ns=user_ns)


# noinspection DuplicatedCode
async def test_two_steps_single_dep(compiler, translator, workflow_cell):
    cell1 = copy.deepcopy(workflow_cell)
    set_outputs(cell1, ['a'])
    set_code(cell1, get_from_file('init_param.py'))
    cell2 = copy.deepcopy(workflow_cell)
    set_code(cell2, get_from_file('sum.py'))
    outputs = await run(
        cells=[cell1, cell2],
        compiler=compiler,
        translator=translator,
        user_ns=prepare_ns({}))
    assert get_stdout(outputs) == '2'


# noinspection DuplicatedCode
async def test_param_overwrite(compiler, translator, workflow_cell):
    cell1 = copy.deepcopy(workflow_cell)
    set_outputs(cell1, ['a'])
    set_code(cell1, get_from_file('init_param.py'))
    cell2 = copy.deepcopy(workflow_cell)
    set_code(cell2, get_from_file('param_sum.py'))
    set_outputs(cell2, ['a'])
    cell3 = copy.deepcopy(workflow_cell)
    set_code(cell3, get_from_file('sum.py'))
    outputs = await run(
        cells=[cell1, cell2, cell3],
        compiler=compiler,
        translator=translator,
        user_ns=prepare_ns({}))
    assert get_stdout(outputs) == '3'


# noinspection DuplicatedCode
async def test_simple_scatter_sequence(compiler, translator, workflow_cell):
    cell1 = copy.deepcopy(workflow_cell)
    set_scatter(cell1, {'items': ['a']})
    set_code(cell1, get_from_file('list_param_sum.py'))
    set_outputs(cell1, ['a'])
    cell2 = copy.deepcopy(workflow_cell)
    set_scatter(cell2, {'items': ['a']})
    set_code(cell2, get_from_file('list_param_sum.py'))
    set_outputs(cell2, ['a'])
    cell3 = copy.deepcopy(workflow_cell)
    set_scatter(cell3, {'items': ['a']})
    set_code(cell3, get_from_file('list_sum.py'))
    outputs = await run(
        cells=[cell1, cell2, cell3],
        compiler=compiler,
        translator=translator,
        user_ns=prepare_ns({'a': [1, 2, 3, 4]}))
    assert get_stdout(outputs) == '[4, 5, 6, 7]'


# noinspection DuplicatedCode
async def test_scatter_and_non_scatter_sequences(compiler, translator, workflow_cell):
    cell1 = copy.deepcopy(workflow_cell)
    set_scatter(cell1, {'items': ['a']})
    set_code(cell1, get_from_file('list_param_sum.py'))
    set_outputs(cell1, ['a'])
    cell2 = copy.deepcopy(workflow_cell)
    set_scatter(cell2, {'items': ['a']})
    set_code(cell2, get_from_file('list_param_sum.py'))
    set_outputs(cell2, ['a'])
    cell3 = copy.deepcopy(workflow_cell)
    set_scatter(cell3, {'items': ['a']})
    set_code(cell3, get_from_file('list_sum.py'))
    cell4 = copy.deepcopy(workflow_cell)
    set_code(cell4, get_from_file('list_sum.py'))
    outputs = await run(
        cells=[cell1, cell2, cell3, cell4],
        compiler=compiler,
        translator=translator,
        user_ns=prepare_ns({'a': [1, 2, 3, 4]}))
    assert get_ipython_out(outputs) == [4, 5, 6, 7]


# noinspection DuplicatedCode
async def test_notebook_driven_cells(compiler, translator, workflow_cell):
    cell1 = {}
    set_code(cell1, get_from_file('init_param.py'))
    cell2 = copy.deepcopy(workflow_cell)
    set_code(cell2, get_from_file('param_sum.py'))
    set_outputs(cell2, ['a'])
    cell3 = {}
    set_code(cell3, get_from_file('sum.py'))
    stdout = MockOutStream()
    sys.displayhook = MockDisplayHook(sys.displayhook)
    InteractiveShell.instance(display_pub_class=MockDisplayPublisher)
    user_ns = {'get_ipython': IPython.get_ipython}
    with redirect_stdout(stdout), redirect_stderr(stdout):
        await run(
            cells=[cell1, cell2, cell3],
            compiler=compiler,
            translator=translator,
            user_ns=prepare_ns(user_ns))
    assert stdout.getvalue().strip() == '3'
