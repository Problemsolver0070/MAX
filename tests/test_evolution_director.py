"""Tests for EvolutionDirectorAgent -- the main orchestrator for the evolution pipeline."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.evolution.director import EvolutionDirectorAgent
from max.evolution.models import (
    CanaryResult,
    ChangeSet,
    ChangeSetEntry,
    EvolutionProposal,
)

# ── Fixtures ──────────────────────────────────────────────────────────────────


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
    imp = AsyncMock()
    return imp


@pytest.fixture
def canary_runner():
    runner = AsyncMock()
    return runner


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
    impact: float = 0.5,
    effort: float = 0.3,
    risk: float = 0.2,
) -> EvolutionProposal:
    return EvolutionProposal(
        scout_type="pattern_scout",
        description="Improve error handling",
        target_type="prompt",
        target_id="worker_agent",
        impact_score=impact,
        effort_score=effort,
        risk_score=risk,
    )


# ── TestEvaluateProposal ─────────────────────────────────────────────────────


class TestEvaluateProposal:
    def test_accepts_high_priority(self, director):
        """impact=0.8, effort=0.2, risk=0.1 -> priority = 0.8*(1-0.1)/0.2 = 3.6 > 0.3."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        assert director.evaluate_proposal(proposal) is True

    def test_rejects_low_priority(self, director):
        """impact=0.1, effort=0.5, risk=0.8 -> priority = 0.1*(1-0.8)/0.5 = 0.04 < 0.3."""
        proposal = _make_proposal(impact=0.1, effort=0.5, risk=0.8)
        assert director.evaluate_proposal(proposal) is False

    def test_boundary_exact_threshold(self, director):
        """Proposal at exactly the threshold should pass (>=)."""
        # 0.3 * (1-0.0) / 1.0 = 0.3 == threshold
        proposal = _make_proposal(impact=0.3, effort=1.0, risk=0.0)
        assert director.evaluate_proposal(proposal) is True


# ── TestAntiDegradation ──────────────────────────────────────────────────────


class TestAntiDegradation:
    @pytest.mark.asyncio
    async def test_freeze_on_consecutive_drops(self, director, quality_store):
        """Two consecutive drops should trigger freeze (threshold=2)."""
        # Already had 1 drop
        director._consecutive_drops = 1
        # 24h pass_rate=0.80, 48h pass_rate=0.90 -> drop
        quality_store.get_quality_pulse = AsyncMock(
            side_effect=[
                {"pass_rate": 0.80},  # 24h window
                {"pass_rate": 0.90},  # 48h window
            ]
        )
        result = await director.check_anti_degradation()
        assert result is True
        assert director._consecutive_drops == 2

    @pytest.mark.asyncio
    async def test_no_freeze_on_stable(self, director, quality_store):
        """Improving or stable rates should reset counter."""
        director._consecutive_drops = 1
        # 24h pass_rate=0.95, 48h pass_rate=0.90 -> improving
        quality_store.get_quality_pulse = AsyncMock(
            side_effect=[
                {"pass_rate": 0.95},  # 24h window
                {"pass_rate": 0.90},  # 48h window
            ]
        )
        result = await director.check_anti_degradation()
        assert result is False
        assert director._consecutive_drops == 0

    @pytest.mark.asyncio
    async def test_single_drop_no_freeze(self, director, quality_store):
        """A single drop from 0 should not trigger freeze (need 2 consecutive)."""
        director._consecutive_drops = 0
        quality_store.get_quality_pulse = AsyncMock(
            side_effect=[
                {"pass_rate": 0.80},  # 24h
                {"pass_rate": 0.90},  # 48h
            ]
        )
        result = await director.check_anti_degradation()
        assert result is False
        assert director._consecutive_drops == 1


# ── TestFullPipeline ─────────────────────────────────────────────────────────


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_successful_evolution(
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
        """Verify all steps: snapshot, implement, canary, promote, record, bus publish."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        changeset = ChangeSet(
            proposal_id=proposal.id,
            entries=[
                ChangeSetEntry(
                    target_type="prompt",
                    target_id="worker_agent",
                    old_value="old prompt",
                    new_value="new prompt",
                ),
            ],
        )
        improver.implement = AsyncMock(return_value=changeset)

        task_ids = [uuid.uuid4(), uuid.uuid4()]
        task_store.get_active_tasks = AsyncMock(
            return_value=[
                {"id": task_ids[0], "status": "completed"},
                {"id": task_ids[1], "status": "completed"},
            ]
        )

        canary_result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=True,
            duration_seconds=1.0,
        )
        canary_runner.run = AsyncMock(return_value=canary_result)

        await director.run_pipeline(proposal)

        # Step 3: snapshot captured
        snapshot_manager.capture.assert_called_once()
        # Step 4: improver called
        improver.implement.assert_called_once_with(proposal)
        # Step 6: canary called
        canary_runner.run.assert_called_once()
        # Step 7: promote
        evo_store.promote_candidates.assert_called_once()
        # Journal and ledger recorded
        self_model.record_evolution.assert_called()
        evo_store.record_to_ledger.assert_called()
        # Bus event published
        bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_rollback_on_canary_failure(
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
        """Canary fails -> snapshot restore, discard candidates, promote NOT called."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        changeset = ChangeSet(
            proposal_id=proposal.id,
            entries=[
                ChangeSetEntry(
                    target_type="prompt",
                    target_id="worker_agent",
                    old_value="old",
                    new_value="new",
                ),
            ],
        )
        improver.implement = AsyncMock(return_value=changeset)

        task_ids = [uuid.uuid4()]
        task_store.get_active_tasks = AsyncMock(
            return_value=[{"id": task_ids[0], "status": "completed"}]
        )

        canary_result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=False,
            duration_seconds=1.0,
        )
        canary_runner.run = AsyncMock(return_value=canary_result)

        await director.run_pipeline(proposal)

        # Rollback: snapshot restored, candidates discarded
        snapshot_manager.restore.assert_called_once()
        evo_store.discard_candidates.assert_called_once()
        # Promote should NOT be called
        evo_store.promote_candidates.assert_not_called()
        # Journal and ledger recorded
        self_model.record_evolution.assert_called()
        evo_store.record_to_ledger.assert_called()
        # Bus event published (rollback event)
        bus.publish.assert_called()

    @pytest.mark.asyncio
    async def test_rollback_on_empty_changeset(
        self,
        director,
        snapshot_manager,
        improver,
        canary_runner,
        evo_store,
        task_store,
    ):
        """Empty changeset -> canary NOT called, discard_candidates called."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        empty_changeset = ChangeSet(proposal_id=proposal.id, entries=[])
        improver.implement = AsyncMock(return_value=empty_changeset)

        await director.run_pipeline(proposal)

        # Snapshot still captured (step 3 happens before implement)
        snapshot_manager.capture.assert_called_once()
        # Canary should NOT run on empty changeset
        canary_runner.run.assert_not_called()
        # Candidates discarded
        evo_store.discard_candidates.assert_called_once()


# ── TestFreezeHandling ────────────────────────────────────────────────────────


class TestFreezeHandling:
    @pytest.mark.asyncio
    async def test_skips_pipeline_when_frozen(
        self,
        director,
        snapshot_manager,
        improver,
        canary_runner,
    ):
        """When frozen, run_pipeline should return immediately without doing anything."""
        director._frozen = True
        proposal = _make_proposal()

        await director.run_pipeline(proposal)

        snapshot_manager.capture.assert_not_called()
        improver.implement.assert_not_called()
        canary_runner.run.assert_not_called()

    @pytest.mark.asyncio
    async def test_freeze_sets_state_and_publishes(
        self, director, evo_store, self_model, bus
    ):
        """freeze() sets _frozen, records ledger entry, journal, publishes bus event."""
        await director.freeze("quality degradation detected")

        assert director._frozen is True
        evo_store.record_to_ledger.assert_called_once()
        self_model.record_evolution.assert_called_once()
        bus.publish.assert_called_once()

    @pytest.mark.asyncio
    async def test_unfreeze_clears_state_and_publishes(
        self, director, evo_store, self_model, bus
    ):
        """unfreeze() clears _frozen, records ledger entry, journal, publishes bus event."""
        director._frozen = True
        await director.unfreeze()

        assert director._frozen is False
        evo_store.record_to_ledger.assert_called_once()
        self_model.record_evolution.assert_called_once()
        bus.publish.assert_called_once()


# ── TestBusIntegration ────────────────────────────────────────────────────────


class TestBusIntegration:
    @pytest.mark.asyncio
    async def test_start_subscribes_to_channels(self, director, bus):
        """start() should subscribe to evolution.trigger and evolution.proposal."""
        await director.start()

        assert bus.subscribe.call_count == 2
        channels = [call.args[0] for call in bus.subscribe.call_args_list]
        assert "evolution.trigger" in channels
        assert "evolution.proposal" in channels

    @pytest.mark.asyncio
    async def test_on_proposal_evaluates_and_runs(
        self,
        director,
        bus,
        snapshot_manager,
        improver,
        canary_runner,
        evo_store,
        task_store,
    ):
        """_on_proposal with a high-priority proposal should trigger the pipeline."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        changeset = ChangeSet(
            proposal_id=proposal.id,
            entries=[
                ChangeSetEntry(
                    target_type="prompt",
                    target_id="worker_agent",
                    old_value="old",
                    new_value="new",
                ),
            ],
        )
        improver.implement = AsyncMock(return_value=changeset)

        task_store.get_active_tasks = AsyncMock(return_value=[])

        canary_result = CanaryResult(
            experiment_id=uuid.uuid4(),
            task_results=[],
            overall_passed=True,
            duration_seconds=1.0,
        )
        canary_runner.run = AsyncMock(return_value=canary_result)

        data = proposal.model_dump(mode="json")
        await director._on_proposal("evolution.proposal", data)

        # Pipeline should have run (snapshot captured)
        snapshot_manager.capture.assert_called_once()

    @pytest.mark.asyncio
    async def test_on_proposal_rejects_low_priority(
        self,
        director,
        snapshot_manager,
        evo_store,
    ):
        """_on_proposal with low-priority proposal should not run pipeline."""
        proposal = _make_proposal(impact=0.1, effort=0.5, risk=0.8)
        data = proposal.model_dump(mode="json")
        await director._on_proposal("evolution.proposal", data)

        # Pipeline should NOT have run
        snapshot_manager.capture.assert_not_called()
        # Status should be updated to rejected
        evo_store.update_proposal_status.assert_called_once()
        status_arg = evo_store.update_proposal_status.call_args[0][1]
        assert status_arg == "rejected"


# ── TestPipelineErrorHandling ─────────────────────────────────────────────────


class TestPipelineErrorHandling:
    @pytest.mark.asyncio
    async def test_rollback_on_exception(
        self,
        director,
        snapshot_manager,
        improver,
        evo_store,
    ):
        """Exception during pipeline triggers rollback attempt."""
        proposal = _make_proposal(impact=0.8, effort=0.2, risk=0.1)
        improver.implement = AsyncMock(side_effect=RuntimeError("LLM timeout"))

        await director.run_pipeline(proposal)

        # Snapshot was captured before the error
        snapshot_manager.capture.assert_called_once()
        # Rollback should have been attempted
        snapshot_manager.restore.assert_called_once()
        evo_store.discard_candidates.assert_called_once()
