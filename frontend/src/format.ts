import type { Chain, Protocol } from './api/types';

const COMPACT_SCALES: Array<[number, string]> = [
  [1e12, 'T'], // trilhão
  [1e9, 'B'], // bilhão
  [1e6, 'M'], // milhão
  [1e3, 'k'], // mil
];

function fixed2(n: number): string {
  return n.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

// Sempre no máximo 3 dígitos antes da vírgula + 2 depois (ex: "1,23k", "999,99M").
// Escolhe a maior escala (T/B/M/k) que ainda deixa a parte inteira com <=3 dígitos.
function formatCompactNumber(value: number): string {
  const abs = Math.abs(value);
  for (let i = 0; i < COMPACT_SCALES.length; i++) {
    const [threshold, suffix] = COMPACT_SCALES[i];
    if (abs >= threshold) {
      const scaled = value / threshold;
      // Evita "1000,00k" no arredondamento -- promove pra escala de cima.
      if (Math.round(Math.abs(scaled) * 100) / 100 >= 1000 && i > 0) {
        const [biggerThreshold, biggerSuffix] = COMPACT_SCALES[i - 1];
        return `${fixed2(value / biggerThreshold)}${biggerSuffix}`;
      }
      return `${fixed2(scaled)}${suffix}`;
    }
  }
  return fixed2(value);
}

export function formatUsd(value: number): string {
  return `$${formatCompactNumber(value)}`;
}

export function formatPercent(value: number, digits = 2): string {
  // Alguns pools têm TVL tão baixo (ou economia de taxa fora do padrão, como
  // pools de taxa dinâmica) que o APR calculado (taxas/TVL) explode pra
  // valores de milhares de % -- tecnicamente é o que a conta dá, mas mostrar
  // "528603.53%" como se fosse um número preciso é enganoso, não informativo.
  if (Math.abs(value) > 100) return value > 0 ? '>10000%' : '<-10000%';
  return `${(value * 100).toFixed(digits)}%`;
}

export function formatRatio(value: number): string {
  if (value < 0.01 && value > 0) return '<0,01';
  return value.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

export function formatPrice(value: number): string {
  if (value === 0) return '0';
  if (Math.abs(value) < 0.0001) return value.toExponential(2);
  if (Math.abs(value) < 1) return value.toFixed(6);
  if (Math.abs(value) < 1000) return value.toFixed(4);
  return value.toLocaleString('pt-BR', { maximumFractionDigits: 2 });
}

// Uniswap v4 usa esse valor (0x800000) como flag de "taxa dinâmica, definida
// por um hook" -- não é uma taxa fixa de verdade, então não faz sentido
// dividir por 10_000 e mostrar como "838.86%".
const DYNAMIC_FEE_SENTINEL = 8_388_608;

export function formatFeeTier(feeTier: number): string {
  if (feeTier === DYNAMIC_FEE_SENTINEL) return 'dinâmica';
  return `${(feeTier / 10_000).toFixed(2)}%`;
}

export function protocolLabel(protocol: Protocol): string {
  if (protocol === 'aerodrome') return 'Aerodrome Slipstream';
  // polygon/avalanche são Uniswap v3 (mesmo schema/versão) em outra chain --
  // a chain já aparece separada via formatChainLabel, não precisa repetir
  // aqui (evitaria "Uniswap v3 (Polygon)" ao lado de um badge "Polygon").
  if (protocol === 'polygon' || protocol === 'avalanche') return 'Uniswap v3';
  return `Uniswap ${protocol}`;
}

// Nome de rede pra exibição nas listas -- separado de protocolLabel porque
// múltiplos protocolos podem viver na mesma chain (v2/v3/v4 são todos
// Ethereum mainnet) e o usuário quer ver a rede, não só qual DEX/versão.
// Espelha backend/app/services/pools.py::_PROTOCOL_CHAIN (valores internos
// "mainnet"/"base"/"polygon"/"avalanche") -- se uma chain nova for
// adicionada lá, adicione aqui também.
export function formatChainLabel(chain: Chain): string {
  switch (chain) {
    case 'mainnet':
      return 'Ethereum';
    case 'base':
      return 'Base';
    case 'polygon':
      return 'Polygon';
    case 'avalanche':
      return 'Avalanche';
    default:
      return chain;
  }
}

export function formatDate(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleDateString('pt-BR');
}

export function formatDateTime(unixSeconds: number): string {
  return new Date(unixSeconds * 1000).toLocaleString('pt-BR');
}

// Espelha backend/app/token_categories.py::ALL_CATEGORIES -- lista fixa e
// pequena, não vale a pena um endpoint só pra isso. Se adicionar uma
// categoria nova lá, adicione aqui também.
export const ASSET_CATEGORIES = ['Stablecoin (USD)', 'ETH / LST', 'BTC', 'Governança de DEX'];

// Espelha backend/app/services/pools.py::_PROTOCOL_CHAIN.values() -- usado
// pro filtro "Rede" em /assets e /pools (separado do filtro de protocolo,
// já que um ativo não pertence a uma versão da Uniswap, só a uma chain).
export const ALL_CHAINS: Chain[] = ['mainnet', 'base', 'polygon', 'avalanche'];

// Espelha backend/app/services/pools.py::_PROTOCOL_CHAIN (chave->chain).
const PROTOCOL_CHAIN: Record<Protocol, Chain> = {
  v2: 'mainnet',
  v3: 'mainnet',
  v4: 'mainnet',
  aerodrome: 'base',
  polygon: 'polygon',
  avalanche: 'avalanche',
};

// Rótulo pra uso em listas ACHATADAS de protocolo (ex: dropdown "Protocolos"
// em /pools) -- diferente de `protocolLabel` sozinho, que agora é ambíguo
// entre "v3" (mainnet) e "polygon"/"avalanche" (também "Uniswap v3", só que
// noutra chain, ver comentário em protocolLabel). Nas tabelas de resultado
// isso não é um problema porque a chain já aparece numa coluna/rótulo
// separado ao lado -- só dropdowns "só protocolo" precisam desse rótulo
// combinado.
export function protocolOptionLabel(protocol: Protocol): string {
  return `${protocolLabel(protocol)} (${formatChainLabel(PROTOCOL_CHAIN[protocol])})`;
}

export function truncateAddress(address: string): string {
  if (address.length <= 12) return address;
  return `${address.slice(0, 6)}…${address.slice(-4)}`;
}

// O mesmo endereço de contrato significa coisas diferentes em cada chain,
// então o link do explorador tem que seguir a chain do protocolo, não ser
// sempre etherscan -- v2/v3/v4 (Ethereum mainnet), aerodrome (Base), polygon
// (Polygon PoS), avalanche (Avalanche C-Chain).
export function explorerTokenUrl(address: string, protocol: Protocol): string {
  const explorerByProtocol: Record<Protocol, string> = {
    v2: 'https://etherscan.io',
    v3: 'https://etherscan.io',
    v4: 'https://etherscan.io',
    aerodrome: 'https://basescan.org',
    polygon: 'https://polygonscan.com',
    avalanche: 'https://snowtrace.io',
  };
  return `${explorerByProtocol[protocol]}/token/${address}`;
}
