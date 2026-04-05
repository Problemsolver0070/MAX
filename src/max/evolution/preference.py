"""PreferenceProfileManager -- learn and apply user preferences over time."""

from __future__ import annotations

import json
import logging
import re
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

from max.evolution.models import (
    CodePrefs,
    CommunicationPrefs,
    DomainPrefs,
    PreferenceProfile,
    WorkflowPrefs,
)

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient

logger = logging.getLogger(__name__)

_MAX_OBSERVATIONS = 500

REFRESH_PROMPT = """\
You are a preference-learning system.  Given the recent observations about
a user's behaviour and preferences, produce an updated preference profile
as a JSON object.

The JSON MUST contain only the following top-level keys (omit any key you
have no signal for):

- "communication": {tone, detail_level, update_frequency, languages, timezone}
- "code": {style, review_depth, test_coverage, commit_style}
- "workflow": {clarification_threshold, autonomy_level, reporting_style}
- "domain_knowledge": {expertise_areas, client_contexts, project_conventions}

Respond ONLY with the JSON object, no explanation.
"""


class PreferenceProfileManager:
    """Tracks per-user preference signals and synthesises preference profiles.

    Signals are raw observations (e.g. "user corrected the tone", "user
    asked for verbose output").  Periodically the manager asks an LLM to
    reinterpret recent observations into structured preferences.
    """

    def __init__(self, store: EvolutionStore, llm: LLMClient) -> None:
        self._store = store
        self._llm = llm

    # ── Public API ─────────────────────────────────────────────────────

    async def record_signal(
        self, user_id: str, signal_type: str, data: dict[str, Any]
    ) -> None:
        """Append an observation to the user's preference profile.

        Creates a default profile if one does not exist.  The observation
        log is capped at ``_MAX_OBSERVATIONS`` (FIFO).
        """
        row = await self._store.get_preference_profile(user_id)

        if row is None:
            communication: dict[str, Any] = {}
            code_prefs: dict[str, Any] = {}
            workflow: dict[str, Any] = {}
            domain_knowledge: dict[str, Any] = {}
            observation_log: list[dict[str, Any]] = []
        else:
            communication = _ensure_dict(row.get("communication", {}))
            code_prefs = _ensure_dict(row.get("code_prefs", {}))
            workflow = _ensure_dict(row.get("workflow", {}))
            domain_knowledge = _ensure_dict(row.get("domain_knowledge", {}))
            observation_log = _ensure_list(row.get("observation_log", []))

        observation_log.append({
            "signal_type": signal_type,
            "data": data,
            "recorded_at": datetime.now(UTC).isoformat(),
        })

        # FIFO cap
        if len(observation_log) > _MAX_OBSERVATIONS:
            observation_log = observation_log[-_MAX_OBSERVATIONS:]

        await self._store.save_preference_profile(
            user_id=user_id,
            communication=communication,
            code_prefs=code_prefs,
            workflow=workflow,
            domain_knowledge=domain_knowledge,
            observation_log=observation_log,
        )

    async def get_profile(self, user_id: str) -> PreferenceProfile:
        """Return the preference profile for *user_id*, or a default."""
        row = await self._store.get_preference_profile(user_id)
        if row is None:
            return PreferenceProfile(user_id=user_id)
        return _row_to_profile(user_id, row)

    async def refresh_profile(self, user_id: str) -> PreferenceProfile:
        """Re-synthesise the preference profile using the LLM.

        If the user has no observations the profile is returned as-is
        without calling the LLM.
        """
        row = await self._store.get_preference_profile(user_id)
        if row is None:
            return PreferenceProfile(user_id=user_id)

        observations = _ensure_list(row.get("observation_log", []))
        if not observations:
            return _row_to_profile(user_id, row)

        # Send recent observations to the LLM for synthesis
        recent = observations[-50:]  # last 50 observations for context window
        messages = [
            {
                "role": "user",
                "content": (
                    f"Here are recent observations:\n{json.dumps(recent, default=str)}\n\n"
                    "Produce the updated preference JSON."
                ),
            }
        ]
        response = await self._llm.complete(
            messages=messages,
            system_prompt=REFRESH_PROMPT,
        )

        parsed = _parse_json(response.text)

        # Build updated sections, merging LLM output with existing data
        communication = _ensure_dict(row.get("communication", {}))
        code_prefs = _ensure_dict(row.get("code_prefs", {}))
        workflow = _ensure_dict(row.get("workflow", {}))
        domain_knowledge = _ensure_dict(row.get("domain_knowledge", {}))

        if "communication" in parsed:
            communication.update(parsed["communication"])
        if "code" in parsed:
            code_prefs.update(parsed["code"])
        if "workflow" in parsed:
            workflow.update(parsed["workflow"])
        if "domain_knowledge" in parsed:
            domain_knowledge.update(parsed["domain_knowledge"])

        await self._store.save_preference_profile(
            user_id=user_id,
            communication=communication,
            code_prefs=code_prefs,
            workflow=workflow,
            domain_knowledge=domain_knowledge,
            observation_log=observations,
        )

        return _row_to_profile(user_id, {
            "communication": communication,
            "code_prefs": code_prefs,
            "workflow": workflow,
            "domain_knowledge": domain_knowledge,
            "observation_log": observations,
        })

    async def get_context_injection(self, user_id: str) -> dict[str, Any]:
        """Return a dict suitable for injecting into agent context."""
        profile = await self.get_profile(user_id)
        return {
            "communication": profile.communication.model_dump(),
            "code": profile.code.model_dump(),
            "workflow": profile.workflow.model_dump(),
            "domain": profile.domain_knowledge.model_dump(),
        }


# ── Helpers ────────────────────────────────────────────────────────────────


def _ensure_dict(value: Any) -> dict[str, Any]:
    """Return *value* as a dict, parsing from JSON string if needed."""
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, dict):
        return value
    return {}


def _ensure_list(value: Any) -> list[dict[str, Any]]:
    """Return *value* as a list, parsing from JSON string if needed."""
    if isinstance(value, str):
        return json.loads(value)
    if isinstance(value, list):
        return value
    return []


def _parse_json(text: str) -> dict[str, Any]:
    """Parse a JSON object from *text*, stripping markdown fences if present."""
    cleaned = re.sub(r"```(?:json)?\s*", "", text)
    cleaned = cleaned.strip()
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        logger.warning("Failed to parse LLM response as JSON: %.200s", text)
        return {}


def _row_to_profile(user_id: str, row: dict[str, Any]) -> PreferenceProfile:
    """Build a PreferenceProfile from a database row (or dict)."""
    communication = _ensure_dict(row.get("communication", {}))
    code_prefs = _ensure_dict(row.get("code_prefs", {}))
    workflow = _ensure_dict(row.get("workflow", {}))
    domain_knowledge = _ensure_dict(row.get("domain_knowledge", {}))
    observations_raw = _ensure_list(row.get("observation_log", []))

    return PreferenceProfile(
        user_id=user_id,
        communication=(
            CommunicationPrefs(**communication) if communication else CommunicationPrefs()
        ),
        code=CodePrefs(**code_prefs) if code_prefs else CodePrefs(),
        workflow=WorkflowPrefs(**workflow) if workflow else WorkflowPrefs(),
        domain_knowledge=DomainPrefs(**domain_knowledge) if domain_knowledge else DomainPrefs(),
        observation_log=observations_raw,
    )
