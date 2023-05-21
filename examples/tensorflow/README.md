# Train and serve a TensorFlow model with TensorFlow Serving

This Notebook showcases how Deep Learning can benefit from hybrid Cloud-HPC scenarios, in particular to offload the computationally demanding training phase to an HPC facility, and offering the resulting network as-a-Service on a Cloud architecture to answer time-constrained inference queries.

The notebook is a modified version of [this one](https://github.com/tensorflow/tfx/blob/master/docs/tutorials/serving/rest_simple.ipynb), which focuses mainly on Google Colab. Since we are not interested in pure performance for this use case, we use the small [Fashion MNIST](https://github.com/zalandoresearch/fashion-mnist) dataset and a very small custom Convolutional Neural Network (CNN).

The training phase has been offloaded to an HPC node on the [HPC4AI facility](https://hpc4ai.unito.it/), equipped with four NVIDIA Tesla V100 and two Intel Xeon Gols 6230 sockets. Then, the trained model is sent to a pre-existing TensorFlow Serving Pod on a Kubernetes cluster, hosted on the OpenStack-based  HPC4AI cloud.

## Run the notebook

In order to run the Notebook locally, you can use the `run` script in this folder. It automatically pulls the related container from [DockerHub](https://hub.docker.com/r/alphaunito/tensorflow-notebook). Conversely, if you want to produce your own local version of the container, you can run the `build` script in the `docker/tensorflow-notebook` folder of this repo prior to launch the `run` script.

Documentation related to the single Notebook cells is reported directly in the Notebook. Please be sure to select `Jupyter Workflow` as the Notebook kernel when running the example.
