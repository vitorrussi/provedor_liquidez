import math

import pytest

from app import indicators as ind


class TestPriceFromTick:
    def test_roundtrip(self):
        price = ind.price_from_tick(tick=200_000, decimals0=18, decimals1=6)
        tick_back = ind.tick_from_price(price, decimals0=18, decimals1=6)
        assert tick_back == pytest.approx(200_000, abs=1e-6)

    def test_tick_zero_equals_decimals_adjustment(self):
        # tick=0 -> 1.0001^0 = 1, então price = 10^(dec0-dec1)
        price = ind.price_from_tick(tick=0, decimals0=18, decimals1=6)
        assert price == pytest.approx(10**12)


class TestAmountsForLiquidity:
    def test_below_range_all_token0(self):
        amounts = ind.amounts_for_liquidity(liquidity=1000, price=1.0, price_lower=2.0, price_upper=4.0)
        assert amounts.amount1 == 0.0
        assert amounts.amount0 > 0

    def test_above_range_all_token1(self):
        amounts = ind.amounts_for_liquidity(liquidity=1000, price=10.0, price_lower=2.0, price_upper=4.0)
        assert amounts.amount0 == 0.0
        assert amounts.amount1 > 0

    def test_in_range_has_both(self):
        amounts = ind.amounts_for_liquidity(liquidity=1000, price=3.0, price_lower=2.0, price_upper=4.0)
        assert amounts.amount0 > 0
        assert amounts.amount1 > 0

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError):
            ind.amounts_for_liquidity(liquidity=1000, price=3.0, price_lower=4.0, price_upper=2.0)


class TestImpermanentLossV3ConvergesToV2:
    """Teste central: com faixa quase [0, infinito], o IL v3 deve convergir
    para a fórmula clássica v2 (2*sqrt(r)/(1+r) - 1). Isso pega erros de
    sinal e de domínio de sqrt que não aparecem só olhando o código."""

    @pytest.mark.parametrize("r", [0.2, 0.5, 0.8, 1.0, 1.25, 2.0, 3.0, 5.0])
    def test_convergence(self, r):
        entry_price = 100.0
        current_price = entry_price * r
        price_lower = 1e-9
        price_upper = 1e9

        il_v3 = ind.impermanent_loss_v3(entry_price, current_price, price_lower, price_upper)
        il_v2 = ind.impermanent_loss_v2(r)

        assert il_v3 == pytest.approx(il_v2, abs=1e-4)

    def test_no_price_change_zero_il(self):
        il = ind.impermanent_loss_v3(100.0, 100.0, 1e-9, 1e9)
        assert il == pytest.approx(0.0, abs=1e-9)

    def test_known_reference_2x(self):
        # Do guia do projeto: r=2 -> IL ~= -5.7%
        il = ind.impermanent_loss_v2(2.0)
        assert il == pytest.approx(-0.0572, abs=1e-3)


class TestImpermanentLossV3ConcentratedRange:
    def test_il_is_worse_than_full_range_inside_band(self):
        # Dentro de uma faixa estreita, o IL para o mesmo movimento de preço
        # deve ser mais negativo (pior) do que o IL full-range equivalente.
        entry_price = 100.0
        current_price = 130.0
        il_narrow = ind.impermanent_loss_v3(entry_price, current_price, 90.0, 110.0)
        il_full = ind.impermanent_loss_v3(entry_price, current_price, 1e-9, 1e9)
        assert il_narrow < il_full

    def test_price_exits_range_above_100pct_token1(self):
        entry_price = 100.0
        current_price = 200.0
        price_lower, price_upper = 90.0, 110.0
        il = ind.impermanent_loss_v3(entry_price, current_price, price_lower, price_upper)
        assert il < 0


class TestConcentrationMultiplier:
    def test_narrower_range_has_higher_multiplier(self):
        wide = ind.concentration_multiplier(50.0, 200.0)
        narrow = ind.concentration_multiplier(95.0, 105.0)
        assert narrow > wide > 1

    def test_invalid_range_raises(self):
        with pytest.raises(ValueError):
            ind.concentration_multiplier(200.0, 50.0)


class TestFeeApr:
    def test_basic_annualization(self):
        apr = ind.fee_apr_full_range(fees_usd_period=1000, tvl_usd=100_000, period_days=1)
        assert apr == pytest.approx(1000 / 100_000 * 365)

    def test_position_apr_scales_with_multiplier_and_in_range(self):
        base_apr = 0.1
        pos_apr_full_time = ind.position_fee_apr(base_apr, 95.0, 105.0, in_range_fraction=1.0)
        pos_apr_half_time = ind.position_fee_apr(base_apr, 95.0, 105.0, in_range_fraction=0.5)
        assert pos_apr_half_time == pytest.approx(pos_apr_full_time / 2)
        assert pos_apr_full_time > base_apr  # multiplicador de concentração > 1

    def test_invalid_in_range_fraction_raises(self):
        with pytest.raises(ValueError):
            ind.position_fee_apr(0.1, 95.0, 105.0, in_range_fraction=1.5)


class TestAnnualizedVolatility:
    def test_zero_variance_is_zero(self):
        prices = [100.0] * 10
        vol = ind.annualized_volatility(prices)
        assert vol == pytest.approx(0.0, abs=1e-9)

    def test_needs_at_least_two_prices(self):
        with pytest.raises(ValueError):
            ind.annualized_volatility([100.0])


class TestReplayRangeAgainstHistory:
    def test_all_in_range(self):
        prices = [100.0, 101.0, 99.0, 100.5, 100.0]
        result = ind.replay_range_against_history(
            hourly_prices=prices,
            entry_price=100.0,
            price_lower=90.0,
            price_upper=110.0,
            fee_apr_full_range_value=0.2,
        )
        assert result.in_range_fraction == 1.0
        assert result.sample_count == 5
        assert result.estimated_position_apr > 0.2  # concentração > 1x

    def test_partial_in_range(self):
        prices = [100.0, 120.0, 130.0, 100.0]
        result = ind.replay_range_against_history(
            hourly_prices=prices,
            entry_price=100.0,
            price_lower=90.0,
            price_upper=110.0,
            fee_apr_full_range_value=0.2,
        )
        assert result.in_range_fraction == pytest.approx(0.5)


class TestBreakevenDays:
    def test_negative_il_positive_apr(self):
        days = ind.breakeven_days(position_apr=0.365, impermanent_loss=-0.01)
        # daily_rate = 0.001 -> 0.01 / 0.001 = 10 dias
        assert days == pytest.approx(10.0)

    def test_no_il_returns_none(self):
        assert ind.breakeven_days(position_apr=0.2, impermanent_loss=0.0) is None

    def test_zero_apr_returns_none(self):
        assert ind.breakeven_days(position_apr=0.0, impermanent_loss=-0.01) is None
