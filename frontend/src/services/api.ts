
import axios from "axios";
import type { Stock, StockBar } from "../types/market";

const api = axios.create({
  baseURL: import.meta.env.VITE_API_BASE_URL,
  timeout: 15000,
});

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
