"""Small offline check for the backend design contract."""

from pathlib import Path
import json
import re

import yaml
from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parent


def main() -> None:
    spec = yaml.safe_load((ROOT / "openapi.yaml").read_text(encoding="utf-8"))
    assert spec["openapi"] == "3.1.1"
    paths = spec["paths"]
    required_paths = {
        "/scenarios/{scenario_id}/validate",
        "/scenarios/{scenario_id}/freeze",
        "/scenarios/{scenario_id}/runs",
        "/runs/{run_id}/start",
        "/runs/{run_id}/resume",
        "/runs/{run_id}/stream",
        "/runs/{run_id}/updates",
        "/runs/{run_id}/metrics",
        "/runs/{run_id}/report",
    }
    assert required_paths <= set(paths)
    assert "StreamMessage" in spec["components"]["schemas"]
    assert "MetricPoint" in spec["components"]["schemas"]
    assert spec["components"]["parameters"]["IdempotencyKey"]["name"] == "Idempotency-Key"

    def walk(value):
        if isinstance(value, dict):
            yield value
            for child in value.values():
                yield from walk(child)
        elif isinstance(value, list):
            for child in value:
                yield from walk(child)

    for node in walk(spec):
        if "$ref" not in node:
            continue
        ref = node["$ref"]
        assert ref.startswith("#/"), f"Unverified external reference: {ref}"
        target = spec
        for part in ref[2:].split("/"):
            target = target[part.replace("~1", "/").replace("~0", "~")]

    for schema in spec["components"]["schemas"].values():
        Draft202012Validator.check_schema(schema)

    def validator(name):
        return Draft202012Validator({
            "$ref": f"#/components/schemas/{name}",
            "components": spec["components"],
        })

    operation_ids = []
    for path, item in paths.items():
        for method in ("get", "post", "put", "patch", "delete"):
            operation = item.get(method)
            if operation is None:
                continue
            operation_ids.append(operation["operationId"])
            parameters = item.get("parameters", []) + operation.get("parameters", [])
            parameters = [
                spec["components"]["parameters"][p["$ref"].rsplit("/", 1)[-1]]
                if "$ref" in p else p for p in parameters
            ]
            names = {p["name"] for p in parameters if p["in"] == "path" and p["required"]}
            assert names == set(re.findall(r"\{([^}]+)\}", path)), path
            assert operation.get("responses"), path
    assert len(operation_ids) == len(set(operation_ids))

    source = ROOT.parents[1] / "data/contracts/context-rendering.v2.json"
    actual_stages = set(json.loads(source.read_text())["stage_rendering"])
    assert set(spec["components"]["schemas"]["Stage"]["enum"]) == actual_stages
    for node in walk(spec):
        if "text/event-stream" not in node:
            continue
        wire = node["text/event-stream"].get("example", "")
        for line in wire.splitlines():
            if line.startswith("data: "):
                validator("StreamMessage").validate(json.loads(line[6:]))

    validator("ScenarioSetup").validate({"name": "Draft"})
    validator("Execution").validate({"mode": "parallel", "batch_size": 4})
    validator("Execution").validate({"mode": "sequential", "batch_size": 1})
    for name, invalid in [
        ("ScenarioSetup", {"name": "Draft", "api_key": "forbidden"}),
        ("Execution", {"mode": "sequential", "batch_size": 4}),
        ("Execution", {"mode": "parallel", "batch_size": 0}),
        ("ScoredTag", {"tag_id": "invalid", "score": 2, "selected": True,
                       "rank": 1, "description": "Out-of-range fixture"}),
    ]:
        assert list(validator(name).iter_errors(invalid)), (name, invalid)

    for document in ROOT.glob("*.md"):
        text = document.read_text(encoding="utf-8")
        for target in re.findall(r"\]\(([^)#]+)(?:#[^)]+)?\)", text):
            if target.startswith(("http://", "https://")):
                continue
            assert (document.parent / target).resolve().exists(), (
                f"Missing local link: {document}:{target}"
            )
    print(f"PASS: {len(paths)} paths, {len(operation_ids)} operations, local refs, "
          "schema syntax, SSE example, negative fixtures, stage parity and links")
    print("NOTE: not a full OpenAPI conformance or live backend integration test")


if __name__ == "__main__":
    main()
