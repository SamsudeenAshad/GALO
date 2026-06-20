"""Model gateway protocol and shared types.

The gateway is the *only* part of GALO that talks to the model node. Everything
else depends on this Protocol, never on a concrete backend, so models/providers
can be swapped without touching ingestion or retrieval.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

Vector = list[float]


@dataclass(frozen=True)
class HealthStatus:
    """Result of a dependency health probe."""

    ok: bool
    detail: str


@runtime_checkable
class ModelGateway(Protocol):
    """Abstraction over embedding + generation backends."""

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Embed a batch of texts. Output dimension must equal ``embed_dim``."""
        ...

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        """Generate a completion for a single prompt."""
        ...

    async def health(self) -> HealthStatus:
        """Probe backend reachability (for ``/health``)."""
        ...

    async def aclose(self) -> None:
        """Release any held resources (connections, clients)."""
        ...
