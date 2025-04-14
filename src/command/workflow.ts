import {
  INotebookCellExecutor,
  KernelError,
  Notebook,
  NotebookActions,
  runCell as defaultRunCell
} from "@jupyterlab/notebook";
import { ISessionContext, ISessionContextDialogs, Notification } from "@jupyterlab/apputils";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { Cell, CodeCell, ICodeCellModel } from "@jupyterlab/cells";
import { Signal } from "@lumino/signaling";
import {JSONObject, PromiseDelegate} from "@lumino/coreutils";
import { KernelMessage } from "@jupyterlab/services";

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
      metadata?: JSONObject,
      sessionContext?: ISessionContext
  ): Promise<KernelMessage.IExecuteReplyMsg> {
    const content = {
      notebook: {
        cells: cells.map(cell => {
          const model = cell.model;
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
    const kernel = sessionContext?.session?.kernel;
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
    return kernel.sendShellMessage(request, true, false).done;
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
    const lastCell = cells[cells.length - 1];
    notebook.mode = "command";
    let initializingDialogShown = false;
    const workflowCells: CodeCell[] = [];
    const delegates: PromiseDelegate<boolean>[] = [];
    const promises: (Promise<boolean> | PromiseDelegate<boolean>)[] = cells.map(cell => {
      if (
          cell.model.type === "code" &&
          notebook.notebookConfig.enableKernelInitNotification &&
          sessionContext &&
          sessionContext.kernelDisplayStatus === "initializing" &&
          !initializingDialogShown
      ) {
        initializingDialogShown = true;
        translator = translator ?? nullTranslator;
        const trans = translator.load("jupyterlab");
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
        workflowCells.push(cell as CodeCell);
        const delegate = new PromiseDelegate<boolean>();
        delegates.push(delegate);
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
      const reply = await execute(workflowCells, notebook.model?.getMetadata("workflow"), sessionContext);
      if (reply.content.status === "ok") {
        delegates.forEach(delegate => {
          delegate.resolve(true);
        });
      } else {
        delegates.forEach(delegate => {
          delegate.reject(reply.content);
        })
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