define([
    'jquery',
    'base/js/namespace',
    'base/js/i18n',
    'services/kernels/kernel',
    'notebook/js/codecell',
    'notebook/js/notebook'
], function ($, Jupyter, i18n, _Kernel, _codecell, _notebook) {
    return {
        onload: function () {
            "use strict";

            let CodeCell = _codecell.CodeCell
            CodeCell.prototype.execute = function (stop_on_error) {
                if (!this.kernel) {
                    console.log(i18n.msg._("Can't execute cell since kernel is not set."));
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
                    store_history: false,
                    stop_on_error: stop_on_error
                }

                if (this.metadata !== undefined && this.metadata.hasOwnProperty('workflow')) {
                    if (this.notebook.metadata !== undefined && this.notebook.metadata.hasOwnProperty('workflow')) {
                        kernel_options.workflow = {
                            ...this.metadata['workflow'],
                            ...this.notebook.metadata['workflow']};
                    } else {
                        kernel_options.workflow = JSON.parse(JSON.stringify(this.metadata['workflow']));
                    }
                    kernel_options.workflow['cell_id'] = this.cell_id;
                }

                this.last_msg_id = this.kernel.execute(this.get_text(), callbacks, kernel_options);

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

            let _CallbackProxy = function(cells) {
                this._shell = [];
                this._iopub = [];
                this.cells_ids = cells.map(function(cell) {
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

            _CallbackProxy.prototype._handle_reply = function() {
                const args = arguments;
                this._shell.forEach(function(s) { s.reply.apply(null, args)});
            };
            _CallbackProxy.prototype._handle_payload_set_next_input = function() {
                return null
            };
            _CallbackProxy.prototype._handle_payload_page = function () {
                return this._shell[0].payload.page.apply(null, arguments);
            };
            _CallbackProxy.prototype._handle_output = function(msg) {
                const cell_id = msg.content.name;
                for(let index = 0; index < this.cells_ids.length; index++) {
                    if(this.cells_ids[index] === cell_id) {
                        return this._iopub[index].output.apply(null, arguments);
                    }
                }
            };
            _CallbackProxy.prototype._handle_clear_output = function() {
                return this._iopub[0].clear_output.apply(null, arguments);
            };
            _CallbackProxy.prototype.add_callbacks = function(callbacks) {
                this._shell.push(callbacks.shell);
                this._iopub.push(callbacks.iopub);
            };

            let Notebook = _notebook.Notebook;
            Notebook.prototype.execute_workflow = function() {
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
                const cells = [...Array(this.ncells()).keys()].map(function(index) {
                    return that.get_cell(index);
                });
                if (cells.length === 0) {
                    return;
                }

                let callbacks = new _CallbackProxy(cells);

                cells.forEach(function (cell){
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
                        cell_object.metadata['cell_id'] = cell.cell_id;
                    }
                    notebook.cells.push(cell_object);
                });

                var content = {
                    notebook : notebook
                };
                this.kernel.events.trigger('workflow_request.Kernel', {kernel: this, content: content});

                return this.kernel.send_shell_message("workflow_request", content, callbacks);
            };

            var action = {
                icon: 'fa-random',
                help: 'run the whole notebook asynchronously',
                handler: function(env) {
                    env.notebook.execute_workflow();
                }
            };

            var full_action_name = Jupyter.actions.register(action, 'show-alert', 'jupyter-workflow');
            Jupyter.toolbar.add_buttons_group([full_action_name]);

            console.info('JupyterFlow kernel.js loaded');
        }
    }
});
