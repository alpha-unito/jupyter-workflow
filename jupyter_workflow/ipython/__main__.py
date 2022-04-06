from ipykernel.kernelapp import IPKernelApp

from jupyter_workflow.ipython.ipkernel import WorkflowIPythonKernel

IPKernelApp.launch_instance(
    kernel_class=WorkflowIPythonKernel,
    outstream_class='jupyter_workflow.ipython.iostream.WorkflowOutStream')
