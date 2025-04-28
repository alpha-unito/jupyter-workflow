import {
  INotebookCellExecutor,
  INotebookModel,
  KernelError
} from '@jupyterlab/notebook';
import { nullTranslator } from '@jupyterlab/translation';
import {
  Cell,
  CodeCell,
  ICodeCellModel,
  MarkdownCell
} from '@jupyterlab/cells';
import { Dialog, showDialog } from '@jupyterlab/apputils';
import { KernelMessage } from '@jupyterlab/services';
import { findIndex } from '@lumino/algorithm';

export class JupyterWorkflowCellExecutor implements INotebookCellExecutor {
  async runCell({
    cell,
    notebook,
    notebookConfig,
    onCellExecuted,
    onCellExecutionScheduled,
    sessionContext,
    sessionDialogs,
    translator
  }: INotebookCellExecutor.IRunCellOptions): Promise<boolean> {
    translator = translator ?? nullTranslator;
    const trans = translator.load('jupyterlab');
    switch (cell.model.type) {
      case 'markdown':
        (cell as MarkdownCell).rendered = true;
        cell.inputHidden = false;
        onCellExecuted({ cell, success: true });
        break;
      case 'code':
        if (sessionContext) {
          if (sessionContext.isTerminating) {
            await showDialog({
              title: trans.__('Kernel Terminating'),
              body: trans.__(
                'The kernel for %1 appears to be terminating. You can not run any cell for now.',
                sessionContext.session?.path
              ),
              buttons: [Dialog.okButton()]
            });
            break;
          }
          if (sessionContext.pendingInput) {
            await showDialog({
              title: trans.__('Cell not executed due to pending input'),
              body: trans.__(
                'The cell has not been executed to avoid kernel deadlock as there is another pending input! Type your input in the input box, press Enter and try again.'
              ),
              buttons: [Dialog.okButton()]
            });
            return false;
          }
          if (sessionContext.hasNoKernel) {
            const shouldSelect = await sessionContext.startKernel();
            if (shouldSelect && sessionDialogs) {
              await sessionDialogs.selectKernel(sessionContext);
            }
            cell.model.sharedModel.transact(() => {
              (cell.model as ICodeCellModel).clearExecution();
            });
            return true;
          }
          const deletedCells = notebook.deletedCells;
          onCellExecutionScheduled({ cell });
          let ran = false;
          try {
            const reply = await CodeCell.execute(
              cell as CodeCell,
              sessionContext,
              {
                deletedCells,
                recordTiming: notebookConfig.recordTiming,
                ...(cell.model.getMetadata('workflow')
                  ? {
                      workflow: {
                        ...(notebook.getMetadata('workflow') ?? {}),
                        ...cell.model.getMetadata('workflow')
                      }
                    }
                  : {})
              }
            );
            deletedCells.splice(0, deletedCells.length);
            ran = (() => {
              if (cell.isDisposed) {
                return false;
              }
              if (!reply) {
                return true;
              }
              if (reply.content.status === 'ok') {
                const content = reply.content;
                if (content.payload && content.payload.length) {
                  handlePayload(content, notebook, cell);
                }
                return true;
              } else {
                throw new KernelError(reply.content);
              }
            })();
          } catch (reason) {
            if (
              cell.isDisposed ||
              (reason as KernelError).message.startsWith('Canceled')
            ) {
              ran = false;
            } else {
              onCellExecuted({
                cell,
                success: false,
                error: reason as KernelError
              });
              throw reason;
            }
          }
          if (ran) {
            onCellExecuted({ cell, success: true });
          }
          return ran;
        }
        cell.model.sharedModel.transact(() => {
          (cell.model as ICodeCellModel).clearExecution();
        });
        break;
      default:
        break;
    }
    return Promise.resolve(true);
  }
}

function handlePayload(
  content: KernelMessage.IExecuteReply,
  notebook: INotebookModel,
  cell: Cell
) {
  const setNextInput = content.payload?.filter(i => {
    return i.source === 'set_next_input';
  })[0];
  if (!setNextInput) {
    return;
  }
  const text = setNextInput.text as string;
  const replace = setNextInput.replace;
  if (replace) {
    cell.model.sharedModel.setSource(text);
    return;
  }
  const notebookModel = notebook.sharedModel;
  const cells = notebook.cells;
  const index = findIndex(cells, model => model === cell.model);
  if (index === -1) {
    notebookModel.insertCell(notebookModel.cells.length, {
      cell_type: 'code',
      source: text,
      metadata: {
        trusted: false
      }
    });
  } else {
    notebookModel.insertCell(index + 1, {
      cell_type: 'code',
      source: text,
      metadata: {
        trusted: false
      }
    });
  }
}
