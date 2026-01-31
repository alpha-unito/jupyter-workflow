[![CI Tests](https://github.com/alpha-unito/jupyter-workflow/actions/workflows/ci-tests.yml/badge.svg?branch=master)](https://github.com/alpha-unito/jupyter-workflow/actions/workflows/ci-tests.yml)
[![coverage](https://codecov.io/gh/alpha-unito/jupyter-workflow/branch/master/graph/badge.svg?token=2024K42B7O)](https://codecov.io/gh/alpha-unito/jupyter-workflow)

# Jupyter Workflow

The Jupyter Workflow framework enables Jupyter Notebooks to describe complex workflows and to execute them in a distributed fashion on hybrid HPC-Cloud infrastructures. Jupyter Workflow relies on the [StreamFlow](https://github.com/alpha-unito/streamflow) WMS as its underlying runtime support.

## Install Jupyter Workflow

The Jupyter Workflow IPython kernel is available on [PyPI](https://pypi.org/project/jupyter-workflow/), so you can install it using pip.

```bash
pip install jupyter-workflow
```

Then, you can install it on a Jupyter Notebook server by running the following command.

```bash
python -m jupyter_workflow.ipython.install
```

Please note that Jupyter Workflow requires `python >= 3.10`. Then you can associate your Jupyter Notebooks with the newly installed kernel. Some examples can be found under the `examples` folder in the [GitHub repository](https://github.com/alpha-unito/jupyter-workflow).

## Jupyter Workflow Team

Iacopo Colonnelli <iacopo.colonnelli@unito.it> (creator and maintainer) 
Alberto Mulone <alberto.mulone@unito.it> (maintainer)
Sergio Rabellino <sergio.rabellino@unito.it> (maintainer)  
Barbara Cantalupo <barbara.cantalupo@unito.it> (maintainer)  
Marco Aldinucci <aldinuc@di.unito.it> (maintainer)  
