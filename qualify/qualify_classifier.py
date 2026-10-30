"""StarGate failure-classifier qualification — the evidence flywheel.

Qualifies StarGate's production LLM failure classifier against the frozen
case set in classifier_cases.json and against the deterministic taxonomy
pattern baseline, then emits a fabric.evaluation-card/v1 card. This measures
whether the LLM judge is worth its calls: the case set includes literal
cases the regex baseline solves and paraphrased cases that require semantic
classification. The harness mirrors the production call exactly (same
prompt, temperature, max_tokens, gateway); credentials stay runtime-only in
STARGATE_LITELLM_API_KEY. Cards grant no authority and references are
authored taxonomy expectations, not independent human ground truth.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import ssl
import sys
import time
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from engine.llm_json import parse_llm_json  # noqa: E402

CASES_PATH = ROOT / "qualify" / "classifier_cases.json"
CARD_SCHEMA_PATH = ROOT / "contracts" / "evaluation-card-v1.schema.json"
TAXONOMY_DIR = ROOT / "failure-classes"
PROMPT_PATH = ROOT / "prompts" / "classify.yaml"
Z = 1.96
TRIAL_TIMEOUT = 30

CARD_SCHEMA = json.loads(CARD_SCHEMA_PATH.read_text())
CONSTRUCTS = {
    "production": {
        "workload": "stargate-failure-classification",
        "statement": "Whether StarGate's failure classifier - the production LLM judge that proposes a failure class from scan evidence with the known class list and similar past classifications in context - correctly identifies the taxonomy class of a failure case, compared against the deterministic taxonomy pattern baseline on the same frozen cases.",
        "metric": "Exact proposed_class match per case against authored taxonomy references with the known-class list injected into the evidence, repeated k times per case at production temperature 0.1 and max_tokens 500, reported as single-attempt rate, pass@k and pass-all-k with Wilson 95% intervals, per system including the regex baseline.",
        "gaming_analysis": "Cases 1-8 are authored from the taxonomy's own regex patterns, so a pure pattern-matcher scores on them; cases 9-12 paraphrase the same failure modes so literal matching fails and semantic classification is required. With the class list in context, an LLM could still score by echoing frequent classes rather than reading the failure; temperature 0.1 with repeated trials exposes inconsistency as pass-at-k versus pass-all-k divergence. References are authored diagnostic expectations from the taxonomy, not independent human ground truth.",
    },
    "ablation": {
        "workload": "stargate-failure-classification-ablation",
        "statement": "Whether StarGate's failure classifier can name taxonomy classes when run WITHOUT the known-class list and similar-past-classification context that the production pipeline injects - measuring how load-bearing the context injection is.",
        "metric": "Exact proposed_class match per case against authored taxonomy references with the failure message only (no class list, no past classifications), repeated k times per case, reported as single-attempt rate, pass@k and pass-all-k with Wilson 95% intervals, per system including the regex baseline.",
        "gaming_analysis": "The judge is prompted to propose a class from a known list it cannot see; without context it must invent names, so a low score demonstrates context-dependence rather than model incapacity. The prompt explicitly permits novel class names when none fit, so semantically correct but differently-formatted answers score RED by the exact-match rule - this is the production grading contract, applied honestly. The regex baseline is unaffected by the ablation and serves as the control.",
    },
}

# Lifecycle (provisioning/reclamation outcome) constructs — selected when the
# run uses qualify/lifecycle_cases.json via --cases.
CONSTRUCTS_LIFECYCLE = {
    "production": {
        "workload": "stargate-lifecycle-classification",
        "statement": "Whether StarGate's failure classifier correctly identifies the lifecycle outcome class (provisioning or reclamation) of a control-plane case with the known class list in context, compared against the deterministic taxonomy baseline on the same frozen lifecycle cases.",
        "metric": "Exact proposed_class match per case against authored lifecycle taxonomy references with the known-class list injected into the evidence, repeated k times per case at production temperature 0.1 and max_tokens 500, reported as single-attempt rate, pass@k and pass-all-k with Wilson 95% intervals, per system including the regex baseline.",
        "gaming_analysis": "Cases 1-7 are authored from the lifecycle taxonomy's own regex patterns, so a pure pattern-matcher scores on them; cases 8-12 paraphrase the same lifecycle outcomes so literal matching fails and semantic classification is required. With the class list in context, an LLM could still score by echoing a frequent lifecycle class rather than reading the evidence; temperature 0.1 with repeated trials exposes inconsistency as pass-at-k versus pass-all-k divergence. References are authored diagnostic expectations, not independent human ground truth.",
    },
    "ablation": {
        "workload": "stargate-lifecycle-classification-ablation",
        "statement": "Whether StarGate's failure classifier can name lifecycle outcome classes when run WITHOUT the known-class list - measuring how load-bearing the context injection is for lifecycle classification.",
        "metric": "Exact proposed_class match per case against authored lifecycle taxonomy references with the failure message only (no class list), repeated k times per case, reported as single-attempt rate, pass@k and pass-all-k with Wilson 95% intervals, per system including the regex baseline.",
        "gaming_analysis": "The judge must infer lifecycle classes it cannot see named; a low score demonstrates context-dependence rather than model incapacity. The regex baseline is unaffected by the ablation and serves as the control.",
    },
}


def _cases_id(cases_path: Path) -> str:
    """Stable identity for a case set: 'failure' for the original frozen set
    (preserving historical source_id format), 'lifecycle' for the lifecycle set."""
    stem = cases_path.stem.removesuffix("_cases") or cases_path.stem
    return "failure" if stem == "classifier" else stem


def format_evidence(case: dict, context_mode: str, taxonomy=None) -> str:
    """Build the evidence block. Production mode mirrors the pipeline's
    context injection (known class list + exemplar past classifications);
    ablation mode passes the failure message alone."""
    evidence = case["evidence"]
    if context_mode != "production":
        return evidence
    taxonomy = taxonomy if taxonomy is not None else load_taxonomy()
    class_list = ", ".join(name for name, _ in taxonomy)
    exemplars = [
        "Failure message: pod api-5f9c restarted 3 times with exit code 137. Classification: oom_killed",
        "Failure message: route console returning HTTP 503 after backend rollout. Classification: ingress_5xx_spike",
    ]
    return (evidence + "\n\n## Similar past classifications\n"
            + "\n".join(exemplars)
            + "\n\n## Known failure classes\n" + class_list)


def canonical(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False).encode("utf-8")


def digest(value) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def wilson(successes: int, total: int) -> list:
    if total <= 0:
        raise ValueError("wilson needs a positive denominator")
    p = successes / total
    denom = 1 + Z * Z / total
    centre = (p + Z * Z / (2 * total)) / denom
    half = Z * math.sqrt(p * (1 - p) / total + Z * Z / (4 * total * total)) / denom
    return [round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)]


def rate_block(passed: int, total: int, **extra) -> dict:
    block = {"value": round(passed / total, 4), "passed": passed, "total": total, "wilson_95": wilson(passed, total)}
    block.update(extra)
    return block


# ---------- taxonomy baseline (deterministic) ----------


def load_taxonomy() -> list:
    """Ordered (class_name, compiled_pattern) from the failure-classes files."""
    import yaml

    entries = []
    for path in sorted(TAXONOMY_DIR.glob("*.yaml")):
        data = yaml.safe_load(path.read_text())
        for name, spec in (data.get("classes") or {}).items():
            pattern = spec.get("pattern") if isinstance(spec, dict) else None
            if pattern:
                try:
                    entries.append((name, re.compile(pattern)))
                except re.error:
                    continue
    return entries


def regex_baseline_predict(evidence: str, taxonomy=None):
    for name, pattern in taxonomy if taxonomy is not None else load_taxonomy():
        if pattern.search(evidence):
            return name
    return None


# ---------- production LLM call ----------


def load_prompt():
    import yaml

    prompt = yaml.safe_load(PROMPT_PATH.read_text())
    return prompt["system"].strip(), prompt["user_template"]


def call_llm(evidence: str, model: str, *, api_key: str, api_url: str) -> dict:
    system, user_template = load_prompt()
    payload = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": user_template.replace("{evidence}", evidence)},
        ],
        "max_tokens": 500,
        "temperature": 0.1,
    }
    req = urllib.request.Request(
        api_url,
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json", "Authorization": "Bearer " + api_key},
    )
    started = time.monotonic()
    with urllib.request.urlopen(req, timeout=TRIAL_TIMEOUT, context=ssl.create_default_context()) as response:
        result = json.loads(response.read())
    choice = result["choices"][0]
    content = choice["message"].get("content") or ""
    return {
        "content": content,
        "finish_reason": choice.get("finish_reason"),
        "fingerprint": result.get("system_fingerprint"),
        "latency": round(time.monotonic() - started, 3),
        "usage": result.get("usage", {}),
    }


def parse_proposed_class(content: str):
    """Extract proposed_class from the judge's JSON reply (production format).

    Delegates to engine.llm_json so the harness grades with the same
    tolerant extraction the production pipeline uses (fences, prose
    wrapping, and brace-doubled replies that mirror a prompt example).
    """
    data = parse_llm_json(content)
    if data and isinstance(data.get("proposed_class"), str):
        return data["proposed_class"].strip()
    return None


# ---------- run ----------


def run_qualification(models: list, trials: int, output_dir: Path, context_mode: str = "production",
                      cases_path: Path = None) -> dict:
    cases_path = cases_path or CASES_PATH
    cases = json.loads(cases_path.read_text())["cases"]
    taxonomy = load_taxonomy()
    api_key = os.environ.get("STARGATE_LITELLM_API_KEY", "")
    api_url = os.environ.get("STARGATE_LITELLM_URL", "${STARGATE_LITELLM_URL:-https://LLM-GATEWAY/v1/chat/completions}")
    output_dir.mkdir(parents=True, exist_ok=False)

    systems = [("taxonomy-regex-baseline", None)] + [(model, model) for model in models]
    all_rows = []
    for system_id, model in systems:
        rows = []
        for case in cases:
            evidence = format_evidence(case, context_mode, taxonomy)
            for trial in range(1, trials + 1):
                row = {"system_id": system_id, "case_id": case["id"], "trial": trial,
                       "expected": case["expected_class"], "outcome": "completed", "quality": "RED"}
                if model is None:
                    predicted = regex_baseline_predict(case["evidence"], taxonomy)
                    row.update(predicted=predicted, latency=0.0, fingerprint=None, model_calls=0)
                else:
                    if not api_key:
                        raise SystemExit("STARGATE_LITELLM_API_KEY is required for live model trials")
                    try:
                        result = call_llm(evidence, model, api_key=api_key, api_url=api_url)
                        predicted = parse_proposed_class(result["content"])
                        row.update(predicted=predicted, latency=result["latency"],
                                   fingerprint=result.get("fingerprint"), model_calls=1,
                                   finish_reason=result.get("finish_reason"),
                                   raw_reply=result["content"][:2000])
                    except Exception as error:
                        row.update(outcome="adapter_failure", error_type=type(error).__name__,
                                   predicted=None, latency=TRIAL_TIMEOUT, fingerprint=None, model_calls=1)
                row["quality"] = "GREEN" if row.get("predicted") == row["expected"] else "RED"
                rows.append(row)
                with (output_dir / "trials.jsonl").open("a") as handle:
                    handle.write(json.dumps(row, sort_keys=True) + "\n")
        all_rows.extend(rows)

    run = {
        "schema_version": "stargate.classifier-qualification/v1",
        "started_namespace": "stargate",
        "cases_sha256": digest(cases),
        "cases_id": _cases_id(cases_path),
        "prompt_id": "classify",
        "context_mode": context_mode,
        "models": models,
        "trials_per_case": trials,
        "api_base": api_url,
        "finished_at": datetime.now(timezone.utc).isoformat(),
    }
    (output_dir / "run.json").write_text(json.dumps(run, indent=2) + "\n")
    return run


# ---------- card emission ----------


def _system_rows(rows: list, system_id: str) -> list:
    return [row for row in rows if row["system_id"] == system_id]


def build_card(run_dir: Path) -> dict:
    rows = [json.loads(line) for line in (run_dir / "trials.jsonl").read_text().splitlines() if line.strip()]
    run = json.loads((run_dir / "run.json").read_text())
    cases = json.loads(CASES_PATH.read_text())["cases"]

    systems = []
    for system_id in sorted({row["system_id"] for row in rows}):
        system_rows = _system_rows(rows, system_id)
        by_case = {}
        for row in system_rows:
            by_case.setdefault(row["case_id"], []).append(row)
        trials_per_case = run["trials_per_case"]
        if {len(v) for v in by_case.values()} != {trials_per_case}:
            raise ValueError("trials per case do not match the declared repetition")
        completed = [row for row in system_rows if row["outcome"] == "completed"]
        successes = sum(1 for row in system_rows if row["quality"] == "GREEN")
        cases_any = sum(1 for case_rows in by_case.values() if any(r["quality"] == "GREEN" for r in case_rows))
        cases_all = sum(1 for case_rows in by_case.values() if all(r["quality"] == "GREEN" for r in case_rows))
        incomplete = len(system_rows) - len(completed)
        is_baseline = system_id == "taxonomy-regex-baseline"
        fingerprints = {row.get("fingerprint") for row in completed if row.get("fingerprint")}
        model_config = {"model": system_id, "api_base": run.get("api_base", "${STARGATE_LITELLM_URL:-https://LLM-GATEWAY/v1}"),
                        "temperature": 0.1, "max_tokens": 500}
        scope = ("Deterministic taxonomy pattern baseline on the same frozen cases; not a capability equivalent."
                 if is_baseline else
                 "StarGate production failure-classification judge on frozen authored taxonomy cases; "
                 + ("server-attested identity: " + sorted(fingerprints)[0] if fingerprints else
                    "configuration-level identity only: the racmaas gateway does not report system_fingerprint for this model"))
        systems.append({
            "system_id": system_id,
            "scaffold": {"adapter": "taxonomy-regex" if is_baseline else "racmaas-litellm",
                         "procedure_revision": "stargate-classify-v2"},
            "model_binding": {"candidate_kind": "deterministic" if is_baseline else "live-model",
                              "profile_sha256": digest(model_config)},
            "evidence_label": "OFFLINE" if is_baseline else "LIVE",
            "repetition": {"trials_per_case": trials_per_case, "case_count": len(by_case),
                           "total_trials": len(system_rows), "incomplete_trials": incomplete},
            "single_attempt_rate": rate_block(successes, len(system_rows)),
            "pass_at_k": rate_block(cases_any, len(by_case)),
            "pass_all_k": rate_block(cases_all, len(by_case), k=trials_per_case),
            "reliability_claimable": trials_per_case >= 2 and incomplete == 0,
            "reliability_note": ("Single run per case (k=1): pass@k is not evidence of reliability."
                                 if trials_per_case < 2 else
                                 "Incomplete trials present; consistency is not claimable."
                                 if incomplete else
                                 "All k runs per case completed; pass-all-k on the measured case set only."),
            "performance": {
                "latency": {"unit": "seconds",
                            "mean": round(sum(r["latency"] for r in completed) / len(completed), 3) if completed else 0.0,
                            "max": round(max((r["latency"] for r in completed), default=0.0), 3)},
                "model_calls": sum(row.get("model_calls", 0) for row in system_rows),
                "deadline": {"unit": "seconds", "value": TRIAL_TIMEOUT}},
            "scope": scope,
        })

    card = {
        "schema_version": "fabric.evaluation-card/v1",
        "issued_at": datetime.now(timezone.utc).isoformat(),
        "mode": "workload-pipeline",
        "construct": None,  # replaced below
        "evaluation": {
            "source_schema_version": "stargate.classifier-qualification/v1",
            "source_id": f"stargate-{run.get('cases_id', 'failure')}-classification-" + run.get("context_mode", "production"),
            "binding_sha256": run["cases_sha256"],
            "measured_sha256": digest(rows),
            "split": "development",
        },
        "systems": systems,
        "uncertainty": {
            "method": "Wilson score interval (z=1.96) on binomial case outcomes; describes sampling uncertainty of the measured case set only",
            "judge_error_included": False,
            "grading_basis": ["deterministic proposed_class comparison against authored taxonomy references; no LLM grades this run"],
            "notes": "References are authored from the taxonomy, not independent human ground truth. "
                     "Systems without a server-reported system_fingerprint carry configuration-level identity only "
                     "(see the racmaas GPU identity gap record).",
        },
        "holdout_policy": {
            "split": "development",
            "case_origins": ["authored-synthetic"],
            "statement": "Authored teaching cases derived from the frozen taxonomy; no operational traffic and no held-out split.",
        },
        "verdict": {"color": "AMBER" if any(s["pass_all_k"]["value"] >= 0.5 for s in systems) else "RED",
                    "authorizes_execution": False},
        "limits": "StarGate classifier qualification on frozen authored cases. Measures agreement with taxonomy expectations, "
                  "not classification quality on novel operational failures. No authorization, no remediation authority.",
    }
    construct_set = CONSTRUCTS_LIFECYCLE if run.get("cases_id") == "lifecycle" else CONSTRUCTS
    construct = construct_set[run.get("context_mode", "production")]
    card["construct"] = {
        "statement": construct["statement"],
        "metric": construct["metric"],
        "gaming_analysis": construct["gaming_analysis"],
        "construct_sha256": digest(construct),
    }
    card["card_sha256"] = digest(card)
    Draft202012Validator(CARD_SCHEMA).validate(card)
    return card


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    run_parser = sub.add_parser("run")
    run_parser.add_argument("--models", default="llama-scout-17b,granite-3-2-8b-instruct-cpu")
    run_parser.add_argument("--trials", type=int, default=3)
    run_parser.add_argument("--context-mode", choices=("production", "ablation"), default="production")
    run_parser.add_argument("--cases", type=Path, default=CASES_PATH,
                            help="Case set to qualify (default: the frozen failure-classification set; "
                                 "qualify/lifecycle_cases.json qualifies lifecycle outcomes)")
    run_parser.add_argument("--output-dir", type=Path, required=True)
    emit_parser = sub.add_parser("emit-card")
    emit_parser.add_argument("--run-dir", type=Path, required=True)
    emit_parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "run":
        models = [m.strip() for m in args.models.split(",") if m.strip()]
        result = run_qualification(models, args.trials, args.output_dir,
                                   context_mode=args.context_mode, cases_path=args.cases)
        print(json.dumps({"models": result["models"], "trials": result["trials_per_case"],
                          "context_mode": result["context_mode"], "cases_id": result["cases_id"]}))
        return 0

    card = build_card(args.run_dir)
    args.output.write_text(json.dumps(card, indent=2) + "\n")
    print(json.dumps({"card_sha256": card["card_sha256"], "systems": len(card["systems"])}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
