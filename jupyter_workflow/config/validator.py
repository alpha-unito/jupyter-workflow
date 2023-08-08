import os
from pathlib import Path
from typing import Any, MutableMapping

import streamflow.config
from jsonref import loads
from jsonschema.validators import validator_for
from streamflow.core import utils
from streamflow.deployment.connector import connector_classes


def load_jsonschema(metadata):
    base_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "schemas", metadata["version"]
    )
    filename = os.path.join(base_path, "config_schema.json")
    if not os.path.exists(filename):
        raise Exception(f'Version in "{filename}" is unsupported')
    with open(filename) as f:
        return loads(
            s=f.read(),
            base_uri="file://{}/schemas/{}/".format(
                Path(streamflow.config.__file__).parent, metadata["version"]
            ),
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
