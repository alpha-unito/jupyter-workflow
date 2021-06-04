FROM python:3.9-slim
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

RUN apt-get update \
    && apt-get install -y --no-install-recommends                   \
        curl                                                        \
        gawk                                                        \
        gzip                                                        \
        openssl                                                     \
        procps                                                      \
   && useradd -ms /bin/bash -u 1000 -g 100 jovyan                   \
   && pip3 install --no-cache-dir                                   \
        bcrypt==3.2.0                                               \
        dill==0.3.3                                                 \
        ipython==7.23.1                                             \
        matplotlib==3.4.2                                           \
        numpy==1.20.3                                               \
   && curl -fsSL https://git.io/get_helm.sh -o /tmp/get_helm.sh     \
   && chmod +x /tmp/get_helm.sh                                     \
   && /tmp/get_helm.sh --version v3.5.4

USER jovyan
