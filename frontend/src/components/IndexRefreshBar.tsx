import type { IndexStatusResponse } from '../api/types';
import { formatDateTime } from '../format';

interface Props {
  status: IndexStatusResponse | null;
  refreshing: boolean;
  onRefresh: () => void;
}

export function IndexRefreshBar({ status, refreshing, onRefresh }: Props) {
  const protocolErrorEntries = status ? Object.entries(status.protocol_errors) : [];

  return (
    <div className="index-refresh-bar">
      <div className="index-refresh-bar__info">
        <span className="muted">
          {status?.updated_at
            ? `Atualizado em ${formatDateTime(status.updated_at)}`
            : 'Ainda não foi atualizado nesta instalação'}
        </span>
        {status?.min_tvl_usd !== null && status?.min_tvl_usd !== undefined && (
          <span className="muted">· Piso de TVL/reserva: ${status.min_tvl_usd.toLocaleString('pt-BR')}</span>
        )}
      </div>
      <button type="button" className="btn btn--secondary" onClick={onRefresh} disabled={refreshing}>
        {refreshing ? 'Atualizando... (pode levar ~30-60s)' : 'Atualizar lista'}
      </button>
      {protocolErrorEntries.length > 0 && (
        <p className="status-box status-box--note index-refresh-bar__warning">
          Aviso: falha ao atualizar {protocolErrorEntries.map(([p]) => p).join(', ')} na última tentativa — os dados
          desses protocolos podem estar desatualizados até a próxima atualização funcionar.
        </p>
      )}
    </div>
  );
}
