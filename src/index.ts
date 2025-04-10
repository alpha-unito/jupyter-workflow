import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';

const plugin: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-workflow:plugin',
  description:
    'Distributed workflows design and execution with Jupyter Notebooks',
  autoStart: true,
  activate: (app: JupyterFrontEnd) => {
    console.log('Jupyter Workflow extension is active');
  }
};

export default plugin;
