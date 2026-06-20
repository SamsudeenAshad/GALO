"""Learning path: ordered traversal over :PREREQUISITE edges.

Resolves two concept names to graph entities and returns the shortest directed
prerequisite chain between them — the order a learner should progress through.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from galo.stores.neo4j import Neo4jStore


@dataclass(frozen=True)
class PathStep:
    entity_id: uuid.UUID
    name: str


@dataclass(frozen=True)
class LearningPath:
    found: bool
    steps: list[PathStep]
    reason: str | None = None  # why a path is empty, when found is False


async def learning_path(
    graph: Neo4jStore, from_concept: str, to_concept: str
) -> LearningPath:
    src = await graph.find_entity(from_concept)
    if src is None:
        return LearningPath(False, [], reason=f"unknown concept: {from_concept!r}")
    tgt = await graph.find_entity(to_concept)
    if tgt is None:
        return LearningPath(False, [], reason=f"unknown concept: {to_concept!r}")
    if src == tgt:
        return LearningPath(True, [PathStep(src, from_concept)])

    raw = await graph.prerequisite_path(src, tgt)
    if raw is None:
        return LearningPath(
            False, [], reason="no prerequisite path between the concepts"
        )
    return LearningPath(True, [PathStep(eid, name) for eid, name in raw])
