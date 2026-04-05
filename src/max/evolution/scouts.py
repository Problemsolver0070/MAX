"""Scout Agents -- discover evolution proposals by analyzing system state via LLM."""

from __future__ import annotations

import json
import logging
import re
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

from max.evolution.models import EvolutionProposal

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient
    from max.memory.metrics import MetricCollector
    from max.quality.store import QualityStore

logger = logging.getLogger(__name__)

MAX_PROPOSALS_PER_SCOUT = 3

# ── Prompts ──────────────────────────────────────────────────────────────────

TOOL_SCOUT_PROMPT = """\
You are a tool optimization scout. Analyze the tool configurations and metric \
baselines below. Identify up to {max} improvements to tool configs or prompts \
that would improve reliability, speed, or quality.

Tool configs:
{tool_configs}

Metric baselines:
{baselines}

Respond with a JSON object containing a "proposals" array. Each proposal must have:
- description (str): what to change and why
- target_type (str): "tool_config" or "prompt"
- target_id (str): which tool or agent type to change
- impact_score (float 0-1): expected positive impact
- effort_score (float 0-1): estimated effort to implement
- risk_score (float 0-1): risk of regression
"""

PATTERN_SCOUT_PROMPT = """\
You are a pattern optimization scout. Analyze the quality patterns, prompts, \
and quality pulse below. Identify up to {max} improvements to prompts that \
would reinforce successful patterns and eliminate anti-patterns.

Quality patterns:
{patterns}

Current prompts:
{prompts}

Quality pulse:
{pulse}

Respond with a JSON object containing a "proposals" array. Each proposal must have:
- description (str): what to change and why
- target_type (str): "prompt" or "tool_config"
- target_id (str): which agent type or tool to change
- impact_score (float 0-1): expected positive impact
- effort_score (float 0-1): estimated effort to implement
- risk_score (float 0-1): risk of regression
"""

QUALITY_SCOUT_PROMPT = """\
You are a quality improvement scout. Analyze the active quality rules, pulse, \
and prompts below. Look for recurring failure patterns and identify up to {max} \
changes that would reduce failure rates and improve audit scores.

Active quality rules:
{rules}

Quality pulse:
{pulse}

Current prompts:
{prompts}

Respond with a JSON object containing a "proposals" array. Each proposal must have:
- description (str): what to change and why
- target_type (str): "prompt" or "tool_config"
- target_id (str): which agent type or tool to change
- impact_score (float 0-1): expected positive impact
- effort_score (float 0-1): estimated effort to implement
- risk_score (float 0-1): risk of regression
"""

ECOSYSTEM_SCOUT_PROMPT = """\
You are an ecosystem optimization scout. Analyze the tool configs and prompts \
below. Look for cross-cutting optimization opportunities such as combining \
tools, simplifying workflows, or removing redundancy. Identify up to {max} \
improvements.

Tool configs:
{tool_configs}

Current prompts:
{prompts}

Respond with a JSON object containing a "proposals" array. Each proposal must have:
- description (str): what to change and why
- target_type (str): "tool_config" or "prompt"
- target_id (str): which tool or agent type to change
- impact_score (float 0-1): expected positive impact
- effort_score (float 0-1): estimated effort to implement
- risk_score (float 0-1): risk of regression
"""


# ── Base Scout ───────────────────────────────────────────────────────────────


class BaseScout(ABC):
    """Abstract base class for all scout agents."""

    scout_type: str

    def __init__(self, llm: LLMClient) -> None:
        self._llm = llm

    @abstractmethod
    async def discover(self) -> list[EvolutionProposal]:
        """Discover evolution proposals. Must be implemented by subclasses."""

    # ── Shared helpers ────────────────────────────────────────────────────

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse a JSON string, handling markdown code fences.

        Returns an empty dict if parsing fails.
        """
        cleaned = text.strip()
        # Strip markdown fences: ```json ... ``` or ``` ... ```
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {}

    def _parse_proposals(self, text: str) -> list[EvolutionProposal]:
        """Parse LLM JSON response into EvolutionProposal objects.

        Returns an empty list if the response cannot be parsed.
        Caps results at MAX_PROPOSALS_PER_SCOUT.
        """
        data = self._parse_json(text)
        raw_proposals = data.get("proposals", [])
        if not isinstance(raw_proposals, list):
            return []

        results: list[EvolutionProposal] = []
        for raw in raw_proposals[:MAX_PROPOSALS_PER_SCOUT]:
            if not isinstance(raw, dict):
                continue
            try:
                proposal = EvolutionProposal(
                    scout_type=self.scout_type,
                    description=raw.get("description", ""),
                    target_type=raw.get("target_type", "unknown"),
                    target_id=raw.get("target_id"),
                    impact_score=_clamp(raw.get("impact_score", 0.0)),
                    effort_score=_clamp(raw.get("effort_score", 0.0)),
                    risk_score=_clamp(raw.get("risk_score", 0.0)),
                )
                results.append(proposal)
            except Exception:
                logger.warning("Skipping invalid proposal: %s", raw, exc_info=True)
                continue
        return results


def _clamp(value: float, lo: float = 0.0, hi: float = 1.0) -> float:
    """Clamp a value between lo and hi."""
    try:
        return max(lo, min(hi, float(value)))
    except (TypeError, ValueError):
        return 0.0


# ── Tool Scout ───────────────────────────────────────────────────────────────


class ToolScout(BaseScout):
    """Discovers tool configuration and prompt improvements based on metrics."""

    scout_type = "tool"

    def __init__(
        self,
        llm: LLMClient,
        metrics: MetricCollector,
        evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._metrics = metrics
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        """Get tool configs and metric baselines, ask LLM for improvement proposals."""
        try:
            tool_configs = await self._evo_store.get_all_tool_configs()
            baselines: dict[str, float] = {}
            for metric_name in ("audit_score", "audit_duration_seconds"):
                baseline = await self._metrics.get_baseline(metric_name)
                if baseline is not None:
                    baselines[metric_name] = baseline.mean

            prompt_text = TOOL_SCOUT_PROMPT.format(
                max=MAX_PROPOSALS_PER_SCOUT,
                tool_configs=json.dumps(tool_configs, indent=2),
                baselines=json.dumps(baselines, indent=2),
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.error("ToolScout.discover failed", exc_info=True)
            return []


# ── Pattern Scout ────────────────────────────────────────────────────────────


class PatternScout(BaseScout):
    """Discovers prompt improvements by analyzing quality patterns."""

    scout_type = "pattern"

    def __init__(
        self,
        llm: LLMClient,
        quality_store: QualityStore,
        evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._quality_store = quality_store
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        """Get quality patterns and prompts, ask LLM for improvement proposals."""
        try:
            patterns = await self._quality_store.get_patterns()
            prompts = await self._evo_store.get_all_prompts()
            pulse = await self._quality_store.get_quality_pulse()

            patterns_summary = [
                {"pattern": p.get("pattern", ""), "count": p.get("reinforcement_count", 0)}
                for p in patterns[:10]
            ]

            prompt_text = PATTERN_SCOUT_PROMPT.format(
                max=MAX_PROPOSALS_PER_SCOUT,
                patterns=json.dumps(patterns_summary, indent=2),
                prompts=json.dumps(prompts, indent=2),
                pulse=json.dumps(pulse, indent=2),
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.error("PatternScout.discover failed", exc_info=True)
            return []


# ── Quality Scout ────────────────────────────────────────────────────────────


class QualityScout(BaseScout):
    """Discovers improvements by analyzing recurring failure patterns."""

    scout_type = "quality"

    def __init__(
        self,
        llm: LLMClient,
        quality_store: QualityStore,
        evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._quality_store = quality_store
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        """Get quality rules, pulse, and prompts; ask LLM for failure-reducing proposals."""
        try:
            rules = await self._quality_store.get_active_rules()
            pulse = await self._quality_store.get_quality_pulse()
            prompts = await self._evo_store.get_all_prompts()

            rules_summary = [
                {"rule": r.get("rule", ""), "category": r.get("category", "")}
                for r in rules[:10]
            ]

            prompt_text = QUALITY_SCOUT_PROMPT.format(
                max=MAX_PROPOSALS_PER_SCOUT,
                rules=json.dumps(rules_summary, indent=2),
                pulse=json.dumps(pulse, indent=2),
                prompts=json.dumps(prompts, indent=2),
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.error("QualityScout.discover failed", exc_info=True)
            return []


# ── Ecosystem Scout ──────────────────────────────────────────────────────────


class EcosystemScout(BaseScout):
    """Discovers cross-cutting optimizations across tools and prompts."""

    scout_type = "ecosystem"

    def __init__(
        self,
        llm: LLMClient,
        evo_store: EvolutionStore,
    ) -> None:
        super().__init__(llm)
        self._evo_store = evo_store

    async def discover(self) -> list[EvolutionProposal]:
        """Get tool configs and prompts, ask LLM for ecosystem optimization proposals."""
        try:
            tool_configs = await self._evo_store.get_all_tool_configs()
            prompts = await self._evo_store.get_all_prompts()

            prompt_text = ECOSYSTEM_SCOUT_PROMPT.format(
                max=MAX_PROPOSALS_PER_SCOUT,
                tool_configs=json.dumps(tool_configs, indent=2),
                prompts=json.dumps(prompts, indent=2),
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )
            return self._parse_proposals(response.text)
        except Exception:
            logger.error("EcosystemScout.discover failed", exc_info=True)
            return []
