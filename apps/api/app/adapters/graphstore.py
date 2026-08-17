"""Impact-graph storage.

`InMemoryGraphStore` is the local fallback; `Neo4jGraphStore` is used when
NEO4J_URI/USER/PASSWORD are configured and the driver is installed. Both satisfy
the same traversal contract, so `/api/impact/{change_id}` behaves identically.
"""

from __future__ import annotations

import logging
from typing import Protocol

from ..config import get_settings
from ..domain import ImpactEdge, ImpactGraph, ImpactNode

log = logging.getLogger("graph")


class GraphStore(Protocol):
    backend: str

    def upsert(self, graph: ImpactGraph) -> None: ...
    def traverse(self, change_id: str, max_depth: int = 5) -> ImpactGraph | None: ...
    def clear(self) -> None: ...


class InMemoryGraphStore:
    backend = "in_memory"

    def __init__(self) -> None:
        # One isolated sub-graph per change. Re-analysing a change *replaces* its
        # sub-graph, exactly as Neo4jGraphStore.upsert does with DETACH DELETE —
        # otherwise superseded impacts would linger after the evidence is fixed.
        self._graphs: dict[str, tuple[dict[str, ImpactNode], set[tuple[str, str, str]]]] = {}

    def upsert(self, graph: ImpactGraph) -> None:
        self._graphs[graph.change_id] = (
            {node.id: node for node in graph.nodes},
            {(e.source, e.target, e.relation) for e in graph.edges},
        )

    def traverse(self, change_id: str, max_depth: int = 5) -> ImpactGraph | None:
        stored = self._graphs.get(change_id)
        root = f"change:{change_id}"
        if not stored or root not in stored[0]:
            return None
        all_nodes, all_edges = stored
        seen = {root}
        edges: list[ImpactEdge] = []
        paths: list[list[str]] = [[root]]
        for _ in range(max_depth):
            grew = False
            new_paths: list[list[str]] = []
            for path in paths:
                tail = path[-1]
                children = [(s, t, r) for (s, t, r) in all_edges if s == tail and t not in path]
                if not children:
                    new_paths.append(path)
                    continue
                grew = True
                for _s, target, relation in children:
                    edges.append(ImpactEdge(source=tail, target=target, relation=relation))
                    new_paths.append(path + [target])
                    seen.add(target)
            paths = new_paths
            if not grew:
                break
        return ImpactGraph(
            change_id=change_id,
            nodes=[all_nodes[n] for n in seen if n in all_nodes],
            edges=list({(e.source, e.target, e.relation): e for e in edges}.values()),
            paths=[p for p in paths if len(p) > 1],
            backend=self.backend,
        )

    def clear(self) -> None:
        self._graphs.clear()


class Neo4jGraphStore:
    """Cypher-backed store. Mirrors the in-memory semantics exactly."""

    backend = "neo4j"

    def __init__(self, uri: str, user: str, password: str) -> None:
        from neo4j import GraphDatabase  # imported lazily: optional dependency

        self._driver = GraphDatabase.driver(uri, auth=(user, password))
        self._driver.verify_connectivity()

    def upsert(self, graph: ImpactGraph) -> None:
        with self._driver.session() as session:
            session.run("MATCH (n:Impact {change_id:$c}) DETACH DELETE n", c=graph.change_id)
            for node in graph.nodes:
                session.run(
                    "MERGE (n:Impact {id:$id}) SET n += $props",
                    id=node.id,
                    props={
                        "label": node.label,
                        "kind": node.kind,
                        "status": node.status,
                        "detail": node.detail,
                        "change_id": graph.change_id,
                    },
                )
            for edge in graph.edges:
                session.run(
                    "MATCH (a:Impact {id:$s}),(b:Impact {id:$t}) "
                    "MERGE (a)-[r:IMPACTS {relation:$rel}]->(b)",
                    s=edge.source,
                    t=edge.target,
                    rel=edge.relation,
                )

    def traverse(self, change_id: str, max_depth: int = 5) -> ImpactGraph | None:
        query = (
            f"MATCH p=(c:Impact {{id:$root}})-[:IMPACTS*1..{int(max_depth)}]->(x) "
            "RETURN [n IN nodes(p) | n {.id,.label,.kind,.status,.detail}] AS ns, "
            "[r IN relationships(p) | {source:startNode(r).id, target:endNode(r).id, "
            "relation:r.relation}] AS rs"
        )
        nodes: dict[str, ImpactNode] = {}
        edges: dict[tuple, ImpactEdge] = {}
        paths: list[list[str]] = []
        with self._driver.session() as session:
            records = list(session.run(query, root=f"change:{change_id}"))
        if not records:
            return None
        for record in records:
            path_ids = []
            for raw in record["ns"]:
                node = ImpactNode(**raw)
                nodes[node.id] = node
                path_ids.append(node.id)
            for raw in record["rs"]:
                edge = ImpactEdge(**raw)
                edges[(edge.source, edge.target, edge.relation)] = edge
            paths.append(path_ids)
        return ImpactGraph(
            change_id=change_id,
            nodes=list(nodes.values()),
            edges=list(edges.values()),
            paths=paths,
            backend=self.backend,
        )

    def clear(self) -> None:
        with self._driver.session() as session:
            session.run("MATCH (n:Impact) DETACH DELETE n")


_graph: GraphStore | None = None


def get_graph_store() -> GraphStore:
    global _graph
    if _graph is None:
        settings = get_settings()
        if settings.neo4j_live:
            try:
                _graph = Neo4jGraphStore(
                    settings.neo4j_uri, settings.neo4j_user, settings.neo4j_password
                )
                log.info("using neo4j graph store")
            except Exception as exc:  # driver missing or server unreachable
                log.warning("neo4j unavailable, using in-memory graph", extra={"error": str(exc)})
                _graph = InMemoryGraphStore()
        else:
            _graph = InMemoryGraphStore()
    return _graph


def set_graph_store(store: GraphStore | None) -> None:
    global _graph
    _graph = store
