"""Project MatrAIx rows into reduced JSONL personas.

Example:
    python3 -m paper_research.project_matraix_persona \
      --shard data/matraix/persona_1m/sample/sample.parquet \
      --output /tmp/projectdut-personas.jsonl --limit 100
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from simulation.personas.matraix import (
    PersonaDecodeError,
    complete_persona_record,
    iter_projected_shard,
    load_source_schema,
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shard", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--industry", default="cafe")
    parser.add_argument("--profile-version", default="cafe-mvp-v1")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument(
        "--complete", action="store_true",
        help="Fill missing fields with auditable deterministic values.",
    )
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args()
    if args.limit < 0:
        parser.error("--limit must be >= 0")
    if args.industry != "cafe" or args.profile_version != "cafe-mvp-v1":
        parser.error("The current installed MatrAIx projector supports cafe-mvp-v1 only.")

    from simulation.personas.industry_profile import load_profile
    profile = load_profile(args.industry, args.profile_version)
    count = 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    try:
        with args.output.open("w", encoding="utf-8") as output:
            for persona in iter_projected_shard(
                args.shard, profile, schema=load_source_schema()
            ):
                if args.complete:
                    persona = complete_persona_record(
                        persona, profile, load_source_schema(), seed=args.seed
                    )
                output.write(json.dumps(persona, ensure_ascii=False) + "\n")
                count += 1
                if args.limit and count >= args.limit:
                    break
    except PersonaDecodeError as error:
        raise SystemExit(f"ERROR: {error}") from error
    print(f"Wrote {count} reduced personas to {args.output}")


if __name__ == "__main__":
    main()
