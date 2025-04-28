import { JupyterFrontEndPlugin } from '@jupyterlab/application';
import { executor } from './executor';
import { commands } from './command';
import { editor } from './editor';
import { INotebookCellExecutor } from '@jupyterlab/notebook';

const plugins: JupyterFrontEndPlugin<void | INotebookCellExecutor>[] = [
  commands,
  editor,
  executor
];

export default plugins;
