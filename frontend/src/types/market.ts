
export interface Stock {
  id: string;
  symbol: string;
  name: string;
  exchange: string;
  asset_class: string;
  is_active: boolean;
}

export interface StockBar {
  timestamp: string;
  timeframe: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
  provider: string;
  feed: string;
  adjustment: string;
}
