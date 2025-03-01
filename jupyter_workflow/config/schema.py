from __future__ import annotations

from importlib.resources import files

from streamflow.config import ext_schemas
from streamflow.core.config import Schema
from streamflow.deployment.connector import connector_classes


class JfSchema(Schema):
    def __init__(self):
        super().__init__(
            {
                "v1.0": "https://jupyter-workflow.di.unito.it/config/schemas/v1.0/config_schema.json"
            }
        )
        for version in self.configs.keys():
            self.add_schema(
                files(__package__)
                .joinpath("schemas")
                .joinpath(version)
                .joinpath("config_schema.json")
                .read_text("utf-8")
            )
        self.inject_ext(connector_classes, "deployment")
        for schema in ext_schemas:
            self.add_schema(schema.read_text("utf-8"))
        self._registry = self.registry.crawl()
