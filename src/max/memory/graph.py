"""Full graph layer for Max's memory — nodes, edges, traversal."""

from __future__ import annotations

import json
import logging
import uuid as uuid_mod
from collections import deque
from typing import Any

from max.db.postgres import Database
from max.memory.models import (
    EdgeRelation,
    GraphEdge,
    GraphNode,
    GraphStats,
    SubGraph,
    TraversalPath,
)

logger = logging.getLogger(__name__)


class MemoryGraph:
    """Graph layer backed by PostgreSQL for persistent node/edge storage."""

    def __init__(self, db: Database) -> None:
        self._db = db

    # ── Node CRUD ────────────────────────────────────────────────────────

    async def add_node(
        self,
        node_type: str,
        content_id: uuid_mod.UUID,
        metadata: dict[str, Any] | None = None,
    ) -> uuid_mod.UUID:
        node_id = uuid_mod.uuid4()
        meta_json = json.dumps(metadata or {})
        await self._db.execute(
            "INSERT INTO graph_nodes (id, node_type, content_id, metadata) "
            "VALUES ($1, $2, $3, $4::jsonb)",
            node_id,
            node_type,
            content_id,
            meta_json,
        )
        return node_id

    async def get_node(self, node_id: uuid_mod.UUID) -> GraphNode | None:
        row = await self._db.fetchone(
            "SELECT id, node_type, content_id, metadata, created_at FROM graph_nodes WHERE id = $1",
            node_id,
        )
        if row is None:
            return None
        return GraphNode(
            id=row["id"],
            node_type=row["node_type"],
            content_id=row["content_id"],
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
            created_at=row["created_at"],
        )

    async def remove_node(self, node_id: uuid_mod.UUID) -> None:
        await self._db.execute("DELETE FROM graph_nodes WHERE id = $1", node_id)

    # ── Edge CRUD ────────────────────────────────────────────────────────

    async def add_edge(
        self,
        source_id: uuid_mod.UUID,
        target_id: uuid_mod.UUID,
        relation: EdgeRelation,
        weight: float = 1.0,
        metadata: dict[str, Any] | None = None,
    ) -> uuid_mod.UUID:
        edge_id = uuid_mod.uuid4()
        meta_json = json.dumps(metadata or {})
        await self._db.execute(
            "INSERT INTO graph_edges "
            "(id, source_id, target_id, relation, weight, metadata) "
            "VALUES ($1, $2, $3, $4, $5, $6::jsonb)",
            edge_id,
            source_id,
            target_id,
            relation.value,
            weight,
            meta_json,
        )
        return edge_id

    async def get_edge(self, edge_id: uuid_mod.UUID) -> GraphEdge | None:
        row = await self._db.fetchone(
            "SELECT id, source_id, target_id, relation, weight, metadata, "
            "created_at, last_traversed FROM graph_edges WHERE id = $1",
            edge_id,
        )
        if row is None:
            return None
        return GraphEdge(
            id=row["id"],
            source_id=row["source_id"],
            target_id=row["target_id"],
            relation=EdgeRelation(row["relation"]),
            weight=float(row["weight"]),
            metadata=row["metadata"] if isinstance(row["metadata"], dict) else {},
            created_at=row["created_at"],
            last_traversed=row["last_traversed"],
        )

    async def remove_edge(self, edge_id: uuid_mod.UUID) -> None:
        await self._db.execute("DELETE FROM graph_edges WHERE id = $1", edge_id)

    async def update_edge_weight(self, edge_id: uuid_mod.UUID, weight: float) -> None:
        await self._db.execute(
            "UPDATE graph_edges SET weight = $1 WHERE id = $2",
            weight,
            edge_id,
        )

    async def find_related(
        self,
        node_id: uuid_mod.UUID,
        relation: EdgeRelation,
        min_weight: float = 0.1,
    ) -> list[GraphNode]:
        rows = await self._db.fetchall(
            "SELECT gn.id, gn.node_type, gn.content_id, gn.metadata, gn.created_at "
            "FROM graph_edges ge "
            "JOIN graph_nodes gn ON gn.id = ge.target_id "
            "WHERE ge.source_id = $1 AND ge.relation = $2 AND ge.weight >= $3",
            node_id,
            relation.value,
            min_weight,
        )
        return [
            GraphNode(
                id=r["id"],
                node_type=r["node_type"],
                content_id=r["content_id"],
                metadata=r["metadata"] if isinstance(r["metadata"], dict) else {},
                created_at=r["created_at"],
            )
            for r in rows
        ]

    # ── Traversal ────────────────────────────────────────────────────────

    async def traverse(
        self,
        start_node: uuid_mod.UUID,
        direction: str = "outbound",
        max_depth: int = 3,
        min_weight: float = 0.1,
        relation_filter: set[EdgeRelation] | None = None,
        max_results: int = 50,
    ) -> list[TraversalPath]:
        """Depth-limited BFS traversal with path scoring."""
        visited: set[uuid_mod.UUID] = {start_node}
        queue: deque[tuple[uuid_mod.UUID, list[GraphEdge], int]] = deque()
        queue.append((start_node, [], 0))
        paths: list[TraversalPath] = []

        while queue and len(paths) < max_results:
            current_id, path_edges, depth = queue.popleft()
            if depth >= max_depth:
                continue

            edges = await self._get_edges(current_id, direction, min_weight, relation_filter)
            for edge in edges:
                neighbor_id = edge.target_id if direction != "inbound" else edge.source_id
                if direction == "both":
                    neighbor_id = edge.target_id if edge.source_id == current_id else edge.source_id

                if neighbor_id in visited:
                    continue
                visited.add(neighbor_id)

                new_path = [*path_edges, edge]
                await self._db.execute(
                    "UPDATE graph_edges SET last_traversed = NOW() WHERE id = $1",
                    edge.id,
                )

                terminal_node = await self.get_node(neighbor_id)
                if terminal_node is None:
                    continue

                score = self._score_path(new_path, depth + 1)
                paths.append(
                    TraversalPath(
                        edges=new_path,
                        terminal_node=terminal_node,
                        score=score,
                    )
                )
                queue.append((neighbor_id, new_path, depth + 1))

        paths.sort(key=lambda p: p.score, reverse=True)
        return paths[:max_results]

    async def _get_edges(
        self,
        node_id: uuid_mod.UUID,
        direction: str,
        min_weight: float,
        relation_filter: set[EdgeRelation] | None,
    ) -> list[GraphEdge]:
        if direction == "outbound":
            where = "ge.source_id = $1"
        elif direction == "inbound":
            where = "ge.target_id = $1"
        else:
            where = "(ge.source_id = $1 OR ge.target_id = $1)"

        query = (
            f"SELECT id, source_id, target_id, relation, weight, metadata, "
            f"created_at, last_traversed FROM graph_edges ge "
            f"WHERE {where} AND ge.weight >= $2"
        )
        params: list[Any] = [node_id, min_weight]

        if relation_filter:
            placeholders = ", ".join(f"${i + 3}" for i in range(len(relation_filter)))
            query += f" AND ge.relation IN ({placeholders})"
            params.extend(r.value for r in relation_filter)

        rows = await self._db.fetchall(query, *params)
        return [
            GraphEdge(
                id=r["id"],
                source_id=r["source_id"],
                target_id=r["target_id"],
                relation=EdgeRelation(r["relation"]),
                weight=float(r["weight"]),
                metadata=r["metadata"] if isinstance(r["metadata"], dict) else {},
                created_at=r["created_at"],
                last_traversed=r["last_traversed"],
            )
            for r in rows
        ]

    @staticmethod
    def _score_path(edges: list[GraphEdge], depth: int) -> float:
        if not edges:
            return 0.0
        weight_product = 1.0
        for e in edges:
            weight_product *= e.weight
        depth_penalty = 1.0 / (1.0 + 0.3 * depth)
        return weight_product * depth_penalty

    async def shortest_path(
        self,
        source: uuid_mod.UUID,
        target: uuid_mod.UUID,
        max_depth: int = 6,
    ) -> TraversalPath | None:
        """BFS shortest path from source to target."""
        visited: set[uuid_mod.UUID] = {source}
        queue: deque[tuple[uuid_mod.UUID, list[GraphEdge]]] = deque()
        queue.append((source, []))

        depth = 0
        level_size = len(queue)
        while queue and depth < max_depth:
            for _ in range(level_size):
                current_id, path_edges = queue.popleft()
                edges = await self._get_edges(current_id, "outbound", 0.0, None)
                for edge in edges:
                    if edge.target_id in visited:
                        continue
                    visited.add(edge.target_id)
                    new_path = [*path_edges, edge]
                    if edge.target_id == target:
                        terminal = await self.get_node(target)
                        if terminal is None:
                            return None
                        return TraversalPath(
                            edges=new_path,
                            terminal_node=terminal,
                            score=self._score_path(new_path, len(new_path)),
                        )
                    queue.append((edge.target_id, new_path))
            depth += 1
            level_size = len(queue)
        return None

    async def subgraph(self, center: uuid_mod.UUID, depth: int = 2) -> SubGraph:
        """Extract the neighborhood around a center node."""
        paths = await self.traverse(
            center, direction="both", max_depth=depth, min_weight=0.0, max_results=500
        )
        node_ids: set[uuid_mod.UUID] = {center}
        nodes_list: list[GraphNode] = []
        edges_list: list[GraphEdge] = []

        center_node = await self.get_node(center)
        if center_node:
            nodes_list.append(center_node)

        for path in paths:
            if path.terminal_node.id not in node_ids:
                node_ids.add(path.terminal_node.id)
                nodes_list.append(path.terminal_node)
            edges_list.extend(path.edges)

        seen_edge_ids: set[uuid_mod.UUID] = set()
        unique_edges: list[GraphEdge] = []
        for e in edges_list:
            if e.id not in seen_edge_ids:
                seen_edge_ids.add(e.id)
                unique_edges.append(e)

        return SubGraph(
            center_id=center,
            nodes=nodes_list,
            edges=unique_edges,
            depth=depth,
        )

    # ── Maintenance ──────────────────────────────────────────────────────

    async def decay_weights(self, cutoff_hours: float = 168.0, decay_factor: float = 0.95) -> int:
        result = await self._db.execute(
            "UPDATE graph_edges "
            "SET weight = GREATEST(0.0, weight * POWER($1::real, "
            "  EXTRACT(EPOCH FROM (NOW() - last_traversed)) / 3600.0 / $2::real"
            ")) "
            "WHERE last_traversed < NOW() - INTERVAL '1 hour'",
            decay_factor,
            cutoff_hours,
        )
        count = int(result.split()[-1]) if result else 0
        logger.info("Decayed %d edge weights", count)
        return count

    async def merge_nodes(self, keep: uuid_mod.UUID, remove: uuid_mod.UUID) -> None:
        await self._db.execute(
            "UPDATE graph_edges SET source_id = $1 WHERE source_id = $2",
            keep,
            remove,
        )
        await self._db.execute(
            "UPDATE graph_edges SET target_id = $1 WHERE target_id = $2",
            keep,
            remove,
        )
        await self.remove_node(remove)

    async def find_orphans(self) -> list[uuid_mod.UUID]:
        rows = await self._db.fetchall(
            "SELECT gn.id FROM graph_nodes gn "
            "LEFT JOIN graph_edges ge_out ON ge_out.source_id = gn.id "
            "LEFT JOIN graph_edges ge_in ON ge_in.target_id = gn.id "
            "WHERE ge_out.id IS NULL AND ge_in.id IS NULL"
        )
        return [r["id"] for r in rows]

    async def get_stats(self) -> GraphStats:
        node_count = await self._db.fetchone("SELECT COUNT(*) AS cnt FROM graph_nodes")
        edge_count = await self._db.fetchone("SELECT COUNT(*) AS cnt FROM graph_edges")
        orphan_count = len(await self.find_orphans())
        avg_weight_row = await self._db.fetchone(
            "SELECT COALESCE(AVG(weight), 0) AS avg_w FROM graph_edges"
        )
        return GraphStats(
            total_nodes=node_count["cnt"] if node_count else 0,
            total_edges=edge_count["cnt"] if edge_count else 0,
            orphan_nodes=orphan_count,
            avg_edge_weight=float(avg_weight_row["avg_w"]) if avg_weight_row else 0.0,
        )
