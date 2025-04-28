import { MetadataForm, MetadataFormWidget } from '@jupyterlab/metadataform';
import { ITranslator, nullTranslator } from '@jupyterlab/translation';
import { WidgetProps } from '@rjsf/utils';
import React from 'react';

export const SwitchWidget = function (props: WidgetProps) {
  return (
    <button
      aria-checked={props.value}
      className="jp-switch"
      id={props.id}
      onClick={() => props.onChange(!props.value)}
      role="switch"
      title={props.label}
    >
      <label className="jp-switch-label" title={props.label}>
        {props.label}
      </label>
      <div className="jp-switch-track" aria-hidden="true" />
    </button>
  );
};

export class WorkflowPanel extends MetadataFormWidget {
  constructor(options: WorkflowPanel.IOptions) {
    super({
      metadataSchema: options.schema,
      metaInformation: {},
      pluginId: `jupyter-workflow-editor-${options.title.toLowerCase()}`,
      translator: options.translator
    });
    const trans = (options.translator ?? nullTranslator).load('jupyterlab');
    this.title.label = trans.__(options.title);
    this.addClass('jp-WorkflowEditorPanel');
    this.addClass(`jp-WorkflowEditor${options.title}`);
  }
}

export namespace WorkflowPanel {
  export interface IOptions {
    schema: MetadataForm.IMetadataSchema;
    title: string;
    translator?: ITranslator;
  }
}
