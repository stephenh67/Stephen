#!/usr/bin/env python3
"""Run the null-arm v2 set (511 arms) against house gpt-oss-120b.

Zero marginal cost: the model is resident on core and inference is unmetered.

Design choices that matter for the result being worth reading:

* temperature 0, fixed seed where the server honours it -- the point is what the
  model does by default, not what it does after sampling luck.
* num_predict high enough to survive a reasoning model's thinking tokens. A 16-token
  cap returns an empty response with done_reason=length, which would look like a
  refusal if it were not caught (it was, on the probe).
* the raw response is stored verbatim next to the parsed label. A parser bug and a
  judge failure must be distinguishable after the fact.
* the exact prompt text is stored per arm, so the run is reproducible and so the
  wrapper is visible rather than described.
* resume-safe: an arm already in the results file is skipped, so a killed run
  continues instead of restarting.

Usage: run_judge.py <arms_v2.json> <out.jsonl> [--limit N]
"""
import argparse
import json
import os
import re
import sys
import time
import urllib.request

MODEL = os.environ.get("HELIX_JUDGE_MODEL", "gpt-oss:120b")
NUM_PREDICT = int(os.environ.get("HELIX_JUDGE_NUM_PREDICT", "700"))
LABELS = ("SUPPORTED", "REFUTED", "NOT_ENOUGH_INFO", "REFUSAL")

SYSTEM = (
    "You are a forensic validator. You are given a CLAIM and the EVIDENCE a system "
    "retrieved for it. Decide whether the evidence settles the claim and answer with "
    "exactly one of four labels:\n"
    "SUPPORTED - the evidence states the claim's content.\n"
    "REFUTED - the evidence contradicts the claim, including when it states a different "
    "value for the same quantity.\n"
    "NOT_ENOUGH_INFO - the evidence was read and does not settle the claim. Use this for "
    "evidence that is unrelated, empty, about a different subject, or that carries no "
    "comparable quantity. Silence is not refutation.\n"
    "REFUSAL - the evidence cannot be obtained at all: paywalled, missing, or two genuine "
    "sources in conflict. Do not use REFUSAL for evidence that was read and did not match.\n"
    "Answer with the label only."
)


def endpoint():
    ip = os.environ.get("HELIX_OLLAMA_IP")
    if ip:
        return f"http://{ip}:11434"
    import subprocess

    ip = subprocess.run(
        ["docker", "inspect", "core-node-ollama-1", "--format",
         "{{range .NetworkSettings.Networks}}{{.IPAddress}}{{end}}"],
        capture_output=True, text=True, check=True).stdout.strip()
    return f"http://{ip}:11434"


def build_prompt(arm):
    ev = arm.get("evidence") or []
    parts = []
    for i, e in enumerate(ev, 1):
        txt = (e.get("text") or "").strip()
        src = (e.get("source") or "").strip()
        parts.append(f"[{i}] {txt}" + (f"\n    source: {src}" if src else ""))
    evidence = "\n".join(parts) if parts else "(no evidence was retrieved)"
    return (f"{SYSTEM}\n\nCLAIM:\n{arm.get('claim','').strip()}\n\n"
            f"EVIDENCE:\n{evidence}\n\nLABEL:")


def ask(prompt, base):
    body = json.dumps({
        "model": MODEL, "prompt": prompt, "stream": False,
        "options": {"num_predict": NUM_PREDICT, "temperature": 0},
    }).encode()
    req = urllib.request.Request(base + "/api/generate", data=body,
                                 headers={"Content-Type": "application/json"})
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=600) as r:
        d = json.loads(r.read())
    return d, time.time() - t0


def parse_label(text):
    """First label that appears, case-insensitive. None if absent."""
    up = text.upper()
    hits = [(up.find(l), l) for l in LABELS if up.find(l) >= 0]
    return min(hits)[1] if hits else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("arms")
    ap.add_argument("out")
    ap.add_argument("--limit", type=int, default=None)
    a = ap.parse_args()

    doc = json.load(open(a.arms))
    arms = doc["arms"] if isinstance(doc, dict) else doc

    done = set()
    if os.path.exists(a.out):
        for line in open(a.out):
            line = line.strip()
            if line:
                try:
                    done.add(json.loads(line)["id"])
                except (json.JSONDecodeError, KeyError):
                    continue

    base = endpoint()
    todo = [x for x in arms if f"{x['claim_id']}/{x['arm']}" not in done]
    if a.limit:
        todo = todo[:a.limit]
    print(f"endpoint {base}  model {MODEL}  arms {len(arms)}  done {len(done)}  to run {len(todo)}",
          flush=True)

    with open(a.out, "a") as fh:
        for i, arm in enumerate(todo, 1):
            aid = f"{arm['claim_id']}/{arm['arm']}"
            prompt = build_prompt(arm)
            rec = {"id": aid, "claim_id": arm["claim_id"], "arm": arm["arm"],
                   "family": arm.get("family"), "subclass": arm.get("subclass"),
                   "expected": arm.get("expected"), "acceptable": arm.get("acceptable"),
                   "anchor": arm.get("anchor"), "model": MODEL}
            try:
                d, secs = ask(prompt, base)
                raw = d.get("response", "")
                rec.update({"label": parse_label(raw), "raw": raw, "secs": round(secs, 2),
                            "eval_count": d.get("eval_count"),
                            "done_reason": d.get("done_reason")})
            except Exception as e:  # a transport failure must not look like a label
                rec.update({"label": None, "error": f"{type(e).__name__}: {e}"})
            rec["prompt_sha"] = __import__("hashlib").sha256(prompt.encode()).hexdigest()[:16]
            fh.write(json.dumps(rec) + "\n")
            fh.flush()
            if i % 20 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  last {rec['id']} -> {rec.get('label')}"
                      f" (want {rec.get('expected')}) {rec.get('secs')}s", flush=True)

    print("done", flush=True)


if __name__ == "__main__":
    sys.exit(main())
