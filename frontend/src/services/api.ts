
import axios from "axios";
import type { Stock, StockBar } from "../types/market";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 15000,
});

export interface LeaderboardEntry {
  rank: number;
  agent_id: string;
  agent_name: string;
  strategy_type: string;
  agent_status: string;
  cash_balance: string;
  market_value: string | null;
  portfolio_equity: string | null;
  initial_cash: string;
  realised_pnl: string;
  unrealised_pnl: string | null;
  total_pnl: string | null;
  total_return_pct: string | null;
  total_fees: string;
  total_slippage: string;
  valuation_complete: boolean;
  missing_price_symbols: string[];
  inconsistent_positions: string[];
}

export interface PositionValuation {
  stock_symbol: string;
  quantity: number;
  average_entry_price: string;
  latest_price: string | null;
  market_value: string | null;
  cost_basis: string;
  unrealised_pnl: string | null;
  price_timestamp: string | null;
}

export interface PortfolioResponse {
  agent_id: string;
  agent_name: string;
  strategy_type: string;
  agent_status: string;
  cash_balance: string;
  market_value: string | null;
  portfolio_equity: string | null;
  initial_cash: string;
  realised_pnl: string;
  unrealised_pnl: string | null;
  total_pnl: string | null;
  total_return_pct: string | null;
  total_fees: string;
  total_slippage: string;
  valuation_complete: boolean;
  missing_price_symbols: string[];
  inconsistent_positions: string[];
  positions: PositionValuation[];
}

export async function getStocks(): Promise<Stock[]> {
  const response = await api.get<Stock[]>("/api/stocks");
  return response.data;
}

export async function getStockBars(
  symbol: string,
  limit = 5000,
): Promise<StockBar[]> {
  const response = await api.get<StockBar[]>(
    `/api/stocks/${symbol}/bars`,
    { params: { limit } },
  );

  return response.data.map((bar) => ({
    ...bar,
    open: Number(bar.open),
    high: Number(bar.high),
    low: Number(bar.low),
    close: Number(bar.close),
    volume: Number(bar.volume),
  }));
}

export async function getLeaderboard(
  competitionId: string,
): Promise<LeaderboardEntry[]> {
  const response = await api.get<LeaderboardEntry[]>(
    `/api/competitions/${competitionId}/leaderboard`,
  );

  return response.data;
}

export async function getAgentPortfolio(
  competitionId: string,
  agentId: string,
): Promise<PortfolioResponse> {
  const response = await api.get<PortfolioResponse>(
    `/api/competitions/${competitionId}/agents/${agentId}/portfolio`,
  );

  return response.data;
}
