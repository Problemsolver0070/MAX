"""Tests for EvolutionDirectorAgent integration with Sentinel."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from max.evolution.director import EvolutionDirectorAgent
from max.evolution.models import EvolutionProposal, ChangeSet, ChangeSetEntry
from max.sentinel.models import SentinelVerdict


@pytest.fixture
def mock_settings():
    settings = MagicMock()
    settings.evolution_min_priority = 0.3
    settings.evolution_canary_replay_count = 5
    settings.evolution_canary_timeout_seconds = 300
    settings.evolution_freeze_consecutive_drops = 2
    settings.sentinel_replay_count = 10
    return settings


@pytest.fixture
def mock_sentinel_scorer():
    scorer = AsyncMock()
    scorer.run_baseline = AsyncMock(return_value=uuid.uuid4())
    scorer.run_candidate = AsyncMock(return_value=uuid.uuid4())
    scorer.compare_and_verdict = AsyncMock(return_value=SentinelVerdict(
        experiment_id=uuid.uuid4(),
        baseline_run_id=uuid.uuid4(),
        candidate_run_id=uuid.uuid4(),
        passed=True,
        summary="All passed",
    ))
    return scorer


@pytest.fixture
def director(mock_settings, mock_sentinel_scorer):
    llm = AsyncMock()
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.publish = AsyncMock()
    evo_store = AsyncMock()
    evo_store.update_proposal_status = AsyncMock()
    evo_store.promote_candidates = AsyncMock()
    evo_store.discard_candidates = AsyncMock()
    evo_store.record_to_ledger = AsyncMock()
    evo_store.record_journal = AsyncMock()
    evo_store.get_journal = AsyncMock(return_value=[])
    quality_store = AsyncMock()
    quality_store.get_quality_pulse = AsyncMock(return_value={"pass_rate": 0.9})
    snapshot_manager = AsyncMock()
    snapshot_manager.capture = AsyncMock(return_value=uuid.uuid4())
    snapshot_manager.restore = AsyncMock()
    improver = AsyncMock()
    improver.implement = AsyncMock(return_value=ChangeSet(
        proposal_id=uuid.uuid4(),
        entries=[ChangeSetEntry(target_type="prompt", target_id="test", new_value="new")],
    ))
    canary_runner = AsyncMock()
    self_model = AsyncMock()
    self_model.record_evolution = AsyncMock()
    state_manager = AsyncMock()
    state_manager.update_evolution_state = AsyncMock()
    task_store = AsyncMock()
    task_store.get_active_tasks = AsyncMock(return_value=[])

    d = EvolutionDirectorAgent(
        llm=llm,
        bus=bus,
        evo_store=evo_store,
        quality_store=quality_store,
        snapshot_manager=snapshot_manager,
        improver=improver,
        canary_runner=canary_runner,
        self_model=self_model,
        settings=mock_settings,
        state_manager=state_manager,
        task_store=task_store,
        sentinel_scorer=mock_sentinel_scorer,
    )
    return d


class TestPipelineUsesSentinel:
    @pytest.mark.asyncio
    async def test_calls_sentinel_baseline_before_implement(self, director, mock_sentinel_scorer):
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test proposal",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        mock_sentinel_scorer.run_baseline.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_sentinel_candidate_after_implement(self, director, mock_sentinel_scorer):
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test proposal",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        mock_sentinel_scorer.run_candidate.assert_called_once()

    @pytest.mark.asyncio
    async def test_calls_sentinel_verdict(self, director, mock_sentinel_scorer):
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test proposal",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        mock_sentinel_scorer.compare_and_verdict.assert_called_once()

    @pytest.mark.asyncio
    async def test_promotes_on_pass(self, director, mock_sentinel_scorer):
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        director._evo_store.promote_candidates.assert_called_once()

    @pytest.mark.asyncio
    async def test_rollback_on_sentinel_fail(self, director, mock_sentinel_scorer):
        mock_sentinel_scorer.compare_and_verdict.return_value = SentinelVerdict(
            experiment_id=uuid.uuid4(),
            baseline_run_id=uuid.uuid4(),
            candidate_run_id=uuid.uuid4(),
            passed=False,
            summary="Regression detected",
        )
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        director._snapshot_manager.restore.assert_called()
        director._evo_store.discard_candidates.assert_called()


class TestSentinelScorerProperty:
    def test_has_sentinel_scorer_attribute(self, director):
        assert hasattr(director, '_sentinel_scorer')


# ── Task 10: Gap Fixes ────────────────────────────────────────────────


class TestConsecutiveDropsPersistence:
    @pytest.mark.asyncio
    async def test_freeze_records_consecutive_drops_to_journal(self, director):
        await director.freeze("test reason")
        director._self_model.record_evolution.assert_called()
        call_args = director._self_model.record_evolution.call_args[0][0]
        assert call_args.action == "freeze"

    @pytest.mark.asyncio
    async def test_consecutive_drops_loaded_from_journal_on_init(self):
        """Verify _load_consecutive_drops is called or drops are recoverable."""
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        evo_store = AsyncMock()
        evo_store.get_journal = AsyncMock(return_value=[
            {"action": "freeze", "details": {"reason": "test", "consecutive_drops": 3}},
        ])
        quality_store = AsyncMock()
        snapshot_manager = AsyncMock()
        improver = AsyncMock()
        canary_runner = AsyncMock()
        self_model = AsyncMock()
        settings = MagicMock()
        settings.evolution_freeze_consecutive_drops = 2
        state_manager = AsyncMock()
        task_store = AsyncMock()

        d = EvolutionDirectorAgent(
            llm=llm, bus=bus, evo_store=evo_store, quality_store=quality_store,
            snapshot_manager=snapshot_manager, improver=improver,
            canary_runner=canary_runner, self_model=self_model,
            settings=settings, state_manager=state_manager, task_store=task_store,
        )
        await d.load_persisted_state()
        assert d._frozen is True


class TestCoordinatorStateSync:
    @pytest.mark.asyncio
    async def test_freeze_syncs_coordinator_state(self, director):
        await director.freeze("test reason")
        director._state_manager.update_evolution_state.assert_called()

    @pytest.mark.asyncio
    async def test_unfreeze_syncs_coordinator_state(self, director):
        director._frozen = True
        await director.unfreeze()
        director._state_manager.update_evolution_state.assert_called()

    @pytest.mark.asyncio
    async def test_promote_syncs_coordinator_state(self, director, mock_sentinel_scorer):
        proposal = EvolutionProposal(
            scout_type="test",
            description="Test",
            target_type="prompt",
            impact_score=0.8,
            effort_score=0.2,
            risk_score=0.1,
        )
        await director.run_pipeline(proposal)
        assert director._state_manager.update_evolution_state.call_count >= 1
