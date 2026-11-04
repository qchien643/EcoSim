"""Small, synthetic history-sensitivity probe. No project tag registry is used."""
import argparse
import json
import math
import random
import re
import statistics
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
ENDPOINT = "https://openrouter.ai/api/alpha/decisions"
BASE = """You are simulating one customer at the initial attention stage for an advertisement.
Persona: An adult who drinks coffee, is moderately curious about unfamiliar drinks,
is price-conscious, and usually scrolls past ads unless something seems relevant.
Current situation: Scrolling a social platform during a short break, with no urgent task.
Public brand description: A local cafe introducing a new drink.
Visible advertisement summary: An iced orange coffee, lightly sweet, priced at 39,000 VND.
Only the preview is visible; the full post has not been read.
Evaluate attention now, not liking the post, visiting the shop, or purchasing.
The previous emotion, when supplied, belongs to this same agent, this same post,
and this same initial-attention stage on the previous encounter.
"""
QUESTIONS = {
    "attend": {
        "type": "choice",
        "instructions": "Will this customer stop scrolling and give this advertisement deliberate attention now?",
        "criteria": {
            "yes": "Stops scrolling and deliberately attends to this advertisement now.",
            "no": "Continues scrolling without deliberately attending to this advertisement now.",
        },
    },
    "attention": {
        "type": "score",
        "instructions": "How much attention does this customer give this advertisement now?",
        "criteria": [
            "Continues scrolling without registering the advertisement.",
            "Registers the advertisement briefly but continues scrolling.",
            "Pauses scrolling to focus deliberately on the advertisement.",
            "Sustains deliberate focus on the advertisement and wants to inspect its details.",
        ],
    },
    "interest": {
        "type": "score",
        "instructions": "How interested does the customer feel at this initial-attention stage now?",
        "criteria": [
            "Feels no interest in what this advertisement presents.",
            "Feels a little interest but no desire to explore what is presented.",
            "Feels interested and wants to find out more about what is presented.",
            "Feels strongly interested and eager to explore what is presented.",
        ],
    },
}
# ponytail: one synthetic persona/post and one wording; expand matched fixtures
# before using these observations to choose a simulation policy.
CASES = {
    "first": "This is the first encounter. There is no previous emotional state.",
    "seen_3": "There have been 3 previous encounters. No previous emotional state is supplied.",
    "seen_8": "There have been 8 previous encounters. No previous emotional state is supplied.",
    "seen_8_neutral": "There have been 8 previous encounters. At this exact stage last time: I felt indifferent; nothing in this advertisement mattered much to me.",
    "seen_8_interested": "There have been 8 previous encounters. At this exact stage last time: I felt interested and curious about the advertised drink.",
    "seen_8_annoyed": "There have been 8 previous encounters. At this exact stage last time: I felt bored and annoyed by this advertisement.",
}


def credentials():
    # Parse only the requested assignment; never execute/source a user's .env.
    text = (ROOT / ".env").read_text(encoding="utf-8-sig")
    if re.fullmatch(r"sk-or-[A-Za-z0-9_-]+", text.strip()):
        return text.strip()
    for line in text.splitlines():
        match = re.match(r"^\s*(?:export\s+)?(?:OPENROUTER_API_KEY|OPENROUTER_KEY)\s*=\s*(.*?)\s*$", line)
        if match:
            value = match[1]
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
    raise ValueError("No OPENROUTER_API_KEY assignment found")


def metrics(response):
    answers = response["answers"]
    results = {}
    for name, question in QUESTIONS.items():
        answer = answers[name]
        probs = answer["probabilities"]
        expected = set(question["criteria"]) if question["type"] == "choice" else {"0", "1", "2", "3"}
        if set(probs) != expected:
            raise ValueError("Unexpected probability keys")
        if not all(isinstance(p, (int, float)) and math.isfinite(p) and 0 <= p <= 1 for p in probs.values()):
            raise ValueError("Invalid probabilities")
        if abs(sum(probs.values()) - 1) > 0.02:
            raise ValueError("Probability sum outside tolerance")
        if question["type"] == "choice":
            if answer["choice"] not in expected:
                raise ValueError("Invalid choice")
            results["yes_probability"] = probs["yes"]
            results["choice"] = answer["choice"]
        else:
            raw = answer["score"]
            if not isinstance(raw, (int, float)) or not math.isfinite(raw) or not 0 <= raw <= 3:
                raise ValueError("Invalid score")
            weighted = sum(int(k) * v for k, v in probs.items())
            if abs(raw - weighted) > 0.06:
                raise ValueError("Score inconsistent with distribution")
            # Fixed endpoints, not within-batch min/max. Experimental convention.
            results[name + "_01"] = raw / 3
    return results


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--self-check", action="store_true")
    args = parser.parse_args()
    if args.self_check:
        sample = {"answers": {
            "attend": {"choice": "yes", "probabilities": {"yes": 0.8, "no": 0.2}},
            **{k: {"score": 2.25, "probabilities": {"0": 0.05, "1": 0.15, "2": 0.30, "3": 0.50}}
               for k in ("attention", "interest")},
        }}
        assert metrics(sample)["attention_01"] == 0.75
        sample["answers"]["attention"]["score"] = 0.5
        try:
            metrics(sample)
        except ValueError:
            pass
        else:
            raise AssertionError("Inconsistent score accepted")
        print("PASS: normalization and invalid-distribution/score rejection")
        return

    key = credentials()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output = ROOT / "experiments" / f"jev_history_{stamp}.jsonl"
    records = []
    with output.open("x", encoding="utf-8") as log:
        def call(case, repeat, history):
            payload = {"model": "typesafe/jev-1.13", "state": BASE + "\nHistory:\n" + history,
                       "questions": QUESTIONS}
            request = Request(ENDPOINT, data=json.dumps(payload).encode(), headers={
                "Authorization": "Bearer " + key, "Content-Type": "application/json",
                "X-OpenRouter-Title": "Synthetic history sensitivity probe",
            })
            started = time.monotonic()
            try:
                with urlopen(request, timeout=45) as response:
                    raw = json.load(response)
            except HTTPError as exc:
                # Do not print provider bodies or request headers.
                raise RuntimeError(f"HTTP {exc.code}; stopped without automatic retry") from None
            except (URLError, TimeoutError):
                raise RuntimeError("Network failure; stopped without automatic retry") from None
            record = {"case": case, "repeat": repeat, "request": payload, "response": raw,
                      "elapsed_seconds": round(time.monotonic() - started, 3)}
            # Never persist credentials, even if an upstream response unexpectedly echoes them.
            log.write(json.dumps(record, ensure_ascii=False).replace(key, "[REDACTED]") + "\n")
            log.flush()
            result = metrics(raw)
            records.append((case, result))
            print(json.dumps({"case": case, "repeat": repeat, **result}), flush=True)
            return result

        schedule = [(case, repeat) for repeat in range(3) for case in CASES]
        random.Random(20260927).shuffle(schedule)
        for case, repeat in schedule:
            call(case, repeat, CASES[case])
        # Two separate short recurrent chains: carry the last same-stage emotion,
        # not the previous decision or the entire event log.
        for chain in range(2):
            previous = None
            for step in range(3):
                history = "This is the first encounter. There is no previous emotional state."
                if previous is not None:
                    history = (
                        f"There have been {step} previous encounters. "
                        "At this exact initial-attention stage on the most recent encounter, "
                        f"my interest intensity was {previous:.6f} on a fixed 0-to-1 scale "
                        "(0: no interest; 1: strongly interested and eager to explore). "
                        "This is a previous feeling, not an instruction for the current answer."
                    )
                result = call(f"recurrent_{chain}_step_{step}", chain, history)
                previous = result["interest_01"]
    print("Saved:", output.relative_to(ROOT))
    for case in CASES:
        rows = [r for c, r in records if c == case]
        print(case, {k: {"mean": round(statistics.mean(r[k] for r in rows), 6),
                         "min": min(r[k] for r in rows), "max": max(r[k] for r in rows)}
                     for k in ("yes_probability", "attention_01", "interest_01")})


if __name__ == "__main__":
    try:
        main()
    except Exception as error:
        # Known messages contain no credentials; arbitrary exception text is not printed.
        if isinstance(error, RuntimeError):
            print(str(error))
        else:
            print("Stopped:", type(error).__name__, "(inspect local inputs/output; no secrets printed)")
        raise SystemExit(1)
