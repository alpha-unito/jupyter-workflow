from __future__ import annotations

import argparse
import ast
import asyncio
import builtins
import codeop
import inspect
import io
import json
import sys
import traceback
from collections.abc import MutableMapping
from contextlib import contextmanager, redirect_stderr, redirect_stdout
from tempfile import NamedTemporaryFile
from typing import Any, cast

CELL_OUTPUT = "__JF_CELL_OUTPUT__"
CELL_STATUS = "__JF_CELL_STATUS__"
CELL_LOCAL_NS = "__JF_CELL_LOCAL_NS__"

try:
    import cloudpickle as pickle
except ImportError:
    import pickle  # nosec

# Define args parser
parser = argparse.ArgumentParser()
parser.add_argument("code_file", metavar="JF_CELL_CODE")
parser.add_argument("output_file", metavar="JF_CELL_OUTPUT")
parser.add_argument("--autoawait", action="store_true")
parser.add_argument("--local-ns-file", nargs="?")
parser.add_argument("--postload-input-serializers", nargs="?")
parser.add_argument("--predump-output-serializers", nargs="?")
parser.add_argument("--output-name", action="append")
parser.add_argument("--tmpdir", nargs="?")


def _deserialize(path, default=None):
    if path is not None:
        with open(path, "rb") as f:
            return pickle.load(f)
    else:
        return default


def _serialize(compiler, namespace, args):
    if args.predump_output_serializers:
        predump_output_serializers = _deserialize(args.predump_output_serializers)
        namespace = {
            k: predump(
                compiler=compiler,
                name=k,
                value=v,
                serializer=predump_output_serializers.get(k),
            )
            for k, v in namespace.items()
            if k in args.output_name
        }
    else:
        namespace = {k: v for k, v in namespace.items() if k in args.output_name}
    with NamedTemporaryFile(dir=args.tmpdir, delete=False) as f:
        pickle.dump(namespace, f)
        return f.name


def compare(code_obj):
    is_async = inspect.CO_COROUTINE & code_obj.co_flags == inspect.CO_COROUTINE
    return is_async


def postload(compiler, name, value, serializer):
    if serializer is not None and "postload" in serializer:
        serialization_context = prepare_ns({"x": value})
        postload_module = compiler.ast_parse(
            source=serializer["postload"], filename=f"{name}.postload"
        )
        for node in postload_module.body:
            mod = ast.Module([node], [])
            code_obj = compiler(mod, "", "exec")  # nosec
            exec(code_obj, {}, serialization_context)  # nosec
        return serialization_context["y"]
    else:
        return value


def predump(compiler, name, value, serializer):
    if serializer is not None and "predump" in serializer:
        serialization_context = prepare_ns({"x": value})
        predump_module = compiler.ast_parse(
            source=serializer["predump"], filename=f"{name}.predump"
        )
        for node in predump_module.body:
            mod = ast.Module([node], [])
            code_obj = compiler(mod, "", "exec")  # nosec
            exec(code_obj, {}, serialization_context)  # nosec
        return serialization_context["y"]
    else:
        return value


class RemoteCompiler(codeop.Compile):
    def ast_parse(self, source, filename="<unknown>", symbol="exec"):
        return compile(source, filename, symbol, self.flags | ast.PyCF_ONLY_AST, 1)

    @contextmanager
    def extra_flags(self, flags):
        turn_on_bits = ~self.flags & flags
        self.flags = self.flags | flags
        try:
            yield
        finally:
            self.flags &= ~turn_on_bits


class RemoteDisplayHook:
    def __init__(self, displayhook):
        self.displayhook = displayhook
        self.out_var = io.StringIO()

    def __call__(self, obj):
        with redirect_stdout(self.out_var), redirect_stderr(self.out_var):
            self.displayhook(obj)


def prepare_ns(namespace: dict) -> dict:
    namespace.setdefault("__name__", "__main__")
    namespace.setdefault("__builtin__", builtins)
    namespace.setdefault("__builtins__", builtins)
    if "get_ipython" in locals():
        namespace.setdefault("get_ipython", locals()["get_ipython"])
    elif "get_ipython" in globals():
        namespace.setdefault("get_ipython", globals()["get_ipython"])
    return namespace


async def run_ast_nodes(
    ast_nodes: list[tuple[ast.AST, str]],
    autoawait: bool,
    compiler: codeop.Compile,
    user_ns: MutableMapping[str, Any],
):
    for node, mode in ast_nodes:
        if mode == "exec":
            mod = ast.Module([node], [])
        elif mode == "single":
            mod = ast.Interactive([node])
        with compiler.extra_flags(
            getattr(ast, "PyCF_ALLOW_TOP_LEVEL_AWAIT", 0x0) if autoawait else 0x0
        ):
            code_obj = compiler(mod, "", mode)
            asynchronous = compare(code_obj)
        if asynchronous:
            await eval(code_obj, cast(dict[str, Any], user_ns), user_ns)  # nosec
        else:
            exec(code_obj, cast(dict[str, Any], user_ns), user_ns)  # nosec


async def run_code(args):
    output = {CELL_LOCAL_NS: {}}
    command_output = io.StringIO()
    try:
        # Instantiate compiler
        compiler = RemoteCompiler()
        # Deserialize elements
        ast_nodes = _deserialize(args.code_file)
        user_ns = prepare_ns(_deserialize(args.local_ns_file, {}))
        # Apply postload serialization hooks if present
        if args.postload_input_serializers:
            postload_input_serializers = _deserialize(args.postload_input_serializers)
            user_ns = {
                k: postload(
                    compiler=compiler,
                    name=k,
                    value=v,
                    serializer=postload_input_serializers.get(k),
                )
                for k, v in user_ns.items()
            }
        if "get_ipython" in user_ns:
            user_ns["get_ipython"]().user_ns = user_ns
        # Exec cell code
        with redirect_stdout(command_output), redirect_stderr(command_output):
            sys.displayhook = RemoteDisplayHook(sys.displayhook)
            await run_ast_nodes(ast_nodes, args.autoawait, compiler, user_ns)
        # Populate output object
        output[CELL_OUTPUT] = command_output.getvalue().strip()
        if "Out" not in user_ns:
            user_ns["Out"] = {}
        user_ns["Out"] = sys.displayhook.out_var.getvalue().strip()
        if args.output_name:
            output[CELL_LOCAL_NS] = _serialize(compiler, user_ns, args)
        else:
            output[CELL_LOCAL_NS] = ""
        output[CELL_STATUS] = "COMPLETED"
    except Exception:
        # Populate output object
        output[CELL_OUTPUT] = command_output.getvalue().strip()
        if output[CELL_OUTPUT]:
            output[CELL_OUTPUT] = (
                output[CELL_OUTPUT] + "\n" + traceback.format_exc().strip()
            )
        else:
            output[CELL_OUTPUT] = traceback.format_exc().strip()
        output[CELL_STATUS] = "FAILED"
    finally:
        # Save output json to file
        with open(args.output_file, "w") as f:
            f.write(json.dumps(output))


def main(args):
    # Load arguments
    args = parser.parse_args(args)
    # Run code asynchronously
    asyncio.run(run_code(args))


if __name__ == "__main__":
    main(sys.argv[1:])
