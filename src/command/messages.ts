import { JSONObject } from "@lumino/coreutils";
import { IShellMessage } from "@jupyterlab/services/lib/kernel/messages";


export interface IWorkflowRequestMsg extends IShellMessage {
  content: {
    notebook: {
      cells: JSONObject[],
      metadata?: JSONObject
    }
  }
}