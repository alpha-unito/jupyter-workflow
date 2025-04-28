from jupyter_workflow.handlers import setup_handlers


def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyter-workflow"}]


def _jupyter_server_extension_points():
    return [{"module": "jupyter_workflow"}]


def _load_jupyter_server_extension(server_app):
    setup_handlers(server_app.web_app)
    server_app.log.info(f"Registered Jupyter Workflow server extension")
