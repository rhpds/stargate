# Failure-classifier qualification — the evidence flywheel

Qualifies StarGate's production LLM failure classifier (the judge that
proposes failure classes from scan evidence) against the frozen case set in
`classifier_cases.json` and against the deterministic taxonomy pattern
baseline, then emits a `fabric.evaluation-card/v1` card for notarization on
the eval-cards chain.

## Why

StarGate runs an LLM judge in production every day, and until now that judge
has never been validated. This is the survey's unvalidated-LLM-judge gap
living in our own stack. The card answers the operational question directly:
**does the LLM beat the regex baseline it is meant to improve on, and how
consistently?**

## The case design is the test

- Cases `fc-01`–`fc-08` use failure language the taxonomy regex patterns
  match literally — the deterministic baseline should solve these.
- Cases `fc-09`–`fc-12` paraphrase the same failure modes so literal
  matching fails — the LLM's value is measured as the delta on these.
- References are authored from the taxonomy (honest limitation: not
  independent human ground truth), and grading is a deterministic
  proposed-class comparison — no LLM grades this run.

## Usage

```sh
# tests (offline, no cluster, no key)
.venv/bin/python -m pytest tests/test_qualify_classifier.py -q

# the qualification (runtime-only key; ~13 minutes)
export STARGATE_LITELLM_API_KEY=<runtime key>
.venv/bin/python qualify/qualify_classifier.py run \
  --models llama-scout-17b,granite-3-2-8b-instruct-cpu \
  --trials 3 --output-dir runs/classifier-qual-1

# emit the card (validates against the pinned schema)
.venv/bin/python qualify/qualify_classifier.py emit-card \
  --run-dir runs/classifier-qual-1 \
  --output runs/classifier-qual-1/evaluation-card.json
```

The harness mirrors the production call exactly: the `classify` prompt,
temperature 0.1, max_tokens 500, the racmaas gateway. `llama-scout-17b` is
the deployed production model; `granite-3-2-8b-instruct-cpu` is included
because it is the one racmaas model with a server-attested
`system_fingerprint` (see the fabric's racmaas GPU identity gap record —
models without fingerprints carry configuration-level identity only, stated
on the card).

## Limits

Authored cases measure agreement with taxonomy expectations, not
classification quality on novel operational failures. No remediation
authority, no authorization, and a passing card does not exempt the judge
from periodic re-qualification as the taxonomy and models change.
