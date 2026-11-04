"""Offline import of a prepared cohort, industry bundle and MatrAIx metadata."""

import argparse
from collections import Counter
import hashlib
import json
import os
from pathlib import Path
import re
import sqlite3

from simulation.personas.bundle import load_bundle, validate_persona
from .contracts import issues_for
from .store import BackendConflictError, BackendStore, dumps, hash_json

ROOT = Path(__file__).resolve().parents[1]


def require(condition, message):
    if not condition:
        raise ValueError(message)


def read_json(path):
    value = json.loads(path.read_text(encoding="utf-8"))
    require(isinstance(value, dict), f"Expected a JSON object: {path.name}")
    dumps(value)  # Reject NaN/Infinity before hashing or writing.
    return value


def prepare(cohort_dir, source_dir, cohort_id=None):
    """Validate the existing reduced records; never synthesize missing values."""
    cohort_dir, source_dir = Path(cohort_dir), Path(source_dir)
    manifest = read_json(cohort_dir / "manifest.json")
    metadata = read_json(source_dir.parent / "source_metadata.json")
    source_manifest = read_json(source_dir / "manifest.json")
    schema = read_json(source_dir / "persona_codes.schema.json")
    require(manifest.get("format") == "projectdut_persona_cohort", "Unknown cohort format")
    require(manifest.get("files") == ["cohort.jsonl"], "Expected one prepared cohort.jsonl")
    require(type(manifest.get("size")) is int and manifest["size"] > 0, "Invalid cohort size")
    require(type(manifest.get("seed")) is int and manifest["seed"] >= 0, "Invalid selection seed")
    require(metadata.get("id") == "MatrAIx2026/MatrAIx_Persona_1M", "Unexpected source dataset")
    revision = metadata.get("sha")
    require(isinstance(revision, str) and re.fullmatch(r"[a-f0-9]{40}", revision),
            "Source metadata must identify a pinned release SHA")
    require(source_manifest.get("format") == "matraix_persona_1m_coreset",
            "Unexpected source manifest format")
    require(manifest.get("source_manifest", {}).get("rows") == source_manifest.get("rows"),
            "Cohort/source manifest row count mismatch")
    notice = manifest.get("research_license_notice")
    require(isinstance(notice, str) and notice.strip(), "Source usage notice is required")
    cohort_id = cohort_id or manifest.get("version")
    require(isinstance(cohort_id, str) and
            re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,127}", cohort_id), "Invalid cohort ID")
    industry, version = manifest["industry_id"], manifest["industry_profile_version"]
    bundle = load_bundle(industry, version)
    fields = set().union(*(bundle["profile"][key] for key in (
        "core_persona_fields", "domain_persona_fields", "grouping_fields")))
    source_columns = {column["id"]: column["values"] for column in schema["columns"]}
    require(fields <= source_columns.keys(), "Selected fields missing from source codebook")
    policy = manifest["selection_policy"]
    minimum_observed = policy.get("min_observed_domain_fields")
    require(type(minimum_observed) is int and minimum_observed >= 0, "Invalid eligibility policy")
    raw = (cohort_dir / "cohort.jsonl").read_bytes()
    members, ids, source_ids = [], set(), set()
    buckets, statuses = Counter(), Counter()
    for line_no, line in enumerate(raw.decode("utf-8").splitlines(), 1):
        if not line.strip():
            continue
        row = json.loads(line)
        require(isinstance(row, dict), f"Cohort row {line_no} must be an object")
        require(row.get("missing_fields") == [], f"Row {line_no} has missing fields")
        member = {key: row.get(key) for key in (
            "cohort_persona_id", "source_persona_id", "persona", "provenance",
            "field_provenance", "cohort_bucket")}
        public_persona = {k: v for k, v in member.items() if k != "cohort_bucket"}
        require(not issues_for({"cohort_id": cohort_id, **public_persona}, "Persona"),
                f"Row {line_no} violates the persona/provenance contract")
        require(set(member["persona"]) == fields, f"Row {line_no} lacks required industry fields")
        require(set(member["field_provenance"]) == fields,
                f"Row {line_no} lacks field provenance")
        validate_persona(member["persona"], bundle)
        require(all(value in source_columns[key] for key, value in member["persona"].items()),
                f"Row {line_no} has an enum outside the MatrAIx codebook")
        persona_id, source_id = member["cohort_persona_id"], member["source_persona_id"]
        require(persona_id not in ids and source_id not in source_ids, "Duplicate persona identity")
        require(source_id.strip(), "Empty source persona identity")
        ids.add(persona_id)
        source_ids.add(source_id)
        provenance = member["provenance"]
        source = provenance.get("source")
        require(source in source_manifest["sources"], f"Row {line_no} has an unknown source")
        require(provenance.get("schema_version") == schema["format_version"],
                f"Row {line_no} uses another source schema version")
        bucket = "synthetic" if source == "synthetic" else "human_grounded"
        require(member["cohort_bucket"] == bucket, f"Row {line_no} has an inconsistent source bucket")
        observed = sum(member["field_provenance"][key]["status"] == "observed"
                       for key in bundle["profile"]["domain_persona_fields"])
        require(observed >= minimum_observed, f"Row {line_no} fails domain eligibility")
        for origin in member["field_provenance"].values():
            if origin["status"] != "observed":
                require(bool(origin.get("policy_id")) and
                        origin["policy_id"] == provenance.get("completion_policy_version") and
                        provenance.get("completion_seed") == manifest["seed"],
                        f"Row {line_no} lacks consistent completion provenance")
            if origin["status"] == "derived":
                require(bool(origin.get("rule_id")) and bool(origin.get("source_fields")) and
                        set(origin["source_fields"]) <= fields,
                        f"Row {line_no} lacks a valid derivation rule")
            statuses[origin["status"]] += 1
        buckets[bucket] += 1
        members.append(member)
    require(len(members) == manifest["size"], "Cohort size differs from manifest")
    require(dict(buckets) == manifest.get("selected_counts") == policy.get("source_quota"),
            "Source counts differ from manifest/quotas")
    require(dict(statuses) == manifest.get("field_status_counts"), "Field provenance counts differ")
    members.sort(key=lambda row: row["cohort_persona_id"])
    return {
        "dataset": {
            "dataset_id": f"matraix_persona_1m_{revision}",
            "source_name": metadata["id"], "revision": revision,
            "source_uri": f"hf://datasets/{metadata['id']}@{revision}",
            "schema_hash": hash_json(schema),
            "manifest": {"source": source_manifest, "source_metadata": metadata,
                         "manifest_hash": hash_json(source_manifest)},
            "usage_notice": notice,
        },
        "industry": {"industry_id": industry, "profile_version": version, "bundle": bundle},
        "cohort": {
            "cohort_id": cohort_id,
            "dataset_id": f"matraix_persona_1m_{revision}",
            "industry_id": industry, "profile_version": version, "members": members,
            "selection_policy": {
                **policy, "seed": manifest["seed"], "version": manifest["version"],
                "manifest": manifest, "manifest_hash": hash_json(manifest),
                "source_file_sha256": hashlib.sha256(raw).hexdigest(),
            },
        },
    }


def install(store, prepared):
    """One transaction: all records become visible together, or none do."""
    dataset, industry, cohort = (prepared[key] for key in ("dataset", "industry", "cohort"))
    expected_dataset = {k: v for k, v in dataset.items() if k != "manifest"}
    expected_dataset.update(manifest_json=dumps(dataset["manifest"]), status="ready")
    expected_industry = {
        "industry_id": industry["industry_id"], "profile_version": industry["profile_version"],
        "bundle_hash": hash_json(industry["bundle"]),
        "profile_json": dumps(industry["bundle"]), "status": "ready",
    }
    expected_cohort = {
        k: cohort[k] for k in ("cohort_id", "dataset_id", "industry_id", "profile_version")}
    expected_cohort.update(
        size=len(cohort["members"]), content_hash=hash_json(cohort["members"]),
        selection_policy_json=dumps(cohort["selection_policy"]), status="ready")
    actions = {}
    with store.transaction():
        for name, table, where, values, expected, register, payload in (
            ("dataset", "persona_datasets", "dataset_id=?", (dataset["dataset_id"],),
             expected_dataset, store.register_dataset, dataset),
            ("industry", "industry_profiles", "industry_id=? AND profile_version=?",
             (industry["industry_id"], industry["profile_version"]),
             expected_industry, store.register_industry, industry),
            ("cohort", "persona_cohorts", "cohort_id=?", (cohort["cohort_id"],),
             expected_cohort, store.register_cohort, cohort),
        ):
            row = store.connection.execute(f"SELECT * FROM {table} WHERE {where}", values).fetchone()
            if row is None:
                register(**payload)
                actions[name] = "inserted"
            else:
                if any(row[key] != value for key, value in expected.items()):
                    raise BackendConflictError(f"{name} differs or is disabled; use a new version/ID")
                actions[name] = "unchanged"
        # Do not trust only the cached content_hash: detect missing/changed DB rows.
        actual = [{
            "cohort_persona_id": r["cohort_persona_id"], "source_persona_id": r["source_persona_id"],
            "persona": json.loads(r["persona_json"]), "provenance": json.loads(r["provenance_json"]),
            "field_provenance": json.loads(r["field_provenance_json"]), "cohort_bucket": r["cohort_bucket"],
        } for r in store.connection.execute(
            "SELECT * FROM cohort_members WHERE cohort_id=? ORDER BY cohort_persona_id",
            (cohort["cohort_id"],))]
        if actual != cohort["members"]:
            raise BackendConflictError("Stored cohort members differ; import did not overwrite them")
    return {
        **actions, "dataset_id": dataset["dataset_id"], "industry_id": industry["industry_id"],
        "profile_version": industry["profile_version"], "cohort_id": cohort["cohort_id"],
        "cohort_size": len(cohort["members"]),
        "content_hash": expected_cohort["content_hash"], "usage_notice": dataset["usage_notice"],
    }


def bootstrap(database, *, cohort_dir=ROOT / "data/personas/cafe_mvp",
              source_dir=ROOT / "data/matraix/persona_1m", cohort_id=None):
    prepared = prepare(cohort_dir, source_dir, cohort_id)
    # Validation precedes creation of the database; failed imports leave no ready subset.
    store = BackendStore(database)
    try:
        return install(store, prepared)
    finally:
        store.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database", type=Path, default=Path(
        os.environ.get("ECOSIM_DATABASE", "data/ecosim-backend.sqlite")))
    parser.add_argument("--cohort-dir", type=Path, default=ROOT / "data/personas/cafe_mvp")
    parser.add_argument("--source-dir", type=Path, default=ROOT / "data/matraix/persona_1m")
    parser.add_argument("--cohort-id", help="New immutable cohort ID; defaults to manifest version")
    args = parser.parse_args()
    try:
        result = bootstrap(args.database, cohort_dir=args.cohort_dir,
                           source_dir=args.source_dir, cohort_id=args.cohort_id)
    except (OSError, ValueError, KeyError, TypeError, sqlite3.Error) as error:
        parser.exit(1, f"Bootstrap failed: {type(error).__name__}: {error}\n")
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
