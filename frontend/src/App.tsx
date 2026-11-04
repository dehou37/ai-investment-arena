
import { useEffect, useMemo, useState } from "react";

import { getStocks, getStockBars } from "./services/api";
import type { Stock, StockBar } from "./types/market";
import StockChart from "./components/StockChart";

import "./App.css";
import AgentDashboard from "./components/AgentDashboard";

function App() {
  const [stocks, setStocks] = useState<Stock[]>([]);
  const [selectedSymbol, setSelectedSymbol] = useState("NVDA");
  const [bars, setBars] = useState<StockBar[]>([]);
  const [loadingStocks, setLoadingStocks] = useState(true);
  const [loadingBars, setLoadingBars] = useState(false);
  const [error, setError] = useState("");
  const [activePage, setActivePage] = useState<
    "market" | "agents" | "leaderboard" | "portfolios"
  >("market");
  useEffect(() => {
    async function loadStocks() {
      try {
        const data = await getStocks();
        setStocks(data);

        if (data.length > 0) {
          setSelectedSymbol((current) =>
            data.some((stock) => stock.symbol === current)
              ? current
              : data[0].symbol,
          );
        }
      } catch {
        setError("Unable to retrieve stocks from the backend.");
      } finally {
        setLoadingStocks(false);
      }
    }

    loadStocks();
  }, []);

  useEffect(() => {
    let cancelled = false;

    async function loadBars() {
      setLoadingBars(true);
      setError("");

      try {
        const data = await getStockBars(selectedSymbol);

        if (!cancelled) {
          setBars(data);
        }
      } catch {
        if (!cancelled) {
          setBars([]);
          setError(`Unable to retrieve historical data for ${selectedSymbol}.`);
        }
      } finally {
        if (!cancelled) {
          setLoadingBars(false);
        }
      }
    }

    if (selectedSymbol) {
      loadBars();
    }

    return () => {
      cancelled = true;
    };
  }, [selectedSymbol]);

  const latestBar = bars[0];
  const previousBar = bars[1];

  const priceChange = useMemo(() => {
    if (!latestBar || !previousBar || previousBar.close === 0) {
      return null;
    }

    const difference = latestBar.close - previousBar.close;

    return {
      difference,
      percentage: (difference / previousBar.close) * 100,
    };
  }, [latestBar, previousBar]);

  const selectedStock = stocks.find(
    (stock) => stock.symbol === selectedSymbol,
  );

  const formatPrice = (value: number) =>
    new Intl.NumberFormat("en-US", {
      style: "currency",
      currency: "USD",
    }).format(value);

  const formatDate = (value: string) =>
    new Date(value).toLocaleDateString("en-US", {
      year: "numeric",
      month: "short",
      day: "numeric",
      timeZone: "UTC",
    });

  return (
    <div className="app">
      <aside className="sidebar">
        <div className="brand">
          <div className="brand-icon">A</div>
          <div>
            <h2>Investment Arena</h2>
            <span>AI Trading Competition</span>
          </div>
        </div>

        <nav>
          <button
            className={`nav-item ${activePage === "market" ? "active" : ""}`}
            onClick={() => setActivePage("market")}
          >
            Market Overview
          </button>

          <button
            className={`nav-item ${activePage === "agents" ? "active" : ""}`}
            onClick={() => setActivePage("agents")}
          >
            AI Agents
          </button>

          <button
            className={`nav-item ${activePage === "leaderboard" ? "active" : ""}`}
            onClick={() => setActivePage("leaderboard")}
          >
            Leaderboard
          </button>

          <button
            className={`nav-item ${activePage === "portfolios" ? "active" : ""}`}
            onClick={() => setActivePage("portfolios")}
          >
            Portfolios
          </button>
        </nav>

        <div className="sidebar-footer">
          <span className="status-dot" />
          Market data connected
        </div>
      </aside>

      <main className="main">
        <header className="topbar">
          <div>
            <h1>
              {activePage === "market"
                ? "Market Overview"
                : activePage === "agents"
                  ? "AI Agents"
                  : activePage === "leaderboard"
                    ? "Leaderboard"
                    : "Portfolios"}
            </h1>
            <p>
              {activePage === "market"
                ? "Monitor your tracked US stocks."
                : activePage === "agents"
                  ? "Monitor your AI trading agents and their portfolios."
                  : activePage === "leaderboard"
                    ? "Compare agent performance in the competition."
                    : "Explore each agent’s portfolio and current holdings."}
            </p>
          </div>
          <div className="feed-badge">ALPACA · IEX FEED</div>
        </header>

        {activePage === "market" ? (
        <>
        {error && <div className="error">{error}</div>}

        <section className="summary-grid">
          <div className="summary-card">
            <span>Tracked stocks</span>
            <strong>{stocks.length}</strong>
            <small>In your watchlist</small>
          </div>

          <div className="summary-card">
            <span>Selected stock</span>
            <strong>{selectedSymbol || "—"}</strong>
            <small>{selectedStock?.exchange ?? "—"}</small>
          </div>

          <div className="summary-card">
            <span>Latest closing price</span>
            <strong>
              {latestBar ? formatPrice(latestBar.close) : "—"}
            </strong>
            <small>
              {latestBar ? formatDate(latestBar.timestamp) : "No data"}
            </small>
          </div>

          <div className="summary-card">
            <span>Daily change</span>
            <strong
              className={
                priceChange
                  ? priceChange.difference >= 0
                    ? "positive"
                    : "negative"
                  : ""
              }
            >
              {priceChange
                ? `${priceChange.difference >= 0 ? "+" : ""}${priceChange.percentage.toFixed(2)}%`
                : "—"}
            </strong>
            <small>Compared with previous bar</small>
          </div>
        </section>

        <section className="content-grid">
          <div className="panel watchlist">
            <div className="panel-heading">
              <div>
                <h2>Watchlist</h2>
                <p>Your tracked stocks</p>
              </div>
            </div>

            {loadingStocks ? (
              <p className="muted">Loading stocks...</p>
            ) : stocks.length === 0 ? (
              <p className="muted">No stocks found.</p>
            ) : (
              stocks.map((stock) => (
                <button
                  key={stock.id}
                  className={`stock-row ${
                    selectedSymbol === stock.symbol ? "selected" : ""
                  }`}
                  onClick={() => setSelectedSymbol(stock.symbol)}
                >
                  <div className="stock-symbol">{stock.symbol}</div>
                  <div className="stock-details">
                    <strong>{stock.name}</strong>
                    <span>{stock.exchange}</span>
                  </div>
                  <span className="row-arrow">›</span>
                </button>
              ))
            )}
          </div>

          <div className="panel chart-panel">
            <div className="panel-heading">
              <div>
                <h2>{selectedSymbol} Price Chart</h2>
                <p>
                  {selectedStock?.name ?? "Historical daily prices"}
                </p>
              </div>
              <span className="chart-period">1D</span>
            </div>

            {loadingBars ? (
              <div className="chart-message">Loading historical prices...</div>
            ) : bars.length === 0 ? (
              <div className="chart-message">
                No historical data available.
              </div>
            ) : (
              <>
                <StockChart bars={bars} />

                <div className="chart-footer">
                  <span>{bars.length} daily bars</span>
                  <span>Source: Alpaca IEX</span>
                </div>
              </>
            )}
          </div>
        </section>

        <section className="panel data-panel">
          <div className="panel-heading">
            <div>
              <h2>Historical Prices</h2>
              <p>Most recent trading sessions</p>
            </div>
          </div>

          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Date</th>
                  <th>Open</th>
                  <th>High</th>
                  <th>Low</th>
                  <th>Close</th>
                  <th>Volume</th>
                </tr>
              </thead>
              <tbody>
                {bars.slice(0, 10).map((bar) => (
                  <tr key={bar.timestamp}>
                    <td>{formatDate(bar.timestamp)}</td>
                    <td>{formatPrice(bar.open)}</td>
                    <td>{formatPrice(bar.high)}</td>
                    <td>{formatPrice(bar.low)}</td>
                    <td>{formatPrice(bar.close)}</td>
                    <td>{bar.volume.toLocaleString("en-US")}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>

        <footer>
          AI Investment Arena · Paper trading simulation · Market data
          provided by Alpaca
        </footer>
          </>
          ) : (
            <AgentDashboard
              mode={activePage === "agents"
                ? "agents"
                : activePage === "leaderboard"
                  ? "leaderboard"
                  : "portfolios"}
            />
          )}
      </main>
    </div>
  );
}

export default App;
