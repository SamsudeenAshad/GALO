"""Ollama-backed implementation of the ModelGateway protocol."""

from __future__ import annotations

import httpx

from galo.models.gateway import HealthStatus, Vector


class OllamaGateway:
    """Talks to a self-hosted Ollama node via its HTTP API.

    Endpoints used:
      - ``POST /api/embeddings``  (one text per call)
      - ``POST /api/generate``    (non-streaming completion)
      - ``GET  /api/tags``        (health / model listing)
    """

    def __init__(
        self,
        base_url: str,
        *,
        gen_model: str,
        embed_model: str,
        embed_dim: int,
        timeout_s: float = 60.0,
    ) -> None:
        self._gen_model = gen_model
        self._embed_model = embed_model
        self._embed_dim = embed_dim
        self._client = httpx.AsyncClient(
            base_url=base_url.rstrip("/"),
            timeout=timeout_s,
        )

    async def embed(self, texts: list[str]) -> list[Vector]:
        """Embed each text. Ollama's embeddings endpoint takes one prompt at a
        time, so we issue one request per text and validate the dimension."""
        vectors: list[Vector] = []
        for text in texts:
            resp = await self._client.post(
                "/api/embeddings",
                json={"model": self._embed_model, "prompt": text},
            )
            resp.raise_for_status()
            vec = resp.json()["embedding"]
            if len(vec) != self._embed_dim:
                raise ValueError(
                    f"embedding dim mismatch: model returned {len(vec)}, "
                    f"config expects {self._embed_dim}"
                )
            vectors.append(vec)
        return vectors

    async def generate(self, prompt: str, *, system: str | None = None) -> str:
        payload: dict = {
            "model": self._gen_model,
            "prompt": prompt,
            "stream": False,
        }
        if system is not None:
            payload["system"] = system
        resp = await self._client.post("/api/generate", json=payload)
        resp.raise_for_status()
        return resp.json()["response"]

    async def health(self) -> HealthStatus:
        try:
            resp = await self._client.get("/api/tags")
            resp.raise_for_status()
            models = {m["name"] for m in resp.json().get("models", [])}
            missing = [
                m
                for m in (self._gen_model, self._embed_model)
                # tags may carry a ``:latest`` suffix; match on the base name
                if not any(name.split(":")[0] == m.split(":")[0] for name in models)
            ]
            if missing:
                return HealthStatus(
                    ok=False, detail=f"models not pulled on node: {missing}"
                )
            return HealthStatus(ok=True, detail=f"{len(models)} models available")
        except (httpx.HTTPError, KeyError, ValueError) as exc:
            return HealthStatus(ok=False, detail=f"unreachable: {exc}")

    async def aclose(self) -> None:
        await self._client.aclose()
