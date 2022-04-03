import copy
from typing import Any, MutableMapping

from jupyter_workflow.streamflow.translator import JupyterNotebook
from jupyter_workflow.streamflow.utils import get_stdout
from tests import conftest
from tests.conftest import build_cell, get_from_file, set_code, set_namespace, set_outputs, set_scatter


async def run(cells, compiler, translator) -> MutableMapping[str, Any]:
    return await conftest.run(
        notebook=JupyterNotebook(
            cells=[build_cell(c, compiler, 'single') for c in cells],
            autoawait=True),
        translator=translator)


# noinspection DuplicatedCode
async def test_two_steps_single_dep(compiler, translator, workflow_cell):
    cell1 = copy.deepcopy(workflow_cell)
    set_outputs(cell1, ['a'])
    set_code(cell1, get_from_file('init_param.py'))
    cell2 = copy.deepcopy(workflow_cell)
    set_code(cell2, get_from_file('sum.py'))
    outputs = await run([cell1, cell2], compiler, translator)
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
    outputs = await run([cell1, cell2, cell3], compiler, translator)
    assert get_stdout(outputs) == '3'


# noinspection DuplicatedCode
async def test_simple_scatter_sequence(compiler, translator, workflow_cell):
    set_namespace(translator, {'a': [1, 2, 3, 4]})
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
    outputs = await run([cell1, cell2, cell3], compiler, translator)
    assert get_stdout(outputs) == '[4, 5, 6, 7]'


# noinspection DuplicatedCode
async def test_scatter_and_non_scatter_sequences(compiler, translator, workflow_cell):
    set_namespace(translator, {'a': [1, 2, 3, 4]})
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
    outputs = await run([cell1, cell2, cell3, cell4], compiler, translator)
    assert get_stdout(outputs) == '[4, 5, 6, 7]'
