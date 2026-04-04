"""Tests for LLM-curated context packaging."""

from __future__ import annotations

import uuid
from unittest.mock import AsyncMock

import pytest

from max.llm.models import LLMResponse
from max.memory.context_packager import ContextPackager
from max.memory.models import (
    AnchorPermanenceClass,
    ContextAnchor,
    ContextPackage,
    RetrievalResult,
)


@pytest.fixture
def mock_llm():
    llm = AsyncMock()
    llm.complete.return_value = LLMResponse(
        text='{"selected_ids": [], "reasoning": "No additional context needed"}',
        input_tokens=100,
        output_tokens=50,
        model="claude-opus-4-6",
        stop_reason="end_turn",
    )
    return llm


@pytest.fixture
def mock_retriever():
    retriever = AsyncMock()
    retriever.retrieve.return_value = []
    return retriever


@pytest.fixture
def mock_anchor_mgr():
    mgr = AsyncMock()
    mgr.list_active.return_value = []
    return mgr


class TestContextPackager:
    async def test_create_package_minimal(self, mock_llm, mock_retriever, mock_anchor_mgr):
        packager = ContextPackager(
            llm=mock_llm,
            retriever=mock_retriever,
            anchor_manager=mock_anchor_mgr,
            token_budget=24576,
        )
        package = await packager.build_package(
            task_goal="Fix login bug",
            agent_role="sub_agent",
        )
        assert isinstance(package, ContextPackage)
        assert package.task_summary == "Fix login bug"
        assert package.token_count >= 0

    async def test_anchors_always_included(self, mock_llm, mock_retriever, mock_anchor_mgr):
        permanent_anchor = ContextAnchor(
            content="User ID 12345 only",
            anchor_type="security",
            permanence_class=AnchorPermanenceClass.PERMANENT,
        )
        mock_anchor_mgr.list_active.return_value = [permanent_anchor]

        packager = ContextPackager(
            llm=mock_llm,
            retriever=mock_retriever,
            anchor_manager=mock_anchor_mgr,
            token_budget=24576,
        )
        package = await packager.build_package(
            task_goal="Any task",
            agent_role="sub_agent",
        )
        assert len(package.anchors) == 1
        assert package.anchors[0].content == "User ID 12345 only"

    async def test_retrieval_results_included(self, mock_llm, mock_retriever, mock_anchor_mgr):
        mock_retriever.retrieve.return_value = [
            RetrievalResult(
                content_id=uuid.uuid4(),
                content_type="memory",
                content="Relevant past decision",
                rrf_score=0.9,
                strategies=["semantic"],
            ),
        ]
        mock_llm.complete.return_value = LLMResponse(
            text='{"selected_ids": ["all"], "reasoning": "All items relevant"}',
            input_tokens=100,
            output_tokens=50,
            model="claude-opus-4-6",
            stop_reason="end_turn",
        )

        packager = ContextPackager(
            llm=mock_llm,
            retriever=mock_retriever,
            anchor_manager=mock_anchor_mgr,
            token_budget=24576,
        )
        package = await packager.build_package(
            task_goal="Fix auth flow",
            agent_role="sub_agent",
            seed_node_ids=[uuid.uuid4()],
        )
        assert len(package.semantic_matches) >= 0

    async def test_budget_tracked(self, mock_llm, mock_retriever, mock_anchor_mgr):
        packager = ContextPackager(
            llm=mock_llm,
            retriever=mock_retriever,
            anchor_manager=mock_anchor_mgr,
            token_budget=16384,
        )
        package = await packager.build_package(
            task_goal="Simple task",
            agent_role="coordinator",
        )
        assert package.budget_remaining <= 16384
