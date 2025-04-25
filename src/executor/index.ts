import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { INotebookCellExecutor } from '@jupyterlab/notebook';
import { JupyterWorkflowCellExecutor } from './cellexecutor';

export const executor: JupyterFrontEndPlugin<INotebookCellExecutor> = {
  id: 'jupyter-workflow:notebook-cell-executor',
  description: 'Jupyter Workflow cell executor',
  autoStart: true,
  provides: INotebookCellExecutor,
  activate: (app: JupyterFrontEnd): INotebookCellExecutor => {
    return new JupyterWorkflowCellExecutor();
  }
};
