
import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
} from "lightweight-charts";

import type { StockBar } from "../types/market";

interface StockChartProps {
  bars: StockBar[];
}

export default function StockChart({ bars }: StockChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!containerRef.current) return;

    const chart = createChart(containerRef.current, {
      autoSize: true,
      layout: {
        background: {
          type: ColorType.Solid,
          color: "#111827",
        },
        textColor: "#9CA3AF",
      },
      grid: {
        vertLines: { color: "#1F2937" },
        horzLines: { color: "#1F2937" },
      },
      rightPriceScale: {
        borderColor: "#374151",
      },
      timeScale: {
        borderColor: "#374151",
        timeVisible: false,
      },
      crosshair: {
        vertLine: { color: "#6B7280" },
        horzLine: { color: "#6B7280" },
      },
    });

    const candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: "#22C55E",
      downColor: "#EF4444",
      borderUpColor: "#22C55E",
      borderDownColor: "#EF4444",
      wickUpColor: "#22C55E",
      wickDownColor: "#EF4444",
    });

    const chartData = [...bars]
      .sort(
        (a, b) =>
          new Date(a.timestamp).getTime() -
          new Date(b.timestamp).getTime(),
      )
      .map((bar) => ({
        time: bar.timestamp.slice(0, 10),
        open: bar.open,
        high: bar.high,
        low: bar.low,
        close: bar.close,
      }));

    candleSeries.setData(chartData);

    chart.timeScale().fitContent();

    return () => {
      chart.remove();
    };
  }, [bars]);

  return (
    <div
      ref={containerRef}
      style={{
        width: "100%",
        height: "380px",
      }}
    />
  );
}
