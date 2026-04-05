"""Tests for QualityStore -- async CRUD for audit reports, ledger, rules, patterns."""

import uuid
from unittest.mock import AsyncMock

import pytest

from max.models.tasks import AuditVerdict
from max.quality.store import QualityStore


@pytest.fixture
def mock_db():
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchone = AsyncMock(return_value=None)
    db.fetchall = AsyncMock(return_value=[])
    return db


@pytest.fixture
def store(mock_db):
    return QualityStore(mock_db)


class TestCreateAuditReport:
    @pytest.mark.asyncio
    async def test_inserts_report(self, store, mock_db):
        report_id = uuid.uuid4()
        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()
        await store.create_audit_report(
            report_id=report_id,
            task_id=task_id,
            subtask_id=subtask_id,
            verdict=AuditVerdict.PASS,
            score=0.85,
            goal_alignment=0.9,
            confidence=0.95,
            issues=[],
            fix_instructions=None,
            strengths=["Good structure"],
            fix_attempt=0,
        )
        mock_db.execute.assert_called_once()
        call_args = mock_db.execute.call_args
        assert "INSERT INTO audit_reports" in call_args[0][0]


class TestGetAuditReports:
    @pytest.mark.asyncio
    async def test_fetches_by_task_id(self, store, mock_db):
        task_id = uuid.uuid4()
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "task_id": task_id, "verdict": "pass", "score": 0.9}
        ]
        rows = await store.get_audit_reports(task_id)
        assert len(rows) == 1
        mock_db.fetchall.assert_called_once()

    @pytest.mark.asyncio
    async def test_returns_empty_list(self, store, mock_db):
        rows = await store.get_audit_reports(uuid.uuid4())
        assert rows == []


class TestGetAuditReportForSubtask:
    @pytest.mark.asyncio
    async def test_fetches_by_subtask_id(self, store, mock_db):
        subtask_id = uuid.uuid4()
        mock_db.fetchone.return_value = {"id": uuid.uuid4(), "subtask_id": subtask_id}
        row = await store.get_audit_report_for_subtask(subtask_id)
        assert row is not None


class TestRecordVerdict:
    @pytest.mark.asyncio
    async def test_inserts_ledger_entry(self, store, mock_db):
        await store.record_verdict(
            task_id=uuid.uuid4(),
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.PASS,
            score=0.85,
            metadata={"fix_attempt": 0},
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_ledger" in call_args[0][0]
        assert call_args[0][2] == "audit_verdict"


class TestQualityRules:
    @pytest.mark.asyncio
    async def test_create_rule(self, store, mock_db):
        rule_id = uuid.uuid4()
        await store.create_rule(
            rule_id=rule_id,
            rule="Always validate input",
            source="audit-123",
            category="validation",
            severity="normal",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_rules" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_active_rules(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "rule": "Validate input", "category": "validation"}
        ]
        rules = await store.get_active_rules()
        assert len(rules) == 1

    @pytest.mark.asyncio
    async def test_get_active_rules_by_category(self, store, mock_db):
        await store.get_active_rules(category="validation")
        call_args = mock_db.fetchall.call_args
        assert "category = $1" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_supersede_rule(self, store, mock_db):
        old_id = uuid.uuid4()
        new_id = uuid.uuid4()
        await store.supersede_rule(old_id, new_id)
        mock_db.execute.assert_called()
        # Should update old rule AND record in ledger
        assert mock_db.execute.call_count == 2


class TestQualityPatterns:
    @pytest.mark.asyncio
    async def test_create_pattern(self, store, mock_db):
        await store.create_pattern(
            pattern_id=uuid.uuid4(),
            pattern="Use structured logging",
            source_task_id=uuid.uuid4(),
            category="code_quality",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_patterns" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_get_patterns(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "pattern": "test", "reinforcement_count": 3}
        ]
        patterns = await store.get_patterns(min_reinforcement=2)
        assert len(patterns) == 1

    @pytest.mark.asyncio
    async def test_reinforce_pattern(self, store, mock_db):
        pattern_id = uuid.uuid4()
        await store.reinforce_pattern(pattern_id)
        # Should update count AND record in ledger
        assert mock_db.execute.call_count == 2


class TestRecordLedgerEntries:
    @pytest.mark.asyncio
    async def test_record_rule_to_ledger(self, store, mock_db):
        await store.record_rule_to_ledger(
            rule_id=uuid.uuid4(),
            rule="Test rule",
            category="test",
            severity="normal",
            source_audit_id=uuid.uuid4(),
        )
        call_args = mock_db.execute.call_args
        assert call_args[0][2] == "quality_rule_created"

    @pytest.mark.asyncio
    async def test_record_pattern_to_ledger(self, store, mock_db):
        await store.record_pattern_to_ledger(
            pattern_id=uuid.uuid4(),
            pattern="Good pattern",
            category="test",
            source_task_id=uuid.uuid4(),
        )
        call_args = mock_db.execute.call_args
        assert call_args[0][2] == "quality_pattern_created"

    @pytest.mark.asyncio
    async def test_get_ledger_entries(self, store, mock_db):
        mock_db.fetchall.return_value = [
            {"id": uuid.uuid4(), "entry_type": "audit_verdict", "content": "{}"}
        ]
        entries = await store.get_ledger_entries("audit_verdict", limit=50)
        assert len(entries) == 1


class TestRecordFixAttempt:
    @pytest.mark.asyncio
    async def test_inserts_fix_attempt_ledger_entry(self, store, mock_db):
        await store.record_fix_attempt(
            task_id=uuid.uuid4(),
            subtask_id=uuid.uuid4(),
            fix_attempt=1,
            fix_instructions="Fix the output",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_ledger" in call_args[0][0]
        assert call_args[0][2] == "fix_attempt"


class TestRecordUserCorrection:
    @pytest.mark.asyncio
    async def test_inserts_user_correction_ledger_entry(self, store, mock_db):
        await store.record_user_correction(
            task_id=uuid.uuid4(),
            subtask_id=uuid.uuid4(),
            correction="The output should include error handling",
        )
        call_args = mock_db.execute.call_args
        assert "INSERT INTO quality_ledger" in call_args[0][0]
        assert call_args[0][2] == "user_correction"

    @pytest.mark.asyncio
    async def test_includes_metadata(self, store, mock_db):
        await store.record_user_correction(
            task_id=uuid.uuid4(),
            subtask_id=uuid.uuid4(),
            correction="Needs more tests",
            metadata={"source": "telegram"},
        )
        call_args = mock_db.execute.call_args
        import json

        content = json.loads(call_args[0][3])
        assert content["source"] == "telegram"
        assert content["correction"] == "Needs more tests"


class TestGetQualityPulse:
    @pytest.mark.asyncio
    async def test_returns_composite_pulse(self, store, mock_db):
        mock_db.fetchone.side_effect = [
            {"pass_rate": 0.85},  # get_pass_rate
            {"avg_score": 0.78},  # get_avg_score
        ]
        mock_db.fetchall.side_effect = [
            [{"id": uuid.uuid4(), "rule": "test", "category": "v"}],  # get_active_rules
            [  # get_patterns
                {
                    "pattern": "good pattern",
                    "reinforcement_count": 3,
                    "category": "code_quality",
                }
            ],
        ]
        pulse = await store.get_quality_pulse(hours=24)
        assert pulse["pass_rate"] == 0.85
        assert pulse["avg_score"] == 0.78
        assert pulse["active_rules_count"] == 1
        assert len(pulse["top_patterns"]) == 1
        assert pulse["top_patterns"][0]["pattern"] == "good pattern"


class TestQualityMetrics:
    @pytest.mark.asyncio
    async def test_get_pass_rate(self, store, mock_db):
        mock_db.fetchone.return_value = {"pass_rate": 0.85}
        rate = await store.get_pass_rate(hours=24)
        assert rate == 0.85

    @pytest.mark.asyncio
    async def test_get_pass_rate_no_data(self, store, mock_db):
        mock_db.fetchone.return_value = {"pass_rate": None}
        rate = await store.get_pass_rate(hours=24)
        assert rate == 0.0

    @pytest.mark.asyncio
    async def test_get_avg_score(self, store, mock_db):
        mock_db.fetchone.return_value = {"avg_score": 0.78}
        score = await store.get_avg_score(hours=24)
        assert score == 0.78
