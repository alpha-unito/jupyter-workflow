from tests.conftest import (
    get_file,
    testflow,
)


@testflow(
    get_file("two_steps_single_dep.ipynb"),
    execute=True,
)
def test_two_steps_single_dep(tb):
    assert tb.cell_output_text(1) == "2"


@testflow(
    get_file("two_steps_single_dep.ipynb"),
    workflow=True,
)
def test_two_steps_single_dep_workflow(tb):
    assert tb.cell_output_text(1) == "2"


@testflow(
    get_file("param_overwrite.ipynb"),
    execute=True,
)
def test_param_overwrite(tb):
    assert tb.cell_output_text(2) == "3"


@testflow(
    get_file("param_overwrite.ipynb"),
    workflow=True,
)
def test_param_overwrite_workflow(tb):
    assert tb.cell_output_text(2) == "3"


@testflow(
    get_file("simple_scatter_sequence.ipynb"),
    execute=True,
)
def test_simple_scatter_sequence(tb):
    assert tb.cell_execute_result(3) == [{"text/plain": "[4, 5, 6, 7]"}]


@testflow(
    get_file("simple_scatter_sequence.ipynb"),
    workflow=True,
)
def test_simple_scatter_sequence_workflow(tb):
    assert tb.cell_execute_result(3) == [{"text/plain": "[4, 5, 6, 7]"}]


@testflow(
    get_file("scatter_and_non_scatter_sequences.ipynb"),
    execute=True,
)
def test_scatter_and_non_scatter_sequences(tb):
    assert tb.cell_execute_result(3) == [{"text/plain": "[4, 5, 6, 7]"}]
    assert tb.cell_execute_result(4) == [{"text/plain": "[4, 5, 6, 7]"}]


@testflow(
    get_file("scatter_and_non_scatter_sequences.ipynb"),
    workflow=True,
)
def test_scatter_and_non_scatter_sequences_workflow(tb):
    assert tb.cell_execute_result(3) == [{"text/plain": "[4, 5, 6, 7]"}]
    assert tb.cell_execute_result(4) == [{"text/plain": "[4, 5, 6, 7]"}]
