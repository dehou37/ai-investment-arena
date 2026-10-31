
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
  open: number | string;
  high: number | string;
  low: number | string;
  close: number | string;
  volume: number | string;
  provider: string;
  feed: string;
  adjustment: string;
}
