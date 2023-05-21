import os.path
from typing import Any, MutableMapping

from jupyter_workflow.streamflow.translator import JupyterNotebook
from tests import conftest
from tests.conftest import (
    build_cell,
    get_from_file,
    get_ipython_out,
    get_output,
    get_stdout,
    set_code,
    set_inputs,
    set_outputs,
    set_scatter,
)


async def run(cell, compiler, translator, user_ns) -> MutableMapping[str, Any]:
    return await conftest.run(
        notebook=JupyterNotebook(
            cells=[build_cell(cell, compiler, "single")], autoawait=True
        ),
        translator=translator,
        user_ns=user_ns,
    )


# noinspection DuplicatedCode
async def test_single_explicit_input_dep(compiler, translator, workflow_cell):
    set_inputs(workflow_cell, ["a"])
    set_code(workflow_cell, get_from_file("sum.py"))
    outputs = await run(
        cell=workflow_cell, compiler=compiler, translator=translator, user_ns={"a": 1}
    )
    assert get_stdout(outputs) == "2"


# noinspection DuplicatedCode
async def test_single_implicit_input_dep(compiler, translator, workflow_cell):
    set_code(workflow_cell, get_from_file("sum.py"))
    outputs = await run(
        cell=workflow_cell, compiler=compiler, translator=translator, user_ns={"a": 1}
    )
    assert get_stdout(outputs) == "2"


# noinspection DuplicatedCode
async def test_interactive_execution(compiler, translator, workflow_cell):
    set_code(workflow_cell, get_from_file("interactive_sum.py"))
    outputs = await run(
        cell=workflow_cell, compiler=compiler, translator=translator, user_ns={"a": 1}
    )
    assert get_ipython_out(outputs) == 2


# noinspection DuplicatedCode
async def test_file_input(compiler, datadir, translator, workflow_cell):
    input_file = os.path.join(datadir, "hello.txt")
    set_inputs(
        workflow_cell,
        [{"name": "input_file", "type": "file", "valueFrom": "input_file"}],
    )
    set_code(workflow_cell, get_from_file("file_read.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"input_file": input_file},
    )
    with open(input_file) as f:
        assert get_ipython_out(outputs) == f.read()


# noinspection DuplicatedCode
async def test_file_output_value(compiler, datadir, translator, workflow_cell):
    input_file = os.path.join(datadir, "hello.txt")
    set_inputs(
        workflow_cell,
        [{"name": "input_file", "type": "file", "valueFrom": "input_file"}],
    )
    set_outputs(
        workflow_cell, [{"name": "output_file", "type": "file", "value": "out.txt"}]
    )
    set_code(workflow_cell, get_from_file("file_rw.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"input_file": input_file},
    )
    with open(input_file) as f:
        content = f.read()
    with open(get_output(outputs, "output_file")) as f:
        assert content == f.read()


# noinspection DuplicatedCode
async def test_file_output_value_from(compiler, datadir, translator, workflow_cell):
    input_file = os.path.join(datadir, "hello.txt")
    set_inputs(
        workflow_cell,
        [{"name": "input_file", "type": "file", "valueFrom": "input_file"}],
    )
    set_outputs(
        workflow_cell,
        [{"name": "output_file", "type": "file", "valueFrom": "output_file"}],
    )
    set_code(workflow_cell, get_from_file("file_rw.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"input_file": input_file},
    )
    with open(input_file) as f:
        content = f.read()
    with open(get_output(outputs, "output_file")) as f:
        assert content == f.read()


# noinspection DuplicatedCode
async def test_list_input_dep(compiler, translator, workflow_cell):
    set_code(workflow_cell, get_from_file("list_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == [2, 3, 4, 5]


# noinspection DuplicatedCode
async def test_scatter_input_dep(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": ["a"]})
    set_code(workflow_cell, get_from_file("list_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == [2, 3, 4, 5]


# noinspection DuplicatedCode
async def test_scatter_input_dep_size(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": [{"name": "a", "size": 3}]})
    set_code(workflow_cell, get_from_file("list_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == [2, 3, 4, 5]


async def test_scatter_input_dep_num(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": [{"name": "a", "num": 3}]})
    set_code(workflow_cell, get_from_file("list_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == [2, 3, 4, 5]


# noinspection DuplicatedCode
async def test_multiple_input_deps(compiler, translator, workflow_cell):
    set_inputs(workflow_cell, ["a"])
    set_code(workflow_cell, get_from_file("two_lists_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"


# noinspection DuplicatedCode
async def test_scatter_input_deps_default(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": ["a", "b"]})
    set_code(workflow_cell, get_from_file("two_lists_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"


# noinspection DuplicatedCode
async def test_mixed_input_deps(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": ["a"]})
    set_code(workflow_cell, get_from_file("two_lists_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"


# noinspection DuplicatedCode
async def test_scatter_input_deps_cartesian(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": ["a", "b"], "method": "cartesian"})
    set_code(workflow_cell, get_from_file("two_lists_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"


# noinspection DuplicatedCode
async def test_scatter_input_deps_dotproduct(compiler, translator, workflow_cell):
    set_scatter(workflow_cell, {"items": ["a", "b"], "method": "dotproduct"})
    set_code(workflow_cell, get_from_file("two_lists_sum.py"))
    outputs = await run(
        cell=workflow_cell,
        compiler=compiler,
        translator=translator,
        user_ns={"a": [1, 2, 3, 4], "b": [1, 2, 3, 4]},
    )
    assert get_ipython_out(outputs) == "2\n4\n6\n8"
