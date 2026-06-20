"""Extraction parser tests — defensive against messy model output."""

from __future__ import annotations

from galo.ingest.extract import parse_extraction


def test_clean_json() -> None:
    raw = '{"entities":[{"name":"GALO","type":"CONCEPT"},{"name":"Neo4j","type":"ORG"}],' \
          '"relations":[{"source":"GALO","target":"Neo4j","type":"uses"}]}'
    ext = parse_extraction(raw)
    assert {e.name for e in ext.entities} == {"GALO", "Neo4j"}
    assert len(ext.relations) == 1
    assert ext.relations[0].type == "uses"


def test_strips_code_fences() -> None:
    raw = '```json\n{"entities":[{"name":"X","type":"OTHER"}],"relations":[]}\n```'
    ext = parse_extraction(raw)
    assert [e.name for e in ext.entities] == ["X"]


def test_recovers_json_wrapped_in_prose() -> None:
    raw = 'Sure! Here is the data:\n{"entities":[{"name":"A","type":"PERSON"}],"relations":[]}\nHope that helps.'
    ext = parse_extraction(raw)
    assert [e.name for e in ext.entities] == ["A"]


def test_garbage_returns_empty() -> None:
    ext = parse_extraction("I cannot help with that.")
    assert ext.entities == [] and ext.relations == []


def test_relation_to_unknown_entity_dropped() -> None:
    raw = '{"entities":[{"name":"A","type":"OTHER"}],' \
          '"relations":[{"source":"A","target":"Ghost","type":"knows"}]}'
    ext = parse_extraction(raw)
    assert ext.relations == []  # target not in entities


def test_duplicate_entities_deduped_by_normalized_name() -> None:
    raw = '{"entities":[{"name":"GALO","type":"CONCEPT"},{"name":"galo","type":"CONCEPT"}],"relations":[]}'
    ext = parse_extraction(raw)
    assert len(ext.entities) == 1


def test_self_relation_dropped() -> None:
    raw = '{"entities":[{"name":"A","type":"OTHER"}],' \
          '"relations":[{"source":"A","target":"A","type":"loops"}]}'
    ext = parse_extraction(raw)
    assert ext.relations == []


def test_entity_id_is_deterministic() -> None:
    a = parse_extraction('{"entities":[{"name":"Neo4j","type":"ORG"}],"relations":[]}').entities[0]
    b = parse_extraction('{"entities":[{"name":"neo4j","type":"ORG"}],"relations":[]}').entities[0]
    assert a.id == b.id  # normalized name + type → same node
