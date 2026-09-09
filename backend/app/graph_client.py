"""Cliente HTTP fino para o gateway do The Graph.

A API key nunca deve sair do backend — o React fala só com o FastAPI.
"""

from __future__ import annotations

import time
from typing import Any

import httpx

from . import request_log, usage_tracker
from .config import get_settings


class GraphQueryError(RuntimeError):
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


async def run_query(
    query: str, variables: dict[str, Any] | None = None, protocol: str = "v3", timeout: float = 20.0
) -> dict[str, Any]:
    settings = get_settings()
    if not settings.graph_api_key:
        raise GraphQueryError(
            "GRAPH_API_KEY não configurada. Defina no arquivo .env do backend "
            "(veja .env.example) — obtenha uma key gratuita em https://thegraph.com/studio/."
        )

    start = time.monotonic()
    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                settings.graph_gateway_url(protocol),
                json={"query": query, "variables": variables or {}},
            )
            usage_tracker.record_request()
            response.raise_for_status()
            payload = response.json()
    except httpx.HTTPError as exc:
        duration_ms = (time.monotonic() - start) * 1000
        request_log.log_request(query, variables, status="error", duration_ms=duration_ms, error=str(exc))
        raise GraphQueryError(f"Erro de rede ao consultar o subgraph: {exc}") from exc

    duration_ms = (time.monotonic() - start) * 1000

    if "errors" in payload and payload["errors"]:
        request_log.log_request(
            query, variables, status="error", duration_ms=duration_ms, error=str(payload["errors"])
        )
        raise GraphQueryError("Erro na consulta ao subgraph da Uniswap", errors=payload["errors"])

    request_log.log_request(query, variables, status="ok", duration_ms=duration_ms)
    return payload["data"]
