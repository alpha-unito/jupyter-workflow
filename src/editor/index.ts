import {
  JupyterFrontEnd,
  JupyterFrontEndPlugin
} from '@jupyterlab/application';
import { ITranslator } from '@jupyterlab/translation';
import { WorkflowEditor } from './editor';
import { INotebookTracker } from '@jupyterlab/notebook';
import { WorkflowHandlers } from '../handlers';

export const editor: JupyterFrontEndPlugin<void> = {
  id: 'jupyter-workflow:editor',
  autoStart: true,
  requires: [INotebookTracker],
  optional: [ITranslator],
  activate: async (
    app: JupyterFrontEnd,
    tracker: INotebookTracker,
    translator?: ITranslator
  ) => {
    const schema = await WorkflowHandlers.getSchema();
    const editorWidget = new WorkflowEditor({ schema, tracker, translator });
    app.shell.add(editorWidget, 'right', { rank: 1000 });
  }
};
