from tests.conftest import get_file, testflow


@testflow(get_file("serialization.ipynb"))
def test_input_predump_serialization(tb):
    tb.inject("a = 'test'")
    tb.execute_cell("input_predump_serializer")
    assert tb.cell_execute_result("input_predump_serializer") == [
        {"text/plain": "'Predumped test'"}
    ]
    assert tb.value("a") == "Predumped test"


@testflow(get_file("serialization.ipynb"))
def test_input_postload_serialization(tb):
    tb.inject("a = 'test'")
    tb.execute_cell("input_postload_serializer")
    assert tb.cell_execute_result("input_postload_serializer") == [
        {"text/plain": "'Postloaded test'"}
    ]
    assert tb.value("a") == "Postloaded test"


@testflow(get_file("serialization.ipynb"))
def test_output_predump_serialization(tb):
    tb.inject("a = 'test'")
    tb.execute_cell("output_predump_serializer")
    assert tb.cell_execute_result("output_predump_serializer") == [
        {"text/plain": "'test'"}
    ]
    assert tb.value("a") == "Predumped test"


@testflow(get_file("serialization.ipynb"))
def test_output_postload_serialization(tb):
    tb.inject("a = 'test'")
    tb.execute_cell("output_postload_serializer")
    assert tb.cell_execute_result("output_postload_serializer") == [
        {"text/plain": "'test'"}
    ]
    assert tb.value("a") == "Postloaded test"
