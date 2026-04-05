"""Phase 7: Self-Evolution System.

Provides the complete self-evolution pipeline for the Max AI agent system.
The evolution system discovers improvement opportunities via scout agents,
implements changes through an improvement agent, validates them with canary
testing, and promotes or rolls back changes automatically.

Key components:

- **EvolutionDirectorAgent** -- orchestrates the full pipeline
- **Scouts** (BaseScout, ToolScout, PatternScout, QualityScout, EcosystemScout)
  -- discover evolution proposals by analysing system state via LLM
- **ImprovementAgent** -- converts proposals into concrete change sets
- **CanaryRunner** -- replays tasks under candidate configuration to detect regressions
- **SnapshotManager** -- captures and restores system state around experiments
- **SelfModel** -- maintains the system's self-awareness model
- **PreferenceProfileManager** -- learns and applies user preferences over time
- **EvolutionStore** -- async CRUD persistence for all evolution tables

All Pydantic domain models live in ``max.evolution.models``.
"""

from max.evolution.canary import CanaryRunner
from max.evolution.director import EvolutionDirectorAgent
from max.evolution.improver import ImprovementAgent
from max.evolution.models import (
    CanaryRequest,
    CanaryResult,
    CanaryTaskResult,
    ChangeSet,
    ChangeSetEntry,
    CodePrefs,
    CommunicationPrefs,
    DomainPrefs,
    EvolutionJournalEntry,
    EvolutionProposal,
    Observation,
    PreferenceProfile,
    PromotionEvent,
    RollbackEvent,
    SnapshotData,
    WorkflowPrefs,
)
from max.evolution.preference import PreferenceProfileManager
from max.evolution.scouts import (
    BaseScout,
    EcosystemScout,
    PatternScout,
    QualityScout,
    ToolScout,
)
from max.evolution.self_model import SelfModel
from max.evolution.snapshot import SnapshotManager
from max.evolution.store import EvolutionStore

__all__ = [
    # Core orchestrator
    "EvolutionDirectorAgent",
    # Agents
    "ImprovementAgent",
    "CanaryRunner",
    # Scouts
    "BaseScout",
    "ToolScout",
    "PatternScout",
    "QualityScout",
    "EcosystemScout",
    # Managers
    "PreferenceProfileManager",
    "SnapshotManager",
    "SelfModel",
    # Persistence
    "EvolutionStore",
    # Models -- preference
    "CommunicationPrefs",
    "CodePrefs",
    "DomainPrefs",
    "WorkflowPrefs",
    "Observation",
    "PreferenceProfile",
    # Models -- pipeline
    "EvolutionProposal",
    "ChangeSetEntry",
    "ChangeSet",
    "SnapshotData",
    # Models -- canary
    "CanaryRequest",
    "CanaryTaskResult",
    "CanaryResult",
    # Models -- events
    "PromotionEvent",
    "RollbackEvent",
    # Models -- self-model
    "EvolutionJournalEntry",
]
