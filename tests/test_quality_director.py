"""Tests for QualityDirectorAgent — audit lifecycle management."""

import uuid
from unittest.mock import AsyncMock, patch

import pytest

from max.agents.base import AgentConfig
from max.quality.director import QualityDirectorAgent
from max.quality.models import AuditRequest, SubtaskAuditItem


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    from max.config import Settings

    return Settings()


def _make_director(monkeypatch):
    settings = _make_settings(monkeypatch)
    llm = AsyncMock()
    bus = AsyncMock()
    bus.subscribe = AsyncMock()
    bus.unsubscribe = AsyncMock()
    bus.publish = AsyncMock()
    db = AsyncMock()
    warm = AsyncMock()
    task_store = AsyncMock()
    quality_store = AsyncMock()
    quality_store.get_active_rules = AsyncMock(return_value=[])
    quality_store.create_audit_report = AsyncMock()
    quality_store.record_verdict = AsyncMock()
    quality_store.get_pass_rate = AsyncMock(return_value=0.85)
    quality_store.get_avg_score = AsyncMock(return_value=0.80)
    rule_engine = AsyncMock()
    rule_engine.get_rules_for_audit = AsyncMock(return_value=[])
    rule_engine.extract_rules = AsyncMock(return_value=[])
    rule_engine.extract_patterns = AsyncMock(return_value=[])
    state_manager = AsyncMock()

    from max.memory.models import CoordinatorState

    state_manager.load = AsyncMock(return_value=CoordinatorState())
    state_manager.save = AsyncMock()

    config = AgentConfig(name="quality_director", system_prompt="")
    director = QualityDirectorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
        task_store=task_store,
        quality_store=quality_store,
        rule_engine=rule_engine,
        state_manager=state_manager,
    )
    return director, bus, llm, quality_store, rule_engine, task_store, state_manager


class TestAuditAllPass:
    @pytest.mark.asyncio
    async def test_all_pass_publishes_success(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Good"],
                    "reasoning": "Well done",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test goal",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=subtask_id,
                        description="Write code",
                        content="def hello(): pass",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"]
        assert len(publish_calls) == 1
        payload = publish_calls[0][0][1]
        assert payload["success"] is True
        assert payload["overall_score"] == pytest.approx(0.85)


class TestAuditWithFailure:
    @pytest.mark.asyncio
    async def test_failure_publishes_fix_instructions(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "fail",
                    "score": 0.3,
                    "goal_alignment": 0.4,
                    "confidence": 0.9,
                    "issues": [{"category": "quality", "description": "Incomplete"}],
                    "fix_instructions": "Add more detail",
                    "strengths": [],
                    "reasoning": "Needs work",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test goal",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=subtask_id,
                        description="Write code",
                        content="incomplete",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"]
        assert len(publish_calls) == 1
        payload = publish_calls[0][0][1]
        assert payload["success"] is False
        assert len(payload["fix_required"]) == 1


class TestConditionalVerdict:
    @pytest.mark.asyncio
    async def test_conditional_treated_as_pass(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "conditional",
                    "score": 0.65,
                    "goal_alignment": 0.7,
                    "confidence": 0.5,
                    "issues": [{"category": "minor", "description": "Small issue"}],
                    "fix_instructions": None,
                    "strengths": [],
                    "reasoning": "Mostly ok",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"]
        assert len(publish_calls) == 1
        assert publish_calls[0][0][1]["success"] is True


class TestLifecycle:
    @pytest.mark.asyncio
    async def test_start_subscribes(self, monkeypatch):
        director, bus, *_ = _make_director(monkeypatch)
        await director.start()
        channels = [c[0][0] for c in bus.subscribe.call_args_list]
        assert "audit.request" in channels

    @pytest.mark.asyncio
    async def test_stop_unsubscribes(self, monkeypatch):
        director, bus, *_ = _make_director(monkeypatch)
        await director.stop()
        channels = [c[0][0] for c in bus.unsubscribe.call_args_list]
        assert "audit.request" in channels


class TestRuleExtraction:
    @pytest.mark.asyncio
    async def test_extracts_rules_on_failure(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "fail",
                    "score": 0.2,
                    "goal_alignment": 0.3,
                    "confidence": 0.9,
                    "issues": [{"category": "validation", "description": "No validation"}],
                    "fix_instructions": "Add validation",
                    "strengths": [],
                    "reasoning": "Missing validation",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        rengine.extract_rules.assert_called_once()

    @pytest.mark.asyncio
    async def test_extracts_patterns_on_high_score(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.95,
                    "goal_alignment": 0.98,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": ["Excellent error handling"],
                    "reasoning": "Outstanding",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        rengine.extract_patterns.assert_called_once()


class TestAuditTimeout:
    @pytest.mark.asyncio
    async def test_timeout_returns_conditional_verdicts(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        task_id = uuid.uuid4()

        async def slow_audit(*args, **kwargs):
            import asyncio

            await asyncio.sleep(999)
            return {"verdict": "pass", "score": 0.9}

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(side_effect=slow_audit)
            mock_auditor_cls.return_value = mock_auditor

            # Set a very short timeout.
            director._settings.quality_audit_timeout_seconds = 0.01

            request = AuditRequest(
                task_id=task_id,
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="test",
                        content="output",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        publish_calls = [c for c in bus.publish.call_args_list if c[0][0] == "audit.complete"]
        assert len(publish_calls) == 1
        payload = publish_calls[0][0][1]
        # Timeout returns success=True because conditional is treated as pass
        assert payload["success"] is True
        assert payload["overall_score"] == pytest.approx(0.5)


class TestMetricCollectorIntegration:
    @pytest.mark.asyncio
    async def test_records_metrics_when_collector_provided(self, monkeypatch):
        settings = _make_settings(monkeypatch)
        llm = AsyncMock()
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()
        bus.publish = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        task_store = AsyncMock()
        quality_store = AsyncMock()
        quality_store.create_audit_report = AsyncMock()
        quality_store.record_verdict = AsyncMock()
        quality_store.get_pass_rate = AsyncMock(return_value=0.85)
        quality_store.get_avg_score = AsyncMock(return_value=0.80)
        rule_engine = AsyncMock()
        rule_engine.get_rules_for_audit = AsyncMock(return_value=[])
        state_manager = AsyncMock()
        from max.memory.models import CoordinatorState

        state_manager.load = AsyncMock(return_value=CoordinatorState())
        state_manager.save = AsyncMock()

        metric_collector = AsyncMock()
        metric_collector.record = AsyncMock()

        config = AgentConfig(name="quality_director", system_prompt="")
        director = QualityDirectorAgent(
            config=config,
            llm=llm,
            bus=bus,
            db=db,
            warm_memory=warm,
            settings=settings,
            task_store=task_store,
            quality_store=quality_store,
            rule_engine=rule_engine,
            state_manager=state_manager,
            metric_collector=metric_collector,
        )

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.85,
                    "goal_alignment": 0.9,
                    "confidence": 0.95,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": [],
                    "reasoning": "ok",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="t",
                        content="c",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        # Should have recorded audit_score and audit_duration_seconds
        assert metric_collector.record.call_count == 2
        metric_names = [c[0][0] for c in metric_collector.record.call_args_list]
        assert "audit_score" in metric_names
        assert "audit_duration_seconds" in metric_names


class TestModelWiring:
    def test_resolve_model_opus(self, monkeypatch):
        director, *_ = _make_director(monkeypatch)
        from max.llm.models import ModelType

        result = director._resolve_model("claude-opus-4-6")
        assert result == ModelType.OPUS

    def test_resolve_model_sonnet(self, monkeypatch):
        director, *_ = _make_director(monkeypatch)
        from max.llm.models import ModelType

        result = director._resolve_model("claude-sonnet-4-6")
        assert result == ModelType.SONNET

    def test_resolve_model_unknown_defaults_to_opus(self, monkeypatch):
        director, *_ = _make_director(monkeypatch)
        from max.llm.models import ModelType

        result = director._resolve_model("unknown-model")
        assert result == ModelType.OPUS


class TestLedgerRecording:
    @pytest.mark.asyncio
    async def test_records_verdict_to_ledger(self, monkeypatch):
        director, bus, llm, qstore, rengine, tstore, smgr = _make_director(monkeypatch)

        with patch("max.quality.director.AuditorAgent") as mock_auditor_cls:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(
                return_value={
                    "verdict": "pass",
                    "score": 0.8,
                    "goal_alignment": 0.85,
                    "confidence": 0.9,
                    "issues": [],
                    "fix_instructions": None,
                    "strengths": [],
                    "reasoning": "ok",
                }
            )
            mock_auditor_cls.return_value = mock_auditor

            request = AuditRequest(
                task_id=uuid.uuid4(),
                goal_anchor="Test",
                subtask_results=[
                    SubtaskAuditItem(
                        subtask_id=uuid.uuid4(),
                        description="t",
                        content="c",
                    ),
                ],
            )
            await director.on_audit_request("audit.request", request.model_dump(mode="json"))

        qstore.record_verdict.assert_called_once()
        qstore.create_audit_report.assert_called_once()
