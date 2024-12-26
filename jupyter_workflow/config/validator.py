from typing import Any
from collections.abc import MutableMapping

from jsonschema.validators import validator_for
from streamflow.core.exception import WorkflowDefinitionException

from jupyter_workflow.config.schema import JfSchema


def handle_errors(errors):
    errors = list(sorted(errors, key=str))
    if not errors:
        return
    raise WorkflowDefinitionException(f"Invalid metadata:\n{errors[0]}")


def validate(workflow_config: MutableMapping[str, Any]) -> None:
    if "version" not in workflow_config:
        raise WorkflowDefinitionException(
            "Required field `version` not found in workflow configuration."
        )
    schema = JfSchema()
    config = schema.get_config(workflow_config["version"]).contents
    cls = validator_for(config)
    validator = cls(config, registry=schema.registry)
    handle_errors(validator.iter_errors(workflow_config))
