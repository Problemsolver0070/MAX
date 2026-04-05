# tests/test_evolution_models.py
"""Tests for Phase 7 evolution domain models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from max.evolution.models import (
    CanaryRequest,
    CanaryResult,
    CanaryTaskResult,
    ChangeSet,
    ChangeSetEntry,
    CodePrefs,
    CommunicationPrefs,
    DomainPrefs,
    EvolutionJournalEntry,
    EvolutionProposal,
    Observation,
    PreferenceProfile,
    PromotionEvent,
    RollbackEvent,
    SnapshotData,
    WorkflowPrefs,
)

# ── CommunicationPrefs ─────────────────────────────────────────────────────


class TestCommunicationPrefs:
    def test_defaults(self):
        prefs = CommunicationPrefs()
        assert prefs.tone == "professional"
        assert prefs.detail_level == "moderate"
        assert prefs.update_frequency == "on_completion"
        assert prefs.languages == ["en"]
        assert prefs.timezone == "UTC"

    def test_custom_values(self):
        prefs = CommunicationPrefs(
            tone="casual",
            detail_level="verbose",
            update_frequency="hourly",
            languages=["en", "es"],
            timezone="US/Eastern",
        )
        assert prefs.tone == "casual"
        assert prefs.languages == ["en", "es"]

    def test_serialization_roundtrip(self):
        prefs = CommunicationPrefs(tone="friendly", languages=["en", "fr"])
        data = prefs.model_dump(mode="json")
        restored = CommunicationPrefs.model_validate(data)
        assert restored.tone == "friendly"
        assert restored.languages == ["en", "fr"]


# ── CodePrefs ───────────────────────────────────────────────────────────────


class TestCodePrefs:
    def test_defaults(self):
        prefs = CodePrefs()
        assert prefs.style == {}
        assert prefs.review_depth == "thorough"
        assert prefs.test_coverage == "high"
        assert prefs.commit_style == "conventional"

    def test_custom_style(self):
        prefs = CodePrefs(style={"python": "black", "js": "prettier"})
        assert prefs.style["python"] == "black"

    def test_serialization_roundtrip(self):
        prefs = CodePrefs(style={"rust": "rustfmt"}, review_depth="light")
        data = prefs.model_dump(mode="json")
        restored = CodePrefs.model_validate(data)
        assert restored.style == {"rust": "rustfmt"}
        assert restored.review_depth == "light"


# ── WorkflowPrefs ──────────────────────────────────────────────────────────


class TestWorkflowPrefs:
    def test_defaults(self):
        prefs = WorkflowPrefs()
        assert prefs.clarification_threshold == 0.3
        assert prefs.autonomy_level == "high"
        assert prefs.reporting_style == "concise"

    def test_custom_values(self):
        prefs = WorkflowPrefs(
            clarification_threshold=0.8,
            autonomy_level="low",
            reporting_style="detailed",
        )
        assert prefs.clarification_threshold == 0.8
        assert prefs.autonomy_level == "low"


# ── DomainPrefs ─────────────────────────────────────────────────────────────


class TestDomainPrefs:
    def test_defaults(self):
        prefs = DomainPrefs()
        assert prefs.expertise_areas == []
        assert prefs.client_contexts == {}
        assert prefs.project_conventions == {}

    def test_custom_values(self):
        prefs = DomainPrefs(
            expertise_areas=["ML", "DevOps"],
            client_contexts={"acme": {"billing": "monthly"}},
            project_conventions={"max": {"style": "black"}},
        )
        assert len(prefs.expertise_areas) == 2
        assert prefs.client_contexts["acme"]["billing"] == "monthly"


# ── Observation ─────────────────────────────────────────────────────────────


class TestObservation:
    def test_construction(self):
        obs = Observation(
            signal_type="tone_correction",
            data={"original": "casual", "corrected": "formal"},
        )
        assert obs.signal_type == "tone_correction"
        assert obs.data["original"] == "casual"
        assert isinstance(obs.recorded_at, datetime)

    def test_recorded_at_default(self):
        before = datetime.now(UTC)
        obs = Observation(signal_type="test", data={})
        after = datetime.now(UTC)
        assert before <= obs.recorded_at <= after


# ── PreferenceProfile ───────────────────────────────────────────────────────


class TestPreferenceProfile:
    def test_defaults(self):
        profile = PreferenceProfile(user_id="user-123")
        assert profile.user_id == "user-123"
        assert isinstance(profile.communication, CommunicationPrefs)
        assert isinstance(profile.code, CodePrefs)
        assert isinstance(profile.workflow, WorkflowPrefs)
        assert isinstance(profile.domain_knowledge, DomainPrefs)
        assert profile.observation_log == []
        assert isinstance(profile.updated_at, datetime)
        assert profile.version == 1

    def test_with_observations(self):
        obs = Observation(signal_type="preference_change", data={"key": "tone"})
        profile = PreferenceProfile(
            user_id="user-456",
            observation_log=[obs],
            version=3,
        )
        assert len(profile.observation_log) == 1
        assert profile.version == 3

    def test_serialization_roundtrip(self):
        profile = PreferenceProfile(user_id="user-789")
        data = profile.model_dump(mode="json")
        restored = PreferenceProfile.model_validate(data)
        assert restored.user_id == "user-789"
        assert isinstance(restored.communication, CommunicationPrefs)
        assert isinstance(restored.updated_at, datetime)

    def test_nested_defaults(self):
        profile = PreferenceProfile(user_id="user-nested")
        assert profile.communication.tone == "professional"
        assert profile.code.review_depth == "thorough"
        assert profile.workflow.autonomy_level == "high"
        assert profile.domain_knowledge.expertise_areas == []


# ── EvolutionProposal ──────────────────────────────────────────────────────


class TestEvolutionProposal:
    def test_defaults(self):
        proposal = EvolutionProposal(
            scout_type="pattern_scout",
            description="Improve prompt caching",
            target_type="prompt",
        )
        assert isinstance(proposal.id, uuid.UUID)
        assert proposal.scout_type == "pattern_scout"
        assert proposal.target_type == "prompt"
        assert proposal.target_id is None
        assert proposal.impact_score == 0.0
        assert proposal.effort_score == 0.0
        assert proposal.risk_score == 0.0
        assert proposal.priority == 0.0
        assert proposal.status == "proposed"
        assert proposal.experiment_id is None
        assert isinstance(proposal.created_at, datetime)

    def test_computed_priority_basic(self):
        proposal = EvolutionProposal(
            scout_type="pattern_scout",
            description="Test",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.4,
            risk_score=0.2,
        )
        # computed_priority = impact * (1 - risk) / max(effort, 0.1)
        # = 0.8 * (1 - 0.2) / max(0.4, 0.1)
        # = 0.8 * 0.8 / 0.4
        # = 1.6
        assert proposal.computed_priority == pytest.approx(1.6)

    def test_computed_priority_zero_effort(self):
        """When effort is 0, max(0, 0.1) = 0.1 prevents division by zero."""
        proposal = EvolutionProposal(
            scout_type="efficiency_scout",
            description="Free win",
            target_type="tool_config",
            impact_score=1.0,
            effort_score=0.0,
            risk_score=0.0,
        )
        # 1.0 * (1 - 0.0) / max(0.0, 0.1) = 1.0 / 0.1 = 10.0
        assert proposal.computed_priority == pytest.approx(10.0)

    def test_computed_priority_high_risk(self):
        proposal = EvolutionProposal(
            scout_type="drift_scout",
            description="Risky change",
            target_type="context_rule",
            impact_score=0.5,
            effort_score=1.0,
            risk_score=0.9,
        )
        # 0.5 * (1 - 0.9) / max(1.0, 0.1) = 0.5 * 0.1 / 1.0 = 0.05
        assert proposal.computed_priority == pytest.approx(0.05)

    def test_all_target_types(self):
        for target in ["prompt", "tool_config", "context_rule", "workflow", "preference"]:
            p = EvolutionProposal(
                scout_type="test_scout",
                description=f"Target {target}",
                target_type=target,
            )
            assert p.target_type == target

    def test_with_target_id(self):
        proposal = EvolutionProposal(
            scout_type="pattern_scout",
            description="Specific prompt update",
            target_type="prompt",
            target_id="main_coordinator_prompt",
        )
        assert proposal.target_id == "main_coordinator_prompt"

    def test_with_experiment_id(self):
        exp_id = uuid.uuid4()
        proposal = EvolutionProposal(
            scout_type="test_scout",
            description="Linked to experiment",
            target_type="prompt",
            experiment_id=exp_id,
        )
        assert proposal.experiment_id == exp_id

    def test_serialization_roundtrip(self):
        proposal = EvolutionProposal(
            scout_type="pattern_scout",
            description="Test roundtrip",
            target_type="prompt",
            impact_score=0.7,
            effort_score=0.3,
            risk_score=0.1,
        )
        data = proposal.model_dump(mode="json")
        restored = EvolutionProposal.model_validate(data)
        assert restored.id == proposal.id
        assert restored.impact_score == 0.7
        assert restored.computed_priority == proposal.computed_priority


# ── ChangeSetEntry & ChangeSet ──────────────────────────────────────────────


class TestChangeSetEntry:
    def test_construction(self):
        entry = ChangeSetEntry(
            target_type="prompt",
            target_id="coordinator_system",
            old_value="You are a helpful assistant.",
            new_value="You are Max, an autonomous AI agent.",
        )
        assert entry.target_type == "prompt"
        assert entry.target_id == "coordinator_system"
        assert entry.old_value == "You are a helpful assistant."
        assert entry.new_value == "You are Max, an autonomous AI agent."

    def test_none_values(self):
        entry = ChangeSetEntry(target_type="tool_config", target_id="search")
        assert entry.old_value is None
        assert entry.new_value is None

    def test_dict_values(self):
        entry = ChangeSetEntry(
            target_type="tool_config",
            target_id="code_exec",
            old_value={"timeout": 30},
            new_value={"timeout": 60},
        )
        assert entry.old_value["timeout"] == 30
        assert entry.new_value["timeout"] == 60


class TestChangeSet:
    def test_construction(self):
        pid = uuid.uuid4()
        cs = ChangeSet(
            proposal_id=pid,
            entries=[
                ChangeSetEntry(
                    target_type="prompt",
                    target_id="system",
                    old_value="old",
                    new_value="new",
                ),
            ],
        )
        assert cs.proposal_id == pid
        assert len(cs.entries) == 1
        assert isinstance(cs.created_at, datetime)

    def test_empty_entries(self):
        cs = ChangeSet(proposal_id=uuid.uuid4(), entries=[])
        assert cs.entries == []

    def test_multiple_entries(self):
        entries = [
            ChangeSetEntry(target_type="prompt", target_id="a", new_value="x"),
            ChangeSetEntry(target_type="tool_config", target_id="b", new_value={"k": "v"}),
            ChangeSetEntry(target_type="context_rule", target_id="c", new_value=[1, 2]),
        ]
        cs = ChangeSet(proposal_id=uuid.uuid4(), entries=entries)
        assert len(cs.entries) == 3

    def test_serialization_roundtrip(self):
        cs = ChangeSet(
            proposal_id=uuid.uuid4(),
            entries=[
                ChangeSetEntry(target_type="prompt", target_id="sys", old_value="a", new_value="b")
            ],
        )
        data = cs.model_dump(mode="json")
        restored = ChangeSet.model_validate(data)
        assert restored.proposal_id == cs.proposal_id
        assert len(restored.entries) == 1
        assert restored.entries[0].old_value == "a"


# ── SnapshotData ────────────────────────────────────────────────────────────


class TestSnapshotData:
    def test_defaults(self):
        snap = SnapshotData(
            prompts={},
            tool_configs={},
            context_rules=[],
            metrics_baseline={},
        )
        assert snap.prompts == {}
        assert snap.tool_configs == {}
        assert snap.context_rules == []
        assert snap.metrics_baseline == {}

    def test_populated(self):
        snap = SnapshotData(
            prompts={"coordinator": "You are Max.", "worker": "Execute the subtask."},
            tool_configs={"code_exec": {"timeout": 30, "sandbox": True}},
            context_rules=[{"type": "include", "pattern": "*.py"}],
            metrics_baseline={"latency_p95": 2.5, "success_rate": 0.98},
        )
        assert len(snap.prompts) == 2
        assert snap.tool_configs["code_exec"]["timeout"] == 30
        assert len(snap.context_rules) == 1
        assert snap.metrics_baseline["success_rate"] == 0.98

    def test_serialization_roundtrip(self):
        snap = SnapshotData(
            prompts={"main": "prompt text"},
            tool_configs={"search": {"max_results": 10}},
            context_rules=[{"rule": "include_all"}],
            metrics_baseline={"score": 0.95},
        )
        data = snap.model_dump(mode="json")
        restored = SnapshotData.model_validate(data)
        assert restored.prompts == snap.prompts
        assert restored.tool_configs == snap.tool_configs
        assert restored.context_rules == snap.context_rules
        assert restored.metrics_baseline == snap.metrics_baseline


# ── CanaryRequest ───────────────────────────────────────────────────────────


class TestCanaryRequest:
    def test_defaults(self):
        exp_id = uuid.uuid4()
        task_ids = [uuid.uuid4(), uuid.uuid4()]
        req = CanaryRequest(
            experiment_id=exp_id,
            task_ids=task_ids,
            candidate_config={"prompt": "new prompt"},
        )
        assert req.experiment_id == exp_id
        assert len(req.task_ids) == 2
        assert req.candidate_config["prompt"] == "new prompt"
        assert req.timeout_seconds == 300

    def test_custom_timeout(self):
        req = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[uuid.uuid4()],
            candidate_config={},
            timeout_seconds=600,
        )
        assert req.timeout_seconds == 600

    def test_empty_task_ids(self):
        req = CanaryRequest(
            experiment_id=uuid.uuid4(),
            task_ids=[],
            candidate_config={"key": "value"},
        )
        assert req.task_ids == []


# ── CanaryTaskResult ────────────────────────────────────────────────────────


class TestCanaryTaskResult:
    def test_passed(self):
        result = CanaryTaskResult(
            task_id=uuid.uuid4(),
            original_score=0.8,
            canary_score=0.85,
            passed=True,
        )
        assert result.passed is True
        assert result.canary_score > result.original_score

    def test_failed(self):
        result = CanaryTaskResult(
            task_id=uuid.uuid4(),
            original_score=0.9,
            canary_score=0.7,
            passed=False,
        )
        assert result.passed is False
        assert result.canary_score < result.original_score

    def test_equal_scores(self):
        result = CanaryTaskResult(
            task_id=uuid.uuid4(),
            original_score=0.85,
            canary_score=0.85,
            passed=True,
        )
        assert result.original_score == result.canary_score


# ── CanaryResult ────────────────────────────────────────────────────────────


class TestCanaryResult:
    def test_defaults(self):
        result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
        )
        assert result.overall_passed is False
        assert result.duration_seconds == 0.0
        assert result.task_results == []

    def test_passed_result(self):
        task_results = [
            CanaryTaskResult(
                task_id=uuid.uuid4(), original_score=0.8, canary_score=0.9, passed=True
            ),
            CanaryTaskResult(
                task_id=uuid.uuid4(), original_score=0.7, canary_score=0.75, passed=True
            ),
        ]
        result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=task_results,
            overall_passed=True,
            duration_seconds=45.3,
        )
        assert result.overall_passed is True
        assert len(result.task_results) == 2
        assert result.duration_seconds == 45.3

    def test_failed_result(self):
        task_results = [
            CanaryTaskResult(
                task_id=uuid.uuid4(), original_score=0.9, canary_score=0.6, passed=False
            ),
        ]
        result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=task_results,
            overall_passed=False,
            duration_seconds=120.0,
        )
        assert result.overall_passed is False

    def test_serialization_roundtrip(self):
        exp_id = uuid.uuid4()
        result = CanaryResult(
            experiment_id=exp_id,
            task_results=[
                CanaryTaskResult(
                    task_id=uuid.uuid4(), original_score=0.8, canary_score=0.85, passed=True
                ),
            ],
            overall_passed=True,
            duration_seconds=10.5,
        )
        data = result.model_dump(mode="json")
        restored = CanaryResult.model_validate(data)
        assert restored.experiment_id == exp_id
        assert restored.overall_passed is True
        assert len(restored.task_results) == 1


# ── PromotionEvent ──────────────────────────────────────────────────────────


class TestPromotionEvent:
    def test_construction(self):
        exp_id = uuid.uuid4()
        event = PromotionEvent(
            experiment_id=exp_id,
            proposal_description="Improved prompt caching",
            score_improvement=0.15,
        )
        assert event.experiment_id == exp_id
        assert event.proposal_description == "Improved prompt caching"
        assert event.score_improvement == 0.15
        assert isinstance(event.promoted_at, datetime)

    def test_defaults(self):
        event = PromotionEvent(
            experiment_id=uuid.uuid4(),
            proposal_description="Test",
        )
        assert event.score_improvement == 0.0
        assert isinstance(event.promoted_at, datetime)

    def test_serialization_roundtrip(self):
        event = PromotionEvent(
            experiment_id=uuid.uuid4(),
            proposal_description="Roundtrip test",
            score_improvement=0.05,
        )
        data = event.model_dump(mode="json")
        restored = PromotionEvent.model_validate(data)
        assert restored.proposal_description == "Roundtrip test"
        assert restored.score_improvement == 0.05


# ── RollbackEvent ──────────────────────────────────────────────────────────


class TestRollbackEvent:
    def test_construction(self):
        exp_id = uuid.uuid4()
        snap_id = uuid.uuid4()
        event = RollbackEvent(
            experiment_id=exp_id,
            reason="Quality regression detected",
            snapshot_id=snap_id,
        )
        assert event.experiment_id == exp_id
        assert event.reason == "Quality regression detected"
        assert event.snapshot_id == snap_id
        assert isinstance(event.rolled_back_at, datetime)

    def test_serialization_roundtrip(self):
        event = RollbackEvent(
            experiment_id=uuid.uuid4(),
            reason="Latency spike",
            snapshot_id=uuid.uuid4(),
        )
        data = event.model_dump(mode="json")
        restored = RollbackEvent.model_validate(data)
        assert restored.reason == "Latency spike"
        assert isinstance(restored.rolled_back_at, datetime)


# ── EvolutionJournalEntry ──────────────────────────────────────────────────


class TestEvolutionJournalEntry:
    def test_construction_with_experiment(self):
        exp_id = uuid.uuid4()
        entry = EvolutionJournalEntry(
            experiment_id=exp_id,
            action="promoted",
            details={"score_delta": 0.12, "target": "coordinator_prompt"},
        )
        assert isinstance(entry.id, uuid.UUID)
        assert entry.experiment_id == exp_id
        assert entry.action == "promoted"
        assert entry.details["score_delta"] == 0.12
        assert isinstance(entry.recorded_at, datetime)

    def test_construction_without_experiment(self):
        entry = EvolutionJournalEntry(
            experiment_id=None,
            action="system_observation",
            details={"note": "User prefers concise output"},
        )
        assert entry.experiment_id is None
        assert entry.action == "system_observation"

    def test_unique_ids(self):
        e1 = EvolutionJournalEntry(experiment_id=None, action="a", details={})
        e2 = EvolutionJournalEntry(experiment_id=None, action="b", details={})
        assert e1.id != e2.id

    def test_serialization_roundtrip(self):
        entry = EvolutionJournalEntry(
            experiment_id=uuid.uuid4(),
            action="rollback",
            details={"reason": "regression"},
        )
        data = entry.model_dump(mode="json")
        restored = EvolutionJournalEntry.model_validate(data)
        assert restored.id == entry.id
        assert restored.action == "rollback"
        assert restored.details["reason"] == "regression"


# ── Mutable default isolation ───────────────────────────────────────────────


class TestMutableDefaultIsolation:
    """Ensure mutable defaults are not shared across instances."""

    def test_communication_prefs_languages_isolated(self):
        p1 = CommunicationPrefs()
        p2 = CommunicationPrefs()
        p1.languages.append("de")
        assert "de" not in p2.languages

    def test_code_prefs_style_isolated(self):
        p1 = CodePrefs()
        p2 = CodePrefs()
        p1.style["python"] = "black"
        assert "python" not in p2.style

    def test_domain_prefs_expertise_isolated(self):
        p1 = DomainPrefs()
        p2 = DomainPrefs()
        p1.expertise_areas.append("ML")
        assert "ML" not in p2.expertise_areas

    def test_preference_profile_observation_log_isolated(self):
        p1 = PreferenceProfile(user_id="a")
        p2 = PreferenceProfile(user_id="b")
        p1.observation_log.append(Observation(signal_type="x", data={}))
        assert len(p2.observation_log) == 0
