"""End-to-end integration tests for the Quality Gate pipeline.

Tests the full flow: Orchestrator -> audit.request -> Quality Director -> audit.complete -> Orchestrator -> tasks.complete.
All LLM calls are mocked. Bus publications are tracked and manually routed.
"""

import json
import uuid
from unittest.mock import AsyncMock, patch

import pytest

from max.agents.base import AgentConfig
from max.command.models import ExecutionPlan, PlannedSubtask, SubtaskResult
from max.command.orchestrator import OrchestratorAgent
from max.config import Settings
from max.llm.models import LLMResponse
from max.quality.director import QualityDirectorAgent
from max.quality.models import AuditRequest


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text, input_tokens=100, output_tokens=50,
        model="claude-opus-4-6", stop_reason="end_turn",
    )


class TestFullAuditPipeline:
    @pytest.mark.asyncio
    async def test_happy_path_with_audit(self, monkeypatch):
        """Orchestrator -> audit.request -> Director -> audit.complete -> tasks.complete."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def capture_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=capture_publish)

        llm = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        task_store = AsyncMock()
        runner = AsyncMock()
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

        # Create orchestrator
        orch_config = AgentConfig(name="orchestrator", system_prompt="")
        orch = OrchestratorAgent(
            config=orch_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, runner=runner,
        )

        # Create director
        dir_config = AgentConfig(name="quality_director", system_prompt="")
        director = QualityDirectorAgent(
            config=dir_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, quality_store=quality_store,
            rule_engine=rule_engine, state_manager=state_manager,
        )

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        # Setup: task_store returns subtasks
        task_store.get_subtasks = AsyncMock(return_value=[
            {"id": subtask_id, "description": "Write code", "phase_number": 1,
             "quality_criteria": {}, "status": "pending"},
        ])
        task_store.get_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Build feature",
            "quality_criteria": {}, "status": "in_progress",
        })
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())
        task_store.update_task_status = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.update_subtask_result = AsyncMock()

        # Setup: worker returns success
        runner.run = AsyncMock(return_value=SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="Hello world", confidence=0.9,
        ))

        # Step 1: Orchestrator receives execution plan
        plan = ExecutionPlan(
            task_id=task_id, goal_anchor="Build feature",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1, reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Verify audit.request was published
        audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        assert len(audit_reqs) == 1

        # Step 2: Route audit.request to Director
        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(return_value={
                "verdict": "pass", "score": 0.85, "goal_alignment": 0.9,
                "confidence": 0.95, "issues": [], "fix_instructions": None,
                "strengths": ["Clean code"], "reasoning": "Good",
            })
            MockAuditor.return_value = mock_auditor
            await director.on_audit_request("audit.request", audit_reqs[0][1])

        # Verify audit.complete was published
        audit_completes = [(ch, d) for ch, d in publications if ch == "audit.complete"]
        assert len(audit_completes) == 1
        assert audit_completes[0][1]["success"] is True

        # Step 3: Route audit.complete back to Orchestrator
        await orch.on_audit_complete("audit.complete", audit_completes[0][1])

        # Verify tasks.complete was published
        task_completes = [(ch, d) for ch, d in publications if ch == "tasks.complete"]
        assert len(task_completes) == 1
        assert task_completes[0][1]["success"] is True
        assert "Hello world" in task_completes[0][1]["result_content"]


class TestFixLoopPipeline:
    @pytest.mark.asyncio
    async def test_fix_and_reaudit(self, monkeypatch):
        """Test that a failed audit triggers a fix loop and re-audit."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def capture_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=capture_publish)

        llm = AsyncMock()
        db = AsyncMock()
        warm = AsyncMock()
        task_store = AsyncMock()
        runner = AsyncMock()
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

        dir_config = AgentConfig(name="quality_director", system_prompt="")
        director = QualityDirectorAgent(
            config=dir_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, quality_store=quality_store,
            rule_engine=rule_engine, state_manager=state_manager,
        )

        orch_config = AgentConfig(name="orchestrator", system_prompt="")
        orch = OrchestratorAgent(
            config=orch_config, llm=llm, bus=bus, db=db,
            warm_memory=warm, settings=settings,
            task_store=task_store, runner=runner,
        )

        task_id = uuid.uuid4()
        subtask_id = uuid.uuid4()

        task_store.get_task = AsyncMock(return_value={
            "id": task_id, "goal_anchor": "Build feature",
            "quality_criteria": {}, "status": "in_progress",
        })
        task_store.get_subtasks = AsyncMock(return_value=[
            {"id": subtask_id, "description": "Write code", "phase_number": 1,
             "quality_criteria": {}, "status": "pending"},
        ])
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())
        task_store.update_task_status = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.update_subtask_result = AsyncMock()

        # Worker initially returns "bad" content
        runner.run = AsyncMock(return_value=SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="bad output", confidence=0.8,
        ))

        # Step 1: Orchestrator executes plan
        plan = ExecutionPlan(
            task_id=task_id, goal_anchor="Build feature",
            subtasks=[PlannedSubtask(description="Write code", phase_number=1)],
            total_phases=1, reasoning="test",
        )
        await orch.on_execute("tasks.execute", plan.model_dump(mode="json"))

        # Step 2: Director audits — FAIL
        audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        with patch("max.quality.director.AuditorAgent") as MockAuditor:
            mock_auditor = AsyncMock()
            mock_auditor.run = AsyncMock(return_value={
                "verdict": "fail", "score": 0.3, "goal_alignment": 0.4,
                "confidence": 0.9, "issues": [{"category": "quality", "description": "Bad"}],
                "fix_instructions": "Make it better", "strengths": [], "reasoning": "Needs work",
            })
            MockAuditor.return_value = mock_auditor
            await director.on_audit_request("audit.request", audit_reqs[0][1])

        # Step 3: Orchestrator receives fail -> triggers fix loop
        audit_completes = [(ch, d) for ch, d in publications if ch == "audit.complete"]
        assert audit_completes[0][1]["success"] is False

        # Worker returns "fixed" content on second attempt
        runner.run = AsyncMock(return_value=SubtaskResult(
            subtask_id=subtask_id, task_id=task_id,
            success=True, content="fixed output", confidence=0.9,
        ))
        await orch.on_audit_complete("audit.complete", audit_completes[0][1])

        # Should have published a second audit.request
        all_audit_reqs = [(ch, d) for ch, d in publications if ch == "audit.request"]
        assert len(all_audit_reqs) == 2
