export const CHART_TIMEFRAMES = ["5m", "15m", "1h", "4h", "24h"] as const;
export type Timeframe = (typeof CHART_TIMEFRAMES)[number];

export const CHART_TIMEFRAME_SECONDS: Record<Timeframe, number> = {
  "5m": 300,
  "15m": 900,
  "1h": 3_600,
  "4h": 14_400,
  "24h": 86_400
};

export interface ChartCandle {
  bucketAt: string;
  open: number;
  high: number;
  low: number;
  close: number;
  volumeBase: number | null;
  volumeNotional: number | null;
  complete: boolean;
}

export interface ChartHistory {
  venueInstrumentId: string;
  timeframe: Timeframe;
  generatedAt: string;
  bars: ChartCandle[];
  hasMore: boolean;
  nextBefore: string | null;
}
