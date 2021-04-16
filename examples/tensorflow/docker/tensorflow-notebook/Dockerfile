FROM jupyter/scipy-notebook
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

RUN pip install --no-cache-dir                      \
        bcrypt==3.2.0                               \
        dill==0.3.3                                 \
        jupyter-workflow==0.0.19                    \
        tensorflow==2.4.1                           \
    && python -m jupyter_workflow.ipython.install

USER root

RUN apt-get update                                                                              \
    && apt-get install -y                                                                       \
        curl                                                                                    \
        openssh-client                                                                          \
    && apt-get clean                                                                            \
    && rm -rf /var/lib/apt/lists/*                                                              \
    && fix-permissions "${CONDA_DIR}"                                                           \
    && ln -s /usr/local/cuda/lib64/libcusolver.so.11 /usr/local/cuda/lib64/libcusolver.so.10    \
    && curl -L https://git.io/get_helm.sh -o /tmp/get_helm.sh                                   \
    && chmod +x /tmp/get_helm.sh                                                                \
    && /tmp/get_helm.sh --version v3.5.4

ENV LD_LIBRARY_PATH="/usr/local/cuda/lib:/usr/local/cuda/lib64"

USER ${NB_USER}
