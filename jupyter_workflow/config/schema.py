import json
import posixpath
from importlib_resources import files
from referencing import Registry, Resource
from streamflow.core.context import SchemaEntity
from streamflow.core.exception import WorkflowDefinitionException
from streamflow.deployment.connector import connector_classes
from typing import MutableMapping, Type

_CONFIGS = {
    "v1.0": "https://jupyter-workflow.di.unito.it/config/schemas/v1.0/config_schema.json"
}

ext_schemas = []


class JfSchema:
    def __init__(self):
        self.registry: Registry = Registry()
        for version in _CONFIGS.keys():
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

    def add_schema(self, schema: str) -> Resource:
        resource = Resource.from_contents(json.loads(schema))
        self.registry = resource @ self.registry
        return resource

    def get_config(self, version: str) -> Resource:
        if version not in _CONFIGS:
            raise WorkflowDefinitionException(
                f"Version {version} is unsupported. The `version` clause should be equal to `v1.0`."
            )
        return self.registry.get(_CONFIGS[version])

    def inject_ext(
        self,
        classes: MutableMapping[str, Type[SchemaEntity]],
        definition_name: str,
    ):
        for name, entity in classes.items():
            if entity_schema := entity.get_schema():
                entity_schema = self.add_schema(entity_schema).contents
                for config_id in _CONFIGS.values():
                    config = self.registry.contents(config_id)
                    definition = config["$defs"]
                    for el in definition_name.split(posixpath.sep):
                        definition = definition[el]
                    definition["properties"]["type"].setdefault("enum", []).append(name)
                    definition["$defs"][name] = entity_schema
                    definition.setdefault("allOf", []).append(
                        {
                            "if": {"properties": {"type": {"const": name}}},
                            "then": {"properties": {"config": entity_schema}},
                        }
                    )
