"""LLM-driven entity + relation extraction over chunk text.

Calls the model gateway with a strict JSON-output prompt and parses the result
into typed entities/relations. The model can be unreliable about format, so
parsing is defensive: it strips code fences, tolerates extra prose around the
JSON object, and drops malformed records rather than failing the whole chunk.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass

from galo.models.gateway import ModelGateway

_SYSTEM = (
    "You are an information-extraction engine. Extract the salient named "
    "entities and the relationships between them from the user's text. "
    "Respond with ONLY a JSON object, no prose, no code fences."
)

_PROMPT = """\
Extract entities and relations from the text below.

Return JSON with this exact shape:
{{
  "entities": [{{"name": "<surface form>", "type": "<PERSON|ORG|CONCEPT|PLACE|OTHER>"}}],
  "relations": [{{"source": "<entity name>", "target": "<entity name>", "type": "<short verb phrase>"}}]
}}

Rules:
- Only include relations whose source and target both appear in "entities".
- Use the entity's surface form consistently as its name.
- If nothing salient is present, return {{"entities": [], "relations": []}}.

TEXT:
{text}
"""

# Matches the first balanced-looking {...} block; good enough to recover JSON
# that the model wrapped in stray prose.
_JSON_OBJ = re.compile(r"\{.*\}", re.DOTALL)


@dataclass(frozen=True)
class Entity:
    name: str
    normalized_name: str
    type: str

    @property
    def id(self) -> uuid.UUID:
        # Deterministic id from (normalized_name, type) so the same entity from
        # different chunks resolves to one node. v0 resolution = exact normalized.
        return uuid.uuid5(uuid.NAMESPACE_OID, f"{self.normalized_name}|{self.type}")


@dataclass(frozen=True)
class Relation:
    source: Entity
    target: Entity
    type: str


@dataclass(frozen=True)
class Extraction:
    entities: list[Entity]
    relations: list[Relation]


def _normalize(name: str) -> str:
    return " ".join(name.lower().split())


def _strip_fences(raw: str) -> str:
    raw = raw.strip()
    if raw.startswith("```"):
        # drop ```json ... ``` fencing
        raw = re.sub(r"^```[a-zA-Z]*\n?", "", raw)
        raw = re.sub(r"\n?```$", "", raw)
    return raw.strip()


def parse_extraction(raw: str) -> Extraction:
    """Parse model output into an Extraction. Resilient to formatting noise."""
    text = _strip_fences(raw)
    obj = None
    try:
        obj = json.loads(text)
    except json.JSONDecodeError:
        m = _JSON_OBJ.search(text)
        if m:
            try:
                obj = json.loads(m.group(0))
            except json.JSONDecodeError:
                obj = None
    if not isinstance(obj, dict):
        return Extraction(entities=[], relations=[])

    by_name: dict[str, Entity] = {}
    for item in obj.get("entities", []) or []:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        etype = str(item.get("type", "OTHER")).strip().upper() or "OTHER"
        ent = Entity(name=name, normalized_name=_normalize(name), type=etype)
        by_name.setdefault(ent.normalized_name, ent)

    relations: list[Relation] = []
    for item in obj.get("relations", []) or []:
        if not isinstance(item, dict):
            continue
        src = by_name.get(_normalize(str(item.get("source", ""))))
        tgt = by_name.get(_normalize(str(item.get("target", ""))))
        rtype = str(item.get("type", "")).strip() or "RELATED"
        if src and tgt and src.id != tgt.id:
            relations.append(Relation(source=src, target=tgt, type=rtype))

    return Extraction(entities=list(by_name.values()), relations=relations)


async def extract_chunk(gateway: ModelGateway, text: str) -> Extraction:
    """Run extraction over a single chunk's text."""
    raw = await gateway.generate(_PROMPT.format(text=text), system=_SYSTEM)
    return parse_extraction(raw)
