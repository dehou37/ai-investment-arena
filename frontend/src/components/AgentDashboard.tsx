
import { useEffect, useState } from "react";
import {
  getCompetitions,
  getAgentPortfolio,
  getLeaderboard,
} from "../services/api";
import type {
  CompetitionSummary,
  LeaderboardEntry,
  PortfolioResponse,
} from "../services/api";

type DashboardMode = "agents" | "leaderboard" | "portfolios";

interface Props {
  mode: DashboardMode;
}

function formatMoney(value: string | null): string {
  if (value === null) return "—";

  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
  }).format(Number(value));
}

function formatPercent(value: string | null): string {
  if (value === null) return "—";

  const number = Number(value);
  return `${number >= 0 ? "+" : ""}${number.toFixed(2)}%`;
}

function strategyLabel(strategy: string): string {
  const labels: Record<string, string> = {
    buy_and_hold: "Buy and Hold",
    momentum: "Momentum",
    mean_reversion: "Mean Reversion",
    risk_managed: "Risk Managed",
    llm_analyst: "AI Analyst",
    value: "Value",
  };

  return labels[strategy] ?? strategy;
}

export default function AgentDashboard({ mode }: Props) {
  const [competitions, setCompetitions] = useState<CompetitionSummary[]>([]);
  const [competitionId, setCompetitionId] = useState("");
  const [agents, setAgents] = useState<LeaderboardEntry[]>([]);
  const [selectedAgent, setSelectedAgent] =
    useState<LeaderboardEntry | null>(null);
  const [portfolio, setPortfolio] =
    useState<PortfolioResponse | null>(null);

  const [loading, setLoading] = useState(true);
  const [refreshVersion, setRefreshVersion] = useState(0);
  const [portfolioLoading, setPortfolioLoading] = useState(false);
  const [error, setError] = useState("");
  const [portfolioError, setPortfolioError] = useState("");

  useEffect(() => {
    let active = true;

    async function loadCompetitions() {
      try {
        const data = await getCompetitions();
        if (!active) return;

        setCompetitions(data);
        if (data.length === 0) setLoading(false);
        setCompetitionId((current) => {
          if (data.some((competition) => competition.id === current)) {
            return current;
          }

          return (
            data.find((competition) => competition.status === "active") ??
            data[0]
          )?.id ?? "";
        });
        setError("");
      } catch {
        if (active) {
          setError("Unable to load competitions.");
          setLoading(false);
        }
      }
    }

    void loadCompetitions();
    return () => {
      active = false;
    };
  }, []);

  useEffect(() => {
    if (!competitionId) return;

    let active = true;

    async function refreshAgents() {
      try {
        const data = await getLeaderboard(competitionId);
        if (!active) return;
        setAgents(data);
        setError("");
      } catch {
        if (active) setError("Unable to load agent information.");
      } finally {
        if (active) setLoading(false);
      }
    }

    void refreshAgents();
    const interval = window.setInterval(() => {
      void refreshAgents();
    }, 30000);

    return () => {
      active = false;
      window.clearInterval(interval);
    };
  }, [competitionId, refreshVersion]);

  const selectedCompetition = competitions.find(
    (competition) => competition.id === competitionId,
  );

  const selectAgent = async (agent: LeaderboardEntry) => {
    setSelectedAgent(agent);
    setPortfolio(null);
    setPortfolioError("");
    setPortfolioLoading(true);

    try {
      const data = await getAgentPortfolio(
        competitionId,
        agent.agent_id,
      );

      setPortfolio(data);
    } catch {
      setPortfolioError("Unable to load this agent's portfolio.");
    } finally {
      setPortfolioLoading(false);
    }
  };

  if (loading) {
    return <div className="agent-message">Loading agents...</div>;
  }

  const activeAgents = agents.filter(
    (agent) => agent.agent_status === "active",
  );

  const inactiveAgents = agents.filter(
    (agent) => agent.agent_status !== "active",
  );

  return (
    <div className="agent-dashboard">
      {error && <div className="error">{error}</div>}

      <section className="summary-grid">
        <div className="summary-card">
          <span>Total agents</span>
          <strong>{agents.length}</strong>
          <small>Registered in this competition</small>
        </div>

        <div className="summary-card">
          <span>Active agents</span>
          <strong>{activeAgents.length}</strong>
          <small>Participating in the competition</small>
        </div>

        <div className="summary-card">
          <span>Inactive agents</span>
          <strong>{inactiveAgents.length}</strong>
          <small>Not currently participating</small>
        </div>

        <div className="summary-card">
          <span>Starting capital</span>
          <strong>{selectedCompetition
            ? formatMoney(selectedCompetition.initial_cash)
            : "—"}</strong>
          <small>Per agent</small>
        </div>
      </section>

      <section className="panel">
        <div className="panel-heading">
          <div>
            <h2>
              {mode === "leaderboard"
                ? "Competition Leaderboard"
                : mode === "portfolios"
                  ? "Agent Portfolios"
                  : "AI Agents"}
            </h2>
            <p>
              {mode === "leaderboard"
                ? "Ranked by current portfolio equity"
                : mode === "portfolios"
                  ? "Select an agent to inspect its holdings and performance"
                  : "All registered agents and their strategies"}
            </p>
          </div>
          <div className="dashboard-controls">
            <label className="sr-only" htmlFor="competition-select">
              Competition
            </label>
            <select
              id="competition-select"
              className="competition-select"
              value={competitionId}
              onChange={(event) => {
                setLoading(true);
                setCompetitionId(event.target.value);
                setSelectedAgent(null);
                setPortfolio(null);
              }}
              disabled={competitions.length === 0}
            >
              {competitions.length === 0 ? (
                <option value="">No competitions</option>
              ) : (
                competitions.map((competition) => (
                  <option key={competition.id} value={competition.id}>
                    {competition.name} ({competition.status})
                  </option>
                ))
              )}
            </select>
            <button
              className="refresh-button"
              onClick={() => setRefreshVersion((version) => version + 1)}
            >
              Refresh
            </button>
          </div>
        </div>

        {mode !== "leaderboard" ? (
          <div className="agent-grid">
            {agents.map((agent) => (
              <button
                key={agent.agent_id}
                className={`agent-card ${
                  selectedAgent?.agent_id === agent.agent_id
                    ? "selected"
                    : ""
                }`}
                onClick={() => selectAgent(agent)}
              >
                <div className="agent-card-top">
                  <div className="agent-avatar">
                    {agent.agent_name.charAt(0)}
                  </div>

                  <span
                    className={`agent-status ${
                      agent.agent_status === "active"
                        ? "active"
                        : "inactive"
                    }`}
                  >
                    {agent.agent_status}
                  </span>
                </div>

                <h3>{agent.agent_name}</h3>
                <p>{strategyLabel(agent.strategy_type)}</p>

                <div className="agent-card-value">
                  <span>Portfolio equity</span>
                  <strong>
                    {formatMoney(agent.portfolio_equity)}
                  </strong>
                </div>

                <div className="agent-card-footer">
                  <span>Return</span>
                  <strong
                    className={
                      Number(agent.total_return_pct ?? 0) >= 0
                        ? "positive"
                        : "negative"
                    }
                  >
                    {formatPercent(agent.total_return_pct)}
                  </strong>
                </div>
              </button>
            ))}
          </div>
        ) : (
          <div className="table-wrapper">
            <table>
              <thead>
                <tr>
                  <th>Rank</th>
                  <th>Agent</th>
                  <th>Strategy</th>
                  <th>Status</th>
                  <th>Cash</th>
                  <th>Market value</th>
                  <th>Portfolio equity</th>
                  <th>Total return</th>
                </tr>
              </thead>

              <tbody>
                {agents.map((agent) => (
                    <tr
                      key={agent.agent_id}
                      className="clickable-row"
                      onClick={() => selectAgent(agent)}
                    >
                      <td>#{agent.rank}</td>
                      <td><strong>{agent.agent_name}</strong></td>
                      <td>{strategyLabel(agent.strategy_type)}</td>
                      <td>
                        <span
                          className={`agent-status ${
                            agent.agent_status === "active"
                              ? "active"
                              : "inactive"
                          }`}
                        >
                          {agent.agent_status}
                        </span>
                      </td>
                      <td>{formatMoney(agent.cash_balance)}</td>
                      <td>{formatMoney(agent.market_value)}</td>
                      <td>
                        <strong>
                          {formatMoney(agent.portfolio_equity)}
                        </strong>
                      </td>
                      <td
                        className={
                          Number(agent.total_return_pct ?? 0) >= 0
                            ? "positive"
                            : "negative"
                        }
                      >
                        {formatPercent(agent.total_return_pct)}
                      </td>
                    </tr>
                  ))}
              </tbody>
            </table>
          </div>
        )}
      </section>

      {selectedAgent && (
        <section className="panel agent-detail">
          <div className="panel-heading">
            <div>
              <h2>{selectedAgent.agent_name} — Portfolio</h2>
              <p>{strategyLabel(selectedAgent.strategy_type)}</p>
            </div>

            <button
              className="refresh-button"
              onClick={() => selectAgent(selectedAgent)}
            >
              Refresh portfolio
            </button>
          </div>

          {portfolioLoading ? (
            <p className="muted">Loading portfolio...</p>
          ) : portfolioError ? (
            <div className="error">{portfolioError}</div>
          ) : portfolio ? (
            <>
              <div className="summary-grid">
                <div className="summary-card">
                  <span>Cash balance</span>
                  <strong>{formatMoney(portfolio.cash_balance)}</strong>
                </div>

                <div className="summary-card">
                  <span>Market value</span>
                  <strong>{formatMoney(portfolio.market_value)}</strong>
                </div>

                <div className="summary-card">
                  <span>Portfolio equity</span>
                  <strong>
                    {formatMoney(portfolio.portfolio_equity)}
                  </strong>
                </div>

                <div className="summary-card">
                  <span>Total return</span>
                  <strong
                    className={
                      Number(portfolio.total_return_pct ?? 0) >= 0
                        ? "positive"
                        : "negative"
                    }
                  >
                    {formatPercent(portfolio.total_return_pct)}
                  </strong>
                </div>
              </div>

              <div className="agent-pnl-grid">
                <div>
                  <span>Realised P&L</span>
                  <strong>{formatMoney(portfolio.realised_pnl)}</strong>
                </div>
                <div>
                  <span>Unrealised P&L</span>
                  <strong>{formatMoney(portfolio.unrealised_pnl)}</strong>
                </div>
                <div>
                  <span>Total fees</span>
                  <strong>{formatMoney(portfolio.total_fees)}</strong>
                </div>
                <div>
                  <span>Total slippage</span>
                  <strong>{formatMoney(portfolio.total_slippage)}</strong>
                </div>
              </div>

              <div className="panel-heading holdings-heading">
                <div>
                  <h2>Current Holdings</h2>
                  <p>Stocks currently owned by this agent</p>
                </div>
              </div>

              {portfolio.positions.length === 0 ? (
                <p className="muted">
                  This agent currently has no stock holdings.
                </p>
              ) : (
                <div className="table-wrapper">
                  <table>
                    <thead>
                      <tr>
                        <th>Symbol</th>
                        <th>Quantity</th>
                        <th>Average entry</th>
                        <th>Latest price</th>
                        <th>Market value</th>
                        <th>Unrealised P&L</th>
                      </tr>
                    </thead>

                    <tbody>
                      {portfolio.positions.map((position) => (
                        <tr key={position.stock_symbol}>
                          <td><strong>{position.stock_symbol}</strong></td>
                          <td>{position.quantity}</td>
                          <td>{formatMoney(position.average_entry_price)}</td>
                          <td>{formatMoney(position.latest_price)}</td>
                          <td>{formatMoney(position.market_value)}</td>
                          <td
                            className={
                              Number(position.unrealised_pnl ?? 0) >= 0
                                ? "positive"
                                : "negative"
                            }
                          >
                            {formatMoney(position.unrealised_pnl)}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                </div>
              )}

              {!portfolio.valuation_complete && (
                <div className="error">
                  Portfolio valuation is incomplete.
                  {portfolio.missing_price_symbols.length > 0 &&
                    ` Missing prices: ${portfolio.missing_price_symbols.join(", ")}`}
                </div>
              )}
            </>
          ) : null}
        </section>
      )}
    </div>
  );
}
