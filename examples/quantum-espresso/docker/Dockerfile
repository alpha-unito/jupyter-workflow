FROM jupyter/minimal-notebook AS qe_builder
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

ARG QE_VERSION="6.6"

ENV DEBIAN_FRONTEND="noninteractive"
ENV LC_ALL="C"

USER root

# Install build dependencies
RUN apt-get update \
    && apt-get install -y \
        build-essential \
        libopenblas-openmp-dev \
        libfftw3-dev \
        libhdf5-dev \
        libmpich-dev \
        wget

# Compile QuantumEspresso
RUN wget https://github.com/QEF/q-e/archive/qe-${QE_VERSION}.tar.gz \
    && tar -xzf qe-${QE_VERSION}.tar.gz \
    && rm -f qe-${QE_VERSION}.tar.gz \
    && cd q-e-qe-${QE_VERSION} \
    && ./configure --with-default-prefix="/usr/local" \
    && make pw cp \
    && make install


FROM jupyter/minimal-notebook

ENV DEBIAN_FRONTEND="noninteractive"

COPY --from=qe_builder "/usr/local/bin" "/usr/local/bin"

USER root

RUN apt-get update \
    && apt-get install -y \
        libopenblas0-openmp \
        libfftw3-bin \
        libhdf5-103 \
        libgfortran5 \
        mpich \
        openssh-client \
        wget \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir \
        bcrypt==3.2.0 \
        dill==0.3.3 \
        jupyter-workflow==0.0.37 \
    && python -m jupyter_workflow.ipython.install \
    && fix-permissions /usr/local/bin \
    && fix-permissions "${CONDA_DIR}"

USER ${NB_USER}
