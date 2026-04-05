"""AuditorAgent -- blind audit of subtask outputs."""

from __future__ import annotations

import json
import logging
from typing import Any

from max.agents.base import AgentConfig, BaseAgent
from max.llm.client import LLMClient
from max.llm.models import ModelType

logger = logging.getLogger(__name__)

AUDITOR_SYSTEM_PROMPT_TEMPLATE = (
    "You are a Quality Auditor for Max, an autonomous AI agent system.\n"
    "\n"
    "Your job: evaluate work output against the stated goal and quality criteria.\n"
    "You must be objective, thorough, and fair.\n"
    "\n"
    "Goal: {goal_anchor}\n"
    "Subtask: {subtask_description}\n"
    "Quality Criteria: {quality_criteria}\n"
    "\n"
    "Active Quality Rules (learned from past audits):\n"
    "{quality_rules}\n"
    "\n"
    "Evaluate the following work output and return ONLY valid JSON:\n"
    "{{\n"
    '  "verdict": "pass | fail | conditional",\n'
    '  "score": 0.0 to 1.0,\n'
    '  "goal_alignment": 0.0 to 1.0,\n'
    '  "confidence": 0.0 to 1.0,\n'
    '  "issues": [{{"category": "...", "description": "...", '
    '"severity": "low|normal|high|critical"}}],\n'
    '  "fix_instructions": "Specific instructions for fixing issues '
    '(only if verdict is fail)",\n'
    '  "strengths": ["What was done well"],\n'
    '  "reasoning": "Your evaluation reasoning"\n'
    "}}\n"
    "\n"
    "Scoring guidelines:\n"
    "- score: overall quality (0.0 = terrible, 1.0 = perfect)\n"
    "- goal_alignment: how well the output achieves the stated goal\n"
    "- confidence: how confident you are in your assessment\n"
    '- verdict: "pass" if score >= 0.7 and no critical issues, '
    '"fail" if score < 0.5 or any critical issue, '
    '"conditional" otherwise'
)


class AuditorAgent(BaseAgent):
    """Ephemeral agent that audits a single subtask's output.

    Receives only the work product, goal, and criteria -- never the
    worker's reasoning or confidence (blind audit protocol).
    """

    def __init__(
        self,
        llm: LLMClient,
        model: ModelType = ModelType.OPUS,
    ) -> None:
        config = AgentConfig(
            name="auditor",
            system_prompt="",
            model=model,
            max_turns=3,
        )
        super().__init__(config=config, llm=llm)

    async def run(self, input_data: dict[str, Any]) -> dict[str, Any]:
        """Audit a subtask output and return a verdict dict."""
        goal_anchor = input_data.get("goal_anchor", "")
        subtask_description = input_data.get("subtask_description", "")
        content = input_data.get("content", "")
        quality_criteria = input_data.get("quality_criteria", {})
        quality_rules = input_data.get("quality_rules", [])

        criteria_str = (
            json.dumps(quality_criteria, indent=2) if quality_criteria else "None specified"
        )
        rules_str = "\n".join(f"- {r['rule']}" for r in quality_rules) if quality_rules else "None"

        prompt = AUDITOR_SYSTEM_PROMPT_TEMPLATE.format(
            goal_anchor=goal_anchor,
            subtask_description=subtask_description,
            quality_criteria=criteria_str,
            quality_rules=rules_str,
        )

        self.reset()
        try:
            response = await self.think(
                messages=[
                    {
                        "role": "user",
                        "content": f"Evaluate this work output:\n\n{content}",
                    }
                ],
                system_prompt=prompt,
            )
            parsed = self._parse_response(response.text)
            return {
                "verdict": parsed.get("verdict", "conditional"),
                "score": parsed.get("score", 0.5),
                "goal_alignment": parsed.get("goal_alignment", 0.5),
                "confidence": parsed.get("confidence", 0.5),
                "issues": parsed.get("issues", []),
                "fix_instructions": parsed.get("fix_instructions"),
                "strengths": parsed.get("strengths", []),
                "reasoning": parsed.get("reasoning", ""),
            }
        except Exception as exc:
            logger.exception("Auditor failed")
            return {
                "verdict": "conditional",
                "score": 0.5,
                "goal_alignment": 0.5,
                "confidence": 0.3,
                "issues": [],
                "fix_instructions": None,
                "strengths": [],
                "reasoning": "Audit failed due to error",
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
            return {
                "verdict": "conditional",
                "score": 0.5,
                "goal_alignment": 0.5,
                "confidence": 0.3,
                "issues": [],
                "reasoning": "Failed to parse auditor response",
            }
