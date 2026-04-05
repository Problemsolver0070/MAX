"""RuleEngine -- quality rule extraction, supersession, pattern extraction."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.llm.client import LLMClient
from max.quality.store import QualityStore

logger = logging.getLogger(__name__)

RULE_EXTRACTION_PROMPT = """You are a Quality Rule Extractor for Max.

Given an audit failure, extract reusable quality rules that should be checked in future audits.

Audit issues found:
{issues}

Subtask: {subtask_description}
Output that failed:
{output_content}

Return ONLY valid JSON:
{{
  "rules": [
    {{
      "rule": "Clear, actionable quality rule",
      "category": "validation | completeness | robustness | clarity | correctness",
      "severity": "low | normal | high | critical"
    }}
  ]
}}

Rules should be:
- General enough to apply to future tasks (not specific to this task)
- Actionable and clear
- Not redundant with common sense"""

PATTERN_EXTRACTION_PROMPT = """You are a Quality Pattern Extractor for Max.

Given high-quality work, extract reusable patterns that should be encouraged in future work.

Strengths identified:
{strengths}

Subtask: {subtask_description}
High-quality output:
{output_content}

Return ONLY valid JSON:
{{
  "patterns": [
    {{
      "pattern": "Clear description of what was done well",
      "category": "code_quality | research | communication | structure | thoroughness"
    }}
  ]
}}

Patterns should be general enough to apply to future tasks."""


class RuleEngine:
    """Manages quality rule lifecycle -- extraction, retrieval, pattern extraction."""

    def __init__(
        self,
        llm: LLMClient,
        quality_store: QualityStore,
        max_rules_per_audit: int = 5,
    ) -> None:
        self._llm = llm
        self._store = quality_store
        self._max_rules = max_rules_per_audit

    async def extract_rules(
        self,
        audit_id: uuid.UUID,
        issues: list[dict[str, str]],
        subtask_description: str,
        output_content: str,
    ) -> list[dict[str, Any]]:
        """Extract quality rules from audit failure issues."""
        if not issues:
            return []

        prompt = RULE_EXTRACTION_PROMPT.format(
            issues=json.dumps(issues, indent=2),
            subtask_description=subtask_description,
            output_content=output_content[:2000],
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            raw_rules = parsed.get("rules", [])
        except Exception:
            logger.exception("Rule extraction failed")
            return []

        capped = raw_rules[: self._max_rules]
        result: list[dict[str, Any]] = []
        for r in capped:
            rule_id = uuid.uuid4()
            rule_text = r.get("rule", "")
            category = r.get("category", "general")
            severity = r.get("severity", "normal")
            await self._store.create_rule(
                rule_id=rule_id,
                rule=rule_text,
                source=str(audit_id),
                category=category,
                severity=severity,
            )
            await self._store.record_rule_to_ledger(
                rule_id=rule_id,
                rule=rule_text,
                category=category,
                severity=severity,
                source_audit_id=audit_id,
            )
            result.append(
                {"rule_id": str(rule_id), "rule": rule_text, "category": category}
            )

        return result

    async def extract_patterns(
        self,
        task_id: uuid.UUID,
        strengths: list[str],
        subtask_description: str,
        output_content: str,
    ) -> list[dict[str, Any]]:
        """Extract quality patterns from high-scoring audit successes."""
        if not strengths:
            return []

        prompt = PATTERN_EXTRACTION_PROMPT.format(
            strengths="\n".join(f"- {s}" for s in strengths),
            subtask_description=subtask_description,
            output_content=output_content[:2000],
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
            )
            parsed = self._parse_json(response.text)
            raw_patterns = parsed.get("patterns", [])
        except Exception:
            logger.exception("Pattern extraction failed")
            return []

        result: list[dict[str, Any]] = []
        for p in raw_patterns[:3]:
            pattern_id = uuid.uuid4()
            pattern_text = p.get("pattern", "")
            category = p.get("category", "general")
            await self._store.create_pattern(
                pattern_id=pattern_id,
                pattern=pattern_text,
                source_task_id=task_id,
                category=category,
            )
            await self._store.record_pattern_to_ledger(
                pattern_id=pattern_id,
                pattern=pattern_text,
                category=category,
                source_task_id=task_id,
            )
            result.append(
                {"pattern_id": str(pattern_id), "pattern": pattern_text}
            )

        return result

    async def get_rules_for_audit(
        self, category: str | None = None
    ) -> list[dict[str, Any]]:
        """Get active quality rules for inclusion in auditor prompts."""
        return await self._store.get_active_rules(category=category)

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown fences."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {}
