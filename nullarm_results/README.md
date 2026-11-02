# Helix null-arm run — 2026-11-02

Our judge, run against `null-arm-checks-v2/arms_v2.json` (511 arms), scored with the
repo's own `scoring_v2.py` and `ARM_MANIFEST_v2.json`. Published so the numbers in the
PR comment are checkable rather than asserted.

## What ran

- Model: **gpt-oss-120b** (116.8B), resident on our own hardware, 65.4GB.
- Temperature 0, one pass, 511 calls, ~80 minutes, no egress to any model provider.
- Prompt: `prompt_system.txt`, and per-arm in `run_judge.py`. Every result line carries
  a `prompt_sha` so an individual prompt can be confirmed against the harness.
- Host: our own box, unmetered. Marginal cost of this run: **$0**.

## Files

- `results_gptoss120b.jsonl` — one line per arm: id, claim_id, arm, family, subclass,
  expected, acceptable, anchor, model, label, raw (verbatim model response), secs,
  eval_count, done_reason, prompt_sha.
- `got_helix_gptoss120b.json` — `{claim_id: {arm: label}}`, the input format
  `scoring_v2.py` expects.
- `scoring_v2_output.json` — the unedited scorer output.
- `run_judge.py`, `prompt_system.txt` — the harness and the exact system prompt.

## Headline

| metric | value |
|---|---|
| Acc_A | 0.9149 |
| FDR_neg | 0.0951 (SUP 0.0543 / REF 0.0408) |
| Det_A | 0.9362 |
| J_gate | 0.8198 |

502 cells scored, 9 anchors excluded. Zero transport errors, 2 labels unparsable.

## Where it fails

- **Conflicting sources (`R_pair`): 13/40**, 24 unacceptable determinate. It resolves
  conflicts instead of reporting them.
- **REFUSAL class: 62/92.** 13 leaked to SUPPORTED, 11 to REFUTED.
- **`c07` diagnostic: SCOPE_NOT_REFUSED** — answered with a label where a refusal was owed.
- **`C_num_noise`: 39/47**, 8 unacceptable determinate.

## Reproduce

```
python3 scoring_v2.py got_helix_gptoss120b.json    # from null-arm-checks-v2/
```

The run itself needs a resident gpt-oss-120b; `run_judge.py` resolves the endpoint and
resumes from a partial results file.
