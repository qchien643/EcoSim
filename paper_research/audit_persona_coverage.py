"""Read-only coverage audit of the local release; requires pyarrow.

Run: python3 paper_research/audit_persona_coverage.py
Check decoding: python3 paper_research/audit_persona_coverage.py --self-check
Output: docs/persona-coverage.json (aggregate counts only).
"""

import argparse
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data/matraix/persona_1m"
PANEL = [
    "topic_coffee", "lstyle_coffee_ritual", "lstyle_caffeine",
    "topic_tea", "topic_cooking", "topic_baking", "skill_cooking", "skill_baking",
    "lstyle_cooking_freq", "cuis_vietnamese", "ind_food_beverage", "ind_restaurants",
    "lstyle_shopping_style", "lstyle_frugality", "att_brand_loyalty",
    "att_advertising", "att_consumerism", "lstyle_diet_type",
    "lstyle_morning_routine", "lstyle_work_schedule",
    "lstyle_primary_social", "lstyle_screen_time",
    "topic_fashion", "lstyle_fashion_sense",
    "topic_fitness", "lstyle_exercise_freq",
    "topic_gaming", "lstyle_gaming_freq", "topic_photography",
]
GROUPS = {
    "coffee_pair": ["topic_coffee", "lstyle_coffee_ritual"],
    "coffee_core": ["topic_coffee", "lstyle_coffee_ritual", "lstyle_caffeine"],
    "coffee_commercial": [
        "topic_coffee", "lstyle_coffee_ritual", "lstyle_caffeine",
        "lstyle_shopping_style", "lstyle_frugality", "att_advertising",
    ],
    "cooking_core": ["topic_cooking", "skill_cooking", "lstyle_cooking_freq"],
    "fashion_core": ["topic_fashion", "lstyle_fashion_sense"],
    "fitness_core": ["topic_fitness", "lstyle_exercise_freq"],
    "gaming_core": ["topic_gaming", "lstyle_gaming_freq"],
    "fitness_commercial": [
        "topic_fitness", "lstyle_exercise_freq",
        "lstyle_shopping_style", "lstyle_frugality", "att_advertising",
    ],
}

def contract_valid(value, values):
    return value is not None and value in values


def decode(attributes, bitmap, overrides, index, values):
    # Exact overrides take precedence, including values outside the codebook.
    if index in overrides:
        return overrides[index], False
    if bitmap is not None and bitmap[index // 8] & (1 << (index % 8)):
        return None, False
    code = (attributes[index // 2] >> (4 * (index % 2))) & 15
    return (values[code], False) if code < len(values) else (None, True)


def self_check():
    values = ["None", "Low", "High"]
    assert decode(b"\x21", None, {}, 0, values) == ("Low", False)
    assert decode(b"\x21", None, {}, 1, values) == ("High", False)
    assert decode(b"\x21", b"\x02", {}, 1, values) == (None, False)
    assert decode(b"\x00", b"\x00", {}, 0, values) == ("None", False)
    assert decode(b"\x0f", None, {}, 0, values) == (None, True)
    assert decode(b"\x0f", b"\x01", {0: "Exact"}, 0, values) == ("Exact", False)
    assert sum(v is not None for v in [None, "None", "Neutral"]) == 2
    assert contract_valid("None", values)
    assert not any(contract_valid(v, values) for v in (None, "null", "Unsupported", "Exact"))
    print("PASS: nibble order, missing bitmap, explicit None, invalid code, override")


def main():
    import pyarrow.parquet as pq

    schema_path = DATA / "persona_codes.schema.json"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    columns = schema["columns"]
    assert schema["packing"] == "nibble" and schema["code_base"] == 0
    lookup = {col["id"]: (i, col) for i, col in enumerate(columns)}
    selected = [(name, *lookup[name]) for name in PANEL]
    positions = {name: i for i, name in enumerate(PANEL)}
    groups = {name: [positions[f] for f in fields] for name, fields in GROUPS.items()}
    totals = Counter()
    known = defaultdict(Counter)
    usable = defaultdict(Counter)
    invalid = defaultdict(Counter)
    overrides_used = defaultdict(Counter)
    values = defaultdict(lambda: defaultdict(Counter))
    joint = defaultdict(lambda: defaultdict(Counter))
    joint_usable = defaultdict(lambda: defaultdict(Counter))
    scanned = []
    # ponytail: explicit research panel, not automatic industry selection;
    # extend PANEL/GROUPS when reviewing another domain.
    for entry in manifest["files"]:
        path = DATA / entry["path"]
        if path.stat().st_size != entry["bytes"]:
            raise ValueError(f"Unexpected file size: {path}")
        parquet = pq.ParquetFile(path)
        if parquet.metadata.num_rows != entry["rows"]:
            raise ValueError(f"Unexpected row count: {path}")
        shard_rows = 0
        for batch in parquet.iter_batches(
            batch_size=4096,
            columns=["source", "attributes", "null_bitmap", "attribute_overrides"],
        ):
            payload = batch.to_pydict()
            for source, packed, bitmap, raw_overrides in zip(
                payload["source"], payload["attributes"],
                payload["null_bitmap"], payload["attribute_overrides"],
            ):
                if not source or len(packed) != schema["row_bytes"]:
                    raise ValueError("Missing source or malformed packed row")
                if bitmap is not None and len(bitmap) != (len(columns) + 7) // 8:
                    raise ValueError("Malformed null bitmap")
                overrides = {o["field_index"]: o["value"] for o in raw_overrides or []}
                if len(overrides) != len(raw_overrides or []):
                    raise ValueError("Duplicate override field")
                if any(not 0 <= i < len(columns) or not isinstance(v, str)
                       for i, v in overrides.items()):
                    raise ValueError("Malformed override")
                strata = ("all", "synthetic" if source == "synthetic" else "non_synthetic")
                buckets = (*strata, f"source:{source}")
                totals.update(buckets)
                present = []
                valid = []
                for name, index, col in selected:
                    value, bad = decode(packed, bitmap, overrides, index, col["values"])
                    present.append(value is not None)
                    valid.append(contract_valid(value, col["values"]))
                    for bucket in buckets:
                        usable[bucket][name] += valid[-1]
                        invalid[bucket][name] += bad
                        overrides_used[bucket][name] += index in overrides
                        if value is not None:
                            known[bucket][name] += 1
                            values[bucket][name][value] += 1
                for name, indices in groups.items():
                    count = sum(present[i] for i in indices)
                    valid_count = sum(valid[i] for i in indices)
                    for bucket in buckets:
                        joint[bucket][name][str(count)] += 1
                        joint_usable[bucket][name][str(valid_count)] += 1
                shard_rows += 1
        scanned.append({"path": entry["path"], "rows": shard_rows})
        print(f"{entry['path']}: {shard_rows:,} rows", flush=True)
    assert totals["all"] == manifest["rows"]
    assert totals["synthetic"] == manifest["synthetic_rows"]
    assert totals["non_synthetic"] == manifest["human_grounded_rows"]
    assert {k.removeprefix("source:"): v for k, v in totals.items()
            if k.startswith("source:")} == manifest["sources"]
    for bucket, count in totals.items():
        for name in PANEL:
            assert sum(values[bucket][name].values()) == known[bucket][name]
            assert known[bucket][name] + invalid[bucket][name] <= count
            assert usable[bucket][name] == sum(
                n for v, n in values[bucket][name].items() if v in lookup[name][1]["values"]
            )
        for name in GROUPS:
            assert sum(joint[bucket][name].values()) == count
            assert sum(joint_usable[bucket][name].values()) == count
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "method": "Full scan of manifest shards; null bitmap + packed codes + overrides; no imputation.",
        "schema_sha256": hashlib.sha256(schema_path.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256((DATA / "manifest.json").read_bytes()).hexdigest(),
        "shards": scanned,
        "totals": totals,
        "fields": {name: lookup[name][1] for name in PANEL},
        "groups": GROUPS,
        "known": known,
        "usable_enum": usable,
        "invalid_codes": invalid,
        "overrides_used": overrides_used,
        "value_counts": values,
        "joint_known_histograms": joint,
        "joint_usable_histograms": joint_usable,
    }
    output = ROOT / "docs/persona-coverage.json"
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    # Replace only the generated report, after the complete scan validates.
    temporary = output.with_suffix(".json.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(output)
    print(f"Saved {output}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        self_check()
    else:
        main()
