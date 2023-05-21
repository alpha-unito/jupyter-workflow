# CLAIRE-COVID19 universal pipeline

The CLAIRE-COVID19 universal pipeline has been designed to compare different training algorithms for the AI-assisted diagnosis of COVID-19, in order to define a baseline for such techniques and to allow the community to quantitatively measure AI’s progress in this field. For more information, please read [this post](https://streamflow.di.unito.it/2021/04/12/ai-assisted-covid-19-diagnosis-with-the-claire-universal-pipeline/).

This notebook showcases how the classification-related portion of the pipeline can be successfully described and documented in Jupyter, using the *Jupyter-workflow* to execute it at scale on an HPC facility.

The first preprocessing portion of the pipeline is left outside the notebook. It could clearly (and effectively) be included, but since this example wants to serve as an introductory demonstration, we wanted to keep it as simple as possible.

## Preliminary steps

In order to successfully run this notebook, you first need to produce a pre-processed and filtered version of the [BIMCV-COVID19+](https://bimcv.cipf.es/bimcv-projects/bimcv-covid19/) dataset (Iteration 1). Instructions on how to do this can be found [here](https://github.com/CLAIRE-COVID/AI-Covid19-preprocessing) and [here](https://github.com/CLAIRE-COVID/AI-Covid19-pipelines).

This procedure will produce three different versions of the dataset. For this experiment, we need the `final3_BB` folder, which can be either manually pre-transferred on the remote HPC facility (as we did) or left on the local machine, letting *Jupyter-workflow* automatically perform the data transfer when needed.

Next, if you plan to run on an air-gapped architecture (as HPC facilities normally are), you will need to manually download all the pre-trained neural network models and place them into a `weights` folder, in a portion of file-system shared among all the worker nodes in the data centre. This can be done by running [this script](https://raw.githubusercontent.com/CLAIRE-COVID/AI-Covid19-benchmarking/master/nnframework/init_models.py).

Finally, you need to transfer dependencies (i.e., PyTorch and the CLAIRE-COVID19 benchmarking [code](https://github.com/CLAIRE-COVID/AI-Covid19-benchmarking)) on the remote facility. To enhance portability, we used a Singularity container with everything inside, but you have to manually transfer it on the remote HPC facility, in a shared portion of the file-system, and to change the `environment/cineca-marconi100/slurm_template.jinja2` file accordingly. We plan to make this last transfer automatically managed by *Jupyter-workflow* in the very next releases.

If you plan to run on an x86_64 architecture, creating the Singularity is as easy as trandforming the Docker image for this experiment in a Singularity image. Neverhteless, the [MARCONI 100](https://www.hpc.cineca.it/hardware/marconi100) HPC facility comes with an IBM POWER9 architecture. Therefore, we built a Singularity container on a `ppc64le` architecture using the `build` script in the `singularity` folder of this repository.

## Run the notebook

In order to run the Notebook locally, you can use the `run` script in this folder. It automatically pulls the related container from [DockerHub](https://hub.docker.com/r/alphaunito/claire-covid-notebook). Conversely, if you want to produce your own local version of the container, you can run the `build` script in the `docker` folder of this repo prior to launch the `run` script.

Documentation related to the single Notebook cells is reported directly in the Notebook. Please be sure to select `Jupyter Workflow` as the Notebook kernel when running the example.