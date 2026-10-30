"""Natural-language question answering over the platform's intelligence.

The 'ragified' surface behind the MCP `ask` tool: anyone with an MCP client
can ask questions in plain language. Retrieval is hybrid by design —

- Structured retrieval for operational data: namespaces/lab codes are
  extracted from the question and answered from the live surfaces
  (lifecycle outcomes, evaluations, causal chains, proof matrix). Embedding
  search is the wrong tool for structured operational data.
- Lexical retrieval (token overlap) over the knowledge corpus: the failure
  taxonomy (classes, descriptions, remediations) and key documentation —
  small enough to score in memory, refreshed per call, zero infrastructure.

Synthesis runs through the metered, qualified LLM pipeline with a strict
answer-from-context contract: cite sources, say UNKNOWN when the context
does not answer the question. Read-only; no remediation authority.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import time as _time
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.qa")

# Documents worth indexing for RAG (operational knowledge). Each is split
# into sections so long docs don't lose their tail to the character cap.
_DOC_FILES = (
    "workflows.md",
    "mcp-agent-guide.md",
    "architecture.md",
    "evidence-observation-semantics.md",
    "runbook.md",
    "summary-refresh-release.md",
    "integration-findings.md",
    "proof-lab-ecosystem.md",
    "post-summit-babylon-integration.md",
    # Confluence-sourced operational knowledge (validated, read-only)
    "confluence/demo-platform-provision-failure-classification.md",
    "confluence/troubleshooting-destroy-with-babylon.md",
    "confluence/troubleshooting-provision-with-babylon.md",
    "confluence/anarchy-troubleshooting-general-guide.md",
    "confluence/troubleshooting-anarchy.md",
    "confluence/incident-management.md",
    "confluence/replik8s-snapshot-age-issue.md",
    "confluence/dbpool2-server-space-issue.md",
)

_STOPWORDS = {
    "the", "and", "for", "are", "what", "which", "who", "whom", "this",
    "that", "with", "from", "have", "has", "was", "were", "will", "would",
    "could", "should", "does", "did", "not", "but", "can", "did", "how",
    "why", "when", "where", "into", "about", "over", "under", "than",
    "then", "them", "they", "their", "there", "here", "some", "any",
    "all", "our", "your", "his", "her", "its", "just", "like", "also",
    "get", "got", "let", "use", "using", "used", "tell", "show", "give",
    "find", "need", "want", "know", "see", "look", "make", "made",
}


def _tokens(text: str) -> set:
    return {
        word.lower()
        for word in re.findall(r"[A-Za-z0-9_.-]+", str(text))
        if len(word) >= 3 and word.lower() not in _STOPWORDS
    }


def _split_doc(name: str, content: str, max_chars: int = 4000) -> List[Dict]:
    """Split a document into retrievable sections at markdown headings.

    Long docs lose their tail to a single character cap; splitting at
    headings lets each section score independently.
    """
    sections = re.split(r"\n(?=#{1,3} )", content)
    docs: List[Dict] = []
    for i, section in enumerate(sections):
        section = section.strip()
        if not section or len(section) < 50:
            continue
        # Extract the heading for the source label
        heading_match = re.match(r"^#{1,3}\s+(.+)", section)
        heading = heading_match.group(1).strip() if heading_match else f"section-{i}"
        docs.append({
            "source": f"doc:{name}#{heading}"[:120],
            "text": section[:max_chars],
        })
    return docs


def _knowledge_corpus() -> List[Dict]:
    """The retrieval corpus: taxonomy classes + key docs, as documents."""
    from pathlib import Path

    docs: List[Dict] = []

    # Always-present platform overview (matched by "stargate", "platform",
    # "what is", "overview" — the most common demo questions)
    docs.append({
        "source": "doc:platform-overview",
        "text": (
            "StarGate is a lifecycle intelligence platform for the Red Hat Demo "
            "Platform (RHDP). It monitors lab environments across multiple OpenShift "
            "clusters, classifies failures using a qualified LLM and deterministic "
            "taxonomy, investigates anomalies with an AI agent (Sonnet with tool "
            "calls), and proves when remediation worked via verification evals. "
            "Key capabilities: provisioning outcome contracts (provisioning-outcome/v1), "
            "reclamation outcome contracts (reclamation-outcome/v1), causal chains "
            "(symptom to evidence to diagnosis to remedy to proof), a proof lab "
            "validating 19 of 20 failure classes on synthetic ground truth, and an "
            "MCP server for natural-language access from any AI tool. The platform "
            "collects from 4 AAP controllers (prod0, prod1, event0, event1), scans "
            "8 clusters, and processes millions of evaluations."
        ),
    })

    try:
        from engine.failure_class_loader import get_all_classes
        for cls in get_all_classes():
            remediation = cls.get("remediation")
            remediation_text = (
                " ".join(remediation) if isinstance(remediation, list) else str(remediation or "")
            )[:400]
            docs.append({
                "source": f"taxonomy:{cls['name']}",
                "text": (
                    f"Failure class {cls['name']} (severity {cls.get('severity', '?')}, "
                    f"category {cls.get('_source', '?')}): {cls.get('description', '')} "
                    f"Remediation guidance: {remediation_text}"
                ),
            })
    except Exception as error:
        logger.debug("taxonomy corpus unavailable: %s", error)

    docs_dir = Path(__file__).parent.parent / "docs"
    for name in _DOC_FILES:
        try:
            path = docs_dir / name
            if path.exists():
                docs.extend(_split_doc(name, path.read_text()))
        except Exception:
            continue
    return docs


def _retrieve(question: str, corpus: List[Dict], k: int = 5) -> List[Dict]:
    question_tokens = _tokens(question)
    if not question_tokens:
        return []
    scored = []
    for doc in corpus:
        overlap = question_tokens & _tokens(doc["text"])
        if overlap:
            scored.append((len(overlap), doc, sorted(overlap)[:6]))
    scored.sort(key=lambda item: -item[0])
    return [
        {**doc, "matched_terms": terms}
        for _, doc, terms in scored[:k]
    ]


_NAMESPACE_PATTERN = re.compile(r"\b(?:sandbox|user|lab|lb|summit)-[a-z0-9][a-z0-9-]{2,}", re.IGNORECASE)


def _structured_context(question: str) -> List[str]:
    """Live operational context for namespaces mentioned in the question.

    Also provides direct answers for data questions (counts, statuses,
    recent episodes) without LLM synthesis — the data IS the answer.
    """
    from engine.investigation_agent import (
        tool_query_evaluations, tool_query_lifecycle_outcomes,
    )
    contexts: List[str] = []

    # Direct-answer path for fleet-level questions — no namespace needed
    question_lower = question.lower()
    if any(word in question_lower for word in ("recent", "last", "latest", "today", "recently")):
        if any(word in question_lower for word in ("episode", "lifecycle", "provisioning", "reclamation", "outcome")):
            try:
                from api.mcp_server import get_recent_episodes
                episodes = get_recent_episodes(hours=24)
                contexts.append(f"[recent lifecycle episodes]\n{episodes[:2000]}")
            except Exception:
                pass

    namespaces = list(dict.fromkeys(_NAMESPACE_PATTERN.findall(question)))[:3]
    for namespace in namespaces:
        try:
            outcomes = tool_query_lifecycle_outcomes(namespace)
            contexts.append(f"[lifecycle outcomes for {namespace}]\n{outcomes[:1500]}")
        except Exception:
            pass
        try:
            evals = tool_query_evaluations(namespace, limit=5)
            contexts.append(f"[recent evaluations for {namespace}]\n{evals[:800]}")
        except Exception:
            pass
    try:
        from api.mcp_server import _proof_matrix_summary
        summary = _proof_matrix_summary()
        if "prove" in question_lower or "proof" in question_lower:
            contexts.append(f"[proof lab]\n{summary}")
    except Exception:
        pass
    return contexts


_ANSWER_CONTRACT = (
    "You are answering questions about the StarGate platform (Red Hat Demo "
    "Platform operations). Answer ONLY from the provided context. Cite the "
    "source of every claim as [source:...]. If the context does not answer "
    "the question, say exactly what is missing — do not guess, do not "
    "invent data, and never recommend destructive actions. Keep answers "
    "under 250 words."
)

# Response cache: repeated questions answered instantly.
_CACHE_TTL_SECONDS = 300  # 5 minutes
_cache: Dict[str, tuple] = {}  # question_hash -> (timestamp, answer)


def _cache_key(question: str) -> str:
    return hashlib.sha256(question.lower().strip().encode()).hexdigest()[:16]


def _cache_get(question: str) -> str | None:
    key = _cache_key(question)
    entry = _cache.get(key)
    if entry and _time.time() - entry[0] < _CACHE_TTL_SECONDS:
        return entry[1]
    if entry:
        del _cache[key]
    return None


def _cache_put(question: str, answer: str) -> None:
    # Bounded: keep at most 100 entries (LRU-ish via TTL eviction).
    if len(_cache) > 100:
        oldest = min(_cache, key=lambda k: _cache[k][0])
        del _cache[oldest]
    _cache[_cache_key(question)] = (_time.time(), answer)


def _is_simple_taxonomy_lookup(question: str, knowledge: List[Dict]) -> bool:
    """Detect 'what is X?' style questions answerable from one taxonomy hit.

    These skip LLM synthesis entirely — the retrieved taxonomy entry IS
    the answer, formatted with its source. This makes the most common
    demo questions instant.
    """
    if not knowledge or len(knowledge) != 1:
        return False
    source = knowledge[0].get("source", "")
    if not source.startswith("taxonomy:"):
        return False
    # Short question, single strong taxonomy match, no namespace mentions
    if len(question) > 120:
        return False
    if _NAMESPACE_PATTERN.search(question):
        return False
    # Check for question-word patterns that suggest a definition lookup
    question_lower = question.lower()
    return any(word in question_lower for word in (
        "what is", "what's", "what does", "tell me about", "explain",
        "how does", "how do", "define", "meaning of",
    ))


def ask_stargate(question: str) -> str:
    """Answer a natural-language question about the platform.

    Performance tiers:
    - Cached questions: instant (up to 5-minute TTL)
    - Simple taxonomy lookups ("what is X?"): instant (no LLM — the
      retrieved entry IS the answer)
    - Everything else: LLM synthesis with reduced context (target < 10s)

    Hybrid retrieval: live operational data for namespaces mentioned in the
    question, plus lexical retrieval over the taxonomy and documentation.
    LLM synthesis with citations; UNKNOWN when unanswerable from context.
    """
    question = (question or "").strip()[:1000]
    if not question:
        return "Ask a question about the platform: labs, failures, provisioning, reclamation, proofs."

    # Tier 1: cached — instant
    cached = _cache_get(question)
    if cached is not None:
        return cached

    corpus = _knowledge_corpus()
    knowledge = _retrieve(question, corpus)

    # Tier 2: simple taxonomy lookup — skip LLM entirely
    if _is_simple_taxonomy_lookup(question, knowledge):
        doc = knowledge[0]
        answer = f"{doc['text'][:800]}\n\n[source: {doc['source']}]"
        _cache_put(question, answer)
        return answer

    structured = _structured_context(question)

    if not knowledge and not structured:
        return (
            "No platform context matched the question. Try naming a workload "
            "(e.g. sandbox-xxxx), a failure class, or asking about provisioning, "
            "reclamation, or the proof lab."
        )

    # Tier 3: LLM synthesis — but lean: fewer docs, tighter context,
    # shorter output. Target < 10 seconds.
    context_parts = []
    for doc in knowledge[:3]:  # top 3, not top 5
        context_parts.append(f"[source: {doc['source']}]\n{doc['text'][:800]}")  # 800, not 1200
    context_parts.extend(structured[:2])  # max 2 structured contexts
    context = "\n\n".join(context_parts)[:6000]  # 6K, not 20K

    from api.llm import call_llm
    # qwen3-14b: measured 6.6s for 6K context vs llama-scout-17b's 30s+
    # timeout on the same input. The ask tool values speed over depth.
    result = call_llm(
        endpoint="mcp-ask",
        model=os.environ.get("STARGATE_ASK_MODEL", "qwen3-14b"),
        messages=[
            {"role": "system", "content": _ANSWER_CONTRACT},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ],
        max_tokens=300,  # 300, not 600 — shorter answers generate faster
        temperature=0.1,
        timeout=30,  # 30s, not 45s — fail faster, degrade to context
    )
    if not result.get("success"):
        # Still useful: return the retrieved context without synthesis.
        # Cache the fallback too so the second ask is instant.
        sources = "\n\n".join(
            f"[source: {d['source']}] matched {', '.join(d['matched_terms'])}" for d in knowledge
        )
        fallback = (
            f"LLM synthesis unavailable ({str(result.get('error'))[:100]}). "
            f"Retrieved context:\n\n{sources}\n\n{context[:3000]}"
        )
        _cache_put(question, fallback)
        return fallback
    _cache_put(question, result["content"])
    return result["content"]
