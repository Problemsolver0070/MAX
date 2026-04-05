"""EvolutionStore -- async CRUD for all evolution system tables."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database

logger = logging.getLogger(__name__)


class EvolutionStore:
    """Persistence layer for the Phase 7 Evolution System.

    Manages proposals, snapshots, prompts, tool configs, journal,
    preference profiles, capability map, failure taxonomy, and
    confidence calibration.
    """

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Proposals ──────────────────────────────────────────────────────

    async def create_proposal(self, proposal: dict[str, Any]) -> None:
        """Insert an evolution proposal."""
        await self._db.execute(
            "INSERT INTO evolution_proposals "
            "(id, scout_type, description, target_type, target_id, "
            "impact_score, effort_score, risk_score, priority, status, experiment_id) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11)",
            proposal["id"],
            proposal["scout_type"],
            proposal["description"],
            proposal["target_type"],
            proposal.get("target_id"),
            proposal.get("impact_score", 0.0),
            proposal.get("effort_score", 0.0),
            proposal.get("risk_score", 0.0),
            proposal.get("priority", 0.0),
            proposal.get("status", "proposed"),
            proposal.get("experiment_id"),
        )

    async def get_proposals(
        self, status: str | None = None
    ) -> list[dict[str, Any]]:
        """Get proposals, optionally filtered by status."""
        if status:
            return await self._db.fetchall(
                "SELECT * FROM evolution_proposals WHERE status = $1 "
                "ORDER BY priority DESC",
                status,
            )
        return await self._db.fetchall(
            "SELECT * FROM evolution_proposals ORDER BY priority DESC"
        )

    async def update_proposal_status(
        self,
        proposal_id: uuid.UUID,
        status: str,
        experiment_id: uuid.UUID | None = None,
    ) -> None:
        """Update the status (and optionally experiment_id) of a proposal."""
        if experiment_id is not None:
            await self._db.execute(
                "UPDATE evolution_proposals "
                "SET status = $1, experiment_id = $2 WHERE id = $3",
                status,
                experiment_id,
                proposal_id,
            )
        else:
            await self._db.execute(
                "UPDATE evolution_proposals SET status = $1 WHERE id = $2",
                status,
                proposal_id,
            )

    # ── Snapshots ──────────────────────────────────────────────────────

    async def create_snapshot(
        self, experiment_id: uuid.UUID, data: dict[str, Any]
    ) -> uuid.UUID:
        """Create a snapshot of system state before an experiment.

        Returns the snapshot UUID.
        """
        snap_id = uuid.uuid4()
        metrics_baseline = data.get("metrics_baseline", {})
        await self._db.execute(
            "INSERT INTO evolution_snapshots "
            "(id, experiment_id, snapshot_data, metrics_baseline) "
            "VALUES ($1, $2, $3::jsonb, $4::jsonb)",
            snap_id,
            experiment_id,
            json.dumps(data),
            json.dumps(metrics_baseline),
        )
        return snap_id

    async def get_snapshot(
        self, experiment_id: uuid.UUID
    ) -> dict[str, Any] | None:
        """Get the snapshot for an experiment."""
        return await self._db.fetchone(
            "SELECT * FROM evolution_snapshots WHERE experiment_id = $1",
            experiment_id,
        )

    # ── Prompts ────────────────────────────────────────────────────────

    async def set_prompt(
        self,
        agent_type: str,
        text: str,
        experiment_id: uuid.UUID | None = None,
    ) -> None:
        """Upsert a prompt for an agent type.

        When experiment_id is None, this is a live prompt (uses ON CONFLICT
        on the partial unique index). When experiment_id is set, this is a
        candidate prompt for an experiment.
        """
        if experiment_id is None:
            await self._db.execute(
                "INSERT INTO evolution_prompts (id, agent_type, prompt_text) "
                "VALUES ($1, $2, $3) "
                "ON CONFLICT (agent_type) WHERE experiment_id IS NULL "
                "DO UPDATE SET prompt_text = EXCLUDED.prompt_text, "
                "version = evolution_prompts.version + 1, "
                "updated_at = NOW()",
                uuid.uuid4(),
                agent_type,
                text,
            )
        else:
            await self._db.execute(
                "INSERT INTO evolution_prompts "
                "(id, agent_type, prompt_text, experiment_id) "
                "VALUES ($1, $2, $3, $4)",
                uuid.uuid4(),
                agent_type,
                text,
                experiment_id,
            )

    async def get_prompt(
        self,
        agent_type: str,
        experiment_id: uuid.UUID | None = None,
    ) -> str | None:
        """Get a prompt for an agent type.

        If experiment_id is given, returns the candidate prompt;
        otherwise returns the live prompt.
        """
        if experiment_id is None:
            row = await self._db.fetchone(
                "SELECT prompt_text FROM evolution_prompts "
                "WHERE agent_type = $1 AND experiment_id IS NULL",
                agent_type,
            )
        else:
            row = await self._db.fetchone(
                "SELECT prompt_text FROM evolution_prompts "
                "WHERE agent_type = $1 AND experiment_id = $2",
                agent_type,
                experiment_id,
            )
        return row["prompt_text"] if row else None

    async def get_all_prompts(
        self, experiment_id: uuid.UUID | None = None
    ) -> dict[str, str]:
        """Get all prompts, keyed by agent_type.

        If experiment_id is None, returns live prompts; otherwise candidates.
        """
        if experiment_id is None:
            rows = await self._db.fetchall(
                "SELECT agent_type, prompt_text FROM evolution_prompts "
                "WHERE experiment_id IS NULL"
            )
        else:
            rows = await self._db.fetchall(
                "SELECT agent_type, prompt_text FROM evolution_prompts "
                "WHERE experiment_id = $1",
                experiment_id,
            )
        return {r["agent_type"]: r["prompt_text"] for r in rows}

    # ── Tool Configs ───────────────────────────────────────────────────

    async def set_tool_config(
        self,
        tool_id: str,
        config: dict[str, Any],
        experiment_id: uuid.UUID | None = None,
    ) -> None:
        """Upsert a tool config.

        When experiment_id is None, this is a live config (uses ON CONFLICT
        on the partial unique index). When experiment_id is set, this is a
        candidate config for an experiment.
        """
        if experiment_id is None:
            await self._db.execute(
                "INSERT INTO evolution_tool_configs (id, tool_id, config) "
                "VALUES ($1, $2, $3::jsonb) "
                "ON CONFLICT (tool_id) WHERE experiment_id IS NULL "
                "DO UPDATE SET config = EXCLUDED.config, "
                "version = evolution_tool_configs.version + 1, "
                "updated_at = NOW()",
                uuid.uuid4(),
                tool_id,
                json.dumps(config),
            )
        else:
            await self._db.execute(
                "INSERT INTO evolution_tool_configs "
                "(id, tool_id, config, experiment_id) "
                "VALUES ($1, $2, $3::jsonb, $4)",
                uuid.uuid4(),
                tool_id,
                json.dumps(config),
                experiment_id,
            )

    async def get_tool_config(
        self,
        tool_id: str,
        experiment_id: uuid.UUID | None = None,
    ) -> dict[str, Any] | None:
        """Get a tool config by tool_id."""
        if experiment_id is None:
            row = await self._db.fetchone(
                "SELECT config FROM evolution_tool_configs "
                "WHERE tool_id = $1 AND experiment_id IS NULL",
                tool_id,
            )
        else:
            row = await self._db.fetchone(
                "SELECT config FROM evolution_tool_configs "
                "WHERE tool_id = $1 AND experiment_id = $2",
                tool_id,
                experiment_id,
            )
        return row["config"] if row else None

    async def get_all_tool_configs(
        self, experiment_id: uuid.UUID | None = None
    ) -> dict[str, dict[str, Any]]:
        """Get all tool configs, keyed by tool_id."""
        if experiment_id is None:
            rows = await self._db.fetchall(
                "SELECT tool_id, config FROM evolution_tool_configs "
                "WHERE experiment_id IS NULL"
            )
        else:
            rows = await self._db.fetchall(
                "SELECT tool_id, config FROM evolution_tool_configs "
                "WHERE experiment_id = $1",
                experiment_id,
            )
        return {r["tool_id"]: r["config"] for r in rows}

    # ── Promote / Discard ──────────────────────────────────────────────

    async def promote_candidates(self, experiment_id: uuid.UUID) -> None:
        """Promote candidate prompts and tool configs to live.

        Deletes old live rows that have candidates, then updates
        the candidate rows to become live (experiment_id = NULL).
        """
        # Find candidate prompts for this experiment
        candidate_prompts = await self._db.fetchall(
            "SELECT agent_type FROM evolution_prompts "
            "WHERE experiment_id = $1",
            experiment_id,
        )
        if candidate_prompts:
            agent_types = [r["agent_type"] for r in candidate_prompts]
            # Delete old live prompts that have candidates
            for at in agent_types:
                await self._db.execute(
                    "DELETE FROM evolution_prompts "
                    "WHERE agent_type = $1 AND experiment_id IS NULL",
                    at,
                )
            # Promote candidates to live
            await self._db.execute(
                "UPDATE evolution_prompts "
                "SET experiment_id = NULL, updated_at = NOW() "
                "WHERE experiment_id = $1",
                experiment_id,
            )

        # Find candidate tool configs for this experiment
        candidate_configs = await self._db.fetchall(
            "SELECT tool_id FROM evolution_tool_configs "
            "WHERE experiment_id = $1",
            experiment_id,
        )
        if candidate_configs:
            tool_ids = [r["tool_id"] for r in candidate_configs]
            # Delete old live configs that have candidates
            for tid in tool_ids:
                await self._db.execute(
                    "DELETE FROM evolution_tool_configs "
                    "WHERE tool_id = $1 AND experiment_id IS NULL",
                    tid,
                )
            # Promote candidates to live
            await self._db.execute(
                "UPDATE evolution_tool_configs "
                "SET experiment_id = NULL, updated_at = NOW() "
                "WHERE experiment_id = $1",
                experiment_id,
            )

    async def discard_candidates(self, experiment_id: uuid.UUID) -> None:
        """Delete all candidate prompts and tool configs for an experiment."""
        await self._db.execute(
            "DELETE FROM evolution_prompts WHERE experiment_id = $1",
            experiment_id,
        )
        await self._db.execute(
            "DELETE FROM evolution_tool_configs WHERE experiment_id = $1",
            experiment_id,
        )

    # ── Journal ────────────────────────────────────────────────────────

    async def record_journal(self, entry: dict[str, Any]) -> None:
        """Record an evolution journal entry."""
        await self._db.execute(
            "INSERT INTO evolution_journal "
            "(id, experiment_id, action, details) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            uuid.uuid4(),
            entry.get("experiment_id"),
            entry["action"],
            json.dumps(entry.get("details", {})),
        )

    async def get_journal(
        self,
        limit: int = 50,
        experiment_id: uuid.UUID | None = None,
    ) -> list[dict[str, Any]]:
        """Get journal entries, optionally filtered by experiment."""
        if experiment_id is not None:
            return await self._db.fetchall(
                "SELECT * FROM evolution_journal "
                "WHERE experiment_id = $1 ORDER BY recorded_at DESC LIMIT $2",
                experiment_id,
                limit,
            )
        return await self._db.fetchall(
            "SELECT * FROM evolution_journal "
            "ORDER BY recorded_at DESC LIMIT $1",
            limit,
        )

    # ── Preference Profiles ────────────────────────────────────────────

    async def save_preference_profile(
        self,
        user_id: str,
        communication: dict[str, Any],
        code_prefs: dict[str, Any],
        workflow: dict[str, Any],
        domain_knowledge: dict[str, Any],
        observation_log: list[dict[str, Any]],
    ) -> None:
        """Upsert a user preference profile."""
        await self._db.execute(
            "INSERT INTO preference_profiles "
            "(id, user_id, communication, code_prefs, workflow, "
            "domain_knowledge, observation_log) "
            "VALUES ($1, $2, $3::jsonb, $4::jsonb, $5::jsonb, $6::jsonb, $7::jsonb) "
            "ON CONFLICT (user_id) DO UPDATE SET "
            "communication = EXCLUDED.communication, "
            "code_prefs = EXCLUDED.code_prefs, "
            "workflow = EXCLUDED.workflow, "
            "domain_knowledge = EXCLUDED.domain_knowledge, "
            "observation_log = EXCLUDED.observation_log, "
            "version = preference_profiles.version + 1, "
            "updated_at = NOW()",
            uuid.uuid4(),
            user_id,
            json.dumps(communication),
            json.dumps(code_prefs),
            json.dumps(workflow),
            json.dumps(domain_knowledge),
            json.dumps(observation_log),
        )

    async def get_preference_profile(
        self, user_id: str
    ) -> dict[str, Any] | None:
        """Get a user's preference profile."""
        return await self._db.fetchone(
            "SELECT * FROM preference_profiles WHERE user_id = $1",
            user_id,
        )

    # ── Capability Map ─────────────────────────────────────────────────

    async def upsert_capability(
        self,
        domain: str,
        task_type: str,
        score: float,
        sample_count: int = 1,
    ) -> None:
        """Upsert a capability score for a domain/task_type pair."""
        await self._db.execute(
            "INSERT INTO capability_map (id, domain, task_type, score, sample_count) "
            "VALUES ($1, $2, $3, $4, $5) "
            "ON CONFLICT (domain, task_type) DO UPDATE SET "
            "score = EXCLUDED.score, "
            "sample_count = EXCLUDED.sample_count, "
            "updated_at = NOW()",
            uuid.uuid4(),
            domain,
            task_type,
            score,
            sample_count,
        )

    async def get_capability_map(self) -> dict[str, dict[str, float]]:
        """Get the full capability map as {domain: {task_type: score}}."""
        rows = await self._db.fetchall(
            "SELECT domain, task_type, score FROM capability_map "
            "ORDER BY domain, task_type"
        )
        result: dict[str, dict[str, float]] = {}
        for r in rows:
            result.setdefault(r["domain"], {})[r["task_type"]] = r["score"]
        return result

    # ── Failure Taxonomy ───────────────────────────────────────────────

    async def record_failure(
        self,
        category: str,
        subcategory: str,
        details: dict[str, Any],
        source_task_id: uuid.UUID | None = None,
    ) -> None:
        """Record a failure in the taxonomy."""
        await self._db.execute(
            "INSERT INTO failure_taxonomy "
            "(id, category, subcategory, details, source_task_id) "
            "VALUES ($1, $2, $3, $4::jsonb, $5)",
            uuid.uuid4(),
            category,
            subcategory,
            json.dumps(details),
            source_task_id,
        )

    async def get_failure_counts(self) -> dict[str, int]:
        """Get failure counts grouped by category."""
        rows = await self._db.fetchall(
            "SELECT category, COUNT(*) AS count FROM failure_taxonomy "
            "GROUP BY category ORDER BY count DESC"
        )
        return {r["category"]: r["count"] for r in rows}

    # ── Confidence Calibration ─────────────────────────────────────────

    async def record_prediction(
        self,
        predicted: float,
        actual: float,
        task_type: str | None = None,
    ) -> None:
        """Record a predicted vs actual score for calibration tracking."""
        await self._db.execute(
            "INSERT INTO confidence_calibration "
            "(id, predicted_score, actual_score, task_type) "
            "VALUES ($1, $2, $3, $4)",
            uuid.uuid4(),
            predicted,
            actual,
            task_type,
        )

    async def get_calibration_error(self, limit: int = 100) -> float:
        """Compute mean absolute error over recent predictions.

        Returns 0.0 when there are no calibration records.
        """
        rows = await self._db.fetchall(
            "SELECT predicted_score, actual_score FROM confidence_calibration "
            "ORDER BY recorded_at DESC LIMIT $1",
            limit,
        )
        if not rows:
            return 0.0
        total = sum(abs(r["predicted_score"] - r["actual_score"]) for r in rows)
        return total / len(rows)

    # ── Quality Ledger ─────────────────────────────────────────────────

    async def record_to_ledger(
        self, entry_type: str, content: dict[str, Any]
    ) -> None:
        """Write an entry to the existing quality_ledger table."""
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) "
            "VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            entry_type,
            json.dumps(content),
        )
