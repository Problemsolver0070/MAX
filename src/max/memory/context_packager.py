"""LLM-curated context packaging — two-call Opus pipeline."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from typing import Any

from max.llm.client import LLMClient
from max.memory.anchors import AnchorManager
from max.memory.models import (
    ContextAnchor,
    ContextPackage,
    HybridRetrievalQuery,
    RetrievalResult,
)
from max.memory.retrieval import HybridRetriever

logger = logging.getLogger(__name__)

CHARS_PER_TOKEN = 4


class ContextPackager:
    """Builds curated context packages for agents using LLM reasoning."""

    def __init__(
        self,
        llm: LLMClient,
        retriever: HybridRetriever,
        anchor_manager: AnchorManager,
        token_budget: int = 24576,
    ) -> None:
        self._llm = llm
        self._retriever = retriever
        self._anchor_mgr = anchor_manager
        self._token_budget = token_budget

    async def build_package(
        self,
        task_goal: str,
        agent_role: str,
        seed_node_ids: list[uuid_mod.UUID] | None = None,
        agent_state: dict[str, Any] | None = None,
    ) -> ContextPackage:
        """Build a curated context package for an agent.

        1. Fetch all active anchors (always included — they are non-negotiable).
        2. Run hybrid retrieval to gather candidate context items.
        3. Use an LLM call to select which candidates fit the task and budget.
        4. Assemble everything into a ``ContextPackage``.
        """
        # ── Always-included anchors ─────────────────────────────────────────
        anchors = await self._anchor_mgr.list_active()

        for anchor in anchors:
            await self._anchor_mgr.record_access(anchor.id)

        # ── Hybrid retrieval ────────────────────────────────────────────────
        query = HybridRetrievalQuery(
            query_text=task_goal,
            seed_node_ids=seed_node_ids or [],
        )
        candidates = await self._retriever.retrieve(query)

        # ── Budget accounting ───────────────────────────────────────────────
        anchor_tokens = self._estimate_tokens(anchors)
        remaining_budget = self._token_budget - anchor_tokens

        # ── LLM-curated selection ───────────────────────────────────────────
        selected_context: list[RetrievalResult] = []
        reasoning = "No additional context candidates available"

        if candidates and remaining_budget > 0:
            selected_context, reasoning = await self._select_context(
                task_goal, agent_role, candidates, remaining_budget
            )

        # ── Assemble package ────────────────────────────────────────────────
        context_tokens = sum(len(r.content) // CHARS_PER_TOKEN for r in selected_context)
        total_tokens = anchor_tokens + context_tokens

        return ContextPackage(
            task_summary=task_goal,
            anchors=anchors,
            graph_context=[r.model_dump() for r in selected_context if "graph" in r.strategies],
            semantic_matches=[
                r.model_dump()
                for r in selected_context
                if "semantic" in r.strategies or "keyword" in r.strategies
            ],
            agent_state=agent_state or {},
            navigation_hints="",
            token_count=total_tokens,
            budget_remaining=max(0, self._token_budget - total_tokens),
            packaging_reasoning=reasoning,
        )

    # ── Private helpers ─────────────────────────────────────────────────────

    async def _select_context(
        self,
        task_goal: str,
        agent_role: str,
        candidates: list[RetrievalResult],
        budget_tokens: int,
    ) -> tuple[list[RetrievalResult], str]:
        """LLM Call #1: Select which context items to include."""
        candidate_summaries = []
        for i, c in enumerate(candidates):
            preview = c.content[:100]
            if len(c.content) > 100:
                summary = (
                    f"[{i}] type={c.content_type} score={c.rrf_score:.3f} "
                    f"strategies={c.strategies} preview={preview}..."
                )
            else:
                summary = (
                    f"[{i}] type={c.content_type} score={c.rrf_score:.3f} "
                    f"strategies={c.strategies} content={c.content}"
                )
            candidate_summaries.append(summary)

        prompt = (
            f"Task goal: {task_goal}\n"
            f"Agent role: {agent_role}\n"
            f"Token budget for additional context: {budget_tokens}\n\n"
            f"Available context items:\n"
            + "\n".join(candidate_summaries)
            + "\n\nSelect which items to include. Return JSON: "
            '{"selected_ids": [list of indices], "reasoning": "why"}'
        )

        try:
            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt}],
                system_prompt=(
                    "You are a context curation agent. Select the most relevant "
                    "context items for the given task. Be selective — only include "
                    "what the agent will actually need. Return valid JSON."
                ),
            )
            data = json.loads(response.text)
            selected_indices = data.get("selected_ids", [])
            reasoning = data.get("reasoning", "")

            if selected_indices == ["all"]:
                return candidates, reasoning

            selected = [
                candidates[i]
                for i in selected_indices
                if isinstance(i, int) and 0 <= i < len(candidates)
            ]
            return selected, reasoning
        except (json.JSONDecodeError, KeyError, IndexError) as exc:
            logger.warning("Context selection LLM call failed: %s", exc)
            return candidates[:5], f"Fallback selection due to: {exc}"

    @staticmethod
    def _estimate_tokens(anchors: list[ContextAnchor]) -> int:
        """Rough char-based token estimation for anchor content."""
        return sum(len(a.content) // CHARS_PER_TOKEN for a in anchors)
