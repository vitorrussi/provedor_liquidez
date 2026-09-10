import { useEffect, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { api, ApiError } from '../api/client';
import type { DayDataPoint, PoolDetail, PoolSummary } from '../api/types';
import { ImpermanentLossCalculator } from '../components/ImpermanentLossCalculator';
import { PoolOverview } from '../components/PoolOverview';
import { PriceChart } from '../components/PriceChart';
import { RelatedPools } from '../components/RelatedPools';
import { VolumeChart } from '../components/VolumeChart';

interface IndicatorStats {
  fee_apr_7d: number;
  fee_apr_30d: number;
  annualized_volatility_7d?: number;
  annualized_volatility_30d?: number;
  volume_7d_usd: number;
  volume_30d_usd: number;
}

export function PoolPage() {
  const { id } = useParams<{ id: string }>();
  const poolId = id ? decodeURIComponent(id) : '';

  const [pool, setPool] = useState<PoolDetail | null>(null);
  const [indicators, setIndicators] = useState<IndicatorStats | null>(null);
  const [indicatorsNote, setIndicatorsNote] = useState<string | null>(null);
  const [history, setHistory] = useState<DayDataPoint[]>([]);
  const [relatedPools, setRelatedPools] = useState<PoolSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!poolId) return;

    let cancelled = false;
    setLoading(true);
    setError(null);
    setPool(null);
    setIndicators(null);
    setIndicatorsNote(null);
    setHistory([]);
    setRelatedPools([]);
    window.scrollTo({ top: 0 });

    // O detalhe básico do pool (TVL, preço, volume, taxas) quase sempre funciona --
    // é só um repasse dos campos do subgraph, sem contas que possam falhar. APR/
    // volatilidade, histórico de preço e pools relacionadas já exigem consultas
    // extras e podem não estar disponíveis (pool novo ou pouco negociado) --
    // tratamos como "melhor esforço" em vez de derrubar a tela inteira quando faltam.
    api
      .getPool(poolId)
      .then((p) => {
        if (cancelled) return;
        setPool(p);
        setLoading(false);

        if (p.protocol === 'v2') {
          // v2 não tem série OHLC nem faixa de liquidez concentrada -- o
          // subgraph não indexa isso (só reservas/volume). APR e volume
          // 7d/30d já vêm prontos no próprio detalhe do pool (calculados a
          // partir do volume diário, ver services/pools.py::_get_pool_detail_v2).
          setIndicators({
            fee_apr_7d: p.apr_pool_7d,
            fee_apr_30d: p.apr_pool_30d,
            volume_7d_usd: p.volume_7d_usd,
            volume_30d_usd: p.volume_30d_usd,
          });
        } else {
          api
            .getPoolIndicators(poolId)
            .then((ind) => {
              if (cancelled) return;
              setIndicators({
                fee_apr_7d: ind.fee_apr_full_range_7d,
                fee_apr_30d: ind.fee_apr_full_range_30d,
                annualized_volatility_7d: ind.annualized_volatility_7d,
                annualized_volatility_30d: ind.annualized_volatility_30d,
                volume_7d_usd: ind.volume_7d_usd,
                volume_30d_usd: ind.volume_30d_usd,
              });
            })
            .catch((err) => {
              if (cancelled) return;
              setIndicatorsNote(
                err instanceof ApiError
                  ? err.message
                  : 'Não foi possível calcular APR/volatilidade para este pool.',
              );
            });

          api
            .getDailyHistory(poolId, 30)
            .then((hist) => {
              if (!cancelled) setHistory(hist);
            })
            .catch(() => {
              // Sem histórico de preço -> os gráficos simplesmente não aparecem.
            });
        }

        api
          .getRelatedPools(poolId)
          .then((related) => {
            if (!cancelled) setRelatedPools(related);
          })
          .catch(() => {
            // Sem pools relacionadas -> o card simplesmente não aparece.
          });
      })
      .catch((err) => {
        if (cancelled) return;
        setError(err instanceof ApiError ? err.message : 'Falha ao carregar dados do pool');
        setLoading(false);
      });

    return () => {
      cancelled = true;
    };
  }, [poolId]);

  return (
    <div className="pool-page">
      <Link to="/" className="pool-page__back">
        ← Voltar à busca
      </Link>

      {loading && <p className="status-box muted">Carregando dados do pool...</p>}
      {error && <p className="status-box status-box--error error-text">{error}</p>}

      {pool && !loading && (
        <div className="dashboard">
          <PoolOverview pool={pool} indicators={indicators} indicatorsNote={indicatorsNote} history={history} />
          {history.length > 1 && (
            <div className="dashboard__row">
              <PriceChart data={history} token0Symbol={pool.token0.symbol} token1Symbol={pool.token1.symbol} />
              <VolumeChart data={history} />
            </div>
          )}
          <div className={`dashboard__row ${pool.protocol === 'v2' ? 'dashboard__row--single' : ''}`}>
            <ImpermanentLossCalculator pool={pool} />
            {pool.protocol !== 'v2' && (
              <Link to={`/pool/${encodeURIComponent(pool.id)}/simulate`} className="card range-teaser">
                <div className="card__header">
                  <h3>Simulação avançada de faixa</h3>
                </div>
                <p className="muted">
                  Compare sua faixa com faixas sugeridas (estreita/média/larga por volatilidade + variação de preço
                  realizada), veja gráficos de preço com as faixas sobrepostas e o trade-off APR × IL entre elas.
                </p>
                <span className="range-teaser__cta">Abrir análise completa →</span>
              </Link>
            )}
          </div>
          <RelatedPools pools={relatedPools} />
        </div>
      )}
    </div>
  );
}
