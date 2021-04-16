# Interactive Car-Parrinello simulation on Quantum ESPRESSO

In order to assess the *Jupyter-workflow* capabilities to enable interactive simulations of realistic, large-scale systems, we implement a Notebook describing a multi-step simulation workflow in Quantum ESPRESSO.

In particular, the analyzed workflow implements a Car-Parrinello simulation of 32 Water Molecules, with the aim to sample the water at different temperatures using a Nose-hover thermostat together with a reference microcanonical trajectory.

The workflow is composed of six steps, which were executed on top of the PBS-managed *davinci-1* facility, the HPC centre of the Leonard S.p.A. company.

## Preliminary steps

This time we did not use a Singularity container, but ran the steps directly on bare metal to fully exploit compile-time optimisations of a Quantum ESPRESSO executable compiled with Intel OneAPI. Nevertheless, we packed both the executable (named `cp-oneapi.x`) and all the input files inside the `INPDIR` directory on this repo.

In order to replicate the experiment in a fully-optimised execution environment, you need to compile the Quantum ESPRESSO `cp` executable directly on your facility. The [node-details.txt file](https://raw.githubusercontent.com/alpha-unito/jupyter-workflow/master/examples/quantum-espresso/node-details.txt) provides some information on the libraries used to compile Quantum ESPRESSO.

## Run the notebook

In order to run the Notebook locally, you can use the `run` script in this folder. It automatically pulls the related container from [DockerHub](https://hub.docker.com/r/alphaunito/quantum-espresso-notebook). Conversely, if you want to produce your own local version of the container, you can run the `build` script in the `docker` folder of this repo prior to launch the `run` script.

Documentation related to the single Notebook cells is reported directly in the Notebook. Please be sure to select `Jupyter Workflow` as the Notebook kernel when running the example.
