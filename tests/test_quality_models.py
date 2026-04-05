"""Tests for Phase 5 Quality Gate models."""

import uuid

import pytest
from pydantic import ValidationError

from max.models.tasks import AuditVerdict
from max.quality.models import (
    AuditRequest,
    AuditResponse,
    FixInstruction,
    QualityPattern,
    SubtaskAuditItem,
    SubtaskVerdict,
)


class TestQualityPattern:
    def test_create_with_defaults(self):
        p = QualityPattern(
            pattern="Use structured logging",
            source_task_id=uuid.uuid4(),
            category="code_quality",
        )
        assert p.reinforcement_count == 1
        assert p.id is not None
        assert p.created_at is not None

    def test_create_with_custom_reinforcement(self):
        p = QualityPattern(
            pattern="Test pattern",
            source_task_id=uuid.uuid4(),
            category="research",
            reinforcement_count=5,
        )
        assert p.reinforcement_count == 5


class TestSubtaskAuditItem:
    def test_create_minimal(self):
        item = SubtaskAuditItem(
            subtask_id=uuid.uuid4(),
            description="Write a summary",
            content="Here is my summary...",
        )
        assert item.quality_criteria == {}

    def test_no_reasoning_field(self):
        """SubtaskAuditItem should NOT have reasoning/confidence fields (blind audit)."""
        item = SubtaskAuditItem(
            subtask_id=uuid.uuid4(),
            description="test",
            content="output",
        )
        assert not hasattr(item, "reasoning")
        assert not hasattr(item, "confidence")


class TestAuditRequest:
    def test_create_with_subtasks(self):
        task_id = uuid.uuid4()
        req = AuditRequest(
            task_id=task_id,
            goal_anchor="Deploy the app",
            subtask_results=[
                SubtaskAuditItem(
                    subtask_id=uuid.uuid4(),
                    description="Write deploy script",
                    content="#!/bin/bash\ndeploy.sh",
                ),
            ],
        )
        assert req.task_id == task_id
        assert len(req.subtask_results) == 1

    def test_empty_subtask_results(self):
        req = AuditRequest(
            task_id=uuid.uuid4(),
            goal_anchor="Test",
            subtask_results=[],
        )
        assert req.subtask_results == []


class TestSubtaskVerdict:
    def test_create_pass(self):
        v = SubtaskVerdict(
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.PASS,
            score=0.85,
            goal_alignment=0.9,
        )
        assert v.verdict == "pass"
        assert v.issues == []

    def test_create_fail_with_issues(self):
        v = SubtaskVerdict(
            subtask_id=uuid.uuid4(),
            verdict=AuditVerdict.FAIL,
            score=0.3,
            goal_alignment=0.4,
            issues=[{"category": "completeness", "description": "Missing error handling"}],
        )
        assert len(v.issues) == 1


class TestFixInstruction:
    def test_create(self):
        fi = FixInstruction(
            subtask_id=uuid.uuid4(),
            instructions="Add error handling for network failures",
            original_content="def fetch(): return requests.get(url)",
            issues=[{"category": "robustness", "description": "No error handling"}],
        )
        assert "error handling" in fi.instructions


class TestAuditResponse:
    def test_success_response(self):
        resp = AuditResponse(
            task_id=uuid.uuid4(),
            success=True,
            verdicts=[
                SubtaskVerdict(
                    subtask_id=uuid.uuid4(),
                    verdict=AuditVerdict.PASS,
                    score=0.9,
                    goal_alignment=0.95,
                ),
            ],
            overall_score=0.9,
        )
        assert resp.success is True
        assert resp.fix_required == []

    def test_failure_response_with_fixes(self):
        sid = uuid.uuid4()
        resp = AuditResponse(
            task_id=uuid.uuid4(),
            success=False,
            verdicts=[
                SubtaskVerdict(
                    subtask_id=sid,
                    verdict=AuditVerdict.FAIL,
                    score=0.3,
                    goal_alignment=0.4,
                    issues=[{"category": "quality", "description": "Incomplete"}],
                ),
            ],
            overall_score=0.3,
            fix_required=[
                FixInstruction(
                    subtask_id=sid,
                    instructions="Complete the implementation",
                    original_content="partial...",
                    issues=[{"category": "quality", "description": "Incomplete"}],
                ),
            ],
        )
        assert resp.success is False
        assert len(resp.fix_required) == 1

    def test_score_validation(self):
        """Scores must be between 0 and 1."""
        with pytest.raises(ValidationError):
            SubtaskVerdict(
                subtask_id=uuid.uuid4(),
                verdict=AuditVerdict.PASS,
                score=1.5,
                goal_alignment=0.9,
            )
