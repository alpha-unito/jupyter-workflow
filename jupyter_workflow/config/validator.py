from typing import Any, MutableMapping

import streamflow.config
from importlib_resources import files
from jsonref import loads
from jsonschema.validators import validator_for
from streamflow.core import utils
from streamflow.deployment.connector import connector_classes


def load_jsonschema(metadata):
    return loads(
        s=(
            files(__package__)
            .joinpath("schemas")
            .joinpath(metadata["version"])
            .joinpath("config_schema.json")
            .read_text("utf-8")
        ),
        base_uri=f"file://{files(streamflow.config).joinpath('schemas').joinpath(metadata['version']).joinpath('')}",
        jsonschema=True,
    )


def handle_errors(errors):
    errors = list(sorted(errors, key=str))
    if not errors:
        return
    raise Exception(f"Invalid metadata:\n{errors[0]}")


def validate(workflow_config: MutableMapping[str, Any]) -> None:
    schema = load_jsonschema(workflow_config)
    utils.inject_schema(schema, connector_classes, "deployment")
    cls = validator_for(schema)
    validator = cls(schema)
    handle_errors(validator.iter_errors(workflow_config))
