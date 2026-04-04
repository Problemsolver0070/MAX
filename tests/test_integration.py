import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from max.agents.base import AgentConfig, BaseAgent
from max.llm.client import LLMClient
from max.llm.models import LLMResponse
from max.models import Intent, Priority, Task
from max.tools.registry import ToolDefinition, ToolRegistry


class EchoAgent(BaseAgent):
    async def run(self, input_data: dict) -> dict:
        response = await self.think(
            messages=[{"role": "user", "content": input_data["message"]}],
        )
        return {"response": response.text}


@pytest.mark.asyncio
async def test_full_pipeline_smoke(db, warm_memory, bus):
    """Smoke test: config -> models -> bus -> warm memory -> db -> agent -> tool registry."""

    # 1. Create an intent (simulating Communicator receiving a message)
    intent = Intent(
        user_message="Write a Python hello world script",
        source_platform="telegram",
        goal_anchor="Write a Python hello world script",
        priority=Priority.NORMAL,
    )
    assert intent.id is not None

    # 2. Create a task from the intent (simulating Coordinator)
    task = Task(
        goal_anchor=intent.goal_anchor,
        source_intent_id=intent.id,
    )

    # 3. Persist task to PostgreSQL
    await db.execute(
        "INSERT INTO tasks (id, goal_anchor, source_intent_id, status) VALUES ($1, $2, $3, $4)",
        task.id, task.goal_anchor, task.source_intent_id, task.status.value,
    )
    row = await db.fetchone("SELECT * FROM tasks WHERE id = $1", task.id)
    assert row["goal_anchor"] == "Write a Python hello world script"

    # 4. Store coordinator state in warm memory
    state = {"active_tasks": [str(task.id)], "system_health": "ok"}
    await warm_memory.set("coordinator:state", state)
    retrieved_state = await warm_memory.get("coordinator:state")
    assert str(task.id) in retrieved_state["active_tasks"]

    # 5. Publish task event on message bus
    received = []

    async def on_task(channel, data):
        received.append(data)

    await bus.subscribe("tasks.new", on_task)
    await bus.start_listening()
    await asyncio.sleep(0.1)
    await bus.publish("tasks.new", {"task_id": str(task.id), "goal": task.goal_anchor})
    await asyncio.sleep(0.3)
    await bus.stop_listening()
    assert len(received) == 1
    assert received[0]["goal"] == "Write a Python hello world script"

    # 6. Create a mock LLM and run an agent
    mock_llm = MagicMock(spec=LLMClient)
    mock_llm.complete = AsyncMock(
        return_value=LLMResponse(
            text='print("Hello, World!")',
            input_tokens=50,
            output_tokens=10,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )
    )
    agent = EchoAgent(
        config=AgentConfig(name="code-writer", system_prompt="Write code."),
        llm=mock_llm,
    )
    result = await agent.run({"message": task.goal_anchor})
    assert "Hello, World!" in result["response"]

    # 7. Register and look up a tool
    registry = ToolRegistry()
    registry.register(ToolDefinition(
        tool_id="file.write",
        category="code",
        description="Write content to a file",
        permissions=["fs.write"],
        input_schema={
            "type": "object",
            "properties": {
                "path": {"type": "string"},
                "content": {"type": "string"},
            },
            "required": ["path", "content"],
        },
    ))
    tools = registry.to_anthropic_tools(["file.write"])
    assert len(tools) == 1
    assert tools[0]["name"] == "file.write"
