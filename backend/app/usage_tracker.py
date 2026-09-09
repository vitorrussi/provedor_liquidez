"""Contador local de consultas feitas ao gateway do The Graph.

Serve para estimar quantas consultas ainda restam no plano free do Subgraph
Studio (100k/mês). Não é a fonte de verdade -- essa é o dashboard do Studio
(thegraph.com/studio/apikeys/, seção "Overview" de cada key), que reflete
o uso real cobrado pela The Graph e pode incluir chamadas feitas por outros
lugares que usem a mesma API key. Este contador só enxerga as chamadas
feitas por este backend.

O reset é por mês civil (UTC), o que pode não coincidir exatamente com a
data de corte do ciclo de billing do Studio (essa depende de quando a conta
foi criada).
"""

from __future__ import annotations

import json
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from .config import get_settings

_LOCK = threading.Lock()
_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_USAGE_FILE = _DATA_DIR / "graph_usage.json"


def _current_month() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m")


def _read() -> dict:
    if not _USAGE_FILE.exists():
        return {"month": _current_month(), "count": 0}
    try:
        return json.loads(_USAGE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {"month": _current_month(), "count": 0}


def _write(data: dict) -> None:
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    _USAGE_FILE.write_text(json.dumps(data))


def record_request() -> None:
    """Registra uma consulta feita ao gateway. Chamar uma vez por chamada
    HTTP que de fato saiu para o gateway (não para falhas que nem chegam a
    sair, como API key ausente)."""
    try:
        with _LOCK:
            data = _read()
            month = _current_month()
            if data.get("month") != month:
                data = {"month": month, "count": 0}
            data["count"] = int(data.get("count", 0)) + 1
            _write(data)
    except OSError:
        # Rastreamento é best-effort -- nunca deve derrubar uma consulta real.
        pass


@dataclass(frozen=True)
class UsageStats:
    month: str
    used: int
    limit: int
    remaining: int


def get_usage() -> UsageStats:
    settings = get_settings()
    with _LOCK:
        data = _read()
    month = _current_month()
    used = int(data.get("count", 0)) if data.get("month") == month else 0
    limit = settings.graph_monthly_query_limit
    remaining = max(limit - used, 0)
    return UsageStats(month=month, used=used, limit=limit, remaining=remaining)
