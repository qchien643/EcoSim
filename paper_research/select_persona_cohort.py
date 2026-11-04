"""Select a deterministic reduced persona cohort from MatrAIx shards.

Requires pyarrow in the ingestion environment:

    python3 -m paper_research.select_persona_cohort \
      --output-dir data/personas/cafe_mvp --size 100 --seed 20260928
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
from collections import Counter
from pathlib import Path
from typing import Any

from simulation.personas.industry_profile import load_profile
from simulation.personas.matraix import (
    PersonaDecodeError,
    complete_persona_record,
    iter_projected_shard,
    load_source_schema,
)

ROOT = Path(__file__).resolve().parents[1]
DATA_ROOT = ROOT / "data" / "matraix" / "persona_1m"


def _rank(seed: int, source_persona_id: str) -> int:
    digest = hashlib.sha256(
        f"cohort-v1|{seed}|{source_persona_id}".encode("utf-8")
    ).hexdigest()
    return int(digest, 16)


def _push(heap: list[tuple[int, str, dict[str, Any]]],
          item: tuple[int, str, dict[str, Any]], limit: int) -> None:
    heapq.heappush(heap, item)
    if len(heap) > limit:
        heapq.heappop(heap)


def _files(manifest: dict[str, Any], data_root: Path) -> list[Path]:
    result = []
    for entry in manifest["files"]:
        path = data_root / entry["path"]
        if not path.is_file():
            raise FileNotFoundError(path)
        result.append(path)
    return result


def select(*, data_root: Path, output_dir: Path, size: int, seed: int,
           human_count: int, min_observed_domain_fields: int) -> dict[str, Any]:
    if size < 1 or not 0 <= human_count <= size:
        raise ValueError("size must be positive and human_count must be within size.")
    if min_observed_domain_fields < 0:
        raise ValueError("min_observed_domain_fields must be non-negative.")
    manifest = json.loads((data_root / "manifest.json").read_text(encoding="utf-8"))
    profile = load_profile("cafe", "cafe-mvp-v1")
    schema = load_source_schema(data_root / "persona_codes.schema.json")
    synthetic_count = size - human_count
    limits = {"human_grounded": human_count, "synthetic": synthetic_count}
    heaps: dict[str, list[tuple[int, str, dict[str, Any]]]] = {
        bucket: [] for bucket in limits
    }
    candidates = Counter()
    domain_fields = set(profile["domain_persona_fields"])

    for shard in _files(manifest, data_root):
        for record in iter_projected_shard(shard, profile, schema=schema):
            observed = sum(
                field in record["persona"] for field in domain_fields
            )
            if observed < min_observed_domain_fields:
                continue
            source = record["provenance"].get("source")
            bucket = "synthetic" if source == "synthetic" else "human_grounded"
            candidates[bucket] += 1
            rank = _rank(seed, record["source_persona_id"])
            _push(heaps[bucket], (-rank, record["source_persona_id"], record),
                  limits[bucket])

    if any(len(heaps[bucket]) < limits[bucket] for bucket in limits):
        raise ValueError(
            "Not enough eligible personas by source bucket: "
            + repr({bucket: len(heaps[bucket]) for bucket in limits})
        )

    selected = []
    for bucket in ("human_grounded", "synthetic"):
        for negative_rank, source_persona_id, record in sorted(
            heaps[bucket], key=lambda item: (-item[0], item[1])
        ):
            completed = complete_persona_record(
                record, profile, schema, seed=seed
            )
            completed["cohort_bucket"] = bucket
            completed["cohort_rank"] = -negative_rank
            selected.append(completed)
    selected.sort(key=lambda item: item["source_persona_id"])
    for index, record in enumerate(selected, start=1):
        record["cohort_persona_id"] = f"cafe_mvp_{index:03d}"

    output_dir.mkdir(parents=True, exist_ok=True)
    cohort_path = output_dir / "cohort.jsonl"
    with cohort_path.open("w", encoding="utf-8") as output:
        for record in selected:
            output.write(json.dumps(record, ensure_ascii=False) + "\n")

    field_status = Counter(
        value["status"]
        for record in selected
        for value in record["field_provenance"].values()
    )
    output_manifest = {
        "format": "projectdut_persona_cohort",
        "version": "cafe-mvp-cohort-v1",
        "industry_id": "cafe",
        "industry_profile_version": "cafe-mvp-v1",
        "size": len(selected),
        "seed": seed,
        "selection_policy": {
            "source_quota": {
                "human_grounded": human_count,
                "synthetic": synthetic_count,
            },
            "min_observed_domain_fields": min_observed_domain_fields,
            "ranking": "sha256(cohort-v1|seed|source_persona_id), ascending",
        },
        "candidate_counts": dict(candidates),
        "selected_counts": dict(Counter(record["cohort_bucket"] for record in selected)),
        "field_status_counts": dict(field_status),
        "source_manifest": {
            "rows": manifest["rows"],
            "manifest_path": str(data_root / "manifest.json"),
        },
        "files": ["cohort.jsonl"],
        "research_license_notice": (
            "MatrAIx-derived records inherit the source release's research-only "
            "terms; this cohort is not cleared for commercial use."
        ),
    }
    (output_dir / "manifest.json").write_text(
        json.dumps(output_manifest, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return output_manifest


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--size", type=int, default=100)
    parser.add_argument("--human-count", type=int, default=60)
    parser.add_argument("--min-observed-domain-fields", type=int, default=1)
    parser.add_argument("--seed", type=int, default=20260928)
    args = parser.parse_args()
    try:
        result = select(
            data_root=args.data_root,
            output_dir=args.output_dir,
            size=args.size,
            seed=args.seed,
            human_count=args.human_count,
            min_observed_domain_fields=args.min_observed_domain_fields,
        )
    except (OSError, ValueError, PersonaDecodeError) as error:
        raise SystemExit(f"ERROR: {error}") from error
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
