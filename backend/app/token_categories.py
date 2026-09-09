"""Categorias estáticas pra ativos conhecidos, usado como aproximação de
"correlação" na lista de ativos (/assets): tokens na mesma categoria tendem a
se mover juntos (par 1:1 ou quase). É um mapeamento manual por símbolo, não
verificado on-chain -- qualquer um pode criar um token com esse mesmo símbolo
(mesmo aviso que já existe em PoolOverview sobre isso). Serve só como uma
pista visual, não como fonte de verdade.

Pra ativos que não estão aqui, a coluna "Principais pares" (calculada a
partir das próprias pools indexadas, ver services/index_builder.py) cumpre o
mesmo papel de dar uma pista de com o que o ativo mais negocia.
"""

from __future__ import annotations

_CATEGORIES: dict[str, str] = {}


def _register(category: str, symbols: list[str]) -> None:
    for symbol in symbols:
        _CATEGORIES[symbol.upper()] = category


_register(
    "Stablecoin (USD)",
    [
        "USDT", "USDC", "USDC.E", "USDBC", "DAI", "USDS", "TUSD", "USDP", "GUSD",
        "LUSD", "FRAX", "USDE", "PYUSD", "CRVUSD", "SUSD", "FDUSD", "DOLA", "MIM",
    ],
)
_register(
    "ETH / LST",
    [
        "WETH", "ETH", "STETH", "WSTETH", "RETH", "CBETH", "FRXETH", "SFRXETH",
        "OETH", "WOETH", "WEETH", "EZETH", "RSETH", "METH",
    ],
)
_register("BTC", ["WBTC", "CBBTC", "TBTC", "RENBTC", "BTCB"])
_register("Governança de DEX", ["UNI", "AERO", "VELO"])

# Lista fixa (não vem do banco) pra alimentar o filtro de categoria no
# frontend sem precisar de um endpoint só pra isso -- se adicionar uma
# categoria nova aqui, lembre de espelhar em frontend/src/format.ts
# (ASSET_CATEGORIES).
ALL_CATEGORIES = sorted(set(_CATEGORIES.values()))


def categorize(symbol: str) -> str | None:
    return _CATEGORIES.get(symbol.upper())
