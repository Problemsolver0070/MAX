"""Integration tests for the Phase 7 Evolution System.

Verifies that all public classes and models are importable from
``max.evolution`` and that the end-to-end pipeline (director -> snapshot ->
improver -> canary -> promote/rollback) works correctly with mocked
dependencies.
"""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

# ── TestImportAll ────────────────────────────────────────────────────────────


class TestImportAll:
    """Verify every public symbol is importable from ``max.evolution``."""

    def test_import_evolution_director_agent(self):
        from max.evolution import EvolutionDirectorAgent

        assert EvolutionDirectorAgent is not None

    def test_import_improvement_agent(self):
        from max.evolution import ImprovementAgent

        assert ImprovementAgent is not None

    def test_import_canary_runner(self):
        from max.evolution import CanaryRunner

        assert CanaryRunner is not None

    def test_import_base_scout(self):
        from max.evolution import BaseScout

        assert BaseScout is not None

    def test_import_tool_scout(self):
        from max.evolution import ToolScout

        assert ToolScout is not None

    def test_import_pattern_scout(self):
        from max.evolution import PatternScout

        assert PatternScout is not None

    def test_import_quality_scout(self):
        from max.evolution import QualityScout

        assert QualityScout is not None

    def test_import_ecosystem_scout(self):
        from max.evolution import EcosystemScout

        assert EcosystemScout is not None

    def test_import_preference_profile_manager(self):
        from max.evolution import PreferenceProfileManager

        assert PreferenceProfileManager is not None

    def test_import_snapshot_manager(self):
        from max.evolution import SnapshotManager

        assert SnapshotManager is not None

    def test_import_self_model(self):
        from max.evolution import SelfModel

        assert SelfModel is not None

    def test_import_evolution_store(self):
        from max.evolution import EvolutionStore

        assert EvolutionStore is not None

    def test_import_canary_request(self):
        from max.evolution import CanaryRequest

        assert CanaryRequest is not None

    def test_import_canary_result(self):
        from max.evolution import CanaryResult

        assert CanaryResult is not None

    def test_import_canary_task_result(self):
        from max.evolution import CanaryTaskResult

        assert CanaryTaskResult is not None

    def test_import_change_set(self):
        from max.evolution import ChangeSet

        assert ChangeSet is not None

    def test_import_change_set_entry(self):
        from max.evolution import ChangeSetEntry

        assert ChangeSetEntry is not None

    def test_import_communication_prefs(self):
        from max.evolution import CommunicationPrefs

        assert CommunicationPrefs is not None

    def test_import_code_prefs(self):
        from max.evolution import CodePrefs

        assert CodePrefs is not None

    def test_import_domain_prefs(self):
        from max.evolution import DomainPrefs

        assert DomainPrefs is not None

    def test_import_workflow_prefs(self):
        from max.evolution import WorkflowPrefs

        assert WorkflowPrefs is not None

    def test_import_evolution_journal_entry(self):
        from max.evolution import EvolutionJournalEntry

        assert EvolutionJournalEntry is not None

    def test_import_evolution_proposal(self):
        from max.evolution import EvolutionProposal

        assert EvolutionProposal is not None

    def test_import_observation(self):
        from max.evolution import Observation

        assert Observation is not None

    def test_import_preference_profile(self):
        from max.evolution import PreferenceProfile

        assert PreferenceProfile is not None

    def test_import_promotion_event(self):
        from max.evolution import PromotionEvent

        assert PromotionEvent is not None

    def test_import_rollback_event(self):
        from max.evolution import RollbackEvent

        assert RollbackEvent is not None

    def test_import_snapshot_data(self):
        from max.evolution import SnapshotData

        assert SnapshotData is not None

    def test_all_list_matches_exports(self):
        """The __all__ list should contain every expected symbol."""
        import max.evolution as evo

        expected = {
            "EvolutionDirectorAgent",
            "ImprovementAgent",
            "CanaryRunner",
            "BaseScout",
            "ToolScout",
            "PatternScout",
            "QualityScout",
            "EcosystemScout",
            "PreferenceProfileManager",
            "SnapshotManager",
            "SelfModel",
            "EvolutionStore",
            "CanaryRequest",
            "CanaryResult",
            "CanaryTaskResult",
            "ChangeSet",
            "ChangeSetEntry",
            "CommunicationPrefs",
            "CodePrefs",
            "DomainPrefs",
            "WorkflowPrefs",
            "EvolutionJournalEntry",
            "EvolutionProposal",
            "Observation",
            "PreferenceProfile",
            "PromotionEvent",
            "RollbackEvent",
            "SnapshotData",
        }
        assert set(evo.__all__) == expected

    def test_all_symbols_resolve(self):
        """Every name in __all__ should be accessible as an attribute."""
        import max.evolution as evo

        for name in evo.__all__:
            assert hasattr(evo, name), f"{name} listed in __all__ but not importable"


# ── Fixtures for End-to-End Pipeline ─────────────────────────────────────────


@pytest.fixture
def settings():
    s = MagicMock()
    s.evolution_min_priority = 0.3
    s.evolution_canary_replay_count = 5
    s.evolution_canary_timeout_seconds = 300
    s.evolution_freeze_consecutive_drops = 2
    return s


@pytest.fixture
def bus():
    b = AsyncMock()
    b.subscribe = AsyncMock()
    b.publish = AsyncMock()
    return b


@pytest.fixture
def evo_store():
    store = AsyncMock()
    store.update_proposal_status = AsyncMock()
    store.promote_candidates = AsyncMock()
    store.discard_candidates = AsyncMock()
    store.record_to_ledger = AsyncMock()
    store.record_journal = AsyncMock()
    return store


@pytest.fixture
def quality_store():
    store = AsyncMock()
    store.get_quality_pulse = AsyncMock(return_value={"pass_rate": 0.95})
    return store


@pytest.fixture
def snapshot_manager():
    snap = AsyncMock()
    snap.capture = AsyncMock(return_value=uuid.uuid4())
    snap.restore = AsyncMock()
    return snap


@pytest.fixture
def improver():
    return AsyncMock()


@pytest.fixture
def canary_runner():
    return AsyncMock()


@pytest.fixture
def self_model():
    model = AsyncMock()
    model.record_evolution = AsyncMock()
    return model


@pytest.fixture
def state_manager():
    mgr = AsyncMock()
    mgr.load = AsyncMock(return_value=MagicMock(version=1))
    mgr.save = AsyncMock()
    return mgr


@pytest.fixture
def task_store():
    store = AsyncMock()
    store.get_active_tasks = AsyncMock(return_value=[])
    return store


@pytest.fixture
def director(
    bus,
    evo_store,
    quality_store,
    snapshot_manager,
    improver,
    canary_runner,
    self_model,
    settings,
    state_manager,
    task_store,
):
    from max.evolution import EvolutionDirectorAgent

    llm = AsyncMock()
    return EvolutionDirectorAgent(
        llm=llm,
        bus=bus,
        evo_store=evo_store,
        quality_store=quality_store,
        snapshot_manager=snapshot_manager,
        improver=improver,
        canary_runner=canary_runner,
        self_model=self_model,
        settings=settings,
        state_manager=state_manager,
        task_store=task_store,
    )


def _make_proposal(
    *,
    impact: float = 0.8,
    effort: float = 0.2,
    risk: float = 0.1,
):
    from max.evolution import EvolutionProposal

    return EvolutionProposal(
        scout_type="integration_test",
        description="Integration test proposal",
        target_type="prompt",
        target_id="worker_agent",
        impact_score=impact,
        effort_score=effort,
        risk_score=risk,
    )


# ── TestEndToEndPipeline ─────────────────────────────────────────────────────


class TestEndToEndPipeline:
    """End-to-end integration tests wiring all mocked components through
    the EvolutionDirectorAgent pipeline.
    """

    @pytest.mark.asyncio
    async def test_full_cycle_promote(
        self,
        director,
        snapshot_manager,
        improver,
        canary_runner,
        evo_store,
        self_model,
        bus,
        task_store,
    ):
        """Full pipeline: proposal -> snapshot -> implement -> canary pass -> promote.

        Verifies:
        - snapshot.capture called
        - improver.implement called
        - canary.run called
        - evo_store.promote_candidates called
        - bus.publish called (promotion event)
        """
        from max.evolution import (
            CanaryResult,
            ChangeSet,
            ChangeSetEntry,
        )

        proposal = _make_proposal()

        # Wire up improver to return a non-empty changeset
        changeset = ChangeSet(
            proposal_id=proposal.id,
            entries=[
                ChangeSetEntry(
                    target_type="prompt",
                    target_id="worker_agent",
                    old_value="old system prompt",
                    new_value="improved system prompt",
                ),
            ],
        )
        improver.implement = AsyncMock(return_value=changeset)

        # Wire up task store with active tasks
        task_ids = [uuid.uuid4(), uuid.uuid4()]
        task_store.get_active_tasks = AsyncMock(
            return_value=[
                {"id": task_ids[0], "status": "completed"},
                {"id": task_ids[1], "status": "completed"},
            ]
        )

        # Wire up canary to pass
        canary_result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=True,
            duration_seconds=0.5,
        )
        canary_runner.run = AsyncMock(return_value=canary_result)

        # Run the pipeline
        await director.run_pipeline(proposal)

        # Verify: snapshot captured
        snapshot_manager.capture.assert_called_once()

        # Verify: improver called with the proposal
        improver.implement.assert_called_once_with(proposal)

        # Verify: canary ran
        canary_runner.run.assert_called_once()

        # Verify: candidates promoted (not rolled back)
        evo_store.promote_candidates.assert_called_once()
        evo_store.discard_candidates.assert_not_called()

        # Verify: bus event published for promotion
        bus.publish.assert_called()
        publish_calls = [call.args[0] for call in bus.publish.call_args_list]
        assert "evolution.promoted" in publish_calls

        # Verify: self-model journal recorded
        self_model.record_evolution.assert_called()

    @pytest.mark.asyncio
    async def test_full_cycle_rollback(
        self,
        director,
        snapshot_manager,
        improver,
        canary_runner,
        evo_store,
        self_model,
        bus,
        task_store,
    ):
        """Full pipeline: proposal -> snapshot -> implement -> canary FAIL -> rollback.

        Verifies:
        - snapshot.restore called (rollback)
        - evo_store.discard_candidates called
        - evo_store.promote_candidates NOT called
        """
        from max.evolution import (
            CanaryResult,
            ChangeSet,
            ChangeSetEntry,
        )

        proposal = _make_proposal()

        # Wire up improver to return a non-empty changeset
        changeset = ChangeSet(
            proposal_id=proposal.id,
            entries=[
                ChangeSetEntry(
                    target_type="tool_config",
                    target_id="web_search",
                    old_value={"timeout": 30},
                    new_value={"timeout": 60},
                ),
            ],
        )
        improver.implement = AsyncMock(return_value=changeset)

        # Wire up task store
        task_ids = [uuid.uuid4()]
        task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": task_ids[0], "status": "completed"}]
        )

        # Wire up canary to FAIL
        canary_result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=False,
            duration_seconds=1.2,
        )
        canary_runner.run = AsyncMock(return_value=canary_result)

        # Run the pipeline
        await director.run_pipeline(proposal)

        # Verify: snapshot was captured, then restored on rollback
        snapshot_manager.capture.assert_called_once()
        snapshot_manager.restore.assert_called_once()

        # Verify: candidates discarded (not promoted)
        evo_store.discard_candidates.assert_called_once()
        evo_store.promote_candidates.assert_not_called()

        # Verify: bus event published for rollback
        bus.publish.assert_called()
        publish_calls = [call.args[0] for call in bus.publish.call_args_list]
        assert "evolution.rolled_back" in publish_calls

        # Verify: self-model journal recorded
        self_model.record_evolution.assert_called()
