export type Market = "us" | "india";
export type Period = "1d" | "1w" | "1m";
export type Sentiment = "very_positive" | "positive" | "neutral" | "negative" | "very_negative";
export type MarketSentiment = "very_bullish" | "bullish" | "mixed" | "bearish" | "very_bearish";
export type CatalystType =
  | "earnings" | "fda_approval" | "acquisition" | "partnership"
  | "analyst_upgrade" | "macro" | "technical" | "regulatory" | "unknown";
export type OutlookHorizon = "days" | "weeks" | "months";
export type FundamentalSignal = "strong" | "moderate" | "weak" | "unknown";
export type ValuationSignal = "undervalued" | "fairly_valued" | "overvalued" | "unknown";
export type QualityLabel = "Strong" | "Moderate" | "Watch" | "Risky";
export type SignalTier = "confirmed" | "catalyst" | "mover";

export interface StockGainer {
  ticker: string;
  name: string;
  market: Market;
  price: number;
  change_pct: number;
  change_abs: number;
  volume: number;
  avg_volume?: number;
  market_cap?: number;
  sector?: string;
  industry?: string;
  quality_score?: number;
  quality_label?: QualityLabel;
  signal_tier?: SignalTier;
}

export interface FundamentalsData {
  pe_ratio?: number;
  forward_pe?: number;
  roe?: number;
  debt_equity?: number;
  revenue_growth_yoy?: number;
  earnings_growth_yoy?: number;
  profit_margin?: number;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
  analyst_target_price?: number;
  analyst_recommendation?: string;
}

export interface NewsItem {
  title: string;
  source: string;
  published_at?: string;
  url?: string;
  summary?: string;
}

export interface GainerAnalysis {
  ticker: string;
  why_it_gained: string;
  key_catalysts: string[];
  catalyst_type: CatalystType;
  sentiment: Sentiment;
  is_sustained: boolean;
  sustainability_reason: string;
  confidence: number;
  related_beneficiaries: string[];
  beneficiary_reasoning?: string;
  comparison_to_gainers?: string;
}

export interface StockPrediction {
  ticker: string;
  outlook: string;
  predicted_change_pct: number;
  confidence: number;
  time_horizon: OutlookHorizon;
  key_risks: string[];
  key_tailwinds: string[];
  valuation_signal: ValuationSignal;
  growth_signal: FundamentalSignal;
  debt_signal: FundamentalSignal;
  disclaimer: string;
}

export interface MarketSummary {
  market: Market;
  narrative: string;
  themes: string[];
  dominant_sector?: string;
  sentiment: MarketSentiment;
  watch_list: string[];
  watch_reason: string;
  from_cache: boolean;
  generated_at: string;
}

export interface GainerDetail {
  gainer: StockGainer;
  fundamentals?: FundamentalsData;
  news: NewsItem[];
  from_cache: boolean;
  fetched_at?: string;
}

/** Returned by GET /gainers/{market}/{ticker}/analyse — slow AI endpoint */
export interface StockAnalysisResponse {
  ticker: string;
  market: Market;
  analysis?: GainerAnalysis;
  prediction?: StockPrediction;
  from_cache: boolean;
  analysed_at?: string;
}

export interface GainersListResponse {
  market: Market;
  period: Period;
  date: string;
  gainers: StockGainer[];
  summary?: MarketSummary;
  from_cache: boolean;
  fetched_at: string;
}
