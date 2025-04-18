from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
from tempfile import TemporaryDirectory

from jupyter_client.kernelspec import KernelSpecManager

kernel_json = {
    "argv": [
        sys.executable,
        "-m",
        "jupyter_workflow.ipython",
        "-f",
        "{connection_file}",
    ],
    "display_name": "Jupyter Workflow",
    "language": "python",
}


def install_kernel_spec(user=True, prefix=None):
    with TemporaryDirectory() as td:
        with open(os.path.join(td, "kernel.json"), "w") as f:
            json.dump(kernel_json, f, sort_keys=True)
        kernel_js = os.path.join(os.path.dirname(__file__), "kernelspec", "kernel.js")
        shutil.copy(kernel_js, td)

        print("Installing Jupyter kernel spec")
        KernelSpecManager().install_kernel_spec(
            td, "jupyter-workflow", user=user, prefix=prefix
        )


def _is_root():
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False  # assume not an admin on non-Unix platforms


def main(argv=None):
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--user",
        action="store_true",
        help="Install to the per-user kernels registry. Default if not root.",
    )
    ap.add_argument(
        "--sys-prefix",
        action="store_true",
        help="Install to sys.prefix (e.g. a virtualenv or conda env)",
    )
    ap.add_argument(
        "--prefix",
        help="Install to the given prefix. "
        "Kernelspec will be installed in {PREFIX}/share/jupyter/kernels/",
    )
    args = ap.parse_args(argv)

    if args.sys_prefix:
        args.prefix = sys.prefix
    if not args.prefix and not _is_root():
        args.user = True

    install_kernel_spec(user=args.user, prefix=args.prefix)


if __name__ == "__main__":
    main()
