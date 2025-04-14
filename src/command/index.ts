import { JupyterFrontEnd, JupyterFrontEndPlugin } from "@jupyterlab/application";
import { ITranslator, nullTranslator } from "@jupyterlab/translation";
import { ICommandPalette, ISessionContextDialogs, SemanticCommand, SessionContextDialogs } from "@jupyterlab/apputils";
import { INotebookCellExecutor, INotebookTracker, NotebookPanel } from "@jupyterlab/notebook";
import { ReadonlyPartialJSONObject } from "@lumino/coreutils";
import { setCellExecutor, WorkflowActions } from "./workflow";

namespace CommandIDs {
  export const RESTART_RUN_WORKFLOW = "jupuyter-workflow:restart-run-workflow";
  export const RUN_WORKFLOW = "jupuyter-workflow:run-workflow";
}

function getCurrent(
  tracker: INotebookTracker,
  shell: JupyterFrontEnd.IShell,
  args: ReadonlyPartialJSONObject
): NotebookPanel | null {
  const widget = args[SemanticCommand.WIDGET]
    ? tracker.find(panel => panel.id === args[SemanticCommand.WIDGET]) ?? null
    : tracker.currentWidget;
  const activate = args["activate"] !== false;

  if (activate && widget) {
    shell.activateById(widget.id);
  }

  return widget;
}

export const commands: JupyterFrontEndPlugin<void> = {
  id: "jupyter-workflow:plugin",
  autoStart: true,
  requires: [INotebookCellExecutor, INotebookTracker],
  optional: [ICommandPalette, ISessionContextDialogs, ITranslator],
  activate: async (
    app: JupyterFrontEnd,
    executor: INotebookCellExecutor,
    tracker: INotebookTracker,
    palette: ICommandPalette | null,
    sessionDialogs: ISessionContextDialogs | null,
    translator: ITranslator | null
  ) => {
    translator = translator ?? nullTranslator;
    sessionDialogs = sessionDialogs ?? new SessionContextDialogs({ translator });
    const trans = translator.load("jupyterlab");
    setCellExecutor(executor);
    app.commands.addCommand(CommandIDs.RESTART_RUN_WORKFLOW, {
      label: trans.__("Restart Kernel and Run Workflow"),
      caption: trans.__("Restart the Kernel and run the whole notebook as a distributed workflow"),
      execute: async args => {
        const current = getCurrent(tracker, app.shell, { activate: false, ...args });
        if (!current) {
          return;
        }
        const restarted = await sessionDialogs.restart(current.sessionContext);
        if (restarted) {
          const { context, content } = current;
          return WorkflowActions.runWorkflow(
            content,
            context.sessionContext,
            sessionDialogs,
            translator
          );
        }
      }
    });
    app.commands.addCommand(CommandIDs.RUN_WORKFLOW, {
      label: trans.__("Run Workflow"),
      caption: trans.__("Run the whole notebook as a distributed workflow"),
      execute: args => {
        const current = getCurrent(tracker, app.shell, args);
        if (current) {
          const { context, content } = current;
          return WorkflowActions.runWorkflow(
            content,
            context.sessionContext,
            sessionDialogs,
            translator
          );
        }
      }
    });
    if (palette) {
      palette.addItem({
        command: CommandIDs.RESTART_RUN_WORKFLOW,
        category: trans.__("Workflow")
      });
      palette.addItem({
        command: CommandIDs.RUN_WORKFLOW,
        category: trans.__("Workflow")
      });
    }
  }
};