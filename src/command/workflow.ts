import {
  INotebookCellExecutor,
  KernelError,
  Notebook,
  NotebookActions,
  runCell as defaultRunCell
} from "@jupyterlab/notebook";
import { Dialog, ISessionContext, ISessionContextDialogs, Notification, showDialog } from "@jupyterlab/apputils";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { Cell, CodeCell, ICodeCellModel } from "@jupyterlab/cells";
import { Signal } from "@lumino/signaling";
import { JSONObject, PromiseDelegate } from "@lumino/coreutils";
import { KernelMessage } from "@jupyterlab/services";
import { KernelShellFutureHandler } from "@jupyterlab/services/lib/kernel/future";
import { IExecuteReplyMsg, IExecuteRequestMsg } from "@jupyterlab/services/lib/kernel/messages";
import { IShellFuture } from "@jupyterlab/services/lib/kernel/kernel";

export namespace WorkflowActions {
  export function runWorkflow(
    notebook: Notebook,
    sessionContext?: ISessionContext,
    sessionDialogs?: ISessionContextDialogs,
    translator?: ITranslator
  ): Promise<boolean> {
    if (!notebook.model || !notebook.activeCell) {
      return Promise.resolve(false);
    }
    const state = Private.getState(notebook);
    const lastIndex = notebook.widgets.length;
    const promise = Private.runWorkflow(
      notebook,
      notebook.widgets,
      sessionContext,
      sessionDialogs,
      translator
    );
    notebook.activeCellIndex = lastIndex;
    notebook.deselectAll();
    void Private.handleRunState(notebook, state);
    return promise;
  }
}

export function setCellExecutor(executor: INotebookCellExecutor): void {
  if (Private.executor) {
    throw new Error("Cell executor can only be set once.");
  }
  Private.executor = executor;
}

namespace Private {
  export let executor: INotebookCellExecutor;

  export type ExecutedSignal = Signal<
    any,
    {
      notebook: Notebook;
      cell: Cell;
      success: boolean;
      error?: KernelError | null;
    }
  >;

  export type ExecutionScheduledSignal = Signal<
    any,
    { notebook: Notebook; cell: Cell }
  >;

  export type SelectionExecutedSignal = Signal<
    any,
    { notebook: Notebook; lastCell: Cell }
  >;

  export interface IState {
    wasFocused: boolean;
    activeCellId: string | null;
  }

  export async function execute(
    cells: CodeCell[],
    sessionContext: ISessionContext,
    metadata?: JSONObject
  ): Promise<KernelMessage.IExecuteReplyMsg> {
    const content = {
      notebook: {
        cells: cells.map(cell => {
          const model = cell.model;
          model.sharedModel.transact(
            () => {
              model.clearExecution();
              cell.outputHidden = false;
            },
            false,
            "silent-change"
          );
          model.executionState = "running";
          model.trusted = true;
          return {
            code: model.sharedModel.getSource(),
            metadata: {
              ...model.getMetadata("workflow") ?? {},
              ...{ cellId: model.sharedModel.getId() }
            }
          };
        }),
        ...(metadata ? { metadata: metadata } : {})
      }
    };
    const kernel = sessionContext.session?.kernel;
    if (!kernel) {
      throw new Error("Session has no kernel.");
    }
    const request = KernelMessage.createMessage({
      // @ts-expect-error Introducing the new `workflow_request` type
      msgType: "workflow_request",
      // @ts-expect-error Introducing the new `workflow_request` type
      channel: "shell",
      username: kernel.username,
      session: kernel.clientId,
      subshellId: kernel.subshellId,
      // @ts-expect-error Introducing the new `workflow_request` type
      content: content
    });
    // @ts-expect-error Introducing the new `workflow_request` type
    const future = kernel.sendShellMessage(request, true, false);
    const cellsDict = cells.reduce(
      (dict, cell) => {
        cell.outputArea.future = (new KernelShellFutureHandler(
          () => {
          },
          KernelMessage.createMessage<IExecuteRequestMsg>({
            msgType: "execute_request",
            channel: "shell",
            username: kernel.username,
            session: kernel.clientId,
            subshellId: kernel.subshellId,
            content: { code: "" },
            metadata
          }),
          true,
          false,
          kernel
        ) as IShellFuture<IExecuteRequestMsg, IExecuteReplyMsg>);
        dict[cell.model.sharedModel.getId()] = cell;
        return dict;
      },
      ({} as { [id: string]: CodeCell })
    );
    const msgDispatcher = (msg: KernelMessage.IIOPubMessage) => {
      switch (msg.header.msg_type) {
        case "execute_result": {
          const cell = cellsDict[(msg as KernelMessage.IExecuteResultMsg).content.metadata.cellId as string];
          cell.outputArea.future.onIOPub(msg);
        }
          break;
        case "status":
          cells.forEach(cell => {
            cell.outputArea.future.onIOPub(msg);
          });
          break;
        case "stream": {
          const cell = cellsDict[(msg as KernelMessage.IStreamMsg).metadata.cellId as string];
          cell.outputArea.future.onIOPub(msg);
        }
          break;
        default:
          console.error(`Unhandled workflow reply message ${msg.header.msg_type}`);
      }
      return true;
    };
    future.registerMessageHook(msgDispatcher);
    // @ts-expect-error Introducing the new `workflow_request` type
    return future.done;
  }

  export function getState(notebook: Notebook): IState {
    return {
      wasFocused: notebook.node.contains(document.activeElement),
      activeCellId: notebook.activeCell?.model.id ?? null
    };
  }

  export async function handleRunState(
    notebook: Notebook,
    state: IState,
    alignPreference?: "start" | "end" | "center" | "top-center"
  ): Promise<void> {
    const { activeCell, activeCellIndex } = notebook;
    if (activeCell) {
      await notebook
        .scrollToItem(activeCellIndex, "smart", 0, alignPreference)
        .catch(reason => {
          console.error(reason);
        });
    }
    if (state.wasFocused || notebook.mode === "edit") {
      notebook.activate();
    }
  }

  export async function runWorkflow(
    notebook: Notebook,
    cells: readonly Cell[],
    sessionContext?: ISessionContext,
    sessionDialogs?: ISessionContextDialogs,
    translator?: ITranslator
  ): Promise<boolean> {
    translator = translator ?? nullTranslator;
    const trans = translator.load("jupyterlab");
    const lastCell = cells[cells.length - 1];
    notebook.mode = "command";
    let initializingDialogShown = false;
    const workflowCells: { cell: CodeCell, delegate: PromiseDelegate<boolean> }[] = [];
    const promises: (Promise<boolean> | PromiseDelegate<boolean>)[] = cells.map(cell => {
      if (
        cell.model.type === "code" &&
        notebook.notebookConfig.enableKernelInitNotification &&
        sessionContext &&
        sessionContext.kernelDisplayStatus === "initializing" &&
        !initializingDialogShown
      ) {
        initializingDialogShown = true;
        Notification.emit(
          trans.__(
            `Kernel '${sessionContext.kernelDisplayName}' for '${sessionContext.path}' is still initializing. You can run code cells when the kernel has initialized.`
          ),
          "warning",
          {
            autoClose: false
          }
        );
        return Promise.resolve(false);
      } else if (
        cell.model.type === "code" &&
        notebook.notebookConfig.enableKernelInitNotification &&
        initializingDialogShown
      ) {
        return Promise.resolve(false);
      } else if (
        cell.model.type === "code"
      ) {
        const delegate = new PromiseDelegate<boolean>();
        workflowCells.push({ cell: cell as CodeCell, delegate: delegate });
        return delegate;
      } else {
        return runCell(
          notebook,
          cell,
          sessionContext,
          sessionDialogs,
          translator
        );
      }
    });
    if (workflowCells.length > 0) {
      if (sessionContext) {
        if (sessionContext.isTerminating) {
          await showDialog({
            title: trans.__("Kernel Terminating"),
            body: trans.__(
              "The kernel for %1 appears to be terminating. You can not run any cell for now.",
              sessionContext.session?.path
            ),
            buttons: [Dialog.okButton()]
          });
          workflowCells.forEach(({ delegate }) => {
            delegate.resolve(true);
          });
        } else if (sessionContext.pendingInput) {
          await showDialog({
            title: trans.__("Workflow not executed due to pending input"),
            body: trans.__(
              "The workflow has not been executed to avoid kernel deadlock as there is another pending input! Type your input in the input box, press Enter and try again."
            ),
            buttons: [Dialog.okButton()]
          });
          workflowCells.forEach(({ delegate }) => {
            delegate.resolve(false);
          });
        } else if (sessionContext.hasNoKernel) {
          const shouldSelect = await sessionContext.startKernel();
          if (shouldSelect && sessionDialogs) {
            await sessionDialogs.selectKernel(sessionContext);
          }
          workflowCells.forEach(({ cell, delegate }) => {
            cell.model.sharedModel.transact(() => {
              (cell.model as ICodeCellModel).clearExecution();
            });
            delegate.resolve(true);
          });
        } else {
          workflowCells.forEach(({ cell }) => {
            (NotebookActions.executionScheduled as ExecutionScheduledSignal).emit({
              notebook: notebook,
              cell: cell
            });
          });
          const reply = await execute(
            workflowCells.map(cell => {
              return cell.cell;
            }),
            sessionContext,
            notebook.model?.getMetadata("workflow")
          );
          if (reply.content.status === "ok") {
            workflowCells.forEach(({ cell, delegate }) => {
              cell.model.executionCount = reply.content.execution_count;
              (NotebookActions.executed as ExecutedSignal).emit({
                notebook: notebook,
                cell: cell,
                success: true
              });
              delegate.resolve(true);
            });
          } else {
            workflowCells.forEach(({ cell, delegate }) => {
              (NotebookActions.executed as ExecutedSignal).emit({
                notebook: notebook,
                cell: cell,
                success: false,
                error: new KernelError(reply.content)
              });
              delegate.reject(reply.content);
            });
          }
        }
      } else {
        workflowCells.forEach(({ cell, delegate }) => {
          cell.model.sharedModel.transact(() => {
            (cell.model as ICodeCellModel).clearExecution();
          });
          delegate.resolve(true);
        });
      }
    }
    return Promise.all(promises).then(results => {
      if (notebook.isDisposed) {
        return false;
      }
      (NotebookActions.selectionExecuted as SelectionExecutedSignal).emit({
        notebook,
        lastCell
      });
      notebook.update();
      return results.every(result => result);
    }).catch(reason => {
      if (reason.message.startsWith("KernelReplyNotOK")) {
        cells.map(cell => {
          if (
            cell.model.type === "code" &&
            (cell as CodeCell).model.executionCount === null
          ) {
            (cell.model as ICodeCellModel).executionState = "idle";
          }
        });
      } else {
        throw reason;
      }
      (NotebookActions.selectionExecuted as SelectionExecutedSignal).emit({
        notebook,
        lastCell
      });
      notebook.update();
      return false;
    });
  }

  async function runCell(
    notebook: Notebook,
    cell: Cell,
    sessionContext?: ISessionContext,
    sessionDialogs?: ISessionContextDialogs,
    translator?: ITranslator
  ): Promise<boolean> {
    if (!executor) {
      console.warn(
        "Requesting cell execution without any cell executor defined. Falling back to default execution."
      );
    }
    const options = {
      cell,
      notebook: notebook.model!,
      notebookConfig: notebook.notebookConfig,
      onCellExecuted: args => {
        (NotebookActions.executed as ExecutedSignal).emit({ notebook, ...args });
      },
      onCellExecutionScheduled: args => {
        (NotebookActions.executionScheduled as ExecutionScheduledSignal).emit({ notebook, ...args });
      },
      sessionContext,
      sessionDialogs,
      translator
    } satisfies INotebookCellExecutor.IRunCellOptions;
    return executor ? executor.runCell(options) : defaultRunCell(options);
  }
}