"""Decode and project one MatrAIx persona row without mutating source data."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
from typing import Any, Iterator

from .industry_profile import load_profile

ROOT = Path(__file__).resolve().parents[2]
MATRIAx_ROOT = ROOT / "data" / "matraix" / "persona_1m"


class PersonaDecodeError(ValueError):
    """A MatrAIx row cannot be decoded into the canonical source schema."""


def load_source_schema(path: str | Path = MATRIAx_ROOT / "persona_codes.schema.json") -> dict[str, Any]:
    value = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("columns"), list):
        raise PersonaDecodeError("MatrAIx source schema must contain columns.")
    if value.get("packing") != "nibble" or value.get("code_base") != 0:
        raise PersonaDecodeError("Unsupported MatrAIx packing contract.")
    if value.get("row_bytes") != (len(value["columns"]) + 1) // 2:
        raise PersonaDecodeError("MatrAIx row_bytes does not match column count.")
    return value


def _as_bytes(value: Any, name: str) -> bytes | None:
    if value is None:
        return None
    if isinstance(value, bytes):
        return value
    if isinstance(value, bytearray):
        return bytes(value)
    if isinstance(value, list) and all(type(item) is int and 0 <= item <= 255 for item in value):
        return bytes(value)
    raise PersonaDecodeError(f"{name} must be bytes or a byte list.")


def _override_map(raw: Any) -> dict[int, str]:
    if raw in (None, []):
        return {}
    if not isinstance(raw, list):
        raise PersonaDecodeError("attribute_overrides must be a list.")
    result: dict[int, str] = {}
    for item in raw:
        if not isinstance(item, dict) or set(item) != {"field_index", "value"}:
            raise PersonaDecodeError("Invalid attribute override shape.")
        index, value = item["field_index"], item["value"]
        if type(index) is not int or index < 0 or not isinstance(value, str):
            raise PersonaDecodeError("Invalid attribute override value.")
        if index in result:
            raise PersonaDecodeError("Duplicate attribute override field.")
        result[index] = value
    return result


def decode_attributes(attributes: Any, null_bitmap: Any,
                      attribute_overrides: Any,
                      schema: dict[str, Any] | None = None,
                      field_ids: list[str] | None = None) -> dict[str, str]:
    """Decode all fields; missing attributes are omitted, never imputed."""
    schema = schema or load_source_schema()
    columns = schema["columns"]
    packed = _as_bytes(attributes, "attributes")
    bitmap = _as_bytes(null_bitmap, "null_bitmap")
    if packed is None or len(packed) != schema["row_bytes"]:
        raise PersonaDecodeError("attributes has an unexpected byte length.")
    if bitmap is not None and len(bitmap) != (len(columns) + 7) // 8:
        raise PersonaDecodeError("null_bitmap has an unexpected byte length.")
    overrides = _override_map(attribute_overrides)
    if any(index >= len(columns) for index in overrides):
        raise PersonaDecodeError("attribute override is outside the source schema.")

    selected = set(field_ids) if field_ids is not None else None
    if selected is not None:
        known = {column["id"] for column in columns}
        unknown = selected - known
        if unknown:
            raise PersonaDecodeError(
                "Unknown selected source fields: " + ", ".join(sorted(unknown))
            )
    result: dict[str, str] = {}
    for index, column in enumerate(columns):
        if selected is not None and column["id"] not in selected:
            continue
        if index in overrides:
            value = overrides[index]
        elif bitmap is not None and bitmap[index // 8] & (1 << (index % 8)):
            continue
        else:
            code = (packed[index // 2] >> (4 * (index % 2))) & 0x0F
            values = column["values"]
            if code >= len(values):
                raise PersonaDecodeError(
                    f"Invalid code {code} for source field {column['id']}."
                )
            value = values[code]
        if not isinstance(value, str):
            raise PersonaDecodeError(f"Decoded value for {column['id']} is not text.")
        result[column["id"]] = value
    return result


def project_persona_row(row: dict[str, Any], profile: dict[str, Any],
                        schema: dict[str, Any] | None = None) -> dict[str, Any]:
    """Create a reduced persona record with source and missing-field provenance."""
    schema = schema or load_source_schema()
    field_ids = list(dict.fromkeys(
        profile["core_persona_fields"]
        + profile["domain_persona_fields"]
        + profile["grouping_fields"]
    ))
    source_values = decode_attributes(
        row.get("attributes"), row.get("null_bitmap"),
        row.get("attribute_overrides"), schema, field_ids,
    )
    columns = {column["id"]: column for column in schema["columns"]}
    persona: dict[str, str] = {}
    excluded_fields: dict[str, str] = {}
    for field_id in field_ids:
        if field_id not in source_values:
            continue
        value = source_values[field_id]
        if value not in columns[field_id]["values"]:
            excluded_fields[field_id] = "override_outside_canonical_enum"
            continue
        persona[field_id] = value
    provenance_keys = ("source", "source_row_index", "source_record_id")
    provenance = {key: row[key] for key in provenance_keys if row.get(key) is not None}
    provenance["dataset"] = "MatrAIx Persona 1M"
    provenance["schema_version"] = schema["format_version"]
    if excluded_fields:
        provenance["excluded_fields"] = excluded_fields
    return {
        "source_persona_id": str(
            row.get("source_record_id")
            or f"{row.get('source', 'unknown')}:{row.get('source_row_index', 'unknown')}"
        ),
        "persona": persona,
        "missing_fields": [field_id for field_id in field_ids if field_id not in persona],
        "provenance": provenance,
    }


COMPLETION_POLICY_VERSION = "persona-completion-v1"

PRIORS: dict[str, list[tuple[str, int]]] = {
    "age_bracket": [("18-24", 15), ("25-34", 25), ("35-44", 25),
                    ("45-54", 18), ("55-64", 10), ("65-74", 7)],
    "region": [("North America", 15), ("Latin America", 10),
               ("Western Europe", 12), ("Eastern Europe", 8),
               ("Sub-Saharan Africa", 10), ("MENA", 8), ("South Asia", 12),
               ("East Asia", 10), ("Southeast Asia", 10), ("Oceania", 5)],
    "urbanicity": [("Dense urban", 45), ("Suburban", 35),
                   ("Small town", 15), ("Rural", 5)],
    "socioeconomic_band": [("Low income", 10), ("Lower-middle", 25),
                           ("Middle", 40), ("Upper-middle", 20), ("High income", 5)],
    "life_stage": [("Student", 15), ("Early career", 25),
                   ("Parent of young kids", 20), ("Mid-life", 20),
                   ("Career change", 5), ("Empty nester", 8), ("Retirement", 7)],
    "att_advertising": [("Enthusiast", 10), ("Positive", 25), ("Neutral", 40),
                        ("Skeptical", 20), ("Opposed", 5)],
    "cog_attention_span": [("Very long", 5), ("Long", 25), ("Average", 45),
                           ("Short", 20), ("Very short", 5)],
    "cog_detail_orientation": [("Very high", 5), ("High", 25), ("Moderate", 45),
                               ("Low", 20), ("None", 5)],
    "cog_skepticism": [("Very high", 5), ("High", 20), ("Moderate", 45),
                       ("Low", 25), ("None", 5)],
    "decision_style": [("Analytical", 25), ("Intuitive", 20),
                       ("Consensus-driven", 10), ("Directive", 10),
                       ("Deliberative", 35)],
    "economic_motivation": [("Cost-sensitive", 25), ("Value-driven", 45),
                            ("Premium-seeking", 15), ("Indifferent", 15)],
    "lstyle_shopping_style": [("Researcher", 30), ("Impulse buyer", 15),
                              ("Bargain hunter", 25), ("Brand loyal", 15),
                              ("Minimalist", 15)],
    "need_for_cognition": [("Very high", 5), ("High", 25), ("Average", 45),
                           ("Low", 20), ("Very low", 5)],
    "pref_novelty_vs_familiarity": [("Always novel", 5), ("Novelty-leaning", 25),
                                    ("Balanced", 45), ("Comfort-leaning", 20),
                                    ("Always familiar", 5)],
    "pref_quality_vs_quantity": [("Quality first", 10), ("Quality-leaning", 30),
                                 ("Balanced", 40), ("Quantity-leaning", 15),
                                 ("Quantity first", 5)],
    "schwartz_value_hedonism": [("Very high", 5), ("High", 25), ("Average", 45),
                                ("Low", 20), ("Very low", 5)],
    "trait_curiosity": [("Signature", 5), ("Strong", 20), ("Moderate", 45),
                        ("Slight", 25), ("Absent", 5)],
    "lstyle_caffeine": [("None", 15), ("Low", 25), ("Moderate", 45), ("High", 15)],
    "lstyle_coffee_ritual": [("Home brew", 25), ("Café regular", 20),
                             ("Office coffee", 20), ("Tea instead", 15),
                             ("None", 20)],
    "topic_baking": [("Passionate", 5), ("Interested", 20), ("Neutral", 50),
                     ("Indifferent", 20), ("Averse", 5)],
    "topic_coffee": [("Passionate", 5), ("Interested", 25), ("Neutral", 45),
                     ("Indifferent", 20), ("Averse", 5)],
    "topic_tea": [("Passionate", 5), ("Interested", 25), ("Neutral", 45),
                  ("Indifferent", 20), ("Averse", 5)],
}


def _stable_choice(options: list[tuple[str, int]], key: str) -> str:
    total = sum(weight for _, weight in options)
    number = int(hashlib.sha256(key.encode("utf-8")).hexdigest()[:16], 16) % total
    for value, weight in options:
        if number < weight:
            return value
        number -= weight
    return options[-1][0]


def _derive_value(field_id: str, persona: dict[str, str],
                  key: str) -> tuple[str, str, list[str]] | None:
    topic = persona.get("topic_coffee")
    caffeine = persona.get("lstyle_caffeine")
    ritual = persona.get("lstyle_coffee_ritual")
    age = persona.get("age_bracket")
    curiosity = persona.get("trait_curiosity")
    skepticism = persona.get("cog_skepticism")

    if field_id == "lstyle_caffeine" and topic:
        options = {
            "Passionate": [("Moderate", 65), ("High", 35)],
            "Interested": [("Moderate", 70), ("Low", 20), ("High", 10)],
            "Neutral": [("Low", 45), ("Moderate", 35), ("None", 20)],
            "Indifferent": [("None", 60), ("Low", 40)],
            "Averse": [("None", 80), ("Low", 20)],
        }.get(topic)
        if options:
            return _stable_choice(options, key), "coffee_topic_rule", ["topic_coffee"]
    if field_id == "lstyle_coffee_ritual" and topic:
        options = {
            "Passionate": [("Home brew", 55), ("Café regular", 45)],
            "Interested": [("Home brew", 40), ("Café regular", 35),
                           ("Office coffee", 25)],
            "Neutral": [("Office coffee", 35), ("Home brew", 25), ("None", 40)],
            "Indifferent": [("Tea instead", 45), ("None", 55)],
            "Averse": [("Tea instead", 60), ("None", 40)],
        }.get(topic)
        if options:
            return _stable_choice(options, key), "coffee_topic_rule", ["topic_coffee"]
    if field_id == "topic_coffee" and caffeine:
        options = {
            "High": [("Passionate", 20), ("Interested", 65), ("Neutral", 15)],
            "Moderate": [("Interested", 60), ("Neutral", 35), ("Passionate", 5)],
            "Low": [("Neutral", 55), ("Interested", 25), ("Indifferent", 20)],
            "None": [("Indifferent", 55), ("Neutral", 35), ("Averse", 10)],
        }.get(caffeine)
        if options:
            return _stable_choice(options, key), "caffeine_rule", ["lstyle_caffeine"]
    if field_id == "topic_tea" and ritual == "Tea instead":
        return _stable_choice([("Passionate", 20), ("Interested", 60),
                               ("Neutral", 20)], key), "tea_ritual_rule", [
                                   "lstyle_coffee_ritual"
                               ]
    if field_id == "life_stage" and age:
        options = {
            "18-24": [("Student", 55), ("Early career", 45)],
            "25-34": [("Early career", 60), ("Parent of young kids", 40)],
            "35-44": [("Parent of young kids", 55), ("Mid-life", 45)],
            "45-54": [("Mid-life", 75), ("Career change", 25)],
            "55-64": [("Mid-life", 55), ("Empty nester", 45)],
            "65-74": [("Empty nester", 45), ("Retirement", 55)],
            "75-84": [("Retirement", 80), ("Empty nester", 20)],
            "85+": [("Retirement", 100)],
        }.get(age)
        if options:
            return _stable_choice(options, key), "age_life_stage_rule", ["age_bracket"]
    if field_id == "pref_novelty_vs_familiarity" and curiosity:
        options = {
            "Signature": [("Always novel", 45), ("Novelty-leaning", 55)],
            "Strong": [("Novelty-leaning", 75), ("Balanced", 25)],
            "Moderate": [("Novelty-leaning", 25), ("Balanced", 60),
                         ("Comfort-leaning", 15)],
            "Slight": [("Balanced", 45), ("Comfort-leaning", 45),
                       ("Always familiar", 10)],
            "Absent": [("Comfort-leaning", 55), ("Always familiar", 45)],
        }.get(curiosity)
        if options:
            return _stable_choice(options, key), "curiosity_novelty_rule", [
                "trait_curiosity"
            ]
    if field_id == "att_advertising" and skepticism:
        options = {
            "Very high": [("Skeptical", 70), ("Opposed", 15), ("Neutral", 15)],
            "High": [("Skeptical", 55), ("Neutral", 35), ("Opposed", 10)],
            "Moderate": [("Neutral", 60), ("Skeptical", 30), ("Positive", 10)],
            "Low": [("Positive", 45), ("Neutral", 45), ("Enthusiast", 10)],
            "None": [("Positive", 55), ("Enthusiast", 25), ("Neutral", 20)],
        }.get(skepticism)
        if options:
            return _stable_choice(options, key), "skepticism_advertising_rule", [
                "cog_skepticism"
            ]
    return None


def complete_persona_record(record: dict[str, Any], profile: dict[str, Any],
                            schema: dict[str, Any] | None = None,
                            *, seed: int = 0) -> dict[str, Any]:
    """Complete profile fields with auditable deterministic values."""
    schema = schema or load_source_schema()
    result = json.loads(json.dumps(record, ensure_ascii=False))
    field_ids = list(dict.fromkeys(
        profile["core_persona_fields"]
        + profile["domain_persona_fields"]
        + profile["grouping_fields"]
    ))
    columns = {column["id"]: column for column in schema["columns"]}
    persona = result["persona"]
    provenance = result.setdefault("provenance", {})
    field_provenance = {
        field_id: {"status": "observed"}
        for field_id in persona
    }
    unresolved = [field_id for field_id in field_ids if field_id not in persona]
    while unresolved:
        derived_any = False
        remaining = []
        for field_id in unresolved:
            key = f"{seed}|{COMPLETION_POLICY_VERSION}|{result['source_persona_id']}|{field_id}"
            derived = _derive_value(field_id, persona, key)
            if derived is None:
                remaining.append(field_id)
                continue
            value, rule_id, source_fields = derived
            persona[field_id] = value
            field_provenance[field_id] = {
                "status": "derived",
                "rule_id": rule_id,
                "source_fields": source_fields,
                "policy_id": COMPLETION_POLICY_VERSION,
            }
            derived_any = True
        if derived_any:
            unresolved = remaining
            continue
        field_id = unresolved.pop(0)
        key = f"{seed}|{COMPLETION_POLICY_VERSION}|{result['source_persona_id']}|{field_id}"
        persona[field_id] = _stable_choice(PRIORS[field_id], key)
        field_provenance[field_id] = {
            "status": "imputed_prior",
            "policy_id": COMPLETION_POLICY_VERSION,
        }
    for field_id, value in persona.items():
        if value not in columns[field_id]["values"]:
            raise PersonaDecodeError(
                f"Completion produced a value outside the enum: {field_id}={value}"
            )
    result["missing_fields"] = []
    provenance["completion_policy_version"] = COMPLETION_POLICY_VERSION
    provenance["completion_seed"] = seed
    result["field_provenance"] = field_provenance
    return result


def iter_parquet_rows(path: str | Path, *, batch_size: int = 4096) -> Iterator[dict[str, Any]]:
    """Yield raw rows from one MatrAIx Parquet shard.

    pyarrow is intentionally optional for the rest of the runtime. It is needed
    only by this ingestion boundary.
    """
    try:
        import pyarrow.parquet as pq
    except ImportError as error:
        raise PersonaDecodeError(
            "Reading MatrAIx Parquet requires pyarrow. Install it in the data "
            "ingestion environment; the simulation runtime does not require it."
        ) from error
    parquet = pq.ParquetFile(path)
    required = {
        "source", "source_row_index", "source_record_id",
        "attributes", "null_bitmap", "attribute_overrides",
    }
    missing = required - set(parquet.schema_arrow.names)
    if missing:
        raise PersonaDecodeError("MatrAIx shard is missing columns: " + ", ".join(sorted(missing)))
    for batch in parquet.iter_batches(batch_size=batch_size, columns=sorted(required)):
        payload = batch.to_pydict()
        for index in range(batch.num_rows):
            yield {name: payload[name][index] for name in required}


def iter_projected_shard(path: str | Path, profile: dict[str, Any],
                         *, schema: dict[str, Any] | None = None,
                         batch_size: int = 4096) -> Iterator[dict[str, Any]]:
    schema = schema or load_source_schema()
    for row in iter_parquet_rows(path, batch_size=batch_size):
        yield project_persona_row(row, profile, schema)


def load_cafe_profile() -> dict[str, Any]:
    return load_profile("cafe", "cafe-mvp-v1")
