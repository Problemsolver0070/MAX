"""Sentinel Anti-Degradation Scoring System.

Provides an independent scoring system that tests Max after every evolution
improvement using fixed benchmarks and real task replay. Enforces strict
per-test-case and per-capability non-regression, and logs detailed revert
reasons when regressions are detected.

Key components:

- **SentinelAgent** -- bus integration and scheduled monitoring
- **SentinelScorer** -- orchestrates baseline -> candidate -> verdict flow
- **TestRunner** -- executes benchmarks and replays via LLM-as-judge
- **ScoreComparator** -- detects regressions at both test and capability layers
- **BenchmarkRegistry** -- manages the fixed 28-benchmark suite
- **SentinelStore** -- async CRUD persistence for sentinel tables

All Pydantic domain models live in ``max.sentinel.models``.
"""

from max.sentinel.agent import SentinelAgent
from max.sentinel.benchmarks import BENCHMARKS, BenchmarkRegistry
from max.sentinel.comparator import ScoreComparator
from max.sentinel.models import (
    Benchmark,
    BenchmarkScenario,
    CapabilityRegression,
    CapabilityScore,
    RevertEntry,
    ScheduledRunSummary,
    SentinelVerdict,
    TestRegression,
    TestRun,
    TestScore,
)
from max.sentinel.runner import TestRunner
from max.sentinel.scorer import SentinelScorer
from max.sentinel.store import SentinelStore

__all__ = [
    # Agent
    "SentinelAgent",
    # Orchestrator
    "SentinelScorer",
    # Execution
    "TestRunner",
    # Comparison
    "ScoreComparator",
    # Registry
    "BenchmarkRegistry",
    "BENCHMARKS",
    # Persistence
    "SentinelStore",
    # Models -- benchmark
    "Benchmark",
    "BenchmarkScenario",
    # Models -- test run
    "TestRun",
    "TestScore",
    "CapabilityScore",
    # Models -- regression
    "TestRegression",
    "CapabilityRegression",
    # Models -- verdict
    "SentinelVerdict",
    "RevertEntry",
    "ScheduledRunSummary",
]
