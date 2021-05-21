import argparse
import ast
import asyncio
import builtins
import codeop
import inspect
import io
import json
import os
import shutil
import sys
import traceback
from contextlib import contextmanager, redirect_stdout, redirect_stderr
from tempfile import NamedTemporaryFile
from typing import Dict, MutableSequence

if sys.version_info > (3, 8):
    from ast import Module
else:
    from ast import Module as OriginalModule


    def Module(nodelist, type_ignores):
        return OriginalModule(nodelist)

CELL_OUTPUT = '__JF_CELL_OUTPUT__'
CELL_STATUS = '__JF_CELL_STATUS__'
CELL_LOCAL_NS = '__JF_CELL_LOCAL_NS__'

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
parser.add_argument('--postload-input-serializers', nargs='?')
parser.add_argument('--predump-output-serializers', nargs='?')
parser.add_argument('--output-name', action='append')
parser.add_argument('--workdir', nargs='?')


def _deserialize(path, default=None):
    if path is not None:
        with open(path, "rb") as f:
            return dill.load(f)
    else:
        return default


def _serialize(compiler, namespace, args):
    if args.predump_output_serializers:
        predump_output_serializers = _deserialize(args.predump_output_serializers)
        namespace = {k: predump(
            compiler=compiler,
            name=k,
            value=v,
            serializer=predump_output_serializers.get(k)) for k, v in namespace.items() if k in args.output_name}
    else:
        namespace = {k: v for k, v in namespace.items() if k in args.output_name}
    with NamedTemporaryFile(delete=False) as f:
        dill.dump(namespace, f, recurse=True)
        return f.name


def compare(code_obj):
    is_async = (inspect.CO_COROUTINE & code_obj.co_flags == inspect.CO_COROUTINE)
    return is_async


def postload(compiler, name, value, serializer):
    if serializer is not None and 'postload' in serializer:
        serialization_context = prepare_ns({name: value})
        postload_module = compiler.ast_parse(
            source=serializer['postload'],
            filename='{name}.postload'.format(name=name))
        for node in postload_module.body:
            mod = Module([node], [])
            code_obj = compiler(mod, '', 'exec')
            exec(code_obj, {}, serialization_context)
        return serialization_context[name]
    else:
        return value


def predump(compiler, name, value, serializer):
    if serializer is not None and 'predump' in serializer:
        serialization_context = prepare_ns({name: value})
        predump_module = compiler.ast_parse(
            source=serializer['predump'],
            filename='{name}.predump'.format(name=name))
        for node in predump_module.body:
            mod = Module([node], [])
            code_obj = compiler(mod, '', 'exec')
            exec(code_obj, {}, serialization_context)
        return serialization_context[name]
    else:
        return value


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
    elif 'get_ipython' in globals():
        namespace.setdefault('get_ipython', globals()['get_ipython'])
    return namespace


async def run_code(args):
    output = {CELL_LOCAL_NS: {}}
    command_output = io.StringIO()
    with redirect_stdout(command_output), redirect_stderr(command_output):
        try:
            # Instantiate compiler
            compiler = RemoteCompiler()
            # Deserialize elements
            ast_nodes = _deserialize(args.code_file)
            user_ns = prepare_ns({k: [dill.loads(el) for el in v] if isinstance(v, MutableSequence) else dill.loads(v)
                                  for k, v in _deserialize(args.local_ns_file, {}).items()})
            # Apply postload serialization hooks if present
            if args.postload_input_serializers:
                postload_input_serializers = _deserialize(args.postload_input_serializers)
                user_ns = {k: postload(
                    compiler=compiler,
                    name=k,
                    value=v,
                    serializer=postload_input_serializers.get(k)
                ) for k, v in user_ns.items()}
            if 'get_ipython' in user_ns:
                user_ns['get_ipython']().user_ns = user_ns
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
                    await eval(code_obj, user_ns, user_ns)
                else:
                    exec(code_obj, user_ns, user_ns)
            # Populate output object
            output[CELL_OUTPUT] = command_output.getvalue().strip()
            if 'get_ipython' in locals():
                output[CELL_OUTPUT] = user_ns['Out'][-1].append(output[CELL_OUTPUT])
            if args.output_name:
                output[CELL_LOCAL_NS] = _serialize(compiler, user_ns, args)
                if args.workdir:
                    dest_path = os.path.join(args.workdir, os.path.basename(output[CELL_LOCAL_NS]))
                    shutil.move(output[CELL_LOCAL_NS], dest_path)
                    output[CELL_LOCAL_NS] = dest_path
            output[CELL_STATUS] = 'COMPLETED'
        except BaseException:
            # Populate output object
            output[CELL_OUTPUT] = command_output.getvalue().strip()
            if output[CELL_OUTPUT]:
                output[CELL_OUTPUT] = output[CELL_OUTPUT] + "\n" + traceback.format_exc().strip()
            else:
                output[CELL_OUTPUT] = traceback.format_exc().strip()
            output[CELL_STATUS] = 'FAILED'
        finally:
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
