"""Cliente JSON-RPC fino pra ler saldo real de token via chamada on-chain
(eth_call em ERC20.balanceOf) -- sem web3.py, só o seletor de função padrão
de qualquer ERC20, que é o suficiente pra esse único uso.

Usado só pra verificar o TVL de um pool na página de detalhe: o campo
totalValueLockedUSD do subgraph comunitário da Uniswap pode divergir bastante
do saldo real do contrato (bug de tracking incremental já documentado, ver
CLAUDE.md) -- comparando com o saldo on-chain de verdade a gente corrige isso
em vez de confiar cegamente no número do subgraph.

`rpc_url` é sempre explícito no chamador (nunca lido daqui de dentro) porque
pools de protocolos diferentes vivem em chains diferentes (v2/v3/v4 em
Ethereum mainnet, Aerodrome Slipstream na Base) -- ver
`services/pools.py::_rpc_url_for_protocol`. Chamar com o RPC errado não dá
erro (o eth_call simplesmente não acha o contrato), só devolve um saldo
zerado -- por isso não existe um default aqui que possa mascarar esse tipo de
engano.
"""

from __future__ import annotations

import httpx

_BALANCE_OF_SELECTOR = "0x70a08231"  # balanceOf(address)


class OnchainQueryError(RuntimeError):
    pass


async def get_erc20_balance(token_address: str, holder_address: str, rpc_url: str) -> int:
    """Saldo bruto (sem ajuste de decimais) de `token_address` na carteira
    `holder_address`, via eth_call direto contra `rpc_url`."""
    padded_holder = holder_address.lower().removeprefix("0x").zfill(64)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [{"to": token_address, "data": f"{_BALANCE_OF_SELECTOR}{padded_holder}"}, "latest"],
    }

    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            response = await client.post(rpc_url, json=payload)
            response.raise_for_status()
            result = response.json()
    except httpx.HTTPError as exc:
        raise OnchainQueryError(f"Erro de rede consultando RPC on-chain: {exc}") from exc

    if "error" in result:
        raise OnchainQueryError(f"Erro no RPC on-chain: {result['error']}")

    hex_value = result.get("result")
    if not hex_value or hex_value == "0x":
        return 0
    return int(hex_value, 16)
