FROM jupyter/scipy-notebook
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

RUN conda install --quiet --yes -c pytorch -c conda-forge       \
        dill==0.3.3                                             \
        pytorch=1.8.1                                           \
        torchvision=0.9.1                                       \
        cudatoolkit=11.1                                        \
    && conda clean --all -f -y

RUN pip install --no-cache-dir                                  \
        bcrypt==3.2.0                                           \
        jupyter-workflow==0.0.19                                \
        kiwisolver==1.3.0                                       \
        matplotlib==3.3.2                                       \
        nibabel==3.2.0                                          \
        pandas==1.1.3                                           \
        pydicom==2.1.1                                          \
        pyprg==0.1.1b7                                          \
        pyyaml==5.3.1                                           \
        scikit-learn==0.23.2                                    \
        scipy==1.5.2                                            \
        tensorboard==2.3.0                                      \
        typing==3.7.4.3                                         \
    && python -m jupyter_workflow.ipython.install

USER root

RUN git clone                                                           \
        https://github.com/CLAIRE-COVID/AI-Covid19-benchmarking.git     \
        /opt/claire-covid                                               \
    && mkdir -p ${HOME}/claire-covid/                                   \
    && cp -r /opt/claire-covid/interpretability ${HOME}/claire-covid/   \
    && cp -r /opt/claire-covid/nnframework ${HOME}/claire-covid/        \
    && cp -r /opt/claire-covid/metrics ${HOME}/claire-covid/            \
    && rm -rf /opt/claire-covid

ENV PYTHONPATH="${PYTHONPATH}:${HOME}/claire-covid"

RUN apt-get update \
    && apt-get install -y openssh-client \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && fix-permissions ${HOME}/claire-covid

USER ${NB_USER}
