"""Validate the HTTP boundary against the checked-in OpenAPI contract."""

import json
from pathlib import Path

import yaml
from jsonschema import Draft202012Validator

SPEC = yaml.safe_load(
    (Path(__file__).resolve().parents[1] / "docs/backend/openapi.yaml")
    .read_text(encoding="utf-8")
)


def issues_for(value, schema):
    """Reject non-JSON values before semantic validators touch input."""
    try:
        json.dumps(value, allow_nan=False)
    except (ValueError, TypeError):
        return [{"path": "$", "code": "INVALID_JSON",
                 "message": "Only finite JSON values are accepted.",
                 "severity": "error"}]
    if isinstance(schema, str):
        schema = {"$ref": f"#/components/schemas/{schema}"}
    validator = Draft202012Validator({**schema, "components": SPEC["components"]})
    return [
        {
            "path": "$" + "".join(f"[{p}]" if isinstance(p, int) else f".{p}"
                                  for p in error.absolute_path),
            "code": f"SCHEMA_{error.validator.upper()}",
            # Do not echo supplied values: invalid inputs may contain secrets.
            "message": f"Value does not satisfy {error.validator}.",
            "severity": "error",
        }
        for error in validator.iter_errors(value)
    ]


def request_schema(path, method):
    body = SPEC["paths"][path][method]["requestBody"]
    if "$ref" in body:
        body = SPEC["components"]["requestBodies"][body["$ref"].rsplit("/", 1)[-1]]
    return body["content"]["application/json"]["schema"]
