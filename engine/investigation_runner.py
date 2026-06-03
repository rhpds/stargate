"""Multi-step investigation chain runner.

Runs sequential kubectl commands where each step can:
- Extract structured data from JSON output
- Conditionally skip based on previous results
- Store results for use in subsequent steps
"""

import json
import logging
import re
from typing import Any, Dict

from engine.rollback import _run_oc

logger = logging.getLogger("stargate.investigation")


class InvestigationRunner:
    """Execute a multi-step investigation chain, collecting evidence at each step."""

    def run(self, entry: dict, namespace: str, kubeconfig: str, params: dict) -> dict:
        """Run all steps in the investigation chain.

        Args:
            entry: Catalog entry with 'steps' list
            namespace: Target namespace
            kubeconfig: Path to kubeconfig
            params: Template parameters (pod, service, etc.)

        Returns:
            dict with 'steps' (execution log), 'report' (formatted), 'context' (all variables)
        """
        context: Dict[str, Any] = {"namespace": namespace, **params}
        results = []

        for i, step in enumerate(entry.get("steps", [])):
            # Check condition
            condition = step.get("condition") if isinstance(step, dict) else getattr(step, "condition", None)
            cmd_template = step.get("command") if isinstance(step, dict) else step.command
            extract_expr = step.get("extract") if isinstance(step, dict) else getattr(step, "extract", None)
            store_as = step.get("store_as") if isinstance(step, dict) else getattr(step, "store_as", None)

            if condition and not self._check_condition(condition, context):
                logger.debug("Step %d skipped: condition '%s' not met", i, condition)
                continue

            cmd = self._substitute(cmd_template, context)

            try:
                output = _run_oc(cmd.split(), kubeconfig)
            except Exception as e:
                output = f"Error: {e}"
                logger.warning("Investigation step %d failed: %s", i, e)

            if extract_expr and store_as:
                extracted = self._extract(output, extract_expr)
                context[store_as] = extracted
            elif store_as:
                context[store_as] = output.strip()

            results.append({
                "step": i,
                "command": cmd,
                "output": output[:2000],
                "stored_as": store_as,
            })

        report = self._format_output(entry.get("output_template", ""), context)
        return {"steps": results, "report": report, "context": context}

    def _check_condition(self, condition: str, context: dict) -> bool:
        """Evaluate a condition against the current context.

        Supports:
        - "var_name" -- truthy check (non-empty, non-None)
        - "var_name contains substring" -- substring match
        """
        if " contains " in condition:
            var_name, substring = condition.split(" contains ", 1)
            value = context.get(var_name.strip(), "")
            if isinstance(value, list):
                return len(value) > 0
            return substring.strip() in str(value)

        value = context.get(condition.strip())
        if value is None:
            return False
        if isinstance(value, (list, dict)):
            return len(value) > 0
        if isinstance(value, str):
            return len(value.strip()) > 0
        return bool(value)

    def _extract(self, output: str, expression: str) -> Any:
        """Extract data from JSON output using a simplified JSONPath-like expression.

        Supports:
        - "items[*].metadata.name" -- extract field from all items
        - "items[?(@.status.phase!='Running')].metadata.name" -- filtered extraction
        """
        try:
            data = json.loads(output)
        except (json.JSONDecodeError, ValueError):
            return output.strip()

        # Handle items[?(@.field==value)].path or items[?(@.field!=value)].path
        match = re.match(r"items\[\?\(@\.(.+?)([!=<>]+)'?(.+?)'?\)\]\.(.+)", expression)
        if match:
            field_path, op, expected, extract_path = match.groups()
            items = data.get("items", [])
            results = []
            for item in items:
                actual = self._get_nested(item, field_path)
                if self._compare(actual, op, expected):
                    results.append(self._get_nested(item, extract_path))
            return [r for r in results if r is not None]

        # Simple items[*].path
        match = re.match(r"items\[\*\]\.(.+)", expression)
        if match:
            path = match.group(1)
            return [self._get_nested(item, path) for item in data.get("items", [])]

        return output.strip()

    def _get_nested(self, obj: dict, path: str) -> Any:
        """Get a nested value from a dict using dot notation."""
        for key in path.split("."):
            if isinstance(obj, dict):
                obj = obj.get(key)
            else:
                return None
        return obj

    def _compare(self, actual: Any, op: str, expected: str) -> bool:
        if op == "!=":
            return str(actual) != expected
        if op == "==":
            return str(actual) == expected
        return False

    def _substitute(self, template: str, context: dict) -> str:
        """Replace {var} and {var[0]} placeholders with context values."""
        def replacer(match):
            key = match.group(1)
            # Handle indexed access like {failed_pods[0]}
            idx_match = re.match(r"(.+)\[(\d+)\]", key)
            if idx_match:
                var_name, idx = idx_match.group(1), int(idx_match.group(2))
                value = context.get(var_name, [])
                if isinstance(value, list) and idx < len(value):
                    return str(value[idx])
                return ""
            value = context.get(key, "")
            if isinstance(value, list):
                return " ".join(str(v) for v in value)
            return str(value)

        return re.sub(r"\{([^}]+)\}", replacer, template)

    def _format_output(self, template: str, context: dict) -> str:
        """Format the output template with collected context."""
        if not template:
            parts = []
            for key, value in context.items():
                if key == "namespace":
                    continue
                if isinstance(value, str) and len(value) > 20:
                    parts.append(f"## {key}\n{value}")
            return "\n\n".join(parts)
        return self._substitute(template, context)
