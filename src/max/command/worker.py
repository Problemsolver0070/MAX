"""WorkerAgent -- generic ephemeral subtask executor."""

from __future__ import annotations

import json
import logging
from typing import Any

from max.agents.base import AgentConfig, BaseAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)

WORKER_SYSTEM_PROMPT_TEMPLATE = """You are a worker agent for Max, an autonomous AI system.

Your task:
{description}

Context:
{context_summary}

Quality criteria:
{quality_criteria}

Return ONLY valid JSON:
{{
  "content": "Your work product -- the full result of the subtask",
  "confidence": 0.0 to 1.0,
  "reasoning": "Brief explanation of your approach"
}}"""


class WorkerAgent(BaseAgent):
    """Ephemeral agent that executes a single subtask via LLM reasoning."""

    def __init__(
        self,
        llm: LLMClient,
        system_prompt: str,
        model: ModelType = ModelType.OPUS,
        max_turns: int = 10,
    ) -> None:
        config = AgentConfig(
            name="worker",
            system_prompt=system_prompt,
            model=model,
            max_turns=max_turns,
        )
        super().__init__(config=config, llm=llm)

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Execute the subtask and return a result dict."""
        description = input_data.get("description", "")
        context_pkg = input_data.get("context_package", {})
        quality = input_data.get("quality_criteria", {})

        context_summary = json.dumps(context_pkg, indent=2) if context_pkg else "None provided"
        quality_str = json.dumps(quality, indent=2) if quality else "None specified"

        prompt = WORKER_SYSTEM_PROMPT_TEMPLATE.format(
            description=description,
            context_summary=context_summary,
            quality_criteria=quality_str,
        )

        self.reset()
        try:
            response = await self.think(
                messages=[{"role": "user", "content": f"Execute this subtask: {description}"}],
                system_prompt=prompt,
            )
            parsed = self._parse_response(response.text)
            return {
                "success": True,
                "content": parsed.get("content", response.text),
                "confidence": parsed.get("confidence", 0.5),
                "reasoning": parsed.get("reasoning", ""),
                "error": None,
            }
        except Exception as exc:
            logger.exception("Worker failed executing subtask")
            return {
                "success": False,
                "content": "",
                "confidence": 0.0,
                "reasoning": "",
                "error": str(exc),
            }

    @staticmethod
    def _parse_response(text: str) -> dict[str, Any]:
        """Parse JSON from LLM response, handling markdown code blocks."""
        text = text.strip()
        if "```" in text:
            parts = text.split("```")
            for part in parts:
                part = part.strip()
                if part.startswith("json"):
                    part = part[4:].strip()
                try:
                    return json.loads(part)
                except (json.JSONDecodeError, ValueError):
                    continue
        try:
            return json.loads(text)
        except (json.JSONDecodeError, ValueError):
            return {"content": text, "confidence": 0.5, "reasoning": ""}
