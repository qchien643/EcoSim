"""Offline decoder check; does not require pyarrow."""

import json
from pathlib import Path

from simulation.personas.industry_profile import load_profile
from simulation.personas.matraix import (
    PersonaDecodeError,
    complete_persona_record,
    decode_attributes,
    project_persona_row,
)


def main():
    schema = {
        "format_version": 2,
        "code_base": 0,
        "packing": "nibble",
        "row_bytes": 2,
        "columns": [
            {"id": "first", "values": ["A", "B", "C"]},
            {"id": "second", "values": ["X", "Y", "Z"]},
            {"id": "third", "values": ["0", "1", "2"]},
        ],
    }
    assert decode_attributes(b"\x21\x02", None, [], schema) == {
        "first": "B", "second": "Z", "third": "2",
    }
    assert decode_attributes(
        b"\x21\x02", None, [], schema, ["second"]
    ) == {"second": "Z"}
    assert decode_attributes(b"\x21\x02", b"\x02", [], schema) == {
        "first": "B", "third": "2",
    }
    assert decode_attributes(b"\x21\x02", None, [
        {"field_index": 1, "value": "X"}
    ], schema)["second"] == "X"
    for row in (
        (b"\x21", None, []),
        (b"\xff\xff", None, []),
        (b"\x21\x02", b"\x00", [{"field_index": 1, "value": "X"},
                                  {"field_index": 1, "value": "Y"}]),
    ):
        try:
            decode_attributes(*row, schema)
        except PersonaDecodeError:
            pass
        else:
            raise AssertionError("Invalid packed row was accepted")

    profile = load_profile("cafe", "cafe-mvp-v1")
    source = load_profile("cafe", "cafe-mvp-v1")
    # Use the real source field list with a small synthetic packed row only to
    # test projection shape; no synthetic record is presented as MatrAIx data.
    root = Path(__file__).resolve().parents[1]
    full = json.loads(
        (root / "data/matraix/persona_1m/persona_codes.schema.json").read_text(
            encoding="utf-8"
        )
    )
    packed = bytes([0] * full["row_bytes"])
    projected = project_persona_row({
        "source": "decoder-test",
        "source_row_index": 1,
        "source_record_id": "decoder-test:1",
        "attributes": packed,
        "null_bitmap": bytes([0xFF] * ((len(full["columns"]) + 7) // 8)),
        "attribute_overrides": [],
    }, source, full)
    assert projected["persona"] == {}
    assert len(projected["missing_fields"]) == 22
    assert projected["provenance"]["schema_version"] == 2
    assert "excluded_fields" not in projected["provenance"]
    override = project_persona_row({
        "source": "decoder-test",
        "source_row_index": 2,
        "source_record_id": "decoder-test:2",
        "attributes": packed,
        "null_bitmap": bytes([0xFF] * ((len(full["columns"]) + 7) // 8)),
        "attribute_overrides": [{"field_index": 980, "value": "Outside codebook"}],
    }, source, full)
    assert override["persona"] == {}
    assert override["provenance"]["excluded_fields"]["trait_curiosity"] == (
        "override_outside_canonical_enum"
    )
    completed = complete_persona_record(projected, profile, full, seed=20260928)
    assert len(completed["persona"]) == 22
    assert completed["missing_fields"] == []
    assert set(completed["field_provenance"]) == set(completed["persona"])
    assert all(item["status"] in {"observed", "derived", "imputed_prior"}
               for item in completed["field_provenance"].values())
    assert complete_persona_record(projected, profile, full, seed=20260928) == completed
    print("PASS: nibble decoding, missing bitmap, override precedence and invalid-row checks")
    print("PASS: cafe reduced projection preserves missing fields and provenance")
    print("NOTE: Parquet ingestion was not run because pyarrow is not installed")


if __name__ == "__main__":
    main()
