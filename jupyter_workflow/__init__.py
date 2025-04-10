def _jupyter_labextension_paths():
    return [{"src": "labextension", "dest": "jupyter-workflow"}]


def _jupyter_server_extension_points():
    return [{"module": "jupyter-workflow"}]
