"""TestRunner -- executes Sentinel benchmarks and replays via LLM-as-judge."""

from __future__ import annotations

import json
import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from max.evolution.store import EvolutionStore
    from max.llm.client import LLMClient
    from max.quality.store import QualityStore

logger = logging.getLogger(__name__)

JUDGE_PROMPT = """\
You are an independent quality evaluator for an AI agent system.

Evaluate the following agent response against these criteria:
{criteria}

Scenario: {scenario}
Agent Response: {response}

For each criterion, provide:
- score (0.0-1.0)
- reasoning (1-2 sentences)

Then provide an overall_score (0.0-1.0) that reflects how well the response \
meets ALL criteria.

Respond in JSON:
{{"criteria_scores": [{{"criterion": "<name>", "score": <float>, "reasoning": "<text>"}}], \
"overall_score": <float>, "overall_reasoning": "<text>"}}
"""

REPLAY_JUDGE_PROMPT = """\
You are an independent quality evaluator. Evaluate the quality of this \
task output.

Task goal: {goal}
Subtask: {description}
Output: {output}

Evaluation criteria:
- Correctness: Does the output achieve the subtask goal?
- Completeness: Is the output thorough?
- Quality: Is the output well-structured and clear?

Respond in JSON:
{{"criteria_scores": [{{"criterion": "<name>", "score": <float>, "reasoning": "<text>"}}], \
"overall_score": <float>, "overall_reasoning": "<text>"}}
"""


class TestRunner:
    """Executes Sentinel benchmarks and replay tests via LLM-as-judge."""

    def __init__(
        self,
        llm: LLMClient,
        task_store: Any,
        quality_store: QualityStore,
        evo_store: EvolutionStore,
    ) -> None:
        self._llm = llm
        self._task_store = task_store
        self._quality_store = quality_store
        self._evo_store = evo_store

    async def run_benchmark(
        self, benchmark: dict[str, Any]
    ) -> dict[str, Any]:
        """Run a single benchmark and return the score dict.

        Returns {score, criteria_scores, reasoning} with score=0.0 on error.
        """
        try:
            scenario = benchmark["scenario"]
            system_prompt = scenario.get("system_prompt", "You are an AI assistant.")
            user_message = scenario.get("user_message", json.dumps(scenario))

            # Step 1: Get agent response
            agent_response = await self._llm.complete(
                messages=[
                    {"role": "user", "content": user_message},
                ],
                system=system_prompt,
            )

            # Step 2: Judge the response
            criteria_text = "\n".join(
                f"- {c}" for c in benchmark["evaluation_criteria"]
            )
            judge_prompt = JUDGE_PROMPT.format(
                criteria=criteria_text,
                scenario=json.dumps(scenario, indent=2),
                response=agent_response.text,
            )
            judge_response = await self._llm.complete(
                messages=[{"role": "user", "content": judge_prompt}],
            )

            result = self._parse_judge_response(judge_response.text)
            return {
                "score": max(0.0, min(1.0, result["overall_score"])),
                "criteria_scores": result["criteria_scores"],
                "reasoning": result.get("overall_reasoning", ""),
            }

        except Exception:
            logger.error(
                "Benchmark %s failed", benchmark.get("name", "unknown"),
                exc_info=True,
            )
            return {"score": 0.0, "criteria_scores": [], "reasoning": "Execution error"}

    async def run_replay(
        self,
        task: dict[str, Any],
        subtasks: list[dict[str, Any]],
    ) -> dict[str, Any]:
        """Re-evaluate a historical task's outputs and return a score dict.

        Returns {score, criteria_scores, reasoning} with score=0.0 on error.
        """
        try:
            task_id = task["id"]
            goal = task.get("goal_anchor", "")

            if not subtasks:
                reports = await self._quality_store.get_audit_reports(task_id)
                original = (
                    sum(float(r.get("score", 0.0)) for r in reports) / len(reports)
                    if reports
                    else 0.0
                )
                return {"score": original, "criteria_scores": [], "reasoning": "No subtasks to evaluate"}

            subtask_scores: list[float] = []
            all_criteria: list[dict[str, Any]] = []

            for subtask in subtasks:
                result = subtask.get("result", {})
                output = result.get("output", "") if isinstance(result, dict) else str(result)
                description = subtask.get("description", "")

                judge_prompt = REPLAY_JUDGE_PROMPT.format(
                    goal=goal,
                    description=description,
                    output=output or "(no output)",
                )
                judge_response = await self._llm.complete(
                    messages=[{"role": "user", "content": judge_prompt}],
                )
                parsed = self._parse_judge_response(judge_response.text)
                subtask_scores.append(max(0.0, min(1.0, parsed["overall_score"])))
                all_criteria.extend(parsed["criteria_scores"])

            avg_score = sum(subtask_scores) / len(subtask_scores) if subtask_scores else 0.0
            return {
                "score": avg_score,
                "criteria_scores": all_criteria,
                "reasoning": f"Average of {len(subtask_scores)} subtask evaluations",
            }

        except Exception:
            logger.error(
                "Replay for task %s failed", task.get("id", "unknown"),
                exc_info=True,
            )
            return {"score": 0.0, "criteria_scores": [], "reasoning": "Replay error"}

    async def get_replay_tasks(self, limit: int = 10) -> list[dict[str, Any]]:
        """Get recent completed tasks for replay."""
        return await self._task_store.get_completed_tasks(limit=limit)

    def _parse_judge_response(self, text: str) -> dict[str, Any]:
        """Parse LLM judge response, handling markdown fences.

        Returns a dict with overall_score, criteria_scores, overall_reasoning.
        Defaults to score 0.0 on parse failure.
        """
        cleaned = text.strip()
        fence_match = re.search(
            r"```(?:json)?\s*\n?(.*?)\n?\s*```", cleaned, re.DOTALL
        )
        if fence_match:
            cleaned = fence_match.group(1).strip()
        try:
            data = json.loads(cleaned)
            return {
                "overall_score": float(data.get("overall_score", 0.0)),
                "criteria_scores": data.get("criteria_scores", []),
                "overall_reasoning": data.get("overall_reasoning", ""),
            }
        except (json.JSONDecodeError, ValueError, TypeError):
            return {
                "overall_score": 0.0,
                "criteria_scores": [],
                "overall_reasoning": "Parse error",
            }
