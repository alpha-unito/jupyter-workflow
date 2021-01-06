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
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from tempfile import NamedTemporaryFile
from typing import Dict

if sys.version_info > (3, 8):
    from ast import Module
else:
    from ast import Module as OriginalModule


    def Module(nodelist, type_ignores):
        return OriginalModule(nodelist)

CELL_OUTPUT = '__JF_CELL_OUTPUT__'
CELL_LOCAL_NS = '__JF_CELL_LOCAL_NS__'
CELL_GLOBAL_NS = '__JF_CELL_GLOBAL_NS__'

# Import dill or install it
try:
    import dill
except ImportError:
    import subprocess

    subprocess.call(
        [sys.executable, "-m", "pip", "install", "dill"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.STDOUT
    )
    import dill

# Define args parser
parser = argparse.ArgumentParser()
parser.add_argument('code_file', metavar='JF_CELL_CODE')
parser.add_argument('output_file', metavar='JF_CELL_OUTPUT')
parser.add_argument('--autoawait', action='store_true')
parser.add_argument('--local-ns-file', nargs='?')
parser.add_argument('--global-ns-file', nargs='?')
parser.add_argument('--postload-input-serializers', nargs='?')
parser.add_argument('--output-name', action='append')


def _deserialize(path, default=None):
    if path is not None:
        with open(path, "rb") as f:
            return dill.load(f)
    else:
        return default


def compare(code_obj):
    is_async = (inspect.CO_COROUTINE & code_obj.co_flags == inspect.CO_COROUTINE)
    return is_async


def postload(compiler, namespace, serializers):
    new_namespace = {}
    for name in namespace:
        if name in serializers and 'postload' in serializers[name]:
            serialization_context = prepare_ns({name: namespace[name]})
            postload_module = compiler.ast_parse(
                source=serializers[name]['postload'],
                filename='{name}.postload'.format(name=name))
            for node in postload_module.body:
                mod = Module([node], [])
                code_obj = compiler(mod, '', 'exec')
                exec(code_obj, {}, serialization_context)
            new_namespace[name] = serialization_context[name]
        else:
            new_namespace[name] = namespace[name]
    return new_namespace


def predump(compiler, namespace, serializers):
    new_namespace = {}
    for name in namespace:
        if name in serializers and 'predump' in serializers[name]:
            serialization_context = prepare_ns({name: namespace[name]})
            predump_module = compiler.ast_parse(
                source=serializers[name]['predump'],
                filename='{name}.predump'.format(name=name))
            for node in predump_module.body:
                mod = Module([node], [])
                code_obj = compiler(mod, '', 'exec')
                exec(code_obj, {}, serialization_context)
            new_namespace[name] = serialization_context[name]
        else:
            new_namespace[name] = namespace[name]
    return new_namespace


class RemoteCompiler(codeop.Compile):

    def ast_parse(self, source, filename='<unknown>', symbol='exec'):
        return compile(source, filename, symbol, self.flags | ast.PyCF_ONLY_AST, 1)

    @contextmanager
    def extra_flags(self, flags):
        turn_on_bits = ~self.flags & flags
        self.flags = self.flags | flags
        try:
            yield
        finally:
            self.flags &= ~turn_on_bits


def prepare_ns(namespace: Dict) -> Dict:
    namespace.setdefault('__name__', '__main__')
    namespace.setdefault('__builtin__', builtins)
    namespace.setdefault('__builtins__', builtins)
    if 'get_ipython' in locals():
        namespace.setdefault('get_ipython', locals()['get_ipython'])
    return namespace


async def run_code(args):
    try:
        command_output, command_error = io.StringIO(), io.StringIO()
        with redirect_stdout(command_output), redirect_stderr(command_error):
            # Instantiate compiler
            compiler = RemoteCompiler()
            # Deserialize elements
            ast_nodes = _deserialize(args.code_file)
            user_ns = prepare_ns(_deserialize(args.local_ns_file, {}))
            user_global_ns = _deserialize(args.global_ns_file, user_ns)
            if user_global_ns != user_ns:
                user_global_ns = prepare_ns(user_global_ns)
            # Apply postload serialization hooks if present
            if args.postload_input_serializers:
                postload_input_serializers = _deserialize(args.postload_input_serializers)
                if user_global_ns != user_ns:
                    user_global_ns = postload(compiler, user_global_ns, postload_input_serializers)
                user_ns = postload(compiler, user_ns, postload_input_serializers)
            # Exec cell code
            for node, mode in ast_nodes:
                if mode == 'exec':
                    mod = Module([node], [])
                elif mode == 'single':
                    mod = ast.Interactive([node])
                with compiler.extra_flags(getattr(ast, 'PyCF_ALLOW_TOP_LEVEL_AWAIT', 0x0) if args.autoawait else 0x0):
                    code_obj = compiler(mod, '', mode)
                    asynchronous = compare(code_obj)
                if asynchronous:
                    await eval(code_obj, user_global_ns, user_ns)
                else:
                    exec(code_obj, user_global_ns, user_ns)
        # Create output object
        output = {
            CELL_OUTPUT: command_output.getvalue().strip(),
            CELL_LOCAL_NS: {},
            CELL_GLOBAL_NS: {}
        }
        if args.output_name:
            # Serialize user namespace
            with NamedTemporaryFile(delete=False) as f:
                dill.dump({k: v for k, v in user_ns.items() if k in args.output_name}, f, recurse=True)
                output[CELL_LOCAL_NS] = f.name
            # If global namespace is different from user namespace, serialize global namespace
            if user_global_ns != user_ns:
                with NamedTemporaryFile(delete=False) as f:
                    dill.dump({k: v for k, v in user_global_ns.items() if k in args.output_name}, f, recurse=True)
                    output[CELL_GLOBAL_NS] = f.name
    except BaseException:
        # Create output object
        output = {
            CELL_OUTPUT: traceback.format_exc(),
            CELL_LOCAL_NS: {},
            CELL_GLOBAL_NS: {}
        }
    # Save output json to file
    with open(args.output_file, 'w') as f:
        f.write(json.dumps(output))


def main(args):
    # Load arguments
    args = parser.parse_args(args)
    # Run code asynchronously
    if sys.version_info > (3, 7):
        asyncio.run(run_code(args))
    else:
        loop = asyncio.get_event_loop()
        loop.run_until_complete(run_code(args))


if __name__ == "__main__":
    main(sys.argv[1:])
