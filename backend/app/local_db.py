"""Cache local (SQLite) dos ativos e pools "relevantes" (TVL acima de um
piso), usado por duas coisas: (a) autocomplete rápido no campo de busca
principal sem bater no gateway do Graph a cada tecla digitada, e (b) as
páginas /assets e /pools, que precisam ordenar/filtrar/paginar uma lista sem
re-consultar o subgraph a cada interação.

Não é atualizado automaticamente -- só quando o usuário clica em "Atualizar"
(ver routers/local_index.py -> services/index_builder.py), porque um crawl
completo dos 4 subgraphs custa uma quantidade não-trivial de consultas ao
gateway (~20-30 por refresh). Cada refresh substitui o conteúdo inteiro das
tabelas de uma vez (não faz merge incremental) -- mais simples e evita
registros órfãos de pools que caíram abaixo do piso de TVL entre uma
atualização e outra.
"""

from __future__ import annotations

import json
import sqlite3
import threading
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_DATA_DIR = Path(__file__).resolve().parent.parent / "data"
_DB_PATH = _DATA_DIR / "local_index.db"
_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS assets (
    id TEXT PRIMARY KEY,
    chain TEXT NOT NULL,
    address TEXT NOT NULL,
    symbol TEXT NOT NULL,
    name TEXT NOT NULL,
    decimals INTEGER NOT NULL,
    category TEXT,
    pools_count INTEGER NOT NULL,
    total_tvl_usd REAL NOT NULL,
    total_volume_usd REAL NOT NULL DEFAULT 0,
    top_pairs TEXT NOT NULL,
    volume_1d_usd REAL,
    volume_30d_usd REAL,
    volume_1d_over_tvl REAL
);
CREATE INDEX IF NOT EXISTS idx_assets_symbol ON assets(symbol);
CREATE INDEX IF NOT EXISTS idx_assets_tvl ON assets(total_tvl_usd);

CREATE TABLE IF NOT EXISTS pools (
    id TEXT PRIMARY KEY,
    protocol TEXT NOT NULL,
    chain TEXT NOT NULL,
    token0_symbol TEXT NOT NULL,
    token0_address TEXT NOT NULL,
    token1_symbol TEXT NOT NULL,
    token1_address TEXT NOT NULL,
    fee_tier INTEGER NOT NULL,
    total_value_locked_usd REAL NOT NULL,
    volume_usd REAL NOT NULL,
    created_at INTEGER,
    volume_1d_usd REAL,
    volume_30d_usd REAL,
    volume_1d_over_tvl REAL,
    apr_pool_30d REAL
);
CREATE INDEX IF NOT EXISTS idx_pools_symbols ON pools(token0_symbol, token1_symbol);
CREATE INDEX IF NOT EXISTS idx_pools_tvl ON pools(total_value_locked_usd);

CREATE TABLE IF NOT EXISTS index_meta (
    id INTEGER PRIMARY KEY CHECK (id = 1),
    updated_at INTEGER,
    min_tvl_usd REAL,
    total_assets INTEGER,
    total_pools INTEGER,
    protocol_errors TEXT
);
"""


@contextmanager
def _connect():
    _DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, ddl_type: str) -> None:
    """Migração mínima pra um arquivo local_index.db já existente de antes
    dessa coluna existir -- `CREATE TABLE IF NOT EXISTS` não altera uma
    tabela que já existe, e o cache é sempre reconstruído por completo (ver
    replace_index), não vale a pena um sistema de migração de verdade aqui.
    """
    existing = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})")}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}")


def init_schema() -> None:
    with _LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)
        _ensure_column(conn, "assets", "total_volume_usd", "REAL NOT NULL DEFAULT 0")
        # Métricas por janela (volume 1d/30d, vol1d/TVL, APR 30d) -- NULL, não
        # 0, pra distinguir "não medido" (pools v2, sem poolDayData indexado
        # com relação reversa no subgraph -- ver index_builder.py) de "medido
        # e igual a zero" (pool real sem atividade recente). Um filtro
        # min_* numa coluna NULL nunca casa em SQL (comparação com NULL é
        # sempre falsa) -- efeito pretendido: filtros dessas métricas excluem
        # pools/ativos v2 sem essa medição, em vez de tratá-los como "0".
        for col in ("volume_1d_usd", "volume_30d_usd", "volume_1d_over_tvl", "apr_pool_30d"):
            _ensure_column(conn, "pools", col, "REAL")
        for col in ("volume_1d_usd", "volume_30d_usd", "volume_1d_over_tvl"):
            _ensure_column(conn, "assets", col, "REAL")
        conn.commit()


@dataclass(frozen=True)
class AssetRecord:
    id: str
    chain: str
    address: str
    symbol: str
    name: str
    decimals: int
    category: str | None
    pools_count: int
    total_tvl_usd: float
    total_volume_usd: float
    top_pairs: list[dict[str, Any]]
    # None quando nenhuma das pools desse ativo tem métrica por janela
    # medida (ex: ativo só aparece em pools v2) -- ver comentário em
    # init_schema.
    volume_1d_usd: float | None = None
    volume_30d_usd: float | None = None
    volume_1d_over_tvl: float | None = None


@dataclass(frozen=True)
class PoolRecord:
    id: str
    protocol: str
    chain: str
    token0_symbol: str
    token0_address: str
    token1_symbol: str
    token1_address: str
    fee_tier: int
    total_value_locked_usd: float
    volume_usd: float
    created_at: int | None
    # None para pools v2 (subgraph não tem relação reversa Pair->PairDayData,
    # ver index_builder.py) -- não 0, ver comentário em init_schema.
    volume_1d_usd: float | None = None
    volume_30d_usd: float | None = None
    volume_1d_over_tvl: float | None = None
    apr_pool_30d: float | None = None


@dataclass(frozen=True)
class IndexMeta:
    updated_at: int | None
    min_tvl_usd: float | None
    total_assets: int
    total_pools: int
    protocol_errors: dict[str, str]


def _row_to_asset(row: sqlite3.Row) -> AssetRecord:
    return AssetRecord(
        id=row["id"],
        chain=row["chain"],
        address=row["address"],
        symbol=row["symbol"],
        name=row["name"],
        decimals=row["decimals"],
        category=row["category"],
        pools_count=row["pools_count"],
        total_tvl_usd=row["total_tvl_usd"],
        total_volume_usd=row["total_volume_usd"],
        top_pairs=json.loads(row["top_pairs"]),
        volume_1d_usd=row["volume_1d_usd"],
        volume_30d_usd=row["volume_30d_usd"],
        volume_1d_over_tvl=row["volume_1d_over_tvl"],
    )


def _row_to_pool(row: sqlite3.Row) -> PoolRecord:
    return PoolRecord(
        id=row["id"],
        protocol=row["protocol"],
        chain=row["chain"],
        token0_symbol=row["token0_symbol"],
        token0_address=row["token0_address"],
        token1_symbol=row["token1_symbol"],
        token1_address=row["token1_address"],
        fee_tier=row["fee_tier"],
        total_value_locked_usd=row["total_value_locked_usd"],
        volume_usd=row["volume_usd"],
        created_at=row["created_at"],
        volume_1d_usd=row["volume_1d_usd"],
        volume_30d_usd=row["volume_30d_usd"],
        volume_1d_over_tvl=row["volume_1d_over_tvl"],
        apr_pool_30d=row["apr_pool_30d"],
    )


def replace_index(
    assets: list[AssetRecord], pools: list[PoolRecord], min_tvl_usd: float, protocol_errors: dict[str, str]
) -> IndexMeta:
    init_schema()
    now = int(time.time())
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM assets")
        conn.execute("DELETE FROM pools")
        conn.executemany(
            "INSERT INTO assets (id, chain, address, symbol, name, decimals, category, pools_count, "
            "total_tvl_usd, total_volume_usd, top_pairs, volume_1d_usd, volume_30d_usd, volume_1d_over_tvl) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (a.id, a.chain, a.address, a.symbol, a.name, a.decimals, a.category, a.pools_count,
                 a.total_tvl_usd, a.total_volume_usd, json.dumps(a.top_pairs),
                 a.volume_1d_usd, a.volume_30d_usd, a.volume_1d_over_tvl)
                for a in assets
            ],
        )
        conn.executemany(
            "INSERT INTO pools (id, protocol, chain, token0_symbol, token0_address, token1_symbol, "
            "token1_address, fee_tier, total_value_locked_usd, volume_usd, created_at, "
            "volume_1d_usd, volume_30d_usd, volume_1d_over_tvl, apr_pool_30d) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (p.id, p.protocol, p.chain, p.token0_symbol, p.token0_address, p.token1_symbol,
                 p.token1_address, p.fee_tier, p.total_value_locked_usd, p.volume_usd, p.created_at,
                 p.volume_1d_usd, p.volume_30d_usd, p.volume_1d_over_tvl, p.apr_pool_30d)
                for p in pools
            ],
        )
        conn.execute(
            "INSERT INTO index_meta (id, updated_at, min_tvl_usd, total_assets, total_pools, protocol_errors) "
            "VALUES (1, ?, ?, ?, ?, ?) ON CONFLICT(id) DO UPDATE SET "
            "updated_at=excluded.updated_at, min_tvl_usd=excluded.min_tvl_usd, "
            "total_assets=excluded.total_assets, total_pools=excluded.total_pools, "
            "protocol_errors=excluded.protocol_errors",
            (now, min_tvl_usd, len(assets), len(pools), json.dumps(protocol_errors)),
        )
        conn.commit()
    return IndexMeta(
        updated_at=now, min_tvl_usd=min_tvl_usd, total_assets=len(assets), total_pools=len(pools),
        protocol_errors=protocol_errors,
    )


def get_meta() -> IndexMeta:
    init_schema()
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM index_meta WHERE id = 1").fetchone()
    if row is None:
        return IndexMeta(updated_at=None, min_tvl_usd=None, total_assets=0, total_pools=0, protocol_errors={})
    return IndexMeta(
        updated_at=row["updated_at"],
        min_tvl_usd=row["min_tvl_usd"],
        total_assets=row["total_assets"],
        total_pools=row["total_pools"],
        protocol_errors=json.loads(row["protocol_errors"] or "{}"),
    )


# Whitelist de colunas ordenáveis -- interpolado direto na query (só depois
# de validado contra esse set), nunca vem direto da requisição do usuário.
_ASSET_SORT_COLUMNS = {
    "symbol", "name", "category", "pools_count", "total_tvl_usd",
    "volume_1d_usd", "volume_30d_usd", "volume_1d_over_tvl",
}
_POOL_SORT_COLUMNS = {
    "protocol", "token0_symbol", "token1_symbol", "fee_tier", "total_value_locked_usd", "volume_usd", "created_at",
    "volume_1d_usd", "volume_30d_usd", "volume_1d_over_tvl", "apr_pool_30d",
}

# "Sem atividade" pro filtro hide_inactive -- mesmo critério usado em
# services/pools.py::search_pools (piso pequeno em vez de "> 0" pra não
# depender de precisão exata de ponto flutuante). Não é o mesmo conceito do
# piso de "dado corrompido" (_MIN_PLAUSIBLE_VOLUME_USD em services/pools.py,
# $100) -- esse aqui é só "teve alguma atividade real", não uma checagem
# antifraude.
_MIN_ACTIVE_VOLUME_USD = 0.01


def _add_range_filter(
    where: list[str], params: list[Any], column: str, min_value: float | None, max_value: float | None
) -> None:
    """Adiciona `column >= min` / `column <= max` ao WHERE quando informado.
    Como a coluna pode ser NULL (métrica não medida, ex: pools v2 -- ver
    init_schema), a comparação SQL padrão já exclui essas linhas sozinha
    quando qualquer um dos dois limites é passado -- efeito pretendido.
    """
    if min_value is not None:
        where.append(f"{column} >= ?")
        params.append(min_value)
    if max_value is not None:
        where.append(f"{column} <= ?")
        params.append(max_value)


def query_assets(
    q: str | None,
    category: str | None,
    exact: bool,
    hide_inactive: bool,
    sort: str,
    order: str,
    limit: int,
    offset: int,
    min_volume_1d_usd: float | None = None,
    max_volume_1d_usd: float | None = None,
    min_volume_30d_usd: float | None = None,
    max_volume_30d_usd: float | None = None,
    min_volume_1d_over_tvl: float | None = None,
    max_volume_1d_over_tvl: float | None = None,
    chain: str | None = None,
) -> tuple[list[AssetRecord], int]:
    sort_col = sort if sort in _ASSET_SORT_COLUMNS else "total_tvl_usd"
    order_sql = "ASC" if order == "asc" else "DESC"
    where: list[str] = []
    params: list[Any] = []
    if q:
        if exact:
            where.append("(symbol = ? COLLATE NOCASE OR name = ? COLLATE NOCASE)")
            params.extend([q, q])
        else:
            where.append("(symbol LIKE ? OR name LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])
    if category:
        where.append("category = ?")
        params.append(category)
    if chain:
        where.append("chain = ?")
        params.append(chain)
    if hide_inactive:
        where.append("total_volume_usd >= ?")
        params.append(_MIN_ACTIVE_VOLUME_USD)
    _add_range_filter(where, params, "volume_1d_usd", min_volume_1d_usd, max_volume_1d_usd)
    _add_range_filter(where, params, "volume_30d_usd", min_volume_30d_usd, max_volume_30d_usd)
    _add_range_filter(where, params, "volume_1d_over_tvl", min_volume_1d_over_tvl, max_volume_1d_over_tvl)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    init_schema()
    with _LOCK, _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM assets {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM assets {where_sql} ORDER BY {sort_col} {order_sql}, symbol ASC LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_asset(r) for r in rows], total


def suggest_assets(prefix: str, limit: int) -> list[AssetRecord]:
    init_schema()
    like = f"{prefix}%"
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM assets WHERE symbol LIKE ? ORDER BY total_tvl_usd DESC LIMIT ?",
            (like, limit),
        ).fetchall()
    return [_row_to_asset(r) for r in rows]


def query_pools(
    q: str | None,
    token_a: list[str] | None,
    token_b: list[str] | None,
    exact: bool,
    hide_inactive: bool,
    protocol: str | None,
    sort: str,
    order: str,
    limit: int,
    offset: int,
    min_volume_1d_usd: float | None = None,
    max_volume_1d_usd: float | None = None,
    min_volume_30d_usd: float | None = None,
    max_volume_30d_usd: float | None = None,
    min_volume_1d_over_tvl: float | None = None,
    max_volume_1d_over_tvl: float | None = None,
    min_apr_pool_30d: float | None = None,
    max_apr_pool_30d: float | None = None,
    chain: str | None = None,
) -> tuple[list[PoolRecord], int]:
    sort_col = sort if sort in _POOL_SORT_COLUMNS else "total_value_locked_usd"
    order_sql = "ASC" if order == "asc" else "DESC"
    where: list[str] = []
    params: list[Any] = []

    # Busca por par (chips selecionados no autocomplete de Token A/Token B,
    # ver TokenMultiSelect.tsx -- cada um uma lista de siglas, IN em vez de
    # LIKE) tem prioridade sobre a busca de texto livre -- mesmo
    # comportamento da busca ao vivo em services/pools.py::search_pools.
    # Símbolos vêm do índice local (autocomplete), com a capitalização exata
    # -- não usa COLLATE NOCASE aqui (diferente da busca de texto livre por
    # `q` abaixo, que continua case-insensitive por natureza).
    if token_a and token_b:
        a_ph = ", ".join("?" for _ in token_a)
        b_ph = ", ".join("?" for _ in token_b)
        where.append(
            f"((token0_symbol IN ({a_ph}) AND token1_symbol IN ({b_ph})) OR "
            f"(token0_symbol IN ({b_ph}) AND token1_symbol IN ({a_ph})))"
        )
        params.extend([*token_a, *token_b, *token_b, *token_a])
    elif token_a or token_b:
        symbols = token_a or token_b or []
        ph = ", ".join("?" for _ in symbols)
        where.append(f"(token0_symbol IN ({ph}) OR token1_symbol IN ({ph}))")
        params.extend([*symbols, *symbols])
    elif q:
        if exact:
            where.append("(token0_symbol = ? COLLATE NOCASE OR token1_symbol = ? COLLATE NOCASE)")
            params.extend([q, q])
        else:
            where.append("(token0_symbol LIKE ? OR token1_symbol LIKE ?)")
            like = f"%{q}%"
            params.extend([like, like])

    if protocol:
        where.append("protocol = ?")
        params.append(protocol)
    if chain:
        where.append("chain = ?")
        params.append(chain)
    if hide_inactive:
        where.append("volume_usd >= ?")
        params.append(_MIN_ACTIVE_VOLUME_USD)
    _add_range_filter(where, params, "volume_1d_usd", min_volume_1d_usd, max_volume_1d_usd)
    _add_range_filter(where, params, "volume_30d_usd", min_volume_30d_usd, max_volume_30d_usd)
    _add_range_filter(where, params, "volume_1d_over_tvl", min_volume_1d_over_tvl, max_volume_1d_over_tvl)
    _add_range_filter(where, params, "apr_pool_30d", min_apr_pool_30d, max_apr_pool_30d)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    init_schema()
    with _LOCK, _connect() as conn:
        total = conn.execute(f"SELECT COUNT(*) FROM pools {where_sql}", params).fetchone()[0]
        rows = conn.execute(
            f"SELECT * FROM pools {where_sql} ORDER BY {sort_col} {order_sql} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()
    return [_row_to_pool(r) for r in rows], total
