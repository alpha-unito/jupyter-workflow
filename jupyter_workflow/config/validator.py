import os
from pathlib import Path
from typing import MutableMapping, Any

import streamflow.config
from jsonref import loads, JsonLoader
from jsonschema import Draft7Validator
from typing_extensions import Text


def load_jsonschema(metadata):
    base_path = os.path.join(
        os.path.dirname(os.path.abspath(__file__)),
        'schemas', metadata['version'])
    filename = os.path.join(base_path, "config_schema.json")
    if not os.path.exists(filename):
        raise Exception(
            'Version in "{}" is unsupported'.format(filename))
    with open(filename, "r") as f:
        return loads(
            s=f.read(),
            base_uri='file://{}/schemas/{}/'.format(
                Path(streamflow.config.__file__).parent,
                metadata['version']),
            jsonschema=True)


def handle_errors(errors):
    errors = list(sorted(errors, key=str))
    if not errors:
        return
    raise Exception(
        "Invalid metadata:\n{error_msg}".format(error_msg=errors[0]))


def validate(workflow_config: MutableMapping[Text, Any]) -> None:
    schema = load_jsonschema(workflow_config)
    validator = Draft7Validator(schema)
    handle_errors(validator.iter_errors(workflow_config))
