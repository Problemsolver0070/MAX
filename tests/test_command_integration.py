"""End-to-end integration test for the Command Chain pipeline.

Tests the full flow: intent -> Coordinator -> Planner -> Orchestrator -> Workers -> result.
All LLM calls are mocked. Bus publications are tracked and manually routed.
"""

import json
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.agents.base import AgentConfig
from max.command.coordinator import CoordinatorAgent
from max.command.orchestrator import OrchestratorAgent
from max.command.planner import PlannerAgent
from max.command.runner import InProcessRunner
from max.config import Settings
from max.llm.models import LLMResponse, ModelType


def _make_settings(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_llm_response(data: dict | str) -> LLMResponse:
    text = json.dumps(data) if isinstance(data, dict) else data
    return LLMResponse(
        text=text,
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )


class TestFullPipeline:
    @pytest.mark.asyncio
    async def test_intent_to_result_happy_path(self, monkeypatch):
        """Full pipeline: intent -> coordinator -> planner -> orchestrator -> result."""
        settings = _make_settings(monkeypatch)

        # Track all bus publications
        publications: list[tuple[str, dict]] = []

        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def mock_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=mock_publish)

        db = AsyncMock()
        warm = AsyncMock()

        # Set up coordinator LLM -- classifies as create_task
        coordinator_llm = AsyncMock()
        coordinator_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "action": "create_task",
                    "goal_anchor": "Summarize Python 3.13 features",
                    "priority": "normal",
                    "quality_criteria": {},
                    "reasoning": "New research request",
                }
            )
        )

        # Set up planner LLM -- decomposes into 2 subtasks
        planner_llm = AsyncMock()
        planner_llm.complete = AsyncMock(
            return_value=_make_llm_response(
                {
                    "subtasks": [
                        {
                            "description": "Research Python 3.13 features",
                            "phase_number": 1,
                            "tool_categories": [],
                            "quality_criteria": {},
                            "estimated_complexity": "low",
                        },
                        {
                            "description": "Write summary",
                            "phase_number": 2,
                            "tool_categories": [],
                            "quality_criteria": {},
                            "estimated_complexity": "moderate",
                        },
                    ],
                    "needs_clarification": False,
                    "reasoning": "Research then summarize",
                }
            )
        )

        # Set up worker LLM -- returns results
        worker_llm = AsyncMock()
        worker_call_count = 0

        async def worker_complete(**kwargs):
            nonlocal worker_call_count
            worker_call_count += 1
            if worker_call_count == 1:
                return _make_llm_response(
                    {
                        "content": "Python 3.13 has better error messages and JIT.",
                        "confidence": 0.85,
                        "reasoning": "Based on PEPs",
                    }
                )
            return _make_llm_response(
                {
                    "content": (
                        "Summary: Python 3.13 brings improved error messages"
                        " and experimental JIT compiler."
                    ),
                    "confidence": 0.9,
                    "reasoning": "Synthesized from research",
                }
            )

        worker_llm.complete = AsyncMock(side_effect=worker_complete)

        # Build components
        task_store = AsyncMock()
        intent_id = uuid.uuid4()
        task_id = uuid.uuid4()
        s1_id, s2_id = uuid.uuid4(), uuid.uuid4()

        task_store.create_task = AsyncMock(
            return_value={
                "id": task_id,
                "goal_anchor": "Summarize Python 3.13 features",
                "status": "pending",
                "priority": "normal",
            }
        )
        task_store.update_task_status = AsyncMock()
        task_store.get_task = AsyncMock(
            return_value={
                "id": task_id,
                "goal_anchor": "Summarize Python 3.13 features",
            }
        )
        task_store.create_subtask = AsyncMock(
            side_effect=[
                {
                    "id": s1_id,
                    "description": "Research",
                    "phase_number": 1,
                    "status": "pending",
                },
                {
                    "id": s2_id,
                    "description": "Write summary",
                    "phase_number": 2,
                    "status": "pending",
                },
            ]
        )
        task_store.get_subtasks = AsyncMock(
            return_value=[
                {
                    "id": s1_id,
                    "description": "Research Python 3.13 features",
                    "phase_number": 1,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
                {
                    "id": s2_id,
                    "description": "Write summary",
                    "phase_number": 2,
                    "tool_categories": [],
                    "quality_criteria": {},
                    "status": "pending",
                },
            ]
        )
        task_store.update_subtask_result = AsyncMock()
        task_store.update_subtask_status = AsyncMock()
        task_store.create_result = AsyncMock(return_value=uuid.uuid4())

        state_mgr = AsyncMock()
        state_mgr.load = AsyncMock(
            return_value=MagicMock(
                active_tasks=[],
                task_queue=[],
                model_dump=MagicMock(return_value={}),
            )
        )
        state_mgr.save = AsyncMock()

        runner = InProcessRunner(llm=worker_llm)

        coordinator = CoordinatorAgent(
            config=AgentConfig(name="coordinator", system_prompt="", model=ModelType.OPUS),
            llm=coordinator_llm,
            bus=bus,
            db=db,
            warm_memory=warm,
            settings=settings,
            state_manager=state_mgr,
            task_store=task_store,
        )

        planner = PlannerAgent(
            config=AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS),
            llm=planner_llm,
            bus=bus,
            db=db,
            warm_memory=warm,
            settings=settings,
            task_store=task_store,
        )

        orchestrator = OrchestratorAgent(
            config=AgentConfig(name="orchestrator", system_prompt="", model=ModelType.OPUS),
            llm=AsyncMock(),
            bus=bus,
            db=db,
            warm_memory=warm,
            settings=settings,
            task_store=task_store,
            runner=runner,
        )

        # Run the pipeline manually (in production, bus routes between agents)
        # Step 1: Coordinator receives intent
        intent_data = {
            "id": str(intent_id),
            "user_message": "Research and summarize Python 3.13 features",
            "source_platform": "telegram",
            "goal_anchor": "Summarize Python 3.13 features",
            "priority": "normal",
        }
        await coordinator.on_intent("intents.new", intent_data)

        # Step 2: Find the tasks.plan publication and feed to planner
        plan_pub = next((ch, d) for ch, d in publications if ch == "tasks.plan")
        await planner.on_task_plan("tasks.plan", plan_pub[1])

        # Step 3: Find the tasks.execute publication and feed to orchestrator
        exec_pub = next((ch, d) for ch, d in publications if ch == "tasks.execute")
        await orchestrator.on_execute("tasks.execute", exec_pub[1])

        # Step 3b: After audit integration, successful execution publishes
        # audit.request instead of tasks.complete.  Simulate the audit passing.
        audit_pub = next((ch, d) for ch, d in publications if ch == "audit.request")
        assert audit_pub is not None

        # Simulate audit.complete with pass verdict for all subtasks
        audit_items = audit_pub[1]["subtask_results"]
        audit_response = {
            "task_id": audit_pub[1]["task_id"],
            "success": True,
            "verdicts": [
                {
                    "subtask_id": item["subtask_id"],
                    "verdict": "pass",
                    "score": 0.9,
                    "goal_alignment": 0.9,
                    "issues": [],
                }
                for item in audit_items
            ],
            "overall_score": 0.9,
            "fix_required": [],
        }
        await orchestrator.on_audit_complete("audit.complete", audit_response)

        # Step 4: Find the tasks.complete publication and feed back to coordinator
        complete_pub = next((ch, d) for ch, d in publications if ch == "tasks.complete")
        await coordinator.on_task_complete("tasks.complete", complete_pub[1])

        # Verify the full flow produced a result
        result_pubs = [(ch, d) for ch, d in publications if ch == "results.new"]
        assert len(result_pubs) == 1
        result_data = result_pubs[0][1]
        assert "Python 3.13" in result_data["content"]
        assert result_data["confidence"] > 0.0

        # Verify status updates were published
        status_pubs = [(ch, d) for ch, d in publications if ch == "status_updates.new"]
        assert len(status_pubs) >= 2  # At least planning + phase progress


class TestClarificationPipeline:
    @pytest.mark.asyncio
    async def test_clarification_flow(self, monkeypatch):
        """Test: ambiguous intent -> clarification -> resume -> result."""
        settings = _make_settings(monkeypatch)
        publications: list[tuple[str, dict]] = []
        bus = AsyncMock()
        bus.subscribe = AsyncMock()
        bus.unsubscribe = AsyncMock()

        async def mock_publish(channel, data):
            publications.append((channel, data))

        bus.publish = AsyncMock(side_effect=mock_publish)
        db = AsyncMock()
        warm = AsyncMock()

        # Planner LLM: first asks for clarification, then decomposes
        call_count = 0
        planner_llm = AsyncMock()

        async def planner_complete(**kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_llm_response(
                    {
                        "subtasks": [],
                        "needs_clarification": True,
                        "clarification_question": "Which app?",
                        "clarification_options": ["App A", "App B"],
                        "reasoning": "Ambiguous",
                    }
                )
            return _make_llm_response(
                {
                    "subtasks": [
                        {
                            "description": "Deploy App A",
                            "phase_number": 1,
                            "tool_categories": [],
                            "quality_criteria": {},
                            "estimated_complexity": "moderate",
                        },
                    ],
                    "needs_clarification": False,
                    "reasoning": "Clear after clarification",
                }
            )

        planner_llm.complete = AsyncMock(side_effect=planner_complete)

        task_store = AsyncMock()
        task_id = uuid.uuid4()
        task_store.create_subtask = AsyncMock(
            return_value={
                "id": uuid.uuid4(),
                "description": "Deploy App A",
                "phase_number": 1,
                "status": "pending",
            }
        )

        planner = PlannerAgent(
            config=AgentConfig(name="planner", system_prompt="", model=ModelType.OPUS),
            llm=planner_llm,
            bus=bus,
            db=db,
            warm_memory=warm,
            settings=settings,
            task_store=task_store,
        )

        # Step 1: Plan request triggers clarification
        await planner.on_task_plan(
            "tasks.plan",
            {
                "task_id": str(task_id),
                "goal_anchor": "Deploy the thing",
                "priority": "normal",
                "quality_criteria": {},
            },
        )

        clarification_pubs = [(ch, d) for ch, d in publications if ch == "clarifications.new"]
        assert len(clarification_pubs) == 1
        assert "Which app?" in clarification_pubs[0][1]["question"]

        # Step 2: User answers, resume planning
        await planner.on_clarification_response(
            "clarifications.response",
            {
                "task_id": str(task_id),
                "answer": "App A",
            },
        )

        exec_pubs = [(ch, d) for ch, d in publications if ch == "tasks.execute"]
        assert len(exec_pubs) == 1
        assert "Deploy App A" in json.dumps(exec_pubs[0][1])
