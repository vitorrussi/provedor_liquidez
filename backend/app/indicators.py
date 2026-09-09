"""Funções matemáticas puras para análise de posições de liquidez Uniswap v3.

Nenhuma função aqui faz I/O (rede, disco). Isso torna o módulo fácil de
testar isoladamente e reutilizável em qualquer camada (API, script, notebook).

Convenção de preço: em todo o módulo, "preço" significa token1 por token0
(mesma convenção do campo `token0Price` do subgraph da Uniswap), já ajustado
pelas casas decimais dos tokens. Faixas de posição são [Pa, Pb] com Pa < Pb.
"""

from __future__ import annotations

import math
from dataclasses import dataclass


def price_from_tick(tick: int, decimals0: int, decimals1: int) -> float:
    """Converte um tick da Uniswap v3 em preço (token1 por token0), já
    ajustado pelas casas decimais dos dois tokens.

    Fórmula: 1.0001^tick * 10^(decimals0 - decimals1)
    """
    return (1.0001**tick) * (10 ** (decimals0 - decimals1))


def tick_from_price(price: float, decimals0: int, decimals1: int) -> float:
    """Inverso de price_from_tick — útil para converter um preço-alvo de
    range em tick (para exibição/validação, não para uso on-chain)."""
    if price <= 0:
        raise ValueError("price deve ser positivo")
    raw = price / (10 ** (decimals0 - decimals1))
    return math.log(raw, 1.0001)


@dataclass(frozen=True)
class TokenAmounts:
    amount0: float
    amount1: float


def amounts_for_liquidity(liquidity: float, price: float, price_lower: float, price_upper: float) -> TokenAmounts:
    """Dado L (liquidez) e uma faixa [price_lower, price_upper], retorna as
    quantidades de token0/token1 que compõem a posição no preço atual.

    Implementa as três regiões da curva de liquidez concentrada da Uniswap v3
    (whitepaper v3, seção 6.29-6.30):
      - preço <= price_lower: posição 100% em token0
      - preço >= price_upper: posição 100% em token1
      - preço dentro da faixa: mix dos dois tokens
    """
    if price_lower <= 0 or price_upper <= 0:
        raise ValueError("price_lower e price_upper devem ser positivos")
    if price_lower >= price_upper:
        raise ValueError("price_lower deve ser menor que price_upper")

    sqrt_p = math.sqrt(price)
    sqrt_pa = math.sqrt(price_lower)
    sqrt_pb = math.sqrt(price_upper)

    if price <= price_lower:
        amount0 = liquidity * (1 / sqrt_pa - 1 / sqrt_pb)
        amount1 = 0.0
    elif price >= price_upper:
        amount0 = 0.0
        amount1 = liquidity * (sqrt_pb - sqrt_pa)
    else:
        amount0 = liquidity * (1 / sqrt_p - 1 / sqrt_pb)
        amount1 = liquidity * (sqrt_p - sqrt_pa)

    return TokenAmounts(amount0=amount0, amount1=amount1)


def position_value(amounts: TokenAmounts, price: float) -> float:
    """Valor da posição em unidades de token1 (preço = token1 por token0)."""
    return amounts.amount0 * price + amounts.amount1


def impermanent_loss_v2(price_ratio: float) -> float:
    """IL clássico (pool full-range, estilo Uniswap v2): 2*sqrt(r)/(1+r) - 1,
    onde r = preço_atual / preço_de_entrada. Retorna fração (ex: -0.057 = -5.7%).
    """
    if price_ratio <= 0:
        raise ValueError("price_ratio deve ser positivo")
    r = price_ratio
    return 2 * math.sqrt(r) / (1 + r) - 1


def impermanent_loss_v3(
    entry_price: float,
    current_price: float,
    price_lower: float,
    price_upper: float,
    liquidity: float = 1.0,
) -> float:
    """IL para uma posição de liquidez concentrada (Uniswap v3).

    Compara o valor da posição LP no preço atual contra o valor de apenas
    ter guardado (HODL) as quantidades de token0/token1 recebidas no
    depósito. Retorna fração (negativa = perda vs HODL).

    Quando price_lower -> 0 e price_upper -> infinito, converge para o IL
    clássico da v2 (verificado em teste).
    """
    entry_amounts = amounts_for_liquidity(liquidity, entry_price, price_lower, price_upper)
    current_amounts = amounts_for_liquidity(liquidity, current_price, price_lower, price_upper)

    lp_value = position_value(current_amounts, current_price)
    hodl_value = position_value(entry_amounts, current_price)

    if hodl_value == 0:
        raise ValueError("hodl_value é zero — parâmetros de entrada inválidos")

    return lp_value / hodl_value - 1


def concentration_multiplier(price_lower: float, price_upper: float) -> float:
    """Fator de eficiência de capital de uma faixa [price_lower, price_upper]
    em relação a fornecer liquidez em range completo (0, infinito).

    multiplier = 1 / (1 - sqrt(price_lower / price_upper))

    Ex: um multiplicador de 5x significa que, para a mesma quantidade de
    capital, a posição concentrada gera ~5x mais taxas *enquanto o preço
    estiver dentro da faixa*, comparado a uma posição full-range.
    """
    if price_lower <= 0 or price_upper <= 0:
        raise ValueError("price_lower e price_upper devem ser positivos")
    if price_lower >= price_upper:
        raise ValueError("price_lower deve ser menor que price_upper")

    ratio = math.sqrt(price_lower / price_upper)
    if ratio >= 1:
        raise ValueError("faixa inválida")
    return 1 / (1 - ratio)


def fee_apr_full_range(fees_usd_period: float, tvl_usd: float, period_days: float) -> float:
    """APR anualizado de taxas para uma posição full-range (equivalente ao
    APR "do pool inteiro"), a partir de taxas acumuladas num período.

    Retorna fração anualizada (ex: 0.12 = 12% a.a.). Este é um APR de
    referência do pool — não é o APR de uma posição concentrada específica,
    que deve ser escalado por concentration_multiplier() e pela fração de
    tempo em que o preço ficou dentro da faixa escolhida.
    """
    if tvl_usd <= 0 or period_days <= 0:
        raise ValueError("tvl_usd e period_days devem ser positivos")
    return (fees_usd_period / tvl_usd) * (365 / period_days)


def position_fee_apr(
    fee_apr_full_range_value: float,
    price_lower: float,
    price_upper: float,
    in_range_fraction: float = 1.0,
) -> float:
    """APR estimado de uma posição concentrada específica: APR full-range
    escalado pelo multiplicador de concentração e pela fração de tempo em
    que o preço historicamente ficou dentro da faixa.
    """
    if not 0 <= in_range_fraction <= 1:
        raise ValueError("in_range_fraction deve estar entre 0 e 1")
    mult = concentration_multiplier(price_lower, price_upper)
    return fee_apr_full_range_value * mult * in_range_fraction


def annualized_volatility(prices: list[float], periods_per_year: float = 365.0) -> float:
    """Volatilidade anualizada a partir de uma série de preços (ex: fechamentos
    diários), calculada como desvio-padrão dos log-retornos * sqrt(períodos/ano).
    """
    if len(prices) < 2:
        raise ValueError("são necessários ao menos 2 preços")
    log_returns = [math.log(prices[i] / prices[i - 1]) for i in range(1, len(prices)) if prices[i - 1] > 0]
    if len(log_returns) < 2:
        raise ValueError("dados insuficientes para calcular volatilidade")
    mean = sum(log_returns) / len(log_returns)
    variance = sum((r - mean) ** 2 for r in log_returns) / (len(log_returns) - 1)
    stdev = math.sqrt(variance)
    return stdev * math.sqrt(periods_per_year)


@dataclass(frozen=True)
class RangeReplayResult:
    in_range_fraction: float
    concentration_multiplier: float
    estimated_position_apr: float
    impermanent_loss: float
    entry_price: float
    end_price: float
    sample_count: int


def replay_range_against_history(
    hourly_prices: list[float],
    entry_price: float,
    price_lower: float,
    price_upper: float,
    fee_apr_full_range_value: float,
) -> RangeReplayResult:
    """Estimativa histórica (NÃO é um backtest com execução real) de como uma
    faixa [price_lower, price_upper] teria se comportado sobre uma série de
    preços horários: fração do tempo dentro da faixa, APR de taxas estimado
    para a posição, e IL no preço final vs preço de entrada.

    Ignora gas, rebalanceamento, e liquidez concorrente de outros LPs — serve
    para comparar faixas entre si, não como previsão de retorno.
    """
    if not hourly_prices:
        raise ValueError("hourly_prices não pode ser vazio")

    in_range_count = sum(1 for p in hourly_prices if price_lower <= p <= price_upper)
    in_range_fraction = in_range_count / len(hourly_prices)

    mult = concentration_multiplier(price_lower, price_upper)
    est_apr = fee_apr_full_range_value * mult * in_range_fraction

    end_price = hourly_prices[-1]
    il = impermanent_loss_v3(entry_price, end_price, price_lower, price_upper)

    return RangeReplayResult(
        in_range_fraction=in_range_fraction,
        concentration_multiplier=mult,
        estimated_position_apr=est_apr,
        impermanent_loss=il,
        entry_price=entry_price,
        end_price=end_price,
        sample_count=len(hourly_prices),
    )


def breakeven_days(position_apr: float, impermanent_loss: float) -> float | None:
    """Quantos dias de acúmulo de taxas (no APR informado) seriam necessários
    para compensar o IL atual. Retorna None se não há IL a compensar (>= 0)
    ou se o APR é <= 0 (nunca compensa).
    """
    if impermanent_loss >= 0:
        return None
    if position_apr <= 0:
        return None
    daily_rate = position_apr / 365
    return abs(impermanent_loss) / daily_rate
