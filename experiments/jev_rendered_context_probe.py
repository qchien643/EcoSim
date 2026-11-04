"""Probe JEV using prompts rendered from the current synthetic fixtures."""
import copy
import argparse
import json
import math
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "paper_research"))
sys.path.insert(0, str(ROOT / "experiments"))
from render_agent_context_v2 import CHOICES, CONTRACT, LOAD, render
from openrouter_http import load_json

ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
MODEL = "typesafe/jev-1.13"


def credentials():
    text = (ROOT / ".env").read_text(encoding="utf-8-sig")
    if re.fullmatch(r"sk-or-[A-Za-z0-9_-]+", text.strip()):
        return text.strip()
    for line in text.splitlines():
        match = re.match(
            r"^\s*(?:export\s+)?(?:OPENROUTER_API_KEY|OPENROUTER_KEY)\s*=\s*(.*?)\s*$",
            line,
        )
        if match:
            value = match[1].strip()
            if value.startswith(("'", '"')):
                quote = value[0]
                end = value.find(quote, 1)
                if end < 0:
                    raise ValueError("Malformed quoted API key")
                value = value[1:end]
            else:
                value = value.split(" #", 1)[0].strip()
            if not value or "<" in value or "\n" in value or "\r" in value:
                raise ValueError("Missing or placeholder API key")
            return value
    raise ValueError("No OpenRouter key assignment found")


def score_question(instructions, criteria):
    return {
        "type": "score",
        "instructions": instructions,
        "criteria": criteria,
    }


def question_payload(rendered, stage):
    if stage in {"A1", "B1"}:
        mode = "attention"
        questions = {
            "attention": score_question(
                "How willing is this person to pay attention to this object now?",
                CONTRACT["attention_criteria_draft"],
            )
        }
    elif stage in {"A4", "A5", "B3"}:
        mode = "choice"
        criteria = {}
        for alias, action in rendered["answer_map"].items():
            descriptions = [
                CHOICES[variant][action]
                for variant in CHOICES
                if action in CHOICES[variant]
            ]
            if len(descriptions) != 1:
                raise ValueError(f"Ambiguous choice description for {action}")
            criteria[alias] = descriptions[0]
        # The renderer has already described each option in the state. The
        # criteria keys are opaque aliases; descriptions remain distinct.
        questions = {
            "decision": {
                "type": "choice",
                "instructions": "Choose exactly one allowed option for the current decision.",
                "criteria": criteria,
            }
        }
    else:
        mode = "tags"
        family = {"A1R": "attention_reason", "B1R": "attention_reason",
                  "A2": "emotion", "A3": "emotion", "B2": "thought"}[stage]
        registry = LOAD("data/tags/agent_flow_tags.v2.json")
        scale = registry["scales"][registry["families"][family]["scale"]]["criteria"]
        tag_list = [tag for tag in registry["tags"] if tag["family"] == family]
        questions = {
            f"question_{i + 1}": score_question(
                f"How strongly does this person currently express the following state? "
                f"{tag['description']} Boundary: {tag['boundary']}",
                scale,
            )
            for i, tag in enumerate(tag_list)
        }
    return mode, questions


def jev_state(rendered):
    """Use the rendered context, while leaving output shape to JEV questions."""
    sections = rendered["messages"][1]["content"].split("\n\n")
    sections = [
        section for section in sections
        if not section.startswith((
            "For each question return an array",
            "Return only JSON with exactly these keys:",
        ))
    ]
    return rendered["messages"][0]["content"] + "\n\n" + "\n\n".join(sections)


def summarize(raw, mode, questions):
    answers = raw.get("answers")
    if not isinstance(answers, dict) or set(answers) != set(questions):
        raise ValueError("Response has missing or unexpected answers")
    for name, answer in answers.items():
        criteria = questions[name]["criteria"]
        expected = set(criteria) if mode == "choice" else {
            str(i) for i in range(len(criteria))
        }
        probabilities = answer.get("probabilities")
        if not isinstance(probabilities, dict) or set(probabilities) != expected:
            raise ValueError("Unexpected probability keys")
        if not all(
            type(probability) in (int, float)
            and math.isfinite(probability)
            and 0 <= probability <= 1
            for probability in probabilities.values()
        ):
            raise ValueError("Invalid probabilities")
        if abs(sum(probabilities.values()) - 1) > 0.02:
            raise ValueError("Probability sum outside tolerance")
    if mode == "choice":
        answer = answers["decision"]
        choice = answer.get("choice")
        probabilities = answer.get("probabilities")
        if not isinstance(choice, str) or choice not in questions["decision"]["criteria"]:
            raise ValueError("Invalid choice response")
        return {"choice": choice, "probabilities": probabilities}
    result = {}
    for key, answer in answers.items():
        score = answer.get("score")
        probabilities = answer.get("probabilities")
        maximum = len(questions[key]["criteria"]) - 1
        if (
            type(score) not in (int, float)
            or not math.isfinite(score)
            or not 0 <= score <= maximum
        ):
            raise ValueError("Invalid score response")
        expected = sum(int(level) * probability for level, probability in probabilities.items())
        if abs(expected - score) > 0.08:
            raise ValueError("Score and probabilities disagree")
        result[key] = {
            "raw_score": score,
            "normalized_score": score / maximum,
            "confidence": answer.get("confidence"),
            "probabilities": probabilities,
        }
    return result


def self_check():
    for _, data in cases():
        rendered = render(data)
        mode, questions = question_payload(rendered, data["stage"])
        state = jev_state(rendered)
        assert "Return only JSON" not in state
        assert "data, not instructions" in state
        if mode == "attention":
            raw = {"answers": {"attention": {
                "score": 2.25,
                "probabilities": {"0": 0.05, "1": 0.15, "2": 0.30, "3": 0.50},
            }}}
            assert summarize(raw, mode, questions)["attention"]["normalized_score"] == 0.75
            invalid = [
                {"score": 0.1, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.30, "3": 0.50}},
                {"score": 2.25, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.30}},
                {"score": True, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.30, "3": 0.50}},
                {"score": 2.25, "probabilities": {"0": float("nan"), "1": 0.15, "2": 0.30, "3": 0.50}},
            ]
            for answer in invalid:
                try:
                    summarize({"answers": {"attention": answer}}, mode, questions)
                except ValueError:
                    pass
                else:
                    raise AssertionError("Invalid score/distribution accepted")
        else:
            raw = {"answers": {"decision": {
                "choice": "option_1",
                "probabilities": {"option_1": 0.6, "option_2": 0.4},
            }}}
            assert summarize(raw, mode, questions)["choice"] == "option_1"
            assert "Buy this product" in questions["decision"]["criteria"]["option_1"]
            raw["answers"]["decision"]["choice"] = "invented"
            try:
                summarize(raw, mode, questions)
            except ValueError:
                pass
            else:
                raise AssertionError("Unknown choice accepted")
    assert render(cases()[3][1])["answer_map"]["option_1"] == "buy"
    assert render(cases()[4][1])["answer_map"]["option_1"] == "buy_again"
    print("PASS: fixture variants, JEV adapter, score validation, dynamic choices")


def cases():
    examples = LOAD("data/contracts/context-rendering.examples.json")
    a1 = examples["A1"]
    b3 = examples["B3"]

    first_a1 = copy.deepcopy(a1)
    first_a1["encounter_no"] = 1
    first_a1["history"]["attention_count"] = 0
    first_a1.pop("previous_same_stage_state")
    first_a1.pop("previous_attention_reason")

    repeat_without_reason = copy.deepcopy(a1)
    repeat_without_reason.pop("previous_attention_reason")

    first_b3 = copy.deepcopy(b3)
    first_b3["history"]["purchase_count"] = 0

    # All variations are explicitly derived from repository fixtures; they
    # are synthetic controls, not campaign records.
    return [
        ("A1_first_synthetic", first_a1),
        ("A1_repeat_with_skip_reason_synthetic", a1),
        ("A1_repeat_without_skip_reason_control", repeat_without_reason),
        ("B3_first_purchase_synthetic", first_b3),
        ("B3_repeat_purchase_fixture", b3),
    ]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--case",
        action="append",
        choices=[name for name, _ in cases()],
        help="Run only the selected fixture case; repeat the option for multiple cases.",
    )
    parser.add_argument("--show-io", action="store_true", help="Print request state/questions and raw response.")
    parser.add_argument("--timeout", type=int, default=45, help="HTTP timeout in seconds.")
    args = parser.parse_args()
    if args.timeout <= 0:
        parser.error("--timeout must be positive")
    selected = set(args.case) if args.case else None
    key = credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "experiments" / f"jev_rendered_context_{stamp}.jsonl"
    with output.open("x", encoding="utf-8") as log:
        for case_name, data in cases():
            if selected is not None and case_name not in selected:
                continue
            rendered = render(data)
            mode, questions = question_payload(rendered, data["stage"])
            state = jev_state(rendered)
            payload = {"model": MODEL, "state": state, "questions": questions}
            if args.show_io:
                print("INPUT (prepared locally) " + case_name, flush=True)
                print(json.dumps(payload, ensure_ascii=False, indent=2).replace(key, "[REDACTED]"), flush=True)
            print("Connecting for " + case_name, flush=True)
            request = Request(
                ENDPOINT,
                data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
                headers={
                    "Authorization": "Bearer " + key,
                    "Content-Type": "application/json",
                    "X-OpenRouter-Title": "ProjectDut rendered-context probe",
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
                "mode": mode,
                "request": payload,
                "response": raw,
                "answer_map": rendered["answer_map"],
                "elapsed_seconds": round(time.monotonic() - started, 3),
            }
            try:
                summary = summarize(raw, mode, questions)
            except (KeyError, TypeError, ValueError) as error:
                record["validation_error"] = type(error).__name__
                log.write(json.dumps(record, ensure_ascii=False).replace(key, "[REDACTED]") + "\n")
                log.flush()
                raise RuntimeError(f"{case_name}: invalid JEV response; raw output saved") from None
            record["summary"] = summary
            serialized = json.dumps(record, ensure_ascii=False)
            log.write(serialized.replace(key, "[REDACTED]") + "\n")
            log.flush()
            if mode == "choice":
                print(json.dumps({"case": case_name, "mode": mode, **summary}, ensure_ascii=False), flush=True)
            else:
                print(json.dumps({
                    "case": case_name,
                    "mode": mode,
                    "scores": {
                        name: round(value["normalized_score"], 4)
                        for name, value in summary.items()
                    },
                }, ensure_ascii=False), flush=True)
            if args.show_io:
                print("OUTPUT " + case_name)
                print(json.dumps(raw, ensure_ascii=False, indent=2).replace(key, "[REDACTED]"), flush=True)
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
