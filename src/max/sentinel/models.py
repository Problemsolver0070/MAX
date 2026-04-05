"""Sentinel anti-degradation scoring system domain models."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from typing import Any

from pydantic import BaseModel, Field

# ── Benchmark Models ───────────────────────────────────────────────────


class BenchmarkScenario(BaseModel):
    """Structured scenario data for a benchmark test case."""

    system_prompt: str
    user_message: str
    context: dict[str, Any] = Field(default_factory=dict)


class Benchmark(BaseModel):
    """A fixed test case in the Sentinel benchmark suite."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    name: str
    category: str
    description: str
    scenario: dict[str, Any]
    evaluation_criteria: list[str]
    weight: float = Field(default=1.0, ge=0.0)
    version: int = 1
    active: bool = True
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Test Run Models ────────────────────────────────────────────────────


class TestRun(BaseModel):
    """A single execution of the Sentinel test suite."""

    __test__ = False

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID | None = None
    run_type: str
    status: str = "running"
    started_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    completed_at: datetime | None = None


class TestScore(BaseModel):
    """Score for a single benchmark within a test run."""

    __test__ = False

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    run_id: uuid.UUID
    benchmark_id: uuid.UUID
    score: float = Field(default=0.0, ge=0.0, le=1.0)
    criteria_scores: list[dict[str, Any]] = Field(default_factory=list)
    reasoning: str = ""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class CapabilityScore(BaseModel):
    """Aggregate score for a capability dimension within a test run."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    run_id: uuid.UUID
    capability: str
    aggregate_score: float = Field(default=0.0, ge=0.0, le=1.0)
    test_count: int = 0
    computed_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


# ── Regression Models ──────────────────────────────────────────────────


class TestRegression(BaseModel):
    """A regression detected in a single test case."""

    __test__ = False

    benchmark_id: uuid.UUID
    benchmark_name: str
    capability: str
    before_score: float
    after_score: float
    delta: float
    judge_reasoning: str


class CapabilityRegression(BaseModel):
    """A regression detected in a capability aggregate."""

    capability: str
    before_aggregate: float
    after_aggregate: float
    delta: float
    contributing_tests: list[str]


# ── Verdict Models ─────────────────────────────────────────────────────


class SentinelVerdict(BaseModel):
    """The Sentinel's final verdict on an evolution experiment."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID
    baseline_run_id: uuid.UUID
    candidate_run_id: uuid.UUID
    passed: bool
    test_regressions: list[TestRegression] = Field(default_factory=list)
    capability_regressions: list[CapabilityRegression] = Field(default_factory=list)
    summary: str = ""
    evaluated_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RevertEntry(BaseModel):
    """A single entry in the sentinel revert log."""

    id: uuid.UUID = Field(default_factory=uuid.uuid4)
    experiment_id: uuid.UUID
    verdict_id: uuid.UUID
    regression_type: str
    benchmark_name: str | None = None
    capability: str
    before_score: float
    after_score: float
    delta: float
    reason_detail: str
    logged_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class ScheduledRunSummary(BaseModel):
    """Summary of a scheduled monitoring run."""

    run_id: uuid.UUID
    capability_scores: dict[str, float]
    total_benchmarks: int
    completed_benchmarks: int
