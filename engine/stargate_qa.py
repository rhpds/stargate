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

import json
import logging
import re
from typing import Dict, List, Optional

logger = logging.getLogger("stargate.qa")

# Documents worth indexing from docs/ (operational knowledge, kept small).
_DOC_FILES = (
    "evidence-observation-semantics.md",
    "runbook.md",
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


def _knowledge_corpus() -> List[Dict]:
    """The retrieval corpus: taxonomy classes + key docs, as documents."""
    from pathlib import Path

    docs: List[Dict] = []
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
                content = path.read_text()[:6000]
                docs.append({"source": f"doc:{name}", "text": content})
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
    """Live operational context for namespaces mentioned in the question."""
    from engine.investigation_agent import (
        tool_query_evaluations, tool_query_lifecycle_outcomes,
    )
    contexts: List[str] = []
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
        if "prove" in question.lower() or "proof" in question.lower():
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


def ask_stargate(question: str) -> str:
    """Answer a natural-language question about the platform.

    Hybrid retrieval: live operational data for namespaces mentioned in the
    question, plus lexical retrieval over the taxonomy and documentation.
    LLM synthesis with citations; UNKNOWN when unanswerable from context.
    """
    question = (question or "").strip()[:1000]
    if not question:
        return "Ask a question about the platform: labs, failures, provisioning, reclamation, proofs."

    corpus = _knowledge_corpus()
    knowledge = _retrieve(question, corpus)
    structured = _structured_context(question)

    if not knowledge and not structured:
        return (
            "No platform context matched the question. Try naming a workload "
            "(e.g. sandbox-xxxx), a failure class, or asking about provisioning, "
            "reclamation, or the proof lab."
        )

    context_parts = []
    for doc in knowledge:
        context_parts.append(f"[source: {doc['source']}]\n{doc['text'][:1200]}")
    context_parts.extend(structured)
    context = "\n\n".join(context_parts)[:20000]

    from api.llm import call_llm
    result = call_llm(
        endpoint="mcp-ask",
        messages=[
            {"role": "system", "content": _ANSWER_CONTRACT},
            {"role": "user", "content": f"Question: {question}\n\nContext:\n{context}"},
        ],
        max_tokens=600,
        temperature=0.1,
        timeout=45,
    )
    if not result.get("success"):
        # Still useful: return the retrieved context without synthesis.
        sources = "\n\n".join(
            f"[source: {d['source']}] matched {', '.join(d['matched_terms'])}" for d in knowledge
        )
        return (
            f"LLM synthesis unavailable ({str(result.get('error'))[:100]}). "
            f"Retrieved context:\n\n{sources}\n\n{context[:3000]}"
        )
    return result["content"]
