import tornado
from jupyter_server.base.handlers import APIHandler
from jupyter_server.utils import url_path_join

from jupyter_workflow.config.schema import JfSchema


class SchemaHandler(APIHandler):
    @tornado.web.authenticated
    def get(self, version: str = "v1.0"):
        self.finish(JfSchema().dump(version))


def setup_handlers(web_app):
    host_pattern = ".*$"
    base_url = url_path_join(web_app.settings["base_url"], "jupyter-workflow")
    web_app.add_handlers(
        host_pattern=host_pattern,
        host_handlers=[
            (url_path_join(base_url, "schema"), SchemaHandler),
        ],
    )
