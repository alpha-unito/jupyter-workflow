import { NotebookTools } from '@jupyterlab/notebook';
import { nullTranslator } from '@jupyterlab/translation';
import { treeViewIcon } from '@jupyterlab/ui-components';
import { MetadataForm } from '@jupyterlab/metadataform';
import { WorkflowPanel } from './widgets';

export class WorkflowEditor extends NotebookTools {
  constructor(options: WorkflowEditor.IOptions) {
    super(options);
    const translator = options.translator || nullTranslator;
    const trans = translator.load('jupyterlab');
    this.id = 'jupyter-workflow-workflow-editor';
    this.title.caption = trans.__('Workflow Editor');
    this.title.icon = treeViewIcon;
    this.addClass('jp-WorkflowEditor');
    this.addSection({
      sectionName: 'jupyter-workflow:workflow-editor-step-section',
      label: trans.__('Step'),
      rank: 10,
      tool: new WorkflowPanel({
        schema: {
          ...options.schema,
          properties: { 'workflow/step': options.schema.properties.step }
        },
        title: 'Step',
        translator: translator
      })
    });
    this.addSection({
      sectionName: 'jupyter-workflow:workflow-editor-target-section',
      label: trans.__('Target'),
      rank: 20,
      tool: new WorkflowPanel({
        schema: {
          ...options.schema,
          properties: { 'workflow/target': options.schema.properties.target }
        },
        title: 'Target',
        translator: translator
      })
    });
    this.addSection({
      sectionName: 'jupyter-workflow:workflow-editor-deployments-section',
      label: trans.__('Deployments'),
      rank: 30,
      tool: new WorkflowPanel({
        schema: {
          ...options.schema,
          properties: {
            'workflow/deployments': options.schema.properties.deployments
          }
        },
        title: 'Deployments',
        translator: translator
      })
    });
    this.addSection({
      sectionName: 'jupyter-workflow:workflow-editor-serializers-section',
      label: trans.__('Serializers'),
      rank: 40,
      tool: new WorkflowPanel({
        schema: {
          ...options.schema,
          properties: {
            'workflow/serializers': options.schema.properties.serializers
          }
        },
        title: 'Serializers',
        translator: translator
      })
    });
  }

  addSection(options: NotebookTools.IAddSectionOptions): void {
    super.addSection(options);
    if (options.tool) {
      options.tool.notebookTools = this;
    }
  }
}

export namespace WorkflowEditor {
  export interface IOptions extends NotebookTools.IOptions {
    schema: MetadataForm.IMetadataSchema;
  }
}
