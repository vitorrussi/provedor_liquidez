import { Link, Route, Routes, useLocation } from 'react-router-dom';
import './App.css';
import { PoolSearch } from './components/PoolSearch';
import { UsageBadge } from './components/UsageBadge';
import { PoolPage } from './pages/PoolPage';

function App() {
  const location = useLocation();
  const isPoolPage = location.pathname.startsWith('/pool/');

  return (
    <div className={`app ${isPoolPage ? 'app--wide' : ''}`}>
      <header className="app__header">
        <Link to="/" className="app__home-link">
          <h1>Provedor de Liquidez</h1>
        </Link>
        <p className="muted">Indicadores de risco e retorno para pools da Uniswap v2, v3 e v4</p>
      </header>

      <main className="app__main">
        <Routes>
          <Route path="/" element={<PoolSearch />} />
          <Route path="/pool/:id" element={<PoolPage />} />
        </Routes>
      </main>

      <footer className="app__footer">
        <p className="footnote">
          Ferramenta educacional. Dados via subgraphs da Uniswap v2/v3/v4 (The Graph). Não é recomendação de
          investimento — DeFi envolve risco real de perda de capital.
        </p>
      </footer>

      <UsageBadge />
    </div>
  );
}

export default App;
