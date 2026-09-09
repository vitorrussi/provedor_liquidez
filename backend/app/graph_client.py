"""Cliente HTTP fino para o gateway do The Graph.

A API key nunca deve sair do backend — o React fala só com o FastAPI.
"""

from __future__ import annotations

from typing import Any

import httpx

from .config import get_settings


class GraphQueryError(RuntimeError):
    def __init__(self, message: str, errors: list[dict[str, Any]] | None = None):
        super().__init__(message)
        self.errors = errors or []


async def run_query(query: str, variables: dict[str, Any] | None = None) -> dict[str, Any]:
    settings = get_settings()
    if not settings.graph_api_key:
        raise GraphQueryError(
            "GRAPH_API_KEY não configurada. Defina no arquivo .env do backend "
            "(veja .env.example) — obtenha uma key gratuita em https://thegraph.com/studio/."
        )

    async with httpx.AsyncClient(timeout=15.0) as client:
        response = await client.post(
            settings.graph_gateway_url,
            json={"query": query, "variables": variables or {}},
        )
        response.raise_for_status()
        payload = response.json()

    if "errors" in payload and payload["errors"]:
        raise GraphQueryError("Erro na consulta ao subgraph da Uniswap", errors=payload["errors"])

    return payload["data"]
