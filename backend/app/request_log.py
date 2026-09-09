"""Log de requisições feitas ao gateway do The Graph.

Cada linha do arquivo (`backend/data/graph_requests.log`) é um objeto JSON
(formato JSONL): uma requisição, com nome da operação, variáveis, status e
duração. Serve para auditoria/debug -- ver exatamente quais consultas
saíram, quando, e se deram erro.

Não é retroativo: só registra a partir de quando este recurso foi
adicionado. O contador agregado em usage_tracker.py inclui um offset de
consultas feitas antes disso (e é o que alimenta o indicador de "quantas
restam" na UI) -- os dois arquivos não precisam bater exatamente.
"""

from __future__ import annotations

import json
import re
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_LOCK = threading.Lock()
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_LOG_FILE = _DATA_DIR / "graph_requests.log"

_OPERATION_RE = re.compile(r"\b(?:query|mutation)\s+(\w+)")


def _extract_operation_name(query: str) -> str:
    match = _OPERATION_RE.search(query)
    return match.group(1) if match else "anonymous"


def log_request(
    query: str,
    variables: dict[str, Any] | None,
    status: str,
    duration_ms: float,
    error: str | None = None,
) -> None:
    """Registra uma requisição ao gateway. `status` é "ok" ou "error"."""
    entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "operation": _extract_operation_name(query),
        "variables": variables or {},
        "status": status,
        "duration_ms": round(duration_ms, 1),
    }
    if error:
        entry["error"] = error

    try:
        with _LOCK:
            _DATA_DIR.mkdir(parents=True, exist_ok=True)
            with _LOG_FILE.open("a") as f:
                f.write(json.dumps(entry) + "\n")
    except OSError:
        # Log é best-effort -- nunca deve derrubar uma consulta real.
        pass


@dataclass(frozen=True)
class RequestLogEntry:
    timestamp: str
    operation: str
    variables: dict[str, Any]
    status: str
    duration_ms: float
    error: str | None = None


def read_recent(limit: int = 50) -> list[RequestLogEntry]:
    """Retorna as últimas `limit` entradas do log, mais recentes primeiro."""
    if not _LOG_FILE.exists():
        return []
    try:
        with _LOCK:
            lines = _LOG_FILE.read_text().splitlines()
    except OSError:
        return []

    entries: list[RequestLogEntry] = []
    for line in reversed(lines[-limit:]):
        try:
            data = json.loads(line)
        except json.JSONDecodeError:
            continue
        entries.append(
            RequestLogEntry(
                timestamp=data.get("timestamp", ""),
                operation=data.get("operation", "?"),
                variables=data.get("variables", {}),
                status=data.get("status", "?"),
                duration_ms=data.get("duration_ms", 0.0),
                error=data.get("error"),
            )
        )
    return entries
