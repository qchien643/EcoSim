"""Sequential JEV probe for A2/A3 emotion-tag scoring."""
import argparse
import copy
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "paper_research"))
sys.path.insert(0, str(ROOT / "experiments"))
from render_agent_context_v2 import LOAD, render
from jev_rendered_context_probe import credentials, jev_state, question_payload, summarize
from openrouter_http import load_json

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"
FLOORS = (0.20, 0.30, 0.40, 0.50, 0.60)
TOP_K = 3
# ponytail: A3 uses a validator placeholder; supply a real post before calibrating A3.
ARTICLE_CONTENT = "An example advertisement with explicit content."


def scoped_state(scope, stage, encounter_no, tags):
    return {
        **scope,
        "stage": stage,
        "encounter_no": encounter_no,
        "status": "resolved",
        "tags": [{"tag_id": tag_id, "score": score} for tag_id, score in tags],
    }


def a2_base(a1):
    data = copy.deepcopy(a1)
    data.update({"stage": "A2", "encounter_no": 1, "history": {}})
    data["persona"] = {
        field: data["persona"][field]
        for field in ("att_advertising", "trait_curiosity", "pref_novelty_vs_familiarity")
    }
    data.pop("previous_same_stage_state", None)
    data.pop("previous_attention_reason", None)
    return data


def a3_base(a1, encounter_no, current_tags):
    return {
        "stage": "A3",
        "scope": copy.deepcopy(a1["scope"]),
        "encounter_no": encounter_no,
        "visible_tags": copy.deepcopy(a1["visible_tags"]),
        "facts": {"article_content": ARTICLE_CONTENT},
        "history": {},
        "current_state": scoped_state(a1["scope"], "A2", encounter_no, current_tags),
    }


def cases():
    examples = LOAD("data/contracts/context-rendering.examples.json")
    a1 = examples["A1"]

    first = a2_base(a1)

    repeat_interest = a2_base(a1)
    repeat_interest["encounter_no"] = 2
    repeat_interest["previous_same_stage_state"] = scoped_state(
        a1["scope"], "A2", 1, [("emotion.interest", 0.75)]
    )

    repeat_boredom = a2_base(a1)
    repeat_boredom["encounter_no"] = 2
    repeat_boredom["previous_same_stage_state"] = scoped_state(
        a1["scope"], "A2", 1, [("emotion.boredom", 0.75)]
    )

    repeat_mixed = a2_base(a1)
    repeat_mixed["encounter_no"] = 2
    repeat_mixed["previous_same_stage_state"] = scoped_state(
        a1["scope"], "A2", 1,
        [("emotion.interest", 0.70), ("emotion.worry", 0.55)],
    )

    first_read = a3_base(a1, 1, [("emotion.interest", 0.75)])

    repeat_read = a3_base(a1, 2, [("emotion.interest", 0.75), ("emotion.worry", 0.45)])
    repeat_read["previous_same_stage_state"] = scoped_state(
        a1["scope"], "A3", 1, [("emotion.disappointment", 0.72)]
    )

    return [
        ("A2_first_synthetic", first),
        ("A2_repeat_previous_interest", repeat_interest),
        ("A2_repeat_previous_boredom", repeat_boredom),
        ("A2_repeat_previous_interest_and_worry", repeat_mixed),
        ("A3_first_synthetic", first_read),
        ("A3_repeat_previous_disappointment", repeat_read),
    ]


def selected(scores, floor):
    return [
        item for item in sorted(scores, key=lambda item: (-item["score"], item["tag_id"]))
        if item["score"] >= floor
    ][:TOP_K]


def summarize_emotions(raw, questions, rendered):
    summary = summarize(raw, "tags", questions)
    scores = []
    for alias, value in summary.items():
        scores.append({
            "tag_id": rendered["answer_map"][alias],
            "score": round(value["normalized_score"], 6),
            "raw_score": value["raw_score"],
            "confidence": value.get("confidence"),
            "probabilities": value["probabilities"],
        })
    scores.sort(key=lambda item: (-item["score"], item["tag_id"]))
    return {
        "scores": scores,
        "selection_by_floor": {
            str(floor): selected(scores, floor) for floor in FLOORS
        },
    }


def self_check():
    examples = LOAD("data/contracts/context-rendering.examples.json")
    for name, data in cases():
        rendered = render(data)
        assert data["stage"] in {"A2", "A3"}
        assert rendered["answer_map"]["question_1"] == "emotion.interest"
        mode, questions = question_payload(rendered, data["stage"])
        assert mode == "tags"
        assert set(questions) == set(rendered["answer_map"])
        raw = {"answers": {
            alias: {
                "score": 2.0,
                "probabilities": {"0": 0.0, "1": 0.0, "2": 1.0, "3": 0.0},
            }
            for alias in questions
        }}
        result = summarize_emotions(raw, questions, rendered)
        assert len(result["scores"]) == 8
        assert all(len(result["selection_by_floor"][str(floor)]) == 3 for floor in FLOORS)
    assert examples["A1"]["scope"]["object_type"] == "article"
    boundary_scores = [
        {"tag_id": "emotion.interest", "score": 0.30},
        {"tag_id": "emotion.worry", "score": 0.299999},
    ]
    assert selected(boundary_scores, 0.30) == boundary_scores[:1]
    assert selected(boundary_scores, 0.40) == []
    assert selected([], 0.30) == []
    print("PASS: 6 sequential emotion fixtures, 8 tags, normalization and floor selection")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append", choices=[name for name, _ in cases()])
    parser.add_argument("--show-io", action="store_true")
    parser.add_argument("--timeout", type=int, default=300)
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    selected_cases = set(args.case) if args.case else None
    key = credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "experiments" / f"jev_emotion_tag_{stamp}.jsonl"

    with output.open("x", encoding="utf-8") as log:
        for case_name, data in cases():
            if selected_cases is not None and case_name not in selected_cases:
                continue
            rendered = render(data)
            mode, questions = question_payload(rendered, data["stage"])
            payload = {"model": MODEL, "state": jev_state(rendered), "questions": questions}
            if args.show_io:
                print("INPUT (prepared locally) " + case_name, flush=True)
                print(json.dumps(payload, ensure_ascii=False, indent=2).replace(key, "[REDACTED]"),
                      flush=True)
            print("Connecting for " + case_name, flush=True)
            request = Request(
                ENDPOINT,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "X-OpenRouter-Title": "ProjectDut sequential emotion-tag probe",
                },
            )
            started = time.monotonic()
            try:
                raw = load_json(request, args.timeout)
            except HTTPError as exc:
                raise RuntimeError(f"{case_name}: HTTP {exc.code}") from None
            except (URLError, TimeoutError):
                raise RuntimeError(f"{case_name}: network failure") from None
            record = {
                "case": case_name,
                "source": "repository_fixture_or_controlled_variant",
                "stage": data["stage"],
                "input": payload,
                "response": raw,
                "fixture_snapshot": data,
                "answer_map": rendered["answer_map"],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            try:
                summary = summarize_emotions(raw, questions, rendered)
            except (KeyError, TypeError, ValueError, AttributeError) as error:
                record["validation_error"] = type(error).__name__
                log.write(json.dumps(record, ensure_ascii=False).replace(key, "[REDACTED]") + "\n")
                log.flush()
                raise RuntimeError(f"{case_name}: invalid response; raw output saved") from None
            record["summary"] = summary
            log.write(json.dumps(record, ensure_ascii=False).replace(key, "[REDACTED]") + "\n")
            log.flush()
            print(json.dumps({
                "case": case_name,
                "stage": data["stage"],
                "scores": {item["tag_id"]: item["score"] for item in summary["scores"]},
                "counts_at_floor": {
                    floor: len(tags) for floor, tags in summary["selection_by_floor"].items()
                },
            }, ensure_ascii=False), flush=True)
            if args.show_io:
                print("OUTPUT " + case_name, flush=True)
                print(json.dumps(raw, ensure_ascii=False, indent=2).replace(key, "[REDACTED]"),
                      flush=True)
    print("Saved:", output.relative_to(ROOT))


if __name__ == "__main__":
    try:
        if sys.argv[1:] == ["--self-check"]:
            self_check()
        else:
            main()
    except Exception as error:
        if isinstance(error, RuntimeError):
            print(str(error))
        else:
            print("Stopped:", type(error).__name__)
        raise SystemExit(1)
