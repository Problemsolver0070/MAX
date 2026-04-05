"""QualityStore -- async CRUD for audit reports, quality ledger, rules, patterns."""

from __future__ import annotations

import json
import logging
import uuid
from typing import Any

from max.db.postgres import Database
from max.models.tasks import AuditVerdict

logger = logging.getLogger(__name__)


class QualityStore:
    """Persistence layer for Quality Gate operations."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Audit Reports ───────────────────────────────────────────────────

    async def create_audit_report(
        self,
        report_id: uuid.UUID,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        verdict: AuditVerdict,
        score: float,
        goal_alignment: float,
        confidence: float,
        issues: list[dict[str, str]],
        fix_instructions: str | None = None,
        strengths: list[str] | None = None,
        fix_attempt: int = 0,
    ) -> None:
        """Insert an audit report."""
        await self._db.execute(
            "INSERT INTO audit_reports "
            "(id, task_id, subtask_id, verdict, score, goal_alignment, confidence, "
            "issues, fix_instructions, strengths, fix_attempt) "
            "VALUES ($1, $2, $3, $4, $5, $6, $7, $8::jsonb, $9, $10::jsonb, $11)",
            report_id,
            task_id,
            subtask_id,
            verdict.value,
            score,
            goal_alignment,
            confidence,
            json.dumps(issues),
            fix_instructions,
            json.dumps(strengths or []),
            fix_attempt,
        )

    async def get_audit_reports(self, task_id: uuid.UUID) -> list[dict[str, Any]]:
        """Get all audit reports for a task."""
        return await self._db.fetchall(
            "SELECT * FROM audit_reports WHERE task_id = $1 ORDER BY created_at DESC",
            task_id,
        )

    async def get_audit_report_for_subtask(self, subtask_id: uuid.UUID) -> dict[str, Any] | None:
        """Get the most recent audit report for a subtask."""
        return await self._db.fetchone(
            "SELECT * FROM audit_reports WHERE subtask_id = $1 ORDER BY created_at DESC LIMIT 1",
            subtask_id,
        )

    # ── Quality Ledger (append-only) ────────────────────────────────────

    async def record_verdict(
        self,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        verdict: AuditVerdict,
        score: float,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record an audit verdict in the quality ledger."""
        content = {
            "task_id": str(task_id),
            "subtask_id": str(subtask_id),
            "verdict": verdict.value,
            "score": score,
            **(metadata or {}),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "audit_verdict",
            json.dumps(content),
        )

    async def record_rule_to_ledger(
        self,
        rule_id: uuid.UUID,
        rule: str,
        category: str,
        severity: str,
        source_audit_id: uuid.UUID,
    ) -> None:
        """Record a quality rule creation in the ledger."""
        content = {
            "rule_id": str(rule_id),
            "rule": rule,
            "category": category,
            "severity": severity,
            "source_audit_id": str(source_audit_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_rule_created",
            json.dumps(content),
        )

    async def record_pattern_to_ledger(
        self,
        pattern_id: uuid.UUID,
        pattern: str,
        category: str,
        source_task_id: uuid.UUID,
    ) -> None:
        """Record a quality pattern creation in the ledger."""
        content = {
            "pattern_id": str(pattern_id),
            "pattern": pattern,
            "category": category,
            "source_task_id": str(source_task_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_pattern_created",
            json.dumps(content),
        )

    async def record_fix_attempt(
        self,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        fix_attempt: int,
        fix_instructions: str,
    ) -> None:
        """Record a fix attempt in the quality ledger."""
        content = {
            "task_id": str(task_id),
            "subtask_id": str(subtask_id),
            "fix_attempt": fix_attempt,
            "fix_instructions": fix_instructions,
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "fix_attempt",
            json.dumps(content),
        )

    async def get_ledger_entries(self, entry_type: str, limit: int = 100) -> list[dict[str, Any]]:
        """Get ledger entries by type."""
        return await self._db.fetchall(
            "SELECT * FROM quality_ledger WHERE entry_type = $1 ORDER BY created_at DESC LIMIT $2",
            entry_type,
            limit,
        )

    # ── Quality Rules ───────────────────────────────────────────────────

    async def create_rule(
        self,
        rule_id: uuid.UUID,
        rule: str,
        source: str,
        category: str,
        severity: str = "normal",
    ) -> None:
        """Insert a quality rule."""
        await self._db.execute(
            "INSERT INTO quality_rules (id, rule, source, category, severity) "
            "VALUES ($1, $2, $3, $4, $5)",
            rule_id,
            rule,
            source,
            category,
            severity,
        )

    async def get_active_rules(self, category: str | None = None) -> list[dict[str, Any]]:
        """Get all non-superseded quality rules."""
        if category:
            return await self._db.fetchall(
                "SELECT * FROM quality_rules WHERE superseded_by IS NULL "
                "AND category = $1 ORDER BY created_at DESC",
                category,
            )
        return await self._db.fetchall(
            "SELECT * FROM quality_rules WHERE superseded_by IS NULL ORDER BY created_at DESC"
        )

    async def supersede_rule(self, old_rule_id: uuid.UUID, new_rule_id: uuid.UUID) -> None:
        """Mark an old rule as superseded by a new one."""
        await self._db.execute(
            "UPDATE quality_rules SET superseded_by = $1 WHERE id = $2",
            new_rule_id,
            old_rule_id,
        )
        # Record in ledger
        content = {
            "old_rule_id": str(old_rule_id),
            "new_rule_id": str(new_rule_id),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_rule_superseded",
            json.dumps(content),
        )

    # ── Quality Patterns ────────────────────────────────────────────────

    async def create_pattern(
        self,
        pattern_id: uuid.UUID,
        pattern: str,
        source_task_id: uuid.UUID,
        category: str,
    ) -> None:
        """Insert a quality pattern."""
        await self._db.execute(
            "INSERT INTO quality_patterns (id, pattern, source_task_id, category) "
            "VALUES ($1, $2, $3, $4)",
            pattern_id,
            pattern,
            source_task_id,
            category,
        )

    async def get_patterns(
        self, category: str | None = None, min_reinforcement: int = 1
    ) -> list[dict[str, Any]]:
        """Get quality patterns filtered by category and minimum reinforcement."""
        if category:
            return await self._db.fetchall(
                "SELECT * FROM quality_patterns "
                "WHERE category = $1 AND reinforcement_count >= $2 "
                "ORDER BY reinforcement_count DESC",
                category,
                min_reinforcement,
            )
        return await self._db.fetchall(
            "SELECT * FROM quality_patterns WHERE reinforcement_count >= $1 "
            "ORDER BY reinforcement_count DESC",
            min_reinforcement,
        )

    async def reinforce_pattern(self, pattern_id: uuid.UUID) -> None:
        """Increment a pattern's reinforcement count."""
        await self._db.execute(
            "UPDATE quality_patterns SET reinforcement_count = reinforcement_count + 1 "
            "WHERE id = $1",
            pattern_id,
        )
        # Record in ledger
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "quality_pattern_reinforced",
            json.dumps({"pattern_id": str(pattern_id)}),
        )

    # ── User Corrections (Phase 6 integration point) ─────────────────────

    async def record_user_correction(
        self,
        task_id: uuid.UUID,
        subtask_id: uuid.UUID,
        correction: str,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Record a user correction for future quality rule refinement.

        Stub for Phase 6 user feedback integration. Records the correction
        to the quality ledger so the rule engine can learn from user feedback.
        """
        content = {
            "task_id": str(task_id),
            "subtask_id": str(subtask_id),
            "correction": correction,
            **(metadata or {}),
        }
        await self._db.execute(
            "INSERT INTO quality_ledger (id, entry_type, content) VALUES ($1, $2, $3::jsonb)",
            uuid.uuid4(),
            "user_correction",
            json.dumps(content),
        )

    # ── Metrics ─────────────────────────────────────────────────────────

    async def get_pass_rate(self, hours: int = 24) -> float:
        """Get the audit pass rate over the given window."""
        row = await self._db.fetchone(
            "SELECT AVG(CASE WHEN verdict = 'pass' THEN 1.0 ELSE 0.0 END) AS pass_rate "
            "FROM audit_reports WHERE created_at > NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return float(row["pass_rate"]) if row and row["pass_rate"] is not None else 0.0

    async def get_quality_pulse(self, hours: int = 24) -> dict[str, Any]:
        """Get a composite quality pulse snapshot.

        Returns pass_rate, avg_score, active_rules_count, and top_patterns
        in a single method call for coordinator state updates.
        """
        pass_rate = await self.get_pass_rate(hours=hours)
        avg_score = await self.get_avg_score(hours=hours)
        active_rules = await self.get_active_rules()
        top_patterns = await self.get_patterns(min_reinforcement=2)
        return {
            "pass_rate": pass_rate,
            "avg_score": avg_score,
            "active_rules_count": len(active_rules),
            "top_patterns": [
                {"pattern": p["pattern"], "reinforcement_count": p["reinforcement_count"]}
                for p in top_patterns[:5]
            ],
        }

    async def get_avg_score(self, hours: int = 24) -> float:
        """Get the average audit score over the given window."""
        row = await self._db.fetchone(
            "SELECT AVG(score) AS avg_score FROM audit_reports "
            "WHERE created_at > NOW() - INTERVAL '1 hour' * $1",
            hours,
        )
        return float(row["avg_score"]) if row and row["avg_score"] is not None else 0.0
