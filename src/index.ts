import { JupyterFrontEndPlugin } from "@jupyterlab/application";
import { executor } from "./executor";

const plugins : JupyterFrontEndPlugin<any>[] = [
  executor
];

export default plugins;