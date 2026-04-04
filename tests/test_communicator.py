# tests/test_communicator.py
"""Tests for CommunicatorAgent — intent parsing, commands, batching, urgency."""

from __future__ import annotations

import json
import uuid
from unittest.mock import AsyncMock

import pytest

from max.agents.base import AgentConfig
from max.comm.communicator import CommunicatorAgent
from max.comm.models import (
    InboundMessage,
    MessageType,
    OutboundMessage,
    UrgencyLevel,
)
from max.config import Settings
from max.llm.models import LLMResponse, ModelType


def _make_settings(monkeypatch) -> Settings:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test-key")
    monkeypatch.setenv("POSTGRES_PASSWORD", "test")
    return Settings()


def _make_communicator(
    monkeypatch,
    llm_response_text: str = "",
) -> tuple[CommunicatorAgent, AsyncMock, AsyncMock, AsyncMock]:
    settings = _make_settings(monkeypatch)
    llm = AsyncMock()
    llm.complete = AsyncMock(
        return_value=LLMResponse(
            text=llm_response_text,
            input_tokens=100,
            output_tokens=50,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )
    )
    bus = AsyncMock()
    bus.publish = AsyncMock()
    bus.subscribe = AsyncMock()
    db = AsyncMock()
    db.execute = AsyncMock()
    db.fetchall = AsyncMock(return_value=[])
    warm = AsyncMock()
    warm.get = AsyncMock(return_value=None)
    warm.set = AsyncMock()

    config = AgentConfig(
        name="communicator",
        system_prompt="You are the Communicator for Max.",
        model=ModelType.OPUS,
        max_turns=1000,
    )
    agent = CommunicatorAgent(
        config=config,
        llm=llm,
        bus=bus,
        db=db,
        warm_memory=warm,
        settings=settings,
    )
    return agent, llm, bus, db


class TestIntentParsing:
    @pytest.mark.asyncio
    async def test_parse_simple_intent(self, monkeypatch):
        response_json = json.dumps(
            {
                "goal_anchor": "Deploy the application to production",
                "priority": "normal",
                "is_correction": False,
                "correction_domain": None,
                "requires_clarification": False,
                "clarification_question": None,
            }
        )
        agent, llm, bus, db = _make_communicator(monkeypatch, response_json)

        msg = InboundMessage(
            platform="telegram",
            platform_message_id=1,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="Deploy the app to production",
        )
        await agent.handle_inbound(msg)
        # Should publish to intents.new
        channel_names = [call.args[0] for call in bus.publish.call_args_list]
        assert "intents.new" in channel_names

    @pytest.mark.asyncio
    async def test_parse_correction_triggers_re_eval(self, monkeypatch):
        response_json = json.dumps(
            {
                "goal_anchor": "Actually use Python not Go",
                "priority": "high",
                "is_correction": True,
                "correction_domain": "approach",
                "requires_clarification": False,
                "clarification_question": None,
            }
        )
        agent, llm, bus, db = _make_communicator(monkeypatch, response_json)

        msg = InboundMessage(
            platform="telegram",
            platform_message_id=2,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="Actually use Python not Go",
        )
        await agent.handle_inbound(msg)

        # Should publish both intent and anchor re-evaluation
        channel_names = [call.args[0] for call in bus.publish.call_args_list]
        assert "intents.new" in channel_names
        assert "anchors.re_evaluate" in channel_names

    @pytest.mark.asyncio
    async def test_parse_clarification_needed(self, monkeypatch):
        response_json = json.dumps(
            {
                "goal_anchor": "",
                "priority": "normal",
                "is_correction": False,
                "correction_domain": None,
                "requires_clarification": True,
                "clarification_question": "Which database should I use?",
            }
        )
        agent, llm, bus, db = _make_communicator(monkeypatch, response_json)
        sent_messages: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent_messages.append(m)))

        msg = InboundMessage(
            platform="telegram",
            platform_message_id=3,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="Set up a database",
        )
        await agent.handle_inbound(msg)

        # Should NOT publish an intent
        intent_publishes = [c for c in bus.publish.call_args_list if c.args[0] == "intents.new"]
        assert len(intent_publishes) == 0
        # Should send clarification back
        assert len(sent_messages) == 1
        assert "Which database" in sent_messages[0].text

    @pytest.mark.asyncio
    async def test_fallback_on_bad_json(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch, "not valid json at all")

        msg = InboundMessage(
            platform="telegram",
            platform_message_id=4,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="Do something",
        )
        await agent.handle_inbound(msg)

        # Should still publish an intent with fallback
        channel_names = [call.args[0] for call in bus.publish.call_args_list]
        assert "intents.new" in channel_names


class TestCommandHandling:
    @pytest.mark.asyncio
    async def test_help_command(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=5,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.COMMAND,
            command="help",
        )
        result = await agent.handle_command(msg)
        assert result is not None
        assert "/status" in result.text
        assert "/help" in result.text

    @pytest.mark.asyncio
    async def test_quiet_command(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=6,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.COMMAND,
            command="quiet",
        )
        result = await agent.handle_command(msg)
        assert result is not None
        assert agent._quiet_mode is True

    @pytest.mark.asyncio
    async def test_verbose_command(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        agent._quiet_mode = True
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=7,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.COMMAND,
            command="verbose",
        )
        result = await agent.handle_command(msg)
        assert result is not None
        assert agent._quiet_mode is False

    @pytest.mark.asyncio
    async def test_unknown_command_returns_none(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=8,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.COMMAND,
            command="nonexistent",
        )
        result = await agent.handle_command(msg)
        assert result is None


class TestUrgencyClassification:
    @pytest.mark.asyncio
    async def test_result_urgency_important(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        await agent.on_result(
            "results.new",
            {
                "id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "content": "Done",
                "confidence": 0.9,
                "artifacts": [],
            },
        )
        assert len(sent) == 1
        assert sent[0].urgency == UrgencyLevel.IMPORTANT

    @pytest.mark.asyncio
    async def test_status_update_urgency_silent(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        await agent.on_status_update(
            "status_updates.new",
            {
                "id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "message": "Working...",
                "progress": 0.3,
            },
        )
        # SILENT messages go to batch, not sent immediately
        assert len(sent) == 0
        assert len(agent._pending_batch) == 1

    @pytest.mark.asyncio
    async def test_status_update_high_progress_is_normal(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        await agent.on_status_update(
            "status_updates.new",
            {
                "id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "message": "Almost done",
                "progress": 0.85,
            },
        )
        # progress > 0.8 → NORMAL → sent immediately
        assert len(sent) == 1

    @pytest.mark.asyncio
    async def test_clarification_urgency_important(self, monkeypatch):
        agent, llm, bus, db = _make_communicator(monkeypatch)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        await agent.on_clarification(
            "clarifications.new",
            {
                "id": str(uuid.uuid4()),
                "task_id": str(uuid.uuid4()),
                "question": "Which env?",
                "options": ["staging", "prod"],
            },
        )
        assert len(sent) == 1
        assert sent[0].urgency == UrgencyLevel.IMPORTANT


class TestBatching:
    @pytest.mark.asyncio
    async def test_batch_flush_on_max_size(self, monkeypatch):
        monkeypatch.setenv("COMM_MAX_BATCH_SIZE", "3")
        agent, llm, bus, db = _make_communicator(monkeypatch)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))
        agent._settings.comm_max_batch_size = 3

        for i in range(3):
            await agent.on_status_update(
                "status_updates.new",
                {
                    "id": str(uuid.uuid4()),
                    "task_id": str(uuid.uuid4()),
                    "message": f"Step {i}",
                    "progress": 0.1 * i,
                },
            )

        # Batch should have auto-flushed at size 3
        assert len(agent._pending_batch) == 0
        assert len(sent) == 1
        assert "<b>Updates</b>" in sent[0].text

    @pytest.mark.asyncio
    async def test_batch_flush_on_inbound(self, monkeypatch):
        response_json = json.dumps(
            {
                "goal_anchor": "New task",
                "priority": "normal",
                "is_correction": False,
                "correction_domain": None,
                "requires_clarification": False,
                "clarification_question": None,
            }
        )
        agent, llm, bus, db = _make_communicator(monkeypatch, response_json)
        sent: list[OutboundMessage] = []
        agent.set_send_callback(AsyncMock(side_effect=lambda m: sent.append(m)))

        # Add something to the batch
        agent._pending_batch.append(
            OutboundMessage(chat_id=100, text="Batched update", urgency=UrgencyLevel.SILENT)
        )

        # User sends a new message → should flush batch
        msg = InboundMessage(
            platform="telegram",
            platform_message_id=10,
            platform_chat_id=100,
            platform_user_id=200,
            message_type=MessageType.TEXT,
            text="What's happening?",
        )
        await agent.handle_inbound(msg)

        # Batch should be flushed (sent)
        assert len(agent._pending_batch) == 0
