"""Tests for memory graph layer."""

from __future__ import annotations

import uuid

import pytest

from max.db.postgres import Database
from max.memory.graph import MemoryGraph
from max.memory.models import EdgeRelation


@pytest.fixture
async def graph(db: Database) -> MemoryGraph:
    return MemoryGraph(db)


class TestNodeCRUD:
    async def test_add_node(self, graph: MemoryGraph):
        content_id = uuid.uuid4()
        node_id = await graph.add_node("task", content_id, {"label": "test"})
        assert isinstance(node_id, uuid.UUID)

    async def test_get_node(self, graph: MemoryGraph):
        content_id = uuid.uuid4()
        node_id = await graph.add_node("task", content_id)
        node = await graph.get_node(node_id)
        assert node is not None
        assert node.node_type == "task"
        assert node.content_id == content_id

    async def test_get_node_missing(self, graph: MemoryGraph):
        node = await graph.get_node(uuid.uuid4())
        assert node is None

    async def test_remove_node(self, graph: MemoryGraph):
        content_id = uuid.uuid4()
        node_id = await graph.add_node("task", content_id)
        await graph.remove_node(node_id)
        node = await graph.get_node(node_id)
        assert node is None

    async def test_remove_node_cascades_edges(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        edge_id = await graph.add_edge(n1, n2, EdgeRelation.DEPENDS_ON)
        await graph.remove_node(n1)
        edge = await graph.get_edge(edge_id)
        assert edge is None


class TestEdgeCRUD:
    async def test_add_edge(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        edge_id = await graph.add_edge(n1, n2, EdgeRelation.DEPENDS_ON, weight=0.8)
        assert isinstance(edge_id, uuid.UUID)

    async def test_get_edge(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        edge_id = await graph.add_edge(n1, n2, EdgeRelation.PRODUCED_BY, weight=0.7)
        edge = await graph.get_edge(edge_id)
        assert edge is not None
        assert edge.relation == EdgeRelation.PRODUCED_BY
        assert edge.weight == pytest.approx(0.7, abs=0.01)

    async def test_remove_edge(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        edge_id = await graph.add_edge(n1, n2, EdgeRelation.RELATED_TO)
        await graph.remove_edge(edge_id)
        edge = await graph.get_edge(edge_id)
        assert edge is None

    async def test_update_edge_weight(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        edge_id = await graph.add_edge(n1, n2, EdgeRelation.CONSTRAINS, weight=1.0)
        await graph.update_edge_weight(edge_id, 0.5)
        edge = await graph.get_edge(edge_id)
        assert edge.weight == pytest.approx(0.5, abs=0.01)

    async def test_find_related(self, graph: MemoryGraph):
        center = await graph.add_node("task", uuid.uuid4())
        a1 = await graph.add_node("anchor", uuid.uuid4())
        a2 = await graph.add_node("anchor", uuid.uuid4())
        a3 = await graph.add_node("memory", uuid.uuid4())
        await graph.add_edge(center, a1, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(center, a2, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(center, a3, EdgeRelation.RELATED_TO)

        related = await graph.find_related(center, EdgeRelation.DEPENDS_ON)
        assert len(related) == 2

    async def test_get_stats(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("anchor", uuid.uuid4())
        await graph.add_edge(n1, n2, EdgeRelation.DEPENDS_ON)
        stats = await graph.get_stats()
        assert stats.total_nodes >= 2
        assert stats.total_edges >= 1


class TestTraversal:
    async def test_traverse_outbound_depth1(self, graph: MemoryGraph):
        root = await graph.add_node("task", uuid.uuid4())
        child1 = await graph.add_node("subtask", uuid.uuid4())
        child2 = await graph.add_node("subtask", uuid.uuid4())
        await graph.add_edge(root, child1, EdgeRelation.PARENT_OF, weight=1.0)
        await graph.add_edge(root, child2, EdgeRelation.PARENT_OF, weight=0.8)

        paths = await graph.traverse(root, direction="outbound", max_depth=1)
        assert len(paths) == 2
        assert all(p.score > 0 for p in paths)

    async def test_traverse_respects_min_weight(self, graph: MemoryGraph):
        root = await graph.add_node("task", uuid.uuid4())
        strong = await graph.add_node("anchor", uuid.uuid4())
        weak = await graph.add_node("memory", uuid.uuid4())
        await graph.add_edge(root, strong, EdgeRelation.DEPENDS_ON, weight=0.9)
        await graph.add_edge(root, weak, EdgeRelation.RELATED_TO, weight=0.05)

        paths = await graph.traverse(root, min_weight=0.1)
        node_ids = {p.terminal_node.id for p in paths}
        assert strong in node_ids

    async def test_traverse_cycle_detection(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("task", uuid.uuid4())
        n3 = await graph.add_node("task", uuid.uuid4())
        await graph.add_edge(n1, n2, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(n2, n3, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(n3, n1, EdgeRelation.DEPENDS_ON)

        paths = await graph.traverse(n1, direction="outbound", max_depth=5)
        visited_ids = {p.terminal_node.id for p in paths}
        assert n2 in visited_ids
        assert n3 in visited_ids
        assert len(paths) == 2

    async def test_traverse_relation_filter(self, graph: MemoryGraph):
        root = await graph.add_node("task", uuid.uuid4())
        dep = await graph.add_node("task", uuid.uuid4())
        rel = await graph.add_node("memory", uuid.uuid4())
        await graph.add_edge(root, dep, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(root, rel, EdgeRelation.RELATED_TO)

        paths = await graph.traverse(
            root,
            relation_filter={EdgeRelation.DEPENDS_ON},
        )
        assert len(paths) == 1
        assert paths[0].terminal_node.id == dep

    async def test_shortest_path(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("task", uuid.uuid4())
        n3 = await graph.add_node("task", uuid.uuid4())
        await graph.add_edge(n1, n2, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(n2, n3, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(n1, n3, EdgeRelation.RELATED_TO)

        path = await graph.shortest_path(n1, n3)
        assert path is not None
        assert len(path.edges) == 1

    async def test_shortest_path_not_found(self, graph: MemoryGraph):
        n1 = await graph.add_node("task", uuid.uuid4())
        n2 = await graph.add_node("task", uuid.uuid4())
        path = await graph.shortest_path(n1, n2)
        assert path is None

    async def test_subgraph_extraction(self, graph: MemoryGraph):
        center = await graph.add_node("task", uuid.uuid4())
        n1 = await graph.add_node("anchor", uuid.uuid4())
        n2 = await graph.add_node("memory", uuid.uuid4())
        await graph.add_edge(center, n1, EdgeRelation.DEPENDS_ON)
        await graph.add_edge(center, n2, EdgeRelation.RELATED_TO)

        sg = await graph.subgraph(center, depth=1)
        assert sg.center_id == center
        assert len(sg.nodes) == 3
        assert len(sg.edges) == 2


class TestMaintenance:
    async def test_find_orphans(self, graph: MemoryGraph):
        orphan = await graph.add_node("memory", uuid.uuid4())
        connected = await graph.add_node("task", uuid.uuid4())
        other = await graph.add_node("anchor", uuid.uuid4())
        await graph.add_edge(connected, other, EdgeRelation.DEPENDS_ON)

        orphans = await graph.find_orphans()
        assert orphan in orphans
        assert connected not in orphans

    async def test_merge_nodes(self, graph: MemoryGraph):
        keep = await graph.add_node("task", uuid.uuid4())
        remove = await graph.add_node("task", uuid.uuid4())
        target = await graph.add_node("anchor", uuid.uuid4())
        await graph.add_edge(remove, target, EdgeRelation.DEPENDS_ON)

        await graph.merge_nodes(keep, remove)

        assert await graph.get_node(remove) is None
        related = await graph.find_related(keep, EdgeRelation.DEPENDS_ON)
        assert len(related) == 1
        assert related[0].id == target
