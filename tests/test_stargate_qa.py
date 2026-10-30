"""Tests for the natural-language QA layer (engine/stargate_qa.py)."""

from unittest.mock import patch

from engine import stargate_qa


class TestRetrieval:
    def test_taxonomy_retrieval_matches_the_question(self):
        corpus = stargate_qa._knowledge_corpus()
        assert len(corpus) >= 50  # taxonomy classes
        hits = stargate_qa._retrieve("what is teardown_stuck and how do I fix a stuck destroy?", corpus)
        assert hits, "expected taxonomy hits"
        assert any("teardown_stuck" in h["source"] for h in hits)

    def test_reclamation_and_provisioning_classes_retrievable(self):
        corpus = stargate_qa._knowledge_corpus()
        for term in ("destroy_failed", "workshop_provision_stalled", "resource_leak_pv"):
            hits = stargate_qa._retrieve(f"tell me about {term}", corpus)
            assert any(term in h["source"] for h in hits), f"{term} not retrieved"

    def test_no_match_returns_empty(self):
        assert stargate_qa._retrieve("quantum flux capacitor", []) == []

    def test_namespace_extraction(self):
        found = stargate_qa._NAMESPACE_PATTERN.findall(
            "did sandbox-abc123 and sandbox-xyz9 fail?"
        )
        assert set(found) == {"sandbox-abc123", "sandbox-xyz9"}


class TestAskStargate:
    def test_empty_question_gets_guidance(self):
        result = stargate_qa.ask_stargate("")
        assert "Ask a question" in result

    def test_no_context_gets_honest_guidance(self):
        with patch.object(stargate_qa, "_knowledge_corpus", return_value=[]), \
             patch.object(stargate_qa, "_structured_context", return_value=[]):
            result = stargate_qa.ask_stargate("quantum flux capacitor status?")
        assert "No platform context matched" in result

    def test_llm_synthesis_with_citations(self):
        """Complex questions that need multiple sources go through LLM synthesis."""
        fake_corpus = [
            {"source": "taxonomy:teardown_stuck",
             "text": "Failure class teardown_stuck: AnarchySubject stuck destroying. Remediation: check state."},
            {"source": "taxonomy:destroy_failed",
             "text": "Failure class destroy_failed: destroy job explicitly failed."},
            {"source": "taxonomy:resource_leak_pv",
             "text": "Failure class resource_leak_pv: orphaned PV bound to deleted namespace."},
        ]
        with patch.object(stargate_qa, "_knowledge_corpus", return_value=fake_corpus), \
             patch.object(stargate_qa, "_structured_context", return_value=[]), \
             patch("api.llm.call_llm", return_value={
                 "success": True,
                 "content": "teardown_stuck means stuck destroying [source: taxonomy:teardown_stuck]. destroy_failed means the job failed [source: taxonomy:destroy_failed].",
                 "error": None,
             }) as llm:
            # Complex question with multiple hits — goes through LLM
            result = stargate_qa.ask_stargate(
                "compare teardown_stuck versus destroy_failed versus resource_leak_pv")
        assert "teardown_stuck" in result
        system = llm.call_args.kwargs["messages"][0]["content"]
        assert "Answer ONLY from the provided context" in system

    def test_simple_taxonomy_lookup_skips_llm(self):
        """'what is X?' with a single taxonomy hit returns instantly — no LLM."""
        fake_corpus = [{
            "source": "taxonomy:oom_killed",
            "text": "Failure class oom_killed: container exceeded memory limit.",
        }]
        with patch.object(stargate_qa, "_knowledge_corpus", return_value=fake_corpus), \
             patch.object(stargate_qa, "_structured_context", return_value=[]), \
             patch("api.llm.call_llm") as llm:
            result = stargate_qa.ask_stargate("what is oom_killed?")
        assert "oom_killed" in result
        assert "[source: taxonomy:oom_killed]" in result
        llm.assert_not_called()  # instant — no LLM needed

    def test_cached_question_returns_instantly(self):
        """Second ask of the same question is served from cache."""
        fake_corpus = [{
            "source": "taxonomy:oom_killed",
            "text": "Failure class oom_killed: container exceeded memory limit.",
        }]
        with patch.object(stargate_qa, "_knowledge_corpus", return_value=fake_corpus), \
             patch.object(stargate_qa, "_structured_context", return_value=[]):
            first = stargate_qa.ask_stargate("what is oom_killed?")
            # Second call should be cached — even if corpus is now empty
            with patch.object(stargate_qa, "_knowledge_corpus", return_value=[]):
                second = stargate_qa.ask_stargate("what is oom_killed?")
        assert first == second

    def test_llm_failure_returns_retrieved_context(self):
        """Complex question where LLM fails still serves the context."""
        fake_corpus = [
            {"source": "taxonomy:oom_killed", "text": "Failure class oom_killed: memory limit."},
            {"source": "taxonomy:pods_crashlooping", "text": "Failure class pods_crashlooping: restart loop."},
        ]
        with patch.object(stargate_qa, "_knowledge_corpus", return_value=fake_corpus), \
             patch.object(stargate_qa, "_structured_context", return_value=[]), \
             patch("api.llm.call_llm", return_value={
                 "success": False, "content": "", "error": "timeout",
             }):
            result = stargate_qa.ask_stargate(
                "compare oom_killed with pods_crashlooping for me right now please")
        assert "LLM synthesis unavailable" in result
        assert "oom_killed" in result  # the retrieved context is still served

    def test_structured_context_for_named_namespaces(self):
        with patch("engine.investigation_agent.tool_query_lifecycle_outcomes",
                   return_value="Summary: 2 episodes — 1 pass, 1 fail") as outcomes, \
             patch("engine.investigation_agent.tool_query_evaluations",
                   return_value="last 5 evaluations"), \
             patch("api.llm.call_llm", return_value={
                 "success": True, "content": "reclaimed [source: lifecycle]", "error": None,
             }):
            result = stargate_qa.ask_stargate("did sandbox-probe1 get reclaimed?")
        assert "reclaimed" in result
        outcomes.assert_called_once_with("sandbox-probe1")


class TestAskToolRegistration:
    def test_ask_is_registered(self):
        import asyncio
        from api.mcp_server import mcp
        tools = asyncio.run(mcp.list_tools())
        names = {t.name for t in tools}
        assert "ask" in names
