FROM tensorflow/serving
LABEL maintainer="Iacopo Colonnelli <iacopo.colonnelli@unito.it>"

RUN apt-get update                                  \
    && apt-get install -y                           \
        python3-pip                                 \
    && apt-get clean                                \
    && rm -rf /var/lib/apt/lists/*                  \
    && pip3 install --no-cache-dir                  \
        dill==0.3.3                                 \
        ipython==7.16.1                             \
        numpy==1.19.5                               \
        requests==2.25.1
