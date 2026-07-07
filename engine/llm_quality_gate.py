"""Runtime quality gate for LLM responses.

Evaluates responses against quality rubrics and returns pass/fail.
Designed for logging-only integration initially — does not block responses.
"""

import logging
from pathlib import Path
from typing import Dict, Optional, Tuple

from engine.models import LLMQualityResult, QualityOutcome

logger = logging.getLogger("stargate.llm_quality")

_RUBRIC_DIR = Path(__file__).parent.parent / "rubrics" / "llm-quality"
_OUTCOME_RANK = {QualityOutcome.GREEN: 2, QualityOutcome.YELLOW: 1, QualityOutcome.RED: 0}


def check_response_quality(
    prompt_type: str,
    response: str,
    evidence: Dict,
    metadata: Optional[Dict] = None,
    min_outcome: QualityOutcome = QualityOutcome.YELLOW,
) -> Tuple[bool, Optional[LLMQualityResult]]:
    try:
        from engine.llm_quality_evaluator import evaluate_all_dimensions

        result = evaluate_all_dimensions(
            prompt_type=prompt_type,
            response=response,
            evidence=evidence,
            metadata=metadata,
            rubric_dir=_RUBRIC_DIR,
        )

        passes = _OUTCOME_RANK.get(result.overall_outcome, 0) >= _OUTCOME_RANK.get(min_outcome, 0)

        if not passes:
            red_dims = [
                d for d, r in result.dimensions.items()
                if r.outcome == QualityOutcome.RED
            ]
            logger.warning(
                "LLM response quality below threshold: overall=%s, red_dimensions=%s, prompt=%s",
                result.overall_outcome.value,
                red_dims,
                prompt_type,
            )
        else:
            logger.debug(
                "LLM response quality OK: overall=%s, prompt=%s",
                result.overall_outcome.value,
                prompt_type,
            )

        return passes, result

    except Exception as e:
        logger.error("Quality gate evaluation failed: %s", e)
        return True, None
