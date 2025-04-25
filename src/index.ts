import { JupyterFrontEndPlugin } from '@jupyterlab/application';
import { executor } from './executor';
import { commands } from './command';

const plugins: JupyterFrontEndPlugin<any>[] = [commands, executor];

export default plugins;
