"""ImprovementAgent -- implement evolution proposals as concrete change sets."""

from __future__ import annotations

import json
import logging
import re
import uuid
from typing import TYPE_CHECKING, Any

from max.evolution.models import ChangeSet, ChangeSetEntry, EvolutionProposal

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

MAX_CHANGES = 5

IMPROVEMENT_PROMPT = """\
You are an improvement agent. Given the evolution proposal below, generate \
concrete changes to implement the proposed improvement.

Proposal:
- Description: {description}
- Target type: {target_type}
- Target ID: {target_id}

Current value:
{current_value}

Generate a JSON object with a "changes" array. Each change must have:
- target_type (str): "prompt" or "tool_config"
- target_id (str): which agent type or tool to change
- new_value: the new prompt text (str) or tool config (object)

Return at most {max} changes. Focus on the highest-impact modifications.
"""


class ImprovementAgent:
    """Takes an EvolutionProposal and produces a ChangeSet with concrete modifications.

    Asks the LLM to generate specific prompt text or tool config changes,
    then writes candidate values to the EvolutionStore for experimentation.
    """

    def __init__(self, llm: LLMClient, store: EvolutionStore) -> None:
        self._llm = llm
        self._store = store

    async def implement(self, proposal: EvolutionProposal) -> ChangeSet:
        """Implement a proposal by generating and writing candidate changes.

        Returns a ChangeSet (possibly empty on error). Never raises.
        """
        experiment_id = uuid.uuid4()
        try:
            current_value = await self._get_current_value(
                proposal.target_type, proposal.target_id or ""
            )
            prompt_text = IMPROVEMENT_PROMPT.format(
                description=proposal.description,
                target_type=proposal.target_type,
                target_id=proposal.target_id or "N/A",
                current_value=_format_value(current_value),
                max=MAX_CHANGES,
            )

            response = await self._llm.complete(
                messages=[{"role": "user", "content": prompt_text}],
            )

            data = self._parse_json(response.text)
            raw_changes = data.get("changes", [])
            if not isinstance(raw_changes, list):
                return ChangeSet(proposal_id=proposal.id, entries=[])

            entries: list[ChangeSetEntry] = []
            for raw in raw_changes[:MAX_CHANGES]:
                if not isinstance(raw, dict):
                    continue
                target_type = raw.get("target_type", "")
                target_id = raw.get("target_id", "")
                new_value = raw.get("new_value")

                old_value = await self._get_current_value(target_type, target_id)

                entry = ChangeSetEntry(
                    target_type=target_type,
                    target_id=target_id,
                    old_value=old_value,
                    new_value=new_value,
                )
                entries.append(entry)

                await self._apply_candidate(entry, experiment_id)

            return ChangeSet(proposal_id=proposal.id, entries=entries)

        except Exception:
            logger.error(
                "ImprovementAgent.implement failed for proposal %s",
                proposal.id,
                exc_info=True,
            )
            return ChangeSet(proposal_id=proposal.id, entries=[])

    async def _get_current_value(
        self, target_type: str, target_id: str
    ) -> Any:
        """Get the current value for a target from the store."""
        if target_type == "prompt":
            return await self._store.get_prompt(target_id)
        elif target_type == "tool_config":
            return await self._store.get_tool_config(target_id)
        return None

    async def _apply_candidate(
        self, entry: ChangeSetEntry, experiment_id: uuid.UUID
    ) -> None:
        """Write a candidate value to the store under the experiment_id."""
        if entry.target_type == "prompt":
            await self._store.set_prompt(
                entry.target_id, entry.new_value, experiment_id
            )
        elif entry.target_type == "tool_config":
            config = entry.new_value if isinstance(entry.new_value, dict) else {}
            await self._store.set_tool_config(
                entry.target_id, config, experiment_id
            )

    @staticmethod
    def _parse_json(text: str) -> dict[str, Any]:
        """Parse a JSON string, handling markdown code fences.

        Returns an empty dict if parsing fails.
        """
        cleaned = text.strip()
        fence_match = re.search(r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL)
        if fence_match:
            cleaned = fence_match.group(1).strip()
        try:
            return json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            return {}


def _format_value(value: Any) -> str:
    """Format a value for inclusion in an LLM prompt."""
    if value is None:
        return "(not set)"
    if isinstance(value, dict):
        return json.dumps(value, indent=2)
    return str(value)
