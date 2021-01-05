define([
    'jquery',
    'base/js/i18n',
    'services/kernels/kernel',
    'notebook/js/codecell'
], function ($, i18n, _Kernel, _codecell) {
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
                    store_history: true,
                    stop_on_error: stop_on_error
                }

                if (this.metadata !== undefined && this.metadata.hasOwnProperty('workflow')) {
                    if (this.notebook.metadata !== undefined && this.notebook.metadata.hasOwnProperty('workflow')) {
                        kernel_options.workflow = {
                            ...this.metadata['workflow'],
                            ...this.notebook.metadata['workflow']};
                    } else {
                        kernel_options.workflow = this.metadata['workflow'];
                    }
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

            console.info('JupyterFlow kernel.js loaded');
        }
    }
});