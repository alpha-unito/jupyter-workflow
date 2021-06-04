FROM jupyter/minimal-notebook
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

# Install kernel
RUN pip install --no-cache-dir                      \
        bcrypt==3.2.0                               \
        dill==0.3.3                                 \
        jupyter-workflow==0.0.37                    \
        matplotlib==3.4.2                           \
        numpy==1.20.3                               \
    && python -m jupyter_workflow.ipython.install

USER root

# Install required packages
RUN apt-get update \
    && apt-get install -y \
        curl \
        gawk \
        gzip \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && wget https://git.io/get_helm.sh -O /tmp/get_helm.sh     \
    && chmod +x /tmp/get_helm.sh                               \
    && /tmp/get_helm.sh --version v3.5.4

USER "${NB_USER}"
