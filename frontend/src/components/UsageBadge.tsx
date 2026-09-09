import { useEffect, useState } from 'react';
import { api } from '../api/client';
import type { GraphUsageResponse } from '../api/types';

/** Indicador discreto de quota do The Graph — canto da tela, baixa ênfase de propósito. */
export function UsageBadge() {
  const [usage, setUsage] = useState<GraphUsageResponse | null>(null);

  useEffect(() => {
    let cancelled = false;

    function fetchUsage() {
      api
        .getGraphUsage()
        .then((data) => {
          if (!cancelled) setUsage(data);
        })
        .catch(() => {
          // Silencioso -- é só um indicador de bastidor, não deve incomodar o usuário.
        });
    }

    fetchUsage();
    const interval = setInterval(fetchUsage, 30_000);
    return () => {
      cancelled = true;
      clearInterval(interval);
    };
  }, []);

  if (!usage) return null;

  return (
    <div className="usage-badge" title={`The Graph — ${usage.used.toLocaleString('pt-BR')} consultas usadas em ${usage.month}`}>
      {usage.remaining.toLocaleString('pt-BR')} consultas restantes (Graph)
    </div>
  );
}
