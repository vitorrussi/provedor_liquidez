#!/usr/bin/env python3
"""Baixa um snapshot histórico de pools Uniswap v3 (Ethereum mainnet) para SQLite.

Por que existe: o replay exato (motor v3 em inteiros) e o app offline precisam
do histórico completo de cada pool desde a criação, sem acesso à internet. Este
script roda só localmente, com internet; o resultado (`snapshot.sqlite`) vai
junto com o código.

O que é baixado, por pool:

- Todos os logs emitidos pelo contrato do pool, do bloco de criação até um
  bloco final fixo (`end_block`, um bloco "finalized", igual para todos os
  pools). Guardados CRUS (topics e data em BLOB), com bloco, logIndex,
  transactionIndex, hash da tx e timestamp do bloco. A decodificação fica para
  quem lê o snapshot -- aqui só se identifica o tipo do evento pelo topic0.
- Estado on-chain no `end_block` (retorno cru de `eth_call`): imutáveis
  (token0/1, fee, tickSpacing, maxLiquidityPerTick), slot0, liquidity,
  feeGrowthGlobal0/1X128, protocolFees; `ticks(t)` de todo tick que aparece
  em Mint/Burn; `positions(key)` de toda posição (owner, tickLower, tickUpper)
  que aparece em Mint. Serve de checagem final do replay.
- Recibo (gasUsed, effectiveGasPrice, status, to) de toda tx com Mint, Burn ou
  Collect do pool -- base do custo de gas no backtest.
- Metadados dos tokens (decimals, symbol, name) via eth_call.
- Dados do subgraph v3 que o app usa hoje (pool, tokens, poolDayData e
  poolHourData completos, pools do mesmo par, preço do ETH), para as páginas
  funcionarem offline. Exige GRAPH_API_KEY (lida de backend/.env); a chave
  nunca é gravada no snapshot.

Fontes: RPC archive público sem chave (rpc.mevblocker.io, limite de 10.000
blocos por eth_getLogs, aceita lotes JSON-RPC); o Tenderly público serve de
reserva e de segunda fonte na verificação cruzada.

Uso:
    python3 scripts/download_snapshot.py download [--out DIR] [--pools ...]
    python3 scripts/download_snapshot.py verify   [--out DIR]

`download` pode ser interrompido e rodado de novo: retoma do que falta (o
`end_block` fica fixo na primeira execução). `verify` roda as checagens de
integridade e a conferência cruzada com a segunda fonte, e grava o relatório
na tabela `meta`.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import json
import os
import random
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
DEFAULT_OUT = REPO / "backend" / "data" / "snapshot"

PRIMARY_RPC = "https://rpc.mevblocker.io"
SECONDARY_RPC = "https://gateway.tenderly.co/public/mainnet"
LOG_RANGE = 10_000  # limite do mevblocker para eth_getLogs
BATCH = 100  # chamadas por lote JSON-RPC
WORKERS = 6
RECEIPT_WORKERS = 3  # recibos são o que mais esbarra no limite de taxa (HTTP 429)
USER_AGENT = "provedor-liquidez-snapshot/1.0"

UNISWAP_V3_SUBGRAPH_ID = "5zvR82QoaXYFyDEKLZ9t6v9adgnptxYpKpSbxtgVENFV"

# Pools escolhidos para o projeto (endereço -> rótulo). O bloco de criação vem
# do subgraph e é conferido on-chain (sem código no bloco anterior).
POOLS = {
    "0x8ad599c3a0ff1de082011efddc58f1908eb6e6d8": "USDC/WETH 0.30%",
    "0x7bea39867e4169dbe237d55c8242a8f2fcdcc387": "USDC/WETH 1%",
}


# ---------------------------------------------------------------------------
# keccak256 em Python puro (a stdlib só tem SHA3-256, que tem padding diferente)
# ---------------------------------------------------------------------------

def _keccak_constants():
    rot = [[0] * 5 for _ in range(5)]
    x, y = 1, 0
    for t in range(24):
        rot[x][y] = ((t + 1) * (t + 2) // 2) % 64
        x, y = y, (2 * x + 3 * y) % 5

    def rc_bit(t: int) -> int:
        if t % 255 == 0:
            return 1
        r = 1
        for _ in range(t % 255):
            r <<= 1
            if r & 0x100:
                r ^= 0x171
        return r & 1

    rcs = []
    for i in range(24):
        v = 0
        for j in range(7):
            if rc_bit(j + 7 * i):
                v |= 1 << ((1 << j) - 1)
        rcs.append(v)
    return rot, rcs


_ROT, _RC = _keccak_constants()
_MASK = (1 << 64) - 1


def _rotl(v: int, n: int) -> int:
    return ((v << n) | (v >> (64 - n))) & _MASK if n else v


def _keccak_f(a: list[int]) -> None:
    for rc in _RC:
        c = [a[x] ^ a[x + 5] ^ a[x + 10] ^ a[x + 15] ^ a[x + 20] for x in range(5)]
        d = [c[(x - 1) % 5] ^ _rotl(c[(x + 1) % 5], 1) for x in range(5)]
        for i in range(25):
            a[i] ^= d[i % 5]
        b = [0] * 25
        for x in range(5):
            for y in range(5):
                b[y + 5 * ((2 * x + 3 * y) % 5)] = _rotl(a[x + 5 * y], _ROT[x][y])
        for y in range(5):
            row = b[5 * y:5 * y + 5]
            for x in range(5):
                a[x + 5 * y] = row[x] ^ ((~row[(x + 1) % 5]) & row[(x + 2) % 5])
        a[0] ^= rc


def keccak256(data: bytes) -> bytes:
    rate = 136
    msg = bytearray(data) + b"\x01"
    msg += b"\x00" * (-len(msg) % rate)
    msg[-1] |= 0x80
    state = [0] * 25
    for off in range(0, len(msg), rate):
        for i in range(rate // 8):
            state[i] ^= int.from_bytes(msg[off + 8 * i:off + 8 * i + 8], "little")
        _keccak_f(state)
    return b"".join(state[i].to_bytes(8, "little") for i in range(4))


assert keccak256(b"").hex() == "c5d2460186f7233c927e7db2dcc703c0e500b653ca82273b7bfad8045d85a470"
assert keccak256(b"Transfer(address,address,uint256)").hex() == (
    "ddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
)


def selector(sig: str) -> str:
    return "0x" + keccak256(sig.encode()).hex()[:8]


# Eventos do UniswapV3Pool (topic0 calculado da assinatura, não copiado).
EVENT_SIGS = [
    "Initialize(uint160,int24)",
    "Mint(address,address,int24,int24,uint128,uint256,uint256)",
    "Collect(address,address,int24,int24,uint128,uint128)",
    "Burn(address,int24,int24,uint128,uint256,uint256)",
    "Swap(address,address,int256,int256,uint160,uint128,int24)",
    "Flash(address,address,uint256,uint256,uint256,uint256)",
    "IncreaseObservationCardinalityNext(uint16,uint16)",
    "SetFeeProtocol(uint8,uint8,uint8,uint8)",
    "CollectProtocol(address,address,uint128,uint128)",
]
TOPIC0 = {keccak256(s.encode()): s.split("(")[0] for s in EVENT_SIGS}
GAS_EVENTS = ("Mint", "Burn", "Collect")

POOL_STATE_CALLS = [
    "token0()", "token1()", "fee()", "tickSpacing()", "maxLiquidityPerTick()",
    "slot0()", "liquidity()", "feeGrowthGlobal0X128()", "feeGrowthGlobal1X128()",
    "protocolFees()",
]
TOKEN_CALLS = ["decimals()", "symbol()", "name()"]


# ---------------------------------------------------------------------------
# JSON-RPC
# ---------------------------------------------------------------------------

class RpcError(Exception):
    pass


def _post(url: str, body, timeout: float = 90):
    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def rpc(method: str, params: list, url: str = PRIMARY_RPC, retries: int = 6):
    delay = 1.0
    last: Exception | None = None
    for _ in range(retries):
        try:
            out = _post(url, {"jsonrpc": "2.0", "id": 1, "method": method, "params": params})
            if "error" in out:
                raise RpcError(f"{method}: {out['error']}")
            return out["result"]
        except (urllib.error.URLError, TimeoutError, RpcError, json.JSONDecodeError) as e:
            last = e
            if isinstance(e, RpcError) and "exceeds limit" in str(e):
                raise
            time.sleep(delay + random.random())
            delay = min(delay * 2, 30)
    raise RpcError(f"{method} falhou após {retries} tentativas: {last}")


def rpc_batch(calls: list[tuple[str, list]], url: str = PRIMARY_RPC, retries: int = 10) -> list:
    """Um lote JSON-RPC; devolve os resultados na ordem das chamadas.

    Em HTTP 429 espera mais (respeita Retry-After). Se o primário falhar em
    todas as tentativas, tenta a reserva antes de desistir.
    """
    body = [{"jsonrpc": "2.0", "id": i, "method": m, "params": p} for i, (m, p) in enumerate(calls)]
    delay = 2.0
    last: Exception | None = None
    for _ in range(retries):
        try:
            out = _post(url, body)
            if not isinstance(out, list):
                raise RpcError(f"lote sem lista: {str(out)[:200]}")
            by_id = {o["id"]: o for o in out}
            errs = [o["error"] for o in out if "error" in o]
            if errs or len(by_id) != len(calls):
                raise RpcError(f"lote com erro: {errs[:2]} ({len(by_id)}/{len(calls)})")
            return [by_id[i]["result"] for i in range(len(calls))]
        except (urllib.error.URLError, TimeoutError, RpcError, json.JSONDecodeError) as e:
            last = e
            wait = delay
            if isinstance(e, urllib.error.HTTPError) and e.code == 429:
                retry_after = e.headers.get("Retry-After", "")
                wait = max(delay, float(retry_after)) if retry_after.isdigit() else max(delay, 10.0)
            time.sleep(wait + random.random())
            delay = min(delay * 2, 60)
    if url == PRIMARY_RPC:
        return rpc_batch(calls, SECONDARY_RPC, retries=4)
    raise RpcError(f"lote falhou após {retries} tentativas: {last}")


def get_logs(address: str, start: int, end: int, url: str = PRIMARY_RPC) -> list[dict]:
    """eth_getLogs em [start, end]; divide o intervalo se o RPC recusar."""
    try:
        return rpc("eth_getLogs", [{"address": address, "fromBlock": hex(start), "toBlock": hex(end)}], url)
    except RpcError as e:
        if start == end:
            raise
        if url == PRIMARY_RPC and "exceeds limit" not in str(e):
            # Falha persistente no primário: tenta a reserva antes de dividir.
            try:
                return rpc("eth_getLogs", [{"address": address, "fromBlock": hex(start), "toBlock": hex(end)}], SECONDARY_RPC)
            except RpcError:
                pass
        mid = (start + end) // 2
        return get_logs(address, start, mid, url) + get_logs(address, mid + 1, end, url)


# ---------------------------------------------------------------------------
# SQLite
# ---------------------------------------------------------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL);

CREATE TABLE IF NOT EXISTS pools (
    address TEXT PRIMARY KEY,          -- minúsculo, 0x...
    label TEXT NOT NULL,
    created_block INTEGER NOT NULL,
    end_block INTEGER NOT NULL
);

-- Intervalos de blocos já baixados (inclusivos). Sem lacuna nem sobreposição
-- entre created_block e end_block = download completo.
CREATE TABLE IF NOT EXISTS log_chunks (
    pool TEXT NOT NULL,
    from_block INTEGER NOT NULL,
    to_block INTEGER NOT NULL,
    n_logs INTEGER NOT NULL,
    PRIMARY KEY (pool, from_block)
);

-- Logs crus do contrato do pool. topic1..3 e data em BLOB (32 bytes por
-- palavra, big-endian, como na ABI).
CREATE TABLE IF NOT EXISTS logs (
    pool TEXT NOT NULL,
    block_number INTEGER NOT NULL,
    log_index INTEGER NOT NULL,
    tx_index INTEGER NOT NULL,
    tx_hash BLOB NOT NULL,
    block_timestamp INTEGER NOT NULL,
    event TEXT NOT NULL,               -- nome pelo topic0 ('unknown' se não reconhecido)
    topic0 BLOB NOT NULL,
    topic1 BLOB,
    topic2 BLOB,
    topic3 BLOB,
    data BLOB NOT NULL,
    PRIMARY KEY (pool, block_number, log_index)
) WITHOUT ROWID;
CREATE INDEX IF NOT EXISTS logs_event ON logs (pool, event);

-- Retorno cru de eth_call no end_block.
CREATE TABLE IF NOT EXISTS state_calls (
    target TEXT NOT NULL,              -- contrato chamado (pool ou token)
    block_number INTEGER NOT NULL,
    call TEXT NOT NULL,                -- assinatura, ex. 'slot0()' ou 'ticks(int24)'
    arg TEXT NOT NULL,                 -- argumento em texto ('' se não tem; tick em decimal; chave da posição em hex)
    calldata TEXT NOT NULL,
    result BLOB NOT NULL,
    PRIMARY KEY (target, block_number, call, arg)
) WITHOUT ROWID;

-- Chaves de posição (owner, tickLower, tickUpper) vistas em Mint, com a chave
-- keccak usada em positions(bytes32).
CREATE TABLE IF NOT EXISTS position_keys (
    pool TEXT NOT NULL,
    position_key TEXT NOT NULL,        -- 0x + 64 hex
    owner TEXT NOT NULL,
    tick_lower INTEGER NOT NULL,
    tick_upper INTEGER NOT NULL,
    PRIMARY KEY (pool, position_key)
) WITHOUT ROWID;

CREATE TABLE IF NOT EXISTS receipts (
    tx_hash BLOB PRIMARY KEY,
    block_number INTEGER NOT NULL,
    tx_index INTEGER NOT NULL,
    status INTEGER NOT NULL,
    gas_used INTEGER NOT NULL,
    effective_gas_price INTEGER NOT NULL,  -- wei por unidade de gas
    to_address TEXT
) WITHOUT ROWID;

-- Dados do subgraph Uniswap v3 (derivados, valores BigDecimal como texto).
CREATE TABLE IF NOT EXISTS subgraph_pool (
    address TEXT PRIMARY KEY,
    json TEXT NOT NULL                 -- resposta de pool(id) como o app consulta hoje
);
CREATE TABLE IF NOT EXISTS subgraph_related_pools (
    token0 TEXT NOT NULL,
    token1 TEXT NOT NULL,
    json TEXT NOT NULL                 -- lista de pools do mesmo par (todas as fee tiers)
);
CREATE TABLE IF NOT EXISTS subgraph_pool_day (
    pool TEXT NOT NULL,
    date INTEGER NOT NULL,             -- unix, início do dia UTC
    tvl_usd TEXT, volume_usd TEXT, fees_usd TEXT,
    open TEXT, high TEXT, low TEXT, close TEXT,
    PRIMARY KEY (pool, date)
) WITHOUT ROWID;
CREATE TABLE IF NOT EXISTS subgraph_pool_hour (
    pool TEXT NOT NULL,
    period_start_unix INTEGER NOT NULL,
    close TEXT, tvl_usd TEXT, volume_usd TEXT,
    PRIMARY KEY (pool, period_start_unix)
) WITHOUT ROWID;
"""


def connect(out: Path) -> sqlite3.Connection:
    out.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(out / "snapshot.sqlite")
    db.execute("PRAGMA journal_mode=WAL")
    db.executescript(SCHEMA)
    return db


def meta_get(db, key: str) -> str | None:
    row = db.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def meta_set(db, key: str, value) -> None:
    v = value if isinstance(value, str) else json.dumps(value, sort_keys=True)
    db.execute("INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)", (key, v))
    db.commit()


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


# ---------------------------------------------------------------------------
# Subgraph
# ---------------------------------------------------------------------------

def graph_api_key() -> str:
    key = os.environ.get("GRAPH_API_KEY", "").strip()
    env = REPO / "backend" / ".env"
    if not key and env.exists():
        for line in env.read_text().splitlines():
            if line.startswith("GRAPH_API_KEY="):
                key = line.split("=", 1)[1].strip()
    if not key:
        sys.exit("GRAPH_API_KEY não encontrada (variável de ambiente ou backend/.env)")
    return key


def graph(query: str, variables: dict, key: str) -> dict:
    url = f"https://gateway.thegraph.com/api/{key}/subgraphs/id/{UNISWAP_V3_SUBGRAPH_ID}"
    delay = 2.0
    for _ in range(6):
        try:
            out = _post(url, {"query": query, "variables": variables}, timeout=120)
            if "errors" in out:
                raise RpcError(str(out["errors"])[:300])
            return out["data"]
        except (urllib.error.URLError, TimeoutError, RpcError, json.JSONDecodeError) as e:
            last = e
            time.sleep(delay)
            delay *= 2
    raise RpcError(f"subgraph falhou: {last}")


_POOL_QUERY = """
query ($id: ID!) {
  pool(id: $id) {
    id feeTier totalValueLockedUSD volumeUSD feesUSD txCount tick
    token0Price token1Price createdAtTimestamp createdAtBlockNumber
    token0 { id symbol name decimals derivedETH }
    token1 { id symbol name decimals derivedETH }
  }
  bundle(id: "1") { ethPriceUSD }
  _meta { block { number timestamp } }
}"""

_RELATED_QUERY = """
query ($token0: String!, $token1: String!) {
  pools(where: { token0: $token0, token1: $token1 }, orderBy: totalValueLockedUSD, orderDirection: desc, first: 100) {
    id feeTier totalValueLockedUSD volumeUSD feesUSD txCount createdAtTimestamp
    token0 { id symbol name decimals derivedETH }
    token1 { id symbol name decimals derivedETH }
  }
}"""

_DAY_QUERY = """
query ($pool: String!, $after: Int!) {
  poolDayDatas(where: { pool: $pool, date_gt: $after }, orderBy: date, orderDirection: asc, first: 1000) {
    date tvlUSD volumeUSD feesUSD open high low close
  }
}"""

_HOUR_QUERY = """
query ($pool: String!, $after: Int!) {
  poolHourDatas(where: { pool: $pool, periodStartUnix_gt: $after }, orderBy: periodStartUnix, orderDirection: asc, first: 1000) {
    periodStartUnix close tvlUSD volumeUSD
  }
}"""


def download_subgraph(db, pools: list[str]) -> None:
    if meta_get(db, "subgraph_done") == "1":
        log("subgraph: já baixado")
        return
    key = graph_api_key()
    pairs = set()
    for addr in pools:
        data = graph(_POOL_QUERY, {"id": addr}, key)
        db.execute("INSERT OR REPLACE INTO subgraph_pool VALUES (?, ?)", (addr, json.dumps(data, sort_keys=True)))
        pairs.add((data["pool"]["token0"]["id"], data["pool"]["token1"]["id"]))
        for table, query, field, cols in (
            ("subgraph_pool_day", _DAY_QUERY, "poolDayDatas",
             ("date", "tvlUSD", "volumeUSD", "feesUSD", "open", "high", "low", "close")),
            ("subgraph_pool_hour", _HOUR_QUERY, "poolHourDatas",
             ("periodStartUnix", "close", "tvlUSD", "volumeUSD")),
        ):
            after, n = 0, 0
            while True:
                rows = graph(query, {"pool": addr, "after": after}, key)[field]
                if not rows:
                    break
                db.executemany(
                    f"INSERT OR REPLACE INTO {table} VALUES ({','.join('?' * (len(cols) + 1))})",
                    [(addr, *[r[c] for c in cols]) for r in rows],
                )
                after = int(rows[-1][cols[0]])
                n += len(rows)
            db.commit()
            log(f"subgraph {addr[:10]} {field}: {n} linhas")
    db.execute("DELETE FROM subgraph_related_pools")
    for t0, t1 in sorted(pairs):
        data = graph(_RELATED_QUERY, {"token0": t0, "token1": t1}, key)
        db.execute("INSERT INTO subgraph_related_pools VALUES (?, ?, ?)", (t0, t1, json.dumps(data["pools"], sort_keys=True)))
    db.commit()
    meta_set(db, "subgraph_done", "1")


# ---------------------------------------------------------------------------
# On-chain
# ---------------------------------------------------------------------------

def _b(hexstr: str) -> bytes:
    return bytes.fromhex(hexstr[2:])


def _log_row(pool: str, lg: dict) -> tuple:
    topics = [_b(t) for t in lg["topics"]] + [None] * (4 - len(lg["topics"]))
    return (
        pool,
        int(lg["blockNumber"], 16),
        int(lg["logIndex"], 16),
        int(lg["transactionIndex"], 16),
        _b(lg["transactionHash"]),
        int(lg["blockTimestamp"], 16),
        TOPIC0.get(topics[0], "unknown"),
        topics[0], topics[1], topics[2], topics[3],
        _b(lg["data"]),
    )


def ensure_pool(db, addr: str, label: str, end_block: int) -> int:
    row = db.execute("SELECT created_block FROM pools WHERE address = ?", (addr,)).fetchone()
    if row:
        return row[0]
    sub = db.execute("SELECT json FROM subgraph_pool WHERE address = ?", (addr,)).fetchone()
    created = int(json.loads(sub[0])["pool"]["createdAtBlockNumber"])
    # Confere on-chain: sem código no bloco anterior, com código no bloco de criação.
    before = rpc("eth_getCode", [addr, hex(created - 1)])
    at = rpc("eth_getCode", [addr, hex(created)])
    if before not in ("0x", "0x0") or len(at) <= 2:
        sys.exit(f"{addr}: bloco de criação {created} não confere on-chain")
    db.execute("INSERT INTO pools VALUES (?, ?, ?, ?)", (addr, label, created, end_block))
    db.commit()
    return created


def download_logs(db, addr: str, created: int, end_block: int) -> None:
    done = {r[0] for r in db.execute("SELECT from_block FROM log_chunks WHERE pool = ?", (addr,))}
    todo = [(s, min(s + LOG_RANGE - 1, end_block)) for s in range(created, end_block + 1, LOG_RANGE)]
    todo = [c for c in todo if c[0] not in done]
    log(f"{addr[:10]} logs: {len(done)} intervalos prontos, {len(todo)} a baixar")
    t0, n = time.time(), 0
    with cf.ThreadPoolExecutor(WORKERS) as ex:
        futs = {ex.submit(get_logs, addr, s, e): (s, e) for s, e in todo}
        for i, fut in enumerate(cf.as_completed(futs), 1):
            s, e = futs[fut]
            logs = fut.result()
            rows = [_log_row(addr, lg) for lg in logs]
            if any(lg.get("removed") for lg in logs) or any(r[1] < s or r[1] > e for r in rows):
                sys.exit(f"{addr} [{s},{e}]: log removido ou fora do intervalo")
            db.executemany("INSERT OR REPLACE INTO logs VALUES (?,?,?,?,?,?,?,?,?,?,?,?)", rows)
            db.execute("INSERT INTO log_chunks VALUES (?, ?, ?, ?)", (addr, s, e, len(rows)))
            n += len(rows)
            if i % 50 == 0 or i == len(todo):
                db.commit()
                rate = i / (time.time() - t0)
                log(f"{addr[:10]} logs: {i}/{len(todo)} intervalos, {n} logs, ~{(len(todo) - i) / rate / 60:.1f} min restantes")
    db.commit()


def _int24_bytes(v: int) -> bytes:
    return (v & 0xFFFFFF).to_bytes(3, "big")


def _word_to_int(w: bytes, signed: bool) -> int:
    return int.from_bytes(w, "big", signed=signed)


def build_position_keys(db, addr: str) -> None:
    rows = db.execute(
        "SELECT DISTINCT topic1, topic2, topic3 FROM logs WHERE pool = ? AND event = 'Mint'", (addr,)
    ).fetchall()
    out = []
    for owner_w, lo_w, hi_w in rows:
        owner = owner_w[12:]
        lo, hi = _word_to_int(lo_w, True), _word_to_int(hi_w, True)
        key = keccak256(owner + _int24_bytes(lo) + _int24_bytes(hi))
        out.append((addr, "0x" + key.hex(), "0x" + owner.hex(), lo, hi))
    db.executemany("INSERT OR IGNORE INTO position_keys VALUES (?, ?, ?, ?, ?)", out)
    db.commit()
    log(f"{addr[:10]} posições distintas em Mint: {len(out)}")


def _eth_calls(db, items: list[tuple[str, str, str, str]], block: int, label: str) -> None:
    """items: (target, call, arg, calldata). Pula o que já está gravado."""
    have = {
        (r[0], r[1], r[2])
        for r in db.execute("SELECT target, call, arg FROM state_calls WHERE block_number = ?", (block,))
    }
    items = [it for it in items if (it[0], it[1], it[2]) not in have]
    if not items:
        return
    log(f"{label}: {len(items)} eth_call")
    batches = [items[i:i + BATCH] for i in range(0, len(items), BATCH)]

    def run(batch):
        res = rpc_batch([("eth_call", [{"to": t, "data": cd}, hex(block)]) for t, _, _, cd in batch])
        return [(t, block, c, a, cd, _b(r)) for (t, c, a, cd), r in zip(batch, res)]

    with cf.ThreadPoolExecutor(WORKERS) as ex:
        for i, rows in enumerate(ex.map(run, batches), 1):
            db.executemany("INSERT OR REPLACE INTO state_calls VALUES (?, ?, ?, ?, ?, ?)", rows)
            if i % 20 == 0:
                db.commit()
                log(f"{label}: {i}/{len(batches)} lotes")
    db.commit()


def download_state(db, addr: str, end_block: int) -> None:
    items = [(addr, c, "", selector(c)) for c in POOL_STATE_CALLS]
    _eth_calls(db, items, end_block, f"{addr[:10]} estado do pool")

    def word(call):
        r = db.execute(
            "SELECT result FROM state_calls WHERE target = ? AND block_number = ? AND call = ?", (addr, end_block, call)
        ).fetchone()[0]
        return r

    tokens = ["0x" + word(c)[12:32].hex() for c in ("token0()", "token1()")]
    _eth_calls(db, [(t, c, "", selector(c)) for t in tokens for c in TOKEN_CALLS], end_block, "tokens")

    ticks = set()
    for lo, hi in db.execute(
        "SELECT topic2, topic3 FROM logs WHERE pool = ? AND event IN ('Mint', 'Burn')", (addr,)
    ):
        ticks.add(_word_to_int(lo, True))
        ticks.add(_word_to_int(hi, True))
    sel = selector("ticks(int24)")
    items = [(addr, "ticks(int24)", str(t), sel + (t % (1 << 256)).to_bytes(32, "big").hex()) for t in sorted(ticks)]
    _eth_calls(db, items, end_block, f"{addr[:10]} ticks")

    sel = selector("positions(bytes32)")
    items = [
        (addr, "positions(bytes32)", k, sel + k[2:])
        for (k,) in db.execute("SELECT position_key FROM position_keys WHERE pool = ? ORDER BY position_key", (addr,))
    ]
    _eth_calls(db, items, end_block, f"{addr[:10]} posições")


def download_receipts(db, addr: str) -> None:
    txs = [
        r[0]
        for r in db.execute(
            f"SELECT DISTINCT l.tx_hash FROM logs l LEFT JOIN receipts r ON r.tx_hash = l.tx_hash "
            f"WHERE l.pool = ? AND l.event IN ({','.join('?' * len(GAS_EVENTS))}) AND r.tx_hash IS NULL",
            (addr, *GAS_EVENTS),
        )
    ]
    log(f"{addr[:10]} recibos a baixar: {len(txs)}")
    batches = [txs[i:i + BATCH] for i in range(0, len(txs), BATCH)]

    def run(batch):
        res = rpc_batch([("eth_getTransactionReceipt", ["0x" + h.hex()]) for h in batch])
        rows = []
        for h, rc in zip(batch, res):
            if rc is None:
                raise RpcError(f"recibo nulo para 0x{h.hex()}")
            rows.append((
                h, int(rc["blockNumber"], 16), int(rc["transactionIndex"], 16), int(rc["status"], 16),
                int(rc["gasUsed"], 16), int(rc["effectiveGasPrice"], 16), rc.get("to"),
            ))
        return rows

    t0 = time.time()
    with cf.ThreadPoolExecutor(RECEIPT_WORKERS) as ex:
        for i, rows in enumerate(ex.map(run, batches), 1):
            db.executemany("INSERT OR REPLACE INTO receipts VALUES (?, ?, ?, ?, ?, ?, ?)", rows)
            if i % 20 == 0 or i == len(batches):
                db.commit()
                rate = i / (time.time() - t0)
                log(f"{addr[:10]} recibos: {i}/{len(batches)} lotes, ~{(len(batches) - i) / rate / 60:.1f} min restantes")
    db.commit()


def cmd_download(args) -> None:
    db = connect(args.out)
    pools = {a.lower(): POOLS.get(a.lower(), a.lower()) for a in args.pools}
    end_block = meta_get(db, "end_block")
    if end_block is None:
        fin = rpc("eth_getBlockByNumber", ["finalized", False])
        meta_set(db, "end_block", str(int(fin["number"], 16)))
        meta_set(db, "end_block_timestamp", str(int(fin["timestamp"], 16)))
        meta_set(db, "chain", "ethereum-mainnet (chainId 1)")
        meta_set(db, "sources", {"primary_rpc": PRIMARY_RPC, "secondary_rpc": SECONDARY_RPC,
                                 "subgraph": f"uniswap-v3 mainnet {UNISWAP_V3_SUBGRAPH_ID}"})
        meta_set(db, "started_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
        end_block = meta_get(db, "end_block")
    end_block = int(end_block)
    log(f"end_block = {end_block}")

    download_subgraph(db, list(pools))
    for addr, label in pools.items():
        created = ensure_pool(db, addr, label, end_block)
        log(f"== {label} ({addr}) blocos {created}..{end_block}")
        download_logs(db, addr, created, end_block)
        build_position_keys(db, addr)
        download_state(db, addr, end_block)
        download_receipts(db, addr)
    meta_set(db, "finished_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    log("download completo; rode `verify`")


# ---------------------------------------------------------------------------
# Verificação
# ---------------------------------------------------------------------------

def cmd_verify(args) -> None:
    db = connect(args.out)
    end_block = int(meta_get(db, "end_block"))
    report: dict = {"end_block": end_block, "pools": {}}
    ok = True

    def check(cond: bool, msg: str, bucket: list) -> None:
        nonlocal ok
        bucket.append(("ok  " if cond else "FAIL") + " " + msg)
        if not cond:
            ok = False

    for addr, label, created, pend in db.execute("SELECT * FROM pools ORDER BY created_block").fetchall():
        res: list[str] = []
        check(pend == end_block, f"end_block do pool = {end_block}", res)

        # 1. Cobertura: intervalos contíguos de created até end, sem sobreposição.
        chunks = db.execute(
            "SELECT from_block, to_block, n_logs FROM log_chunks WHERE pool = ? ORDER BY from_block", (addr,)
        ).fetchall()
        expect = created
        gaps = []
        for s, e, _ in chunks:
            if s != expect:
                gaps.append((expect, s))
            expect = e + 1
        check(not gaps and chunks and chunks[0][0] == created and chunks[-1][1] == end_block,
              f"{len(chunks)} intervalos cobrem {created}..{end_block} sem lacuna (lacunas: {gaps[:3]})", res)

        # 2. Contagem por intervalo = linhas gravadas.
        n_rows = db.execute("SELECT COUNT(*) FROM logs WHERE pool = ?", (addr,)).fetchone()[0]
        n_chunks = sum(c[2] for c in chunks)
        check(n_rows == n_chunks, f"logs gravados ({n_rows}) = soma dos intervalos ({n_chunks})", res)

        # 3. Tipos de evento.
        counts = dict(db.execute("SELECT event, COUNT(*) FROM logs WHERE pool = ? GROUP BY event", (addr,)).fetchall())
        check("unknown" not in counts, f"todos os eventos reconhecidos: {counts}", res)
        first = db.execute(
            "SELECT event, block_number FROM logs WHERE pool = ? ORDER BY block_number, log_index LIMIT 1", (addr,)
        ).fetchone()
        check(first == ("Initialize", created) and counts.get("Initialize") == 1,
              f"primeiro evento é o único Initialize, no bloco de criação ({first})", res)

        # 4. Ordem dentro do bloco: logIndex único, e tx_index não decresce com o logIndex.
        bad_order = db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT tx_index, LAG(tx_index) OVER (PARTITION BY block_number ORDER BY log_index) AS prev
                 FROM logs WHERE pool = ?) WHERE prev IS NOT NULL AND tx_index < prev""", (addr,)
        ).fetchone()[0]
        check(bad_order == 0, f"logIndex/txIndex em ordem dentro de cada bloco ({bad_order} fora de ordem)", res)
        bad_ts = db.execute(
            """SELECT COUNT(*) FROM (
                 SELECT block_timestamp, LAG(block_timestamp) OVER (ORDER BY block_number, log_index) AS prev
                 FROM logs WHERE pool = ?) WHERE prev IS NOT NULL AND block_timestamp < prev""", (addr,)
        ).fetchone()[0]
        check(bad_ts == 0, f"timestamps não decrescem ({bad_ts} violações)", res)

        # 5. Recibos de toda tx com Mint/Burn/Collect, com status 1 e bloco igual.
        missing, bad_rc = db.execute(
            f"""SELECT SUM(r.tx_hash IS NULL), SUM(r.tx_hash IS NOT NULL AND (r.status != 1 OR r.block_number != l.block_number))
                FROM (SELECT DISTINCT tx_hash, block_number FROM logs
                      WHERE pool = ? AND event IN ({','.join('?' * len(GAS_EVENTS))})) l
                LEFT JOIN receipts r ON r.tx_hash = l.tx_hash""", (addr, *GAS_EVENTS)
        ).fetchone()
        check(not missing and not bad_rc, f"recibos: {missing or 0} faltando, {bad_rc or 0} com status/bloco errado", res)

        # 6. Estado no end_block: imutáveis + ticks + posições.
        n_pos = db.execute("SELECT COUNT(*) FROM position_keys WHERE pool = ?", (addr,)).fetchone()[0]
        n_pos_calls = db.execute(
            "SELECT COUNT(*) FROM state_calls WHERE target = ? AND call = 'positions(bytes32)'", (addr,)
        ).fetchone()[0]
        n_state = db.execute(
            "SELECT COUNT(*) FROM state_calls WHERE target = ? AND arg = ''", (addr,)
        ).fetchone()[0]
        check(n_state == len(POOL_STATE_CALLS) and n_pos_calls == n_pos,
              f"estado no end_block: {n_state} chamadas do pool, {n_pos_calls}/{n_pos} posições", res)

        # 7. Conferência cruzada com a segunda fonte numa amostra de intervalos
        # (primeiro, último, os 5 mais cheios e aleatórios).
        rnd = random.Random(int(addr, 16))
        busiest = sorted(chunks, key=lambda c: -c[2])[:5]
        sample = {chunks[0], chunks[-1], *busiest, *rnd.sample(chunks, min(len(chunks), args.sample))}
        mismatches = []

        def key_fields(row: tuple) -> tuple:
            # bloco, logIndex, tx, topic0..3, data (o timestamp pode faltar na segunda fonte)
            return (row[1], row[2], row[4], row[7], row[8], row[9], row[10], row[11])

        def theirs(chunk):
            s, e, _ = chunk
            other = get_logs(addr, s, e, SECONDARY_RPC)
            return sorted(key_fields(_log_row(addr, {"blockTimestamp": "0x0", **lg})) for lg in other)

        sample = sorted(sample)
        with cf.ThreadPoolExecutor(4) as ex:
            for (s, e, _), other in zip(sample, ex.map(theirs, sample)):
                ours = sorted(tuple(r) for r in db.execute(
                    "SELECT block_number, log_index, tx_hash, topic0, topic1, topic2, topic3, data FROM logs "
                    "WHERE pool = ? AND block_number BETWEEN ? AND ?", (addr, s, e)))
                if ours != other:
                    mismatches.append((s, e, len(other), len(ours)))
        check(not mismatches, f"conferência cruzada com {SECONDARY_RPC}: {len(sample)} intervalos, "
                              f"{sum(c[2] for c in sample)} logs, divergências: {mismatches[:3]}", res)

        report["pools"][addr] = {"label": label, "created_block": created, "events": counts, "checks": res}
        print(f"\n== {label} ({addr})")
        for line in res:
            print("  " + line)

    # Subgraph
    sub = {
        "pools": db.execute("SELECT COUNT(*) FROM subgraph_pool").fetchone()[0],
        "day_rows": db.execute("SELECT COUNT(*) FROM subgraph_pool_day").fetchone()[0],
        "hour_rows": db.execute("SELECT COUNT(*) FROM subgraph_pool_hour").fetchone()[0],
        "related_lists": db.execute("SELECT COUNT(*) FROM subgraph_related_pools").fetchone()[0],
    }
    print(f"\n== subgraph: {sub}")
    report["subgraph"] = sub
    report["ok"] = ok
    meta_set(db, "verify_report", report)
    meta_set(db, "verified_at", time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()))
    print("\nRESULTADO:", "OK" if ok else "FALHOU")
    sys.exit(0 if ok else 1)


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download")
    d.add_argument("--out", type=Path, default=DEFAULT_OUT)
    d.add_argument("--pools", nargs="+", default=list(POOLS))
    v = sub.add_parser("verify")
    v.add_argument("--out", type=Path, default=DEFAULT_OUT)
    v.add_argument("--sample", type=int, default=25, help="intervalos aleatórios na conferência cruzada, por pool")
    args = p.parse_args()
    {"download": cmd_download, "verify": cmd_verify}[args.cmd](args)


if __name__ == "__main__":
    main()
