import { JupyterFrontEndPlugin } from '@jupyterlab/application';
import { executor } from './executor';
import { commands } from './command';
import { editor } from './editor';

const plugins: JupyterFrontEndPlugin<any>[] = [commands, editor, executor];

export default plugins;
