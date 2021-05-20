from os import path

from setuptools import setup

from jupyter_workflow.version import VERSION

this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, "README.md"), encoding="utf-8") as f:
    long_description = f.read()

setup(
    name="jupyter-workflow",
    version=VERSION,
    license="LGPLv3",
    packages=[
        "jupyter_workflow",
        "jupyter_workflow.config",
        "jupyter_workflow.ipython",
        "jupyter_workflow.streamflow"
    ],
    package_data={
        "jupyter_workflow.config": ["schemas/v1.0/*.json"],
        "jupyter_workflow.ipython": ["kernelspec/kernel.js"]
    },
    include_package_data=True,
    description="Jupyter Workflow Kernel",
    long_description=long_description,
    long_description_content_type="text/markdown",
    author="Iacopo Colonnelli",
    author_email="iacopo.colonnelli@unito.it",
    url='https://github.com/alpha-unito/jupyter-workflow',
    download_url="".join(['https://github.com/alpha-unito/jupyter-workflow/releases']),
    install_requires=[
        "dill",
        "IPython",
        "ipython_genutils",
        "ipykernel",
        "jsonref",
        "jsonschema",
        "jupyter_client",
        "streamflow >= 0.0.29",
        "traitlets"
    ],
    python_requires=">=3.8, <4",
    classifiers=[
        "Development Status :: 3 - Alpha",
        "License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: POSIX",
        "Programming Language :: Python :: 3.8",
        "Topic :: Scientific/Engineering",
        "Topic :: System :: Distributed Computing",
    ],
)
