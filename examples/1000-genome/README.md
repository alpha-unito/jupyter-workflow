# Running the 1000-genome workflow interactively on Kubernetes

To investigate *Jupyter-Workflow* strong scalability on a distribured infrastructure, we execute an 8-chromosomes instance of the [1000-genome workflow](https://github.com/pegasus-isi/1000genome-workflow) on up to 500 concurrent Kubernetes Pods. We selected the 1000-genome workflow for three main reasons:
* Pegasus is a state-of-the-art representative of HPC-oriented WMSs supporting execution environments without shared data spaces (via HTCondor);
* The host code of each step is written in either Bash or Python, both supported by the standard IPython kernel;
* The critical portion of the workflow id a highly-parallel step, composed of 2000 independent short tasks (~120s each on our infrastructure), which are critical for batch workload managers, but that can be executed at scale on on-demand Cloud resources (e.g. Kubernetes)

## Preliminary steps

In order to replicate the experiment, you need a Kubernetes cluster with 3 control plane VMs (4 cores, 8GB RAM each) and 16 large worker VMs (40 cores, 120GB RAM each). In our infrastructure, each Kubernetes worker node has been manually placed on top of a different physical node, managed by an OpenStack Cloud controller. Nodes were interconnected by a 10Gbps Ethernet.

Each Pod requests 1 core and 2GB RAM and mounts a 1GB tmpfs under the `/tmp/streamflow` path, in order to avoid I/O bottlenecks. The description of such deployment is described in the `helm-1000-genome` model, which is managed by the StreamFlow Helm connector.

The Dockerfile of the worker container can be found under the `docker/1000-genome/` folder. It can be recompiled locally (using the `build` script in the same folder) and published to a custom Docker registry. Alternatively, the original `alphaunito/1000-genome` container, published on Docker Hub, can be used.

Initial inputs of the workflow should be downloaded (through the provided `work/data/download_data.sh` script) before lanching the pipeline steps.

## Run the notebook

Also the Jupyter Nortebook driver has been placed inside the Kubernetes cluster, in order to avoid network bottlenecks caused by the external OpenStack loadbalancer in front of the kube-apiserver listeners.

The Dockerfile of the Jupyter Notebook can be found under the `docker/1000-genome-notebook/` folder. As stated for the worker container, it can be either recompiled locally (using the `build` script in the same folder) and published to a custom Docker registry, or downloaded from Docker Hub at `alphaunito/1000-genome-notebook`.

The Kubernetes deployment is described in the `k8s/manifest.yaml` file. It can be deployed by running the following command:
```bash
kubectl apply -f k8s/manifest.yaml
```
Please note that the Jupyter Notebook Pod requires two persistent volumes, which are provided by the `cdk-cinder` StorageClass. To reproduce the experiment on your infrastructure, modify the name of the StorageClass accordingly.

Documentation related to the single Notebook cells is reported directly in the `.ipynb` Notebook. Please be sure to select `Jupyter Workflow` as the Notebook kernel when running the example.