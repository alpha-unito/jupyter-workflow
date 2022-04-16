define([
    'jquery',
    'base/js/dialog',
    'base/js/namespace',
    'base/js/i18n',
    'services/kernels/kernel',
    'notebook/js/celltoolbar',
    'notebook/js/codecell',
    'notebook/js/notebook'
], function ($, dialog, Jupyter, i18n, _Kernel, _celltoolbar, _codecell, _notebook) {
    return {
        onload: function () {
            "use strict";

            let CellToolbar = _celltoolbar.CellToolbar;
            CellToolbar.prototype.show = function () {
                this.element.addClass('ctb_show');
                if ('workflow' in this.cell.metadata) {
                    this.inner_element.css('background-color', '#337ab7');
                }
            }

            let CodeCell = _codecell.CodeCell;
            CodeCell.prototype.execute = function (stop_on_error) {
                if (!this.kernel) {
                    console.log(i18n.msg._("Can't execute cell since kernel is not set."));
                    return;
                }
                if (this.element.hasClass("running")) {
                    console.log(i18n.msg.sprintf("Cell %s is already running.", this.cell_id));
                    return;
                }
                if (stop_on_error === undefined) {
                    if (this.metadata !== undefined &&
                        this.metadata.tags !== undefined) {
                        stop_on_error = this.metadata.tags.indexOf('raises-exception') === -1;
                    } else {
                        stop_on_error = true;
                    }
                }
                this.clear_output(false, true);
                const old_msg_id = this.last_msg_id;
                if (old_msg_id) {
                    this.kernel.clear_callbacks_for_msg(old_msg_id);
                    delete CodeCell.msg_cells[old_msg_id];
                    this.last_msg_id = null;
                }
                if (this.get_text().trim().length === 0) {
                    // nothing to do
                    this.set_input_prompt(null);
                    return;
                }
                this.set_input_prompt('*');
                this.element.addClass("running");
                const callbacks = this.get_callbacks();
                let kernel_options = {
                    silent: false,
                    store_history: true,
                    stop_on_error: stop_on_error
                }
                if (this.metadata !== undefined && this.metadata.hasOwnProperty('workflow')) {
                    if (this.notebook.metadata !== undefined && this.notebook.metadata.hasOwnProperty('workflow')) {
                        kernel_options.workflow = {
                            ...this.metadata['workflow'],
                            ...this.notebook.metadata['workflow']
                        };
                    } else {
                        kernel_options.workflow = JSON.parse(JSON.stringify(this.metadata['workflow']));
                    }
                    kernel_options.workflow['cell_id'] = this.cell_id;
                } else {
                    kernel_options.workflow = {cell_id: this.cell_id, version: 'v1.0'};
                }
                const background = this.metadata !== undefined &&
                    this.metadata.hasOwnProperty('workflow') &&
                    this.metadata['workflow'].hasOwnProperty('step') &&
                    this.metadata['workflow']['step']['background'];
                if (background) {
                    let content = {
                        code : this.get_text(),
                        silent : true,
                        store_history : false,
                        user_expressions : {},
                        allow_stdin : false
                    };
                    if (callbacks.input !== undefined) {
                        content.allow_stdin = true;
                    }
                    $.extend(true, content, kernel_options)
                    this.kernel.events.trigger('background_execution_request.Kernel', {kernel: this, content: content});
                    return this.kernel.send_shell_message("background_execute_request", content, callbacks);
                } else {
                    this.last_msg_id = this.kernel.execute(this.get_text(), callbacks, kernel_options);
                }
                CodeCell.msg_cells[this.last_msg_id] = this;
                this.render();
                this.events.trigger('execute.CodeCell', {cell: this});
                const that = this;
                function handleFinished(evt, data) {
                    if (that.kernel.id === data.kernel.id && that.last_msg_id === data.msg_id) {
                        that.events.trigger('finished_execute.CodeCell', {cell: that});
                        that.events.off('finished_iopub.Kernel', handleFinished);
                    }
                }
                this.events.on('finished_iopub.Kernel', handleFinished);
            };

            CodeCell.prototype.get_auto_inputs = function (container) {
                if (!this.kernel) {
                    console.log(i18n.msg._("Can't retrieve cell inputs since kernel is not set."));
                    return;
                }

                const content = {
                    code: this.get_text()
                }

                const callbacks = {
                    shell: {
                        reply: $.proxy(this._handle_auto_inputs, this, container),
                        payload: {
                            set_next_input: function () {
                            },
                            page: function () {
                            }
                        }
                    },
                    iopub: {
                        output: function () {
                        },
                        clear_output: function () {
                        }
                    }
                };

                this.events.trigger('get_auto_inputs.CodeCell', {cell: this})
                return this.kernel.send_shell_message("auto_inputs_request", content, callbacks);
            }

            CodeCell.prototype._handle_auto_inputs = function (container, msg) {
                if (msg.content.inputs.length === 0) {
                    container.append($('<span/>')
                        .text('No input dependencies retrieved.'));
                } else {
                    let names = []
                    container.parent().find('.in-container').find('.element-name')
                        .each(function () {
                            names.push($(this).val())
                        });
                    msg.content.inputs.forEach(input => {
                        container.append($('<span/>')
                            .addClass('label')
                            .addClass(names.includes(input) ? 'label-success' : 'label-info')
                            .css('margin', '2px')
                            .css('font-size', '12px')
                            .css('display', 'inline-block')
                            .text(input));
                    });
                }
                const button = container.parent().find('.btn-view-inputs')
                button.prop('disabled', true).delay(500).prop('disabled', false);
                button.removeClass('btn-view-inputs').addClass('btn-hide-inputs');
                button.find('.fa').removeClass('fa-eye').addClass('fa-eye-slash');
            }

            CodeCell.prototype._handle_execute_reply = function (msg) {
                if (msg.content.status === 'background') {
                    this.set_input_prompt("b");
                } else {
                    this.set_input_prompt(msg.content.execution_count);
                    this.element.removeClass("running");
                    this.events.trigger('set_dirty.Notebook', {value: true});
                }
            };

            let _CallbackProxy = function (cells) {
                this._shell = [];
                this._iopub = [];
                this.cells_ids = cells.map(function (cell) {
                    return cell.cell_id;
                });

                this.shell = {
                    reply: $.proxy(this._handle_reply, this),
                    payload: {
                        set_next_input: $.proxy(this._handle_payload_set_next_input, this),
                        page: $.proxy(this._handle_payload_page, this)
                    }
                };
                this.iopub = {
                    output: $.proxy(this._handle_output, this),
                    clear_output: $.proxy(this._handle_clear_output, this)
                };
            };

            _CallbackProxy.prototype._handle_reply = function () {
                const args = arguments;
                this._shell.forEach(function (s) {
                    s.reply.apply(null, args)
                });
            };
            _CallbackProxy.prototype._handle_payload_set_next_input = function () {
                return this._shell[0].payload.set_next_input.apply(null, arguments)
            };
            _CallbackProxy.prototype._handle_payload_page = function () {
                return this._shell[0].payload.page.apply(null, arguments);
            };
            _CallbackProxy.prototype._handle_output = function (msg) {
                const cell_id = msg.content.metadata.cell_id;
                for (let index = 0; index < this.cells_ids.length; index++) {
                    if (this.cells_ids[index] === cell_id) {
                        return this._iopub[index].output.apply(null, arguments);
                    }
                }
            };
            _CallbackProxy.prototype._handle_clear_output = function () {
                return this._iopub[0].clear_output.apply(null, arguments);
            };
            _CallbackProxy.prototype.add_callbacks = function (callbacks) {
                this._shell.push(callbacks.shell);
                this._iopub.push(callbacks.iopub);
            };

            let Notebook = _notebook.Notebook;
            Notebook.prototype.execute_workflow = function () {
                if (!this.kernel) {
                    console.log(i18n.msg._("Can't execute cell since kernel is not set."));
                    return;
                }
                this.clear_output(false, true);
                let notebook = {
                    cells: []
                };
                if (this.metadata !== undefined && this.metadata.hasOwnProperty('workflow')) {
                    notebook.metadata = this.metadata['workflow'];
                }
                const that = this;
                const cells = [...Array(this.ncells()).keys()].map(function (index) {
                    return that.get_cell(index);
                }).filter(function (cell) {
                    return cell.cell_type === 'code';
                });
                if (cells.length === 0) {
                    return;
                }
                let callbacks = new _CallbackProxy(cells);
                cells.forEach(function (cell) {
                    cell.clear_output(false, true);
                    const old_msg_id = cell.last_msg_id;
                    if (old_msg_id) {
                        cell.kernel.clear_callbacks_for_msg(old_msg_id);
                        delete CodeCell.msg_cells[old_msg_id];
                        cell.last_msg_id = null;
                    }
                    if (cell.get_text().trim().length === 0) {
                        cell.set_input_prompt(null);
                        return;
                    }
                    callbacks.add_callbacks(cell.get_callbacks());
                    cell.set_input_prompt('*');
                    cell.element.addClass("running");
                    let cell_object = {code: cell.get_text()}
                    if (cell.metadata !== undefined && cell.metadata.hasOwnProperty('workflow')) {
                        cell_object.metadata = JSON.parse(JSON.stringify(cell.metadata['workflow']));
                    } else {
                        cell_object.metadata = {}
                    }
                    cell_object.metadata['cell_id'] = cell.cell_id;
                    notebook.cells.push(cell_object);
                });
                var content = {
                    notebook: notebook
                };
                this.kernel.events.trigger('workflow_request.Kernel', {kernel: this, content: content});
                return this.kernel.send_shell_message("workflow_request", content, callbacks);
            };

            // Notebook toolbar configuration
            const edit_workflow_action = {
                handler: function (env) {
                    edit_workflow({
                        md: ('workflow' in env.notebook.metadata) ? env.notebook.metadata['workflow'] : {},
                        callback: function (md) {
                            env.notebook.metadata['workflow'] = md;
                            env.notebook.save_checkpoint();
                        },
                        name: i18n.msg._('Notebook'),
                        notebook: env.notebook,
                        keyboard_manager: env.notebook.keyboard_manager
                    });
                },
                help: i18n.msg._('edit workflow metadata'),
                icon: 'fa-gear',
            };
            const run_workflow_action = {
                handler: function (env) {
                    env.notebook.execute_workflow();
                },
                help: i18n.msg._('run the whole notebook asynchronously'),
                icon: 'fa-random',
            };
            const edit_workflow_action_name = Jupyter.actions.register(
                edit_workflow_action, 'edit-workflow', 'jupyter-workflow');
            const run_workflow_action_name = Jupyter.actions.register(
                run_workflow_action, 'run-workflow', 'jupyter-workflow');
            Jupyter.toolbar.add_buttons_group([
                {action: edit_workflow_action_name, label: i18n.msg._('Edit Workflow')},
                {action: run_workflow_action_name, label: i18n.msg._('Run Workflow')}]);

            const get_deletable_el_html = function (name, type) {
                let deletable_el = $('<div/>')
                    .css('border', '1px solid #eeeeee')
                    .css('margin-bottom', '10px')
                $('<legend/>')
                    .css('font-size', '16px')
                    .css('line-height', '32px')
                    .css('margin-left', '2%')
                    .css('width', '98%')
                    .text(name)
                    .append($('<div/>')
                        .addClass('pull-right')
                        .append($('<button/>')
                            .addClass('btn')
                            .addClass('btn-danger')
                            .addClass('btn-delete')
                            .attr('type', 'button')
                            .text(i18n.msg._('Delete'))))
                    .appendTo(deletable_el);
                $('<input/>')
                    .addClass('element-type')
                    .attr('type', 'hidden')
                    .val(type)
                    .appendTo(deletable_el);
                return deletable_el;
            }

            // Field form content
            const get_dep_html = function (inout, name, serializers, serializer, type, value, value_from) {
                let dep_el = get_deletable_el_html(name, inout);
                $('<input/>')
                    .addClass('element-name')
                    .attr('name', inout + '-' + name + '-name')
                    .attr('type', 'hidden')
                    .val(name)
                    .appendTo(dep_el);
                let type_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-right', '2%')
                    .appendTo(dep_el);
                $('<label/>')
                    .attr('for', inout + '-' + name + '-type')
                    .css('margin-left', '2%')
                    .text(i18n.msg._('Type'))
                    .appendTo(type_div)
                let type_select = $('<select/>')
                    .addClass('form-control')
                    .addClass('dep-type')
                    .attr('name', inout + '-' + name + '-type')
                    .css('width', '98%')
                    .appendTo(type_div);
                type_select
                    .append($('<option />')
                        .attr('data-value', 'name')
                        .prop('selected', type === 'name')
                        .text(i18n.msg._('Name'))
                        .val('name'))
                    .append($('<option />')
                        .attr('data-value', 'file')
                        .prop('selected', type === 'file')
                        .text(i18n.msg._('File'))
                        .val('file'))
                    .append($('<option />')
                        .attr('data-value', 'control')
                        .prop('selected', type === 'control')
                        .text(i18n.msg._('Control'))
                        .val('control'))
                if (inout === 'in') {
                    type_select
                        .append($('<option />')
                            .attr('data-value', 'env')
                            .prop('selected', type === 'env')
                            .text(i18n.msg._('Environment'))
                            .val('env'))
                }
                let value_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .css('margin-right', '2%')
                    .appendTo(dep_el);
                $('<label/>')
                    .attr('for', inout + '-' + name + '-value')
                    .text(i18n.msg._('Value'))
                    .appendTo(value_div)
                $('<input/>')
                    .addClass('form-control')
                    .addClass('dep-value')
                    .attr('name', inout + '-' + name + '-value')
                    .attr('placeholder', name)
                    .attr('type', 'text')
                    .val((value !== '') ? value : value_from)
                    .appendTo(value_div);
                let value_from_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .appendTo(dep_el);
                $('<div/>')
                    .addClass('checkbox')
                    .append($('<label/>')
                        .append($('<input/>')
                            .addClass('dep-from-name')
                            .attr('type', 'checkbox')
                            .css('margin-top', '0px')
                            .prop('checked', value_from !== '' || value === ''))
                        .append($('<span/>')
                            .text(i18n.msg._('From name'))))
                    .append($('<a/>')
                        .attr('href', '#')
                        .attr('data-toggle', 'tooltip')
                        .attr('title', i18n.msg.sprintf(
                            'When checked, the %s field is interpreted as a variable name from ' +
                            'which to derive the actual value. When unchecked, the %s field ' +
                            'is instead interpreted as a string value for the variable.',
                            i18n.msg._('Value'), i18n.msg._('Value')))
                        .append($('<i/>')
                            .addClass('fa-question-circle')
                            .addClass('fa')
                            .css('margin-left', '5px')))
                    .appendTo(value_from_div)
                let serializer_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-right', '2%')
                    .appendTo(dep_el);
                $('<label/>')
                    .attr('for', inout + '-' + name + '-serializer')
                    .css('margin-left', '2%')
                    .text(i18n.msg._('Serializer'))
                    .appendTo(serializer_div)
                let serializer_select = $('<select/>')
                    .addClass('form-control')
                    .addClass('dep-serializer')
                    .attr('name', inout + '-' + name + '-serializer')
                    .appendTo(serializer_div);
                serializer_select
                    .append($('<option />')
                        .attr('data-value', '')
                        .text(i18n.msg._('Auto'))
                        .val(''));
                for (let s in serializers) {
                    serializer_select
                        .append($('<option />')
                            .attr('data-value', s)
                            .prop('selected', s === serializer)
                            .text(s)
                            .val(s));
                }
                return dep_el
            }

            // Deployment form html
            const get_deployment_html = function (name, type, external, config) {
                let deployment_el = get_deletable_el_html(name, 'deployment');
                $('<input/>')
                    .addClass('element-name')
                    .attr('name', name + '-name')
                    .attr('type', 'hidden')
                    .val(name)
                    .appendTo(deployment_el);
                let type_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-right', '2%')
                    .appendTo(deployment_el);
                $('<label/>')
                    .attr('for', name + '-type')
                    .css('margin-left', '2%')
                    .text(i18n.msg._('Type'))
                    .appendTo(type_div)
                let type_select = $('<select/>')
                    .addClass('form-control')
                    .addClass('deployment-type')
                    .attr('name', name + '-type')
                    .css('width', '98%')
                    .appendTo(type_div);
                type_select
                    .append($('<option />')
                        .attr('data-value', 'docker')
                        .prop('selected', type === 'docker')
                        .text(i18n.msg._('Docker'))
                        .val('docker'))
                    .append($('<option />')
                        .attr('data-value', 'docker-compose')
                        .prop('selected', type === 'docker-compose')
                        .text(i18n.msg._('Docker Compose'))
                        .val('docker-compose'))
                    .append($('<option />')
                        .attr('data-value', 'helm')
                        .prop('selected', type === 'helm')
                        .text(i18n.msg._('Helm'))
                        .val('helm'))
                    .append($('<option />')
                        .attr('data-value', 'pbs')
                        .prop('selected', type === 'pbs')
                        .text(i18n.msg._('PBS'))
                        .val('pbs'))
                    .append($('<option />')
                        .attr('data-value', 'occam')
                        .prop('selected', type === 'occam')
                        .text(i18n.msg._('Occam'))
                        .val('occam'))
                    .append($('<option />')
                        .attr('data-value', 'singularity')
                        .prop('selected', type === 'singularity')
                        .text(i18n.msg._('Singularity'))
                        .val('singularity'))
                    .append($('<option />')
                        .attr('data-value', 'slurm')
                        .prop('selected', type === 'slurm')
                        .text(i18n.msg._('SLURM'))
                        .val('slurm'))
                    .append($('<option />')
                        .attr('data-value', 'ssh')
                        .prop('selected', type === 'ssh')
                        .text(i18n.msg._('SSH'))
                        .val('ssh'));
                $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .append($('<div/>')
                        .addClass('checkbox')
                        .append($('<label/>')
                            .append($('<input/>')
                                .addClass('deployment-external')
                                .attr('type', 'checkbox')
                                .css('margin-top', '0px')
                                .prop('checked', external))
                            .append($('<span/>')
                                .text(i18n.msg._('External')))))
                    .appendTo(deployment_el);
                let config_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .css('margin-right', '2%')
                    .appendTo(deployment_el);
                $('<label/>')
                    .attr('for', name + '-config')
                    .text(i18n.msg._('Configuration'))
                    .appendTo(config_div);
                $('<textarea/>')
                    .addClass('config-textarea')
                    .attr('rows', '13')
                    .attr('cols', '80')
                    .attr('name', name + '-config')
                    .css('margin-left', '2%')
                    .val(config)
                    .appendTo(config_div);
                return deployment_el;
            }

            // Serializer form html
            const get_serializer_html = function (name, predump, postload) {
                let serializer_el = get_deletable_el_html(name, 'serializer');
                $('<input/>')
                    .addClass('element-name')
                    .attr('name', name + '-name')
                    .attr('type', 'hidden')
                    .val(name)
                    .appendTo(serializer_el);
                let predump_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .css('margin-right', '2%')
                    .appendTo(serializer_el);
                $('<label/>')
                    .attr('for', name + '-predump')
                    .text(i18n.msg._('Predump'))
                    .appendTo(predump_div);
                $('<textarea/>')
                    .addClass('predump-textarea')
                    .attr('rows', '13')
                    .attr('cols', '80')
                    .attr('name', name + '-predump')
                    .css('margin-left', '2%')
                    .val(predump)
                    .appendTo(predump_div);
                let postload_div = $('<div/>')
                    .addClass('form-group')
                    .css('margin-left', '2%')
                    .css('margin-right', '2%')
                    .appendTo(serializer_el);
                $('<label/>')
                    .attr('for', name + '-postload')
                    .text(i18n.msg._('Postload'))
                    .appendTo(postload_div);
                $('<textarea/>')
                    .addClass('postload-textarea')
                    .attr('rows', '13')
                    .attr('cols', '80')
                    .attr('name', name + '-postload')
                    .css('margin-left', '2%')
                    .val(postload)
                    .appendTo(postload_div);
                return serializer_el;
            }

            // Edit Workflow window
            const edit_workflow = function (options) {
                const deployments = ('deployments' in options.md) ? options.md['deployments'] : {};
                const serializers = ('serializers' in options.md) ? options.md['serializers'] : {};
                const error_div = $('<div/>').css('color', 'red');

                let config_editors = {}

                const deployments_html = $('<div/>')
                    .addClass('form-group')
                    .addClass('deployments-container');
                for (let name in deployments) {
                    const deployment = deployments[name];
                    const type = ('type' in deployment) ? deployment['type'] : '';
                    const external = ('external' in deployment) ? deployment['external'] : false;
                    const config = ('config' in deployment) ?
                        JSON.stringify(deployment['config'], null, 2) : '';
                    const deployment_html = get_deployment_html(name, type, external, config)
                    deployments_html.append(deployment_html);
                    config_editors[name] = CodeMirror.fromTextArea(deployment_html.find('.config-textarea')[0], {
                        lineNumbers: true,
                        matchBrackets: true,
                        indentUnit: 2,
                        autoIndent: true,
                        mode: 'application/json',
                    });
                    config_editors[name].setValue(config);
                }

                let predump_editors = {};
                let postload_editors = {};

                const serializers_html = $('<div/>')
                    .addClass('form-group')
                    .addClass('serializers-container');
                for (let name in serializers) {
                    const serializer = serializers[name];
                    const predump = ('predump' in serializer) ? serializer['predump'] : '';
                    const postload = ('postload' in serializer) ? serializer['postload'] : false;
                    const serializer_html = get_serializer_html(name, predump, postload)
                    serializers_html.append(serializer_html);
                    predump_editors[name] = CodeMirror.fromTextArea(serializer_html.find('.predump-textarea')[0], {
                        lineNumbers: true,
                        matchBrackets: true,
                        indentUnit: 4,
                        autoIndent: true,
                        mode: {
                            name: 'python',
                            version: 3,
                            singleLineStringErrors: false
                        }
                    });
                    predump_editors[name].setValue(predump);
                    postload_editors[name] = CodeMirror.fromTextArea(serializer_html.find('.postload-textarea')[0], {
                        lineNumbers: true,
                        matchBrackets: true,
                        indentUnit: 4,
                        autoIndent: true,
                        mode: {
                            name: 'python',
                            version: 3,
                            singleLineStringErrors: false
                        }
                    });
                    postload_editors[name].setValue(postload);
                }

                const dialogform = $('<div/>')
                    .append(
                        $('<form/>')
                            .addClass()
                            .append($('<fieldset/>')
                                .append(error_div)
                                .append($('<br/>')))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<legend/>')
                                    .css('margin-bottom', '5px')
                                    .text(i18n.msg._('Deployments')))
                                .append(deployments_html)
                                .append($('<div/>')
                                    .addClass('input-group')
                                    .addClass('mb-3')
                                    .css('margin-top', '10px')
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('m-input')
                                        .attr('type', 'text')
                                        .attr('name', 'deployment[]')
                                        .attr('placeholder', i18n.msg._('Deployment name')))
                                    .append($('<div/>')
                                        .addClass('input-group-btn')
                                        .append($('<button/>')
                                            .addClass('btn')
                                            .addClass('btn-success')
                                            .addClass('btn-add-deployment')
                                            .attr('type', 'button')
                                            .text(i18n.msg._('Add'))))))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<legend/>')
                                    .css('margin-bottom', '5px')
                                    .text(i18n.msg._('Serializers')))
                                .append(serializers_html)
                                .append($('<div/>')
                                    .addClass('input-group')
                                    .addClass('mb-3')
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('m-input')
                                        .attr('type', 'text')
                                        .attr('name', 'serializer[]')
                                        .attr('placeholder', i18n.msg._('Serializer name')))
                                    .append($('<div/>')
                                        .addClass('input-group-btn')
                                        .append($('<button/>')
                                            .addClass('btn')
                                            .addClass('btn-success')
                                            .addClass('btn-add-serializer')
                                            .attr('type', 'button')
                                            .text(i18n.msg._('Add')))))));

                $('body')
                    .on('click', '.btn-add-deployment', function (event) {
                        $(event.currentTarget).prop('disabled', true).delay(500).prop('disabled', false);
                        const name = $(event.currentTarget).parent().prev().val();
                        if (name === '') {
                            error_div.text(i18n.msg._('WARNING: Specify the deployment name you want to add.'));
                            error_div.focus();
                        } else {
                            let defined_deployments = [];
                            $('.deployments-container').find('.element-name').each(function () {
                                defined_deployments.push($(this).val());
                            });
                            if (defined_deployments.includes(name)) {
                                error_div.text(i18n.msg._('WARNING: This deployment is already defined.'));
                                error_div.focus();
                            } else {
                                error_div.text('');
                                const deployment_html = get_deployment_html(name);
                                $('.deployments-container').append(deployment_html);
                                config_editors[name] = CodeMirror.fromTextArea(
                                    deployment_html.find('.config-textarea')[0], {
                                        lineNumbers: true,
                                        matchBrackets: true,
                                        indentUnit: 2,
                                        autoIndent: true,
                                        mode: 'application/json',
                                    }
                                );
                                $(deployment_html).find('.CodeMirror').css('border', 'solid 1px #eeeeee');
                                $(event.currentTarget).parent().prev().val('')
                            }
                        }
                    })
                    .on('click', '.btn-add-serializer', function (event) {
                        $(event.currentTarget).prop('disabled', true).delay(500).prop('disabled', false);
                        const name = $(event.currentTarget).parent().prev().val();
                        if (name === '') {
                            error_div.text(i18n.msg._('WARNING: Specify the serializer name you want to add.'));
                            error_div.focus();
                        } else {
                            let defined_serializers = [];
                            $('.serializers-container').find('.element-name').each(function () {
                                defined_serializers.push($(this).val());
                            });
                            if (defined_serializers.includes(name)) {
                                error_div.text(i18n.msg._('WARNING: This serializer is already defined.'));
                                error_div.focus();
                            } else {
                                error_div.text('');
                                const serializer_html = get_serializer_html(name);
                                $('.serializers-container').append(serializer_html);
                                predump_editors[name] = CodeMirror.fromTextArea(
                                    $(serializer_html).find('.predump-textarea')[0], {
                                        lineNumbers: true,
                                        matchBrackets: true,
                                        indentUnit: 4,
                                        autoIndent: true,
                                        mode: {
                                            name: 'python',
                                            version: 3,
                                            singleLineStringErrors: false
                                        }
                                    }
                                );
                                postload_editors[name] = CodeMirror.fromTextArea(
                                    $(serializer_html).find('.postload-textarea')[0], {
                                        lineNumbers: true,
                                        matchBrackets: true,
                                        indentUnit: 4,
                                        autoIndent: true,
                                        mode: {
                                            name: 'python',
                                            version: 3,
                                            singleLineStringErrors: false
                                        }
                                    }
                                );
                                $(serializer_html).find('.CodeMirror').css('border', 'solid 1px #eeeeee');
                                $(event.currentTarget).parent().prev().val('')
                            }
                        }
                    })
                    .on('click', '.btn-delete', function (event) {
                        event.stopImmediatePropagation();
                        event.preventDefault();
                        const name = $(event.currentTarget).parent().parent().parent().find('.element-name').val();
                        dialog.modal({
                            title: i18n.msg._('Delete'),
                            body: i18n.msg.sprintf("Are you sure you want to delete the '%s' element?", name),
                            default_button: 'Cancel',
                            buttons: {
                                Cancel: {},
                                Delete: {
                                    class: "btn-danger",
                                    click: function () {
                                        const el = $(event.currentTarget).parent().parent().parent();
                                        const name = el.find('.element-name').val();
                                        const type = el.find('.element-type').val();
                                        if (type === 'deployment') {
                                            delete config_editors[name];
                                        } else if (type === 'serializer') {
                                            delete predump_editors[name];
                                            delete postload_editors[name];
                                        }
                                        el.remove();
                                    }
                                }
                            }
                        });
                    });

                const modal_obj = dialog.modal({
                    title: i18n.msg._("Edit Workflow"),
                    body: dialogform,
                    default_button: "Cancel",
                    buttons: {
                        Cancel: {},
                        Reset: {
                            class: "btn-danger",
                            click: function () {
                                dialog.modal({
                                    title: i18n.msg._('Reset Cell Connfiguration'),
                                    body: i18n.msg._("Are you sure you want to restore the default configuration for this cell?"),
                                    default_button: 'Cancel',
                                    buttons: {
                                        Cancel: {},
                                        Reset: {
                                            class: "btn-danger",
                                            click: function () {
                                                options.callback({})
                                            }
                                        }
                                    }
                                });
                            }
                        },
                        Edit: {
                            class: "btn-primary",
                            click: function (event) {
                                let new_md = {};
                                new_md['deployments'] = {};
                                dialogform.find('.deployments-container').children().each(function () {
                                    const name = $(this).find('.element-name').val();
                                    try {
                                        new_md['deployments'][name] = {
                                            type: $(this).find('.deployment-type').find(':selected').val(),
                                            external: $(this).find('.deployment-external').prop('checked'),
                                        };
                                        const config_string = config_editors[name].getValue();
                                        if (config_string !== '') {
                                            new_md['deployments'][name].config = JSON.parse(config_string);
                                        }
                                    } catch (e) {
                                        console.log(e);
                                        error_div.text(i18n.msg._('WARNING: Invalid deployment config JSON.'));
                                        event.preventDefault();
                                        event.stopImmediatePropagation();
                                    }
                                });
                                new_md['serializers'] = {};
                                dialogform.find('.serializers-container').children().each(function () {
                                    const name = $(this).find('.element-name').val();
                                    new_md['serializers'][name] = {
                                        predump: predump_editors[name].getValue(),
                                        postload: postload_editors[name].getValue()
                                    };
                                });
                                options.callback(new_md);
                                options.notebook.apply_directionality();
                            }
                        }
                    },
                    notebook: options.notebook,
                    keyboard_manager: options.keyboard_manager,
                });
                modal_obj.find('.modal')
                    .css('display', 'block');
                modal_obj.find('.modal-dialog')
                    .css('overflow-y', 'initial');
                modal_obj.find('.modal-body')
                    .css('height', '80vh')
                    .css('overflow-y', 'auto');

                modal_obj.on('shown.bs.modal', function () {
                    modal_obj.find('.CodeMirror').each(function () {
                        $(this).css('border', 'solid 1px #eeeeee');
                    });
                    for (let name in config_editors) {
                        config_editors[name].refresh();
                    }
                    for (let name in predump_editors) {
                        predump_editors[name].refresh();
                    }
                    for (let name in postload_editors) {
                        postload_editors[name].refresh();
                    }
                });
            }

            // Edit Step window
            const edit_step = function (options) {
                const interpreter = ('interpreter' in options.md) ? options.md['interpreter'] : '';
                const serializers = ('serializers' in options.notebook_md) ? options.notebook_md['serializers'] : [];
                const step = ('step' in options.md) ? options.md['step'] : {};
                const background = ('background' in step) ? step['background'] : false;
                const inputs = ('in' in step) ? step['in'] : [];
                const outputs = ('out' in step) ? step['out'] : [];
                const autoin = ('autoin' in step) ? step['autoin'] : true;
                const scatter = ('scatter' in step) ? JSON.stringify(step['scatter'], null, 2) : '';
                const target = ('target' in options.md) ? options.md['target'] : {};
                const deployment = ('deployment' in target) ? target['deployment'] : '';
                const locations = ('locations' in target) ? target['locations'] : 1;
                const service = ('service' in target) ? target['service'] : '';
                const workdir = ('workdir' in target) ? target['workdir'] : '';
                const error_div = $('<div/>').css('color', 'red');

                const inputs_html = $('<div/>')
                    .addClass('form-group')
                    .addClass('in-container');
                inputs.forEach(input => {
                    const name = ('name' in input) ? input['name'] : '';
                    const serializer = ('serializer' in input) ? input['serializer'] : undefined;
                    const type = ('type' in input) ? input['type'] : '';
                    const value = ('value' in input) ? input['value'] : '';
                    const value_from = ('valueFrom' in input) ? input['valueFrom'] : '';
                    const input_html = get_dep_html('in', name,
                        serializers, serializer, type, value, value_from);
                    inputs_html.append(input_html);
                });

                const outputs_html = $('<div/>')
                    .addClass('form-group')
                    .addClass('out-container');
                outputs.forEach(output => {
                    const name = ('name' in output) ? output['name'] : '';
                    const serializer = ('serializer' in output) ? output['serializer'] : undefined;
                    const type = ('type' in output) ? output['type'] : '';
                    const value = ('value' in output) ? output['value'] : '';
                    const value_from = ('valueFrom' in output) ? output['valueFrom'] : '';
                    const output_html = get_dep_html('out', name,
                        serializers, serializer, type, value, value_from)
                    outputs_html.append(output_html);
                });

                const deployment_select = $('<select/>')
                    .addClass('form-control')
                    .addClass('target-deployment')
                    .attr('name', 'target')
                    .css('margin-left', '0%');
                deployment_select
                    .append($('<option />')
                        .attr('data-value', 'local')
                        .text(i18n.msg._('Local Process'))
                        .val(''));
                const deployments = ('deployments' in options.notebook_md) ? options.notebook_md['deployments'] : {};
                for (let d in deployments) {
                    deployment_select
                        .append($('<option />')
                            .attr('data-value', d)
                            .prop('selected', d === deployment)
                            .text(d)
                            .val(d));
                }

                const dialogform = $('<div/>')
                    .append(
                        $('<form/>')
                            .append($('<fieldset/>')
                                .append(error_div)
                                .append($('<br/>')))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<legend/>')
                                    .css('margin-bottom', '10px')
                                    .text(i18n.msg._('Configuration')))
                                .append($('<div/>')
                                    .addClass('checkbox-inline')
                                    .css('margin-top', '5px')
                                    .append($('<label/>')
                                        .append($('<input/>')
                                            .addClass('step-background')
                                            .attr('type', 'checkbox')
                                            .css('margin-top', '0px')
                                            .prop('checked', background)
                                            .prop('disabled', outputs.length > 0))
                                        .append($('<span/>')
                                            .text(i18n.msg._('Execute in background')))
                                    .append($('<a/>')
                                        .attr('href', '#')
                                        .attr('data-toggle', 'tooltip')
                                        .attr('title', i18n.msg._(
                                            'A cell without output ports can run in background when the noteboook ' +
                                            'is in interactive mode. Note that this has no effect in workflow mode'))
                                        .append($('<i/>')
                                            .addClass('fa-question-circle')
                                            .addClass('fa')
                                            .css('margin-left', '5px'))))))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<div/>')
                                    .addClass('form-inline')
                                    .append($('<legend/>')
                                        .css('margin-bottom', '10px')
                                        .text(i18n.msg._('Inputs')))
                                    .append($('<div/>')
                                        .addClass('col-md-11')
                                        .addClass('form-group')
                                        .append($('<div/>')
                                            .addClass('checkbox-inline')
                                            .css('margin-top', '5px')
                                            .append($('<label/>')
                                                .append($('<input/>')
                                                    .addClass('step-autoin')
                                                    .attr('type', 'checkbox')
                                                    .css('margin-top', '0px')
                                                    .prop('checked', autoin))
                                                .append($('<span/>')
                                                    .text(i18n.msg._('Automatically infer input dependencies')))))))
                                .append($('<div/>')
                                    .addClass('col-md-1')
                                    .addClass('text-right')
                                    .addClass('form-group')
                                    .append($('<div/>')
                                        .addClass('input-group-btn')
                                        .append($('<button/>')
                                            .addClass('btn')
                                            .addClass('btn-info')
                                            .addClass('btn-view-inputs')
                                            .attr('cell-id', options.cell.cell_id)
                                            .attr('type', 'button')
                                            .prop('disabled', !autoin)
                                            .append($('<i/>')
                                                .addClass('fa-eye')
                                                .addClass('fa')))))
                                .append(inputs_html)
                                .append($('<div/>')
                                    .addClass('input-group')
                                    .addClass('col-md-12')
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('m-input')
                                        .attr('type', 'text')
                                        .attr('name', 'in[]')
                                        .attr('placeholder', i18n.msg._('Input name')))
                                    .append($('<div/>')
                                        .addClass('input-group-btn')
                                        .append($('<button/>')
                                            .addClass('btn')
                                            .addClass('btn-success')
                                            .addClass('btn-add-input')
                                            .attr('type', 'button')
                                            .text(i18n.msg._('Add'))))))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<legend/>')
                                    .css('margin-bottom', '5px')
                                    .text(i18n.msg._('Scatter')))
                                .append($('<textarea/>')
                                    .addClass('scatter-textarea')
                                    .attr('rows', '13')
                                    .attr('cols', '80')
                                    .attr('name', name + '-scatter')
                                    .css('margin-left', '2%')
                                    .val(scatter)))
                            .append($('<fieldset/>')
                                .css('margin-bottom', '20px')
                                .append($('<legend/>')
                                    .css('margin-bottom', '5px')
                                    .text(i18n.msg._('Outputs')))
                                .append(outputs_html)
                                .append($('<div/>')
                                    .addClass('input-group')
                                    .addClass('mb-3')
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('m-input')
                                        .attr('type', 'text')
                                        .attr('name', 'out[]')
                                        .attr('placeholder', i18n.msg._('Output name')))
                                    .append($('<div/>')
                                        .addClass('input-group-btn')
                                        .append($('<button/>')
                                            .addClass('btn')
                                            .addClass('btn-success')
                                            .addClass('btn-add-output')
                                            .attr('type', 'button')
                                            .text(i18n.msg._('Add'))))))
                            .append($('<fieldset/>')
                                .append($('<legend/>')
                                    .text(i18n.msg._('Target')))
                                .append($('<div/>')
                                    .addClass('form-group')
                                    .append($('<label/>')
                                        .attr('for', 'deployment')
                                        .text(i18n.msg._('Deployment')))
                                    .append(deployment_select))
                                .append($('<div/>')
                                    .addClass('form-group')
                                    .append($('<label/>')
                                        .attr('for', 'locations')
                                        .text(i18n.msg._('Locations')))
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('target-locations')
                                        .attr('name', 'locations')
                                        .attr('type', 'number')
                                        .attr('min', 1)
                                        .val(locations)))
                                .append($('<div/>')
                                    .addClass('form-group')
                                    .append($('<label/>')
                                        .attr('for', 'service')
                                        .text(i18n.msg._('Service')))
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('target-service')
                                        .attr('name', 'service')
                                        .attr('type', 'text')
                                        .val(service)))
                                .append($('<div/>')
                                    .addClass('form-group')
                                    .append($('<label/>')
                                        .attr('for', 'workdir')
                                        .text(i18n.msg._('Workdir')))
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('target-workdir')
                                        .attr('name', 'workdir')
                                        .attr('placeholder', '/tmp/streamflow')
                                        .attr('type', 'text')
                                        .val(workdir)))
                                .append($('<div/>')
                                    .addClass('form-group')
                                    .append($('<label/>')
                                        .attr('for', 'interpreter')
                                        .text(i18n.msg._('Python Interpreter')))
                                    .append($('<input/>')
                                        .addClass('form-control')
                                        .addClass('python-interpreter')
                                        .attr('name', 'interpreter')
                                        .attr('placeholder', 'ipython')
                                        .attr('type', 'text')
                                        .val(interpreter)))));

                const scatter_textarea = dialogform.find('.scatter-textarea');
                const scatter_editor = CodeMirror.fromTextArea(scatter_textarea[0], {
                    lineNumbers: true,
                    matchBrackets: true,
                    indentUnit: 2,
                    autoIndent: true,
                    mode: 'application/json',
                });
                scatter_editor.setValue(scatter_textarea.val());

                $('body')
                    .on('click', '.btn-add-input', function (event) {
                        $(event.currentTarget).prop('disabled', true).delay(500).prop('disabled', false);
                        const name = $(event.currentTarget).parent().prev().val();
                        if (name === '') {
                            error_div.text(i18n.msg._('WARNING: Specify the input name you want to add.'));
                            error_div.focus();
                        } else {
                            let defined_names = [];
                            $('.in-container').find('.element-name').each(function () {
                                defined_names.push($(this).val());
                            });
                            if (defined_names.includes(name)) {
                                error_div.text(i18n.msg._('WARNING: This name is already defined.'));
                                error_div.focus();
                            } else {
                                error_div.text('');
                                $('.in-container').append(get_dep_html('in', name, serializers));
                                $(event.currentTarget).parent().prev().val('');
                                $('.auto-inputs-container').find('.label-info').each(function () {
                                    if (name === $(this).text()) {
                                        $(this).removeClass('label-info').addClass('label-success');
                                    }
                                });
                            }
                        }
                    })
                    .on('click', '.btn-add-output', function (event) {
                        $(event.currentTarget).prop('disabled', true).delay(500).prop('disabled', false);
                        const name = $(event.currentTarget).parent().prev().val();
                        if (name === '') {
                            error_div.text(i18n.msg._('WARNING: Specify the output name you want to add.'));
                            error_div.focus();
                            return false;
                        } else {
                            let defined_names = [];
                            $('.out-container').find('.element-name').each(function () {
                                defined_names.push($(this).val());
                            });
                            if (defined_names.includes(name)) {
                                error_div.text(i18n.msg._('WARNING: This name is already defined.'));
                                error_div.focus();
                            } else {
                                error_div.text('');
                                $('.out-container').append(get_dep_html('out', name, serializers));
                                $(event.currentTarget).parent().prev().val('')
                            }
                            $('.step-background').prop('disabled', true).prop('checked', false);
                        }
                    })
                    .on('click', '.btn-delete', function (event) {
                        event.stopImmediatePropagation();
                        event.preventDefault();
                        const name = $(event.currentTarget).parent().parent().parent().find('.element-name').val();
                        dialog.modal({
                            title: i18n.msg._('Delete'),
                            body: i18n.msg.sprintf("Are you sure you want to delete the '%s' element?", name),
                            default_button: 'Cancel',
                            buttons: {
                                Cancel: {},
                                Delete: {
                                    class: "btn-danger",
                                    click: function () {
                                        const el = $(event.currentTarget).parent().parent().parent();
                                        const name = el.find('.element-name').val();
                                        const type = el.find('.element-type').val();
                                        el.remove();
                                        if (type === 'in') {
                                            $('.auto-inputs-container').find('.label-success').each(function () {
                                                if (name === $(this).text()) {
                                                    $(this).removeClass('label-success').addClass('label-info');
                                                }
                                            });
                                        } else if (type === 'out') {
                                            if ($('.out-container').children().length === 0) {
                                                $('.step-background').prop('disabled', false);
                                            }
                                        }
                                    }
                                }
                            }
                        })
                    })
                    .on('click', '.btn-view-inputs', {notebook: options.cell.notebook}, function (event) {
                        event.stopImmediatePropagation();
                        event.preventDefault();

                        const button = $(event.currentTarget);

                        let container = button.parent().parent().parent()
                            .find('.auto-inputs-container');
                        if (container.length) {
                            button.prop('disabled', true).delay(500).prop('disabled', false);
                            button.removeClass('btn-view-inputs').addClass('btn-hide-inputs');
                            button.find('.fa').removeClass('fa-eye').addClass('fa-eye-slash');
                            container.css('display', '');
                        } else {
                            button.prop('disabled', true);
                            container = $('<div/>')
                                .addClass('auto-inputs-container')
                                .addClass('form-group')
                                .css('width', '100%')
                                .css('padding', '5px')
                                .css('margin-top', '10px')
                                .insertAfter(button.parent().parent());
                            const cell_id = button.attr('cell-id');
                            event.data.notebook
                                .get_cells()
                                .find(c => c.cell_id === cell_id)
                                .get_auto_inputs(container);
                        }
                    })
                    .on('click', '.btn-hide-inputs', function (event) {
                        event.stopImmediatePropagation();
                        event.preventDefault();

                        const button = $(event.currentTarget);
                        button.prop('disabled', true).delay(500).prop('disabled', false);
                        button.removeClass('btn-hide-inputs').addClass('btn-view-inputs');
                        button.find('.fa').removeClass('fa-eye-slash').addClass('fa-eye');

                        const container = $(event.currentTarget).parent().parent().parent()
                            .find('.auto-inputs-container');
                        container.css('display', 'none');
                    });

                const modal_obj = dialog.modal({
                    title: i18n.msg._("Edit Workflow Step"),
                    body: dialogform,
                    default_button: "Cancel",
                    buttons: {
                        Cancel: {},
                        Reset: {
                            class: "btn-danger",
                            click: function () {
                                dialog.modal({
                                    title: i18n.msg._('Reset Cell Connfiguration'),
                                    body: i18n.msg._("Are you sure you want to restore the default configuration for this cell?"),
                                    default_button: 'Cancel',
                                    buttons: {
                                        Cancel: {},
                                        Reset: {
                                            class: "btn-danger",
                                            click: function () {
                                                options.callback({})
                                            }
                                        }
                                    }
                                });
                            }
                        },
                        Edit: {
                            class: "btn-primary",
                            click: function (event) {
                                let new_md = {};
                                new_md['version'] = 'v1.0';
                                const interpreter = dialogform.find('.python-interpreter').val();
                                if (interpreter !== '') {
                                    new_md['interpreter'] = interpreter;
                                }
                                new_md['step'] = {};
                                const background = dialogform.find('.step-background')
                                if (!background.prop('disabled')) {
                                    new_md['step']['background'] = dialogform.find('.step-background').prop('checked');
                                } else {
                                    new_md['step']['background'] = false;
                                }
                                new_md['step']['in'] = [];
                                dialogform.find('.in-container').children().each(function () {
                                    const name = $(this).find('.element-name').val();
                                    let input = {
                                        name: name,
                                        type: $(this).find('.dep-type').find(':selected').val()
                                    };
                                    const serializer = $(this).find('.dep-serializer').find(':selected').val();
                                    if (serializer !== '') {
                                        input.serializer = serializer;
                                    }
                                    const from_name = $(this).find('.dep-from-name').prop('checked');
                                    if (from_name) {
                                        const value_from = $(this).find('.dep-value').val()
                                        input.valueFrom = (value_from !== '') ? value_from : name;
                                    } else {
                                        const value = $(this).find('.dep-value').val();
                                        if (value !== '') {
                                            input.value = value;
                                        }
                                    }
                                    new_md['step']['in'].push(input);
                                });
                                try {
                                    const scatter_string = scatter_editor.getValue();
                                    if (scatter_string !== '') {
                                        new_md['step']['scatter'] = JSON.parse(scatter_string);
                                    }
                                } catch (e) {
                                    console.log(e);
                                    error_div.text(i18n.msg._('WARNING: Invalid scatter config JSON.'));
                                    event.preventDefault();
                                    event.stopImmediatePropagation();
                                }
                                new_md['step']['autoin'] = dialogform.find('.step-autoin').prop('checked');
                                new_md['step']['out'] = [];
                                dialogform.find('.out-container').children().each(function () {
                                    const name = $(this).find('.element-name').val();
                                    try {
                                        let output = {
                                            name: name,
                                            type: $(this).find('.dep-type').find(':selected').val()
                                        };
                                        const serializer = $(this).find('.dep-serializer').find(':selected').val();
                                        if (serializer !== '') {
                                            output.serializer = serializer;
                                        }
                                        const from_name = $(this).find('.dep-from-name').prop('checked');
                                        if (from_name) {
                                            const value_from = $(this).find('.dep-value').val()
                                            output.valueFrom = (value_from !== '') ? value_from : name;
                                        } else {
                                            const value = $(this).find('.dep-value').val();
                                            if (value !== '') {
                                                output.value = value;
                                            }
                                        }
                                        new_md['step']['out'].push(output);
                                    } catch (e) {
                                        console.log(e);
                                        error_div.text(i18n.msg._('WARNING: Invalid output scatter JSON.'));
                                        event.preventDefault();
                                        event.stopImmediatePropagation();
                                    }
                                });

                                const deployment = dialogform.find('.target-deployment').find(':selected').val();
                                if (deployment !== '') {
                                    new_md['target'] = {
                                        deployment: deployment,
                                        locations: parseInt(dialogform.find('.target-locations').val()),
                                        service: dialogform.find('.target-service').val(),
                                        workdir: dialogform.find('.target-workdir').val()
                                    };
                                }

                                options.callback(new_md);
                                options.notebook.apply_directionality();
                            }
                        }
                    },
                    notebook: options.notebook,
                    keyboard_manager: options.keyboard_manager
                });
                modal_obj.find('.modal')
                    .css('display', 'block');
                modal_obj.find('.modal-dialog')
                    .css('overflow-y', 'initial');
                modal_obj.find('.modal-body')
                    .css('height', '80vh')
                    .css('overflow-y', 'auto');

                modal_obj.on('shown.bs.modal', function () {
                    modal_obj.find('.CodeMirror').each(function () {
                        $(this).css('border', 'solid 1px #eeeeee');
                    });
                    scatter_editor.refresh();
                });
            }

            // CellToolbar configuration
            let step_edit = function (cell, edit_step_button) {
                edit_step({
                    cell: cell,
                    md: ('workflow' in cell.metadata) ? cell.metadata['workflow'] : {},
                    notebook_md: ('workflow' in cell.notebook.metadata) ? cell.notebook.metadata['workflow'] : {},
                    callback: function (md) {
                        if ($.isEmptyObject(md)) {
                            cell.celltoolbar.inner_element.css('background-color', '#eeeeee');
                            delete cell.metadata['workflow'];
                        } else {
                            cell.celltoolbar.inner_element.css('background-color', '#337ab7');
                            cell.metadata['workflow'] = md;
                        }
                        delete cell.notebook.save_checkpoint();
                    },
                    name: i18n.msg._('Cell'),
                    notebook: cell.notebook,
                    keyboard_manager: cell.notebook.keyboard_manager,
                    edit_step_button: edit_step_button
                });
            };

            const add_step_edit_button = function (div, cell) {
                const button_container = $(div);
                const button = $('<button/>')
                    .addClass('btn')
                    .addClass('btn-default')
                    .addClass('btn-xs')
                    .click(function () {
                        step_edit(cell, this);
                        return false;
                    })
                    .append($('<i/>')
                        .addClass('fa-gear')
                        .addClass('fa'))
                    .append($('<span/>')
                        .addClass('toolbar-btn-label')
                        .text(i18n.msg._("Edit Workflow Step")));
                button_container.append(button);
            };

            const example_preset = [];
            example_preset.push('default.stepedit');

            CellToolbar.register_callback('default.stepedit', add_step_edit_button, [null, 'code']);
            CellToolbar.register_preset(i18n.msg._('Edit Workflow Step'), example_preset, notebook);
            CellToolbar.activate_preset(i18n.msg._('Edit Workflow Step'));
            CellToolbar.global_show();
        }
    }
});
