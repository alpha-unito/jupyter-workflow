from tests.conftest import get_file, testflow


@testflow(get_file("name_deps.ipynb"))
def test_single_explicit_input_dep(tb):
    tb.inject("a = 1")
    tb.execute_cell("single_explicit_input_dep")
    assert tb.cell_output_text("single_explicit_input_dep") == "2"


@testflow(get_file("name_deps.ipynb"))
def test_single_implicit_input_dep(tb):
    tb.inject("a = 1")
    tb.execute_cell("single_implicit_input_dep")
    assert tb.cell_output_text("single_implicit_input_dep") == "2"


@testflow(get_file("name_deps.ipynb"))
def test_interactive_execution(tb):
    tb.inject("a = 1")
    tb.execute_cell("interactive_execution")
    assert tb.cell_execute_result("interactive_execution") == [{"text/plain": "2"}]


@testflow(get_file("name_deps.ipynb"))
def test_bash_execution(tb):
    tb.inject("a = 1")
    tb.execute_cell("bash_execution")
    assert tb.cell_output_text("bash_execution") == "1"


@testflow(get_file("name_deps.ipynb"))
def test_list_input_dep(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.execute_cell("list_input_dep")
    assert tb.cell_execute_result("list_input_dep") == [{"text/plain": "[2, 3, 4, 5]"}]


@testflow(get_file("name_deps.ipynb"))
def test_multiple_input_deps(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.inject("b = [1, 2, 3, 4]")
    tb.execute_cell("multiple_input_deps")
    assert (
        tb.cell_output_text("multiple_input_deps")
        == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"
    )


@testflow(get_file("file_deps.ipynb"))
def test_file_input(tb):
    input_file = get_file("hello.txt")
    tb.inject(f'input_file = "{input_file}"')
    tb.execute_cell("file_input")
    with open(input_file) as f:
        content = f.read().encode("unicode_escape").decode("utf-8")
        assert tb.cell_execute_result("file_input") == [{"text/plain": f"'{content}'"}]


@testflow(get_file("file_deps.ipynb"))
def test_file_input_bash(tb):
    input_file = get_file("hello.txt")
    tb.inject(f'input_file = "{input_file}"')
    tb.execute_cell("file_input_bash")
    with open(input_file) as f:
        content = f.read().encode("unicode_escape").decode("utf-8")
        assert tb.cell_output_text("file_input_bash") == content.rstrip("\\n")


@testflow(get_file("file_deps.ipynb"))
def test_file_output_value(tb):
    input_file = get_file("hello.txt")
    tb.inject(f'input_file = "{input_file}"')
    tb.execute_cell("file_output_value")
    with open(input_file) as f:
        content = f.read()
    with open(tb.ref("output_file")) as f:
        assert content == f.read()


@testflow(get_file("file_deps.ipynb"))
def test_file_output_value_from(tb):
    input_file = get_file("hello.txt")
    tb.inject(f'input_file = "{input_file}"')
    tb.execute_cell("file_output_value_from")
    with open(input_file) as f:
        content = f.read()
    with open(tb.ref("output_file")) as f:
        assert content == f.read()


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_dep(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_dep")
    assert tb.cell_execute_result("scatter_input_dep") == [
        {"text/plain": "[2, 3, 4, 5]"}
    ]


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_dep_size(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_dep_size")
    assert tb.cell_execute_result("scatter_input_dep_size") == [
        {"text/plain": "[2, 3, 4, 5]"}
    ]


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_dep_num(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_dep_num")
    assert tb.cell_execute_result("scatter_input_dep_num") == [
        {"text/plain": "[2, 3, 4, 5]"}
    ]


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_deps_default(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.inject("b = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_deps_default")
    assert (
        tb.cell_output_text("scatter_input_deps_default")
        == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"
    )


@testflow(get_file("scatter_deps.ipynb"))
def test_mixed_input_deps(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.inject("b = [1, 2, 3, 4]")
    tb.execute_cell("mixed_input_deps")
    assert (
        tb.cell_output_text("mixed_input_deps")
        == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"
    )


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_deps_cartesian(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.inject("b = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_deps_cartesian")
    assert (
        tb.cell_output_text("scatter_input_deps_cartesian")
        == "2\n3\n4\n5\n3\n4\n5\n6\n4\n5\n6\n7\n5\n6\n7\n8"
    )


@testflow(get_file("scatter_deps.ipynb"))
def test_scatter_input_deps_dotproduct(tb):
    tb.inject("a = [1, 2, 3, 4]")
    tb.inject("b = [1, 2, 3, 4]")
    tb.execute_cell("scatter_input_deps_dotproduct")
    assert tb.cell_output_text("scatter_input_deps_dotproduct") == "2\n4\n6\n8"
