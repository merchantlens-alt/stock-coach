export type Market = "us" | "india";
export type Period = "1d" | "1w" | "1m";
export type Sentiment = "very_positive" | "positive" | "neutral" | "negative" | "very_negative";
export type MarketSentiment = "very_bullish" | "bullish" | "mixed" | "bearish" | "very_bearish";
/** Per-metric valuation band vs sector average and own 5-year history */
export type ValuationBand = "cheap" | "fair" | "expensive";
/** Overall valuation roll-up across P/E, P/B, EV/EBITDA */
export type ValuationClassification = "undervalued" | "fairly_valued" | "overvalued" | "mixed";
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
  /** Enriched at serve time from the analysis cache — null if no AI analysis run yet */
  ai_prediction_pct?: number;
  ai_prediction_confidence?: number;
}

export interface PeerComparison {
  ticker: string;
  name: string;
  pe?: number;
  pb?: number;
  roe?: number;            // decimal, 0.18 = 18%
  revenue_growth?: number; // decimal, 0.12 = 12%
  de_ratio?: number;
}

export interface FundamentalsData {
  // ── Basic metrics ──────────────────────────────────────────────────────────
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
  // Growth Triggers enrichment
  ttm_revenue?: number;
  ebitda_margin?: number;
  market_cap_value?: number;
  insider_holding_pct?: number;

  // ── Deep valuation context (FundamentalEnricher) ──────────────────────────
  pe_sector_avg?: number;
  pe_5y_avg?: number;
  pb_sector_avg?: number;
  pe_signal?: ValuationBand;
  pb_signal?: ValuationBand;
  ev_ebitda_signal?: ValuationBand;
  valuation_classification?: ValuationClassification;

  // ── Growth CAGRs ──────────────────────────────────────────────────────────
  revenue_cagr_3y?: number;
  revenue_cagr_5y?: number;
  net_profit_cagr_3y?: number;
  net_profit_cagr_5y?: number;
  eps_cagr_3y?: number;

  // ── Historical return quality ─────────────────────────────────────────────
  roe_3y_avg?: number;
  roe_5y_avg?: number;
  roce_current?: number;

  // ── Financial health ──────────────────────────────────────────────────────
  interest_coverage?: number;
  current_ratio?: number;
  free_cash_flow?: number;     // in $M or ₹Cr
  fcf_trend?: "growing" | "stable" | "declining";
  de_5y_trend?: "falling" | "stable" | "rising";

  // ── Peer comparison ───────────────────────────────────────────────────────
  peers?: PeerComparison[];
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
  /** New field — direction-neutral explanation of today's move */
  why_it_moved?: string;
  /** Legacy field kept for backward-compat with cached responses */
  why_it_gained?: string;
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

export interface TechnicalSignals {
  rsi_14?: number;
  rsi_signal?: "overbought" | "neutral" | "oversold";
  macd_line?: number;
  macd_histogram?: number;
  macd_signal?: "bullish_cross" | "bearish_cross";
  macd_direction?: "bullish" | "bearish";
  sma_20?: number;
  sma_50?: number;
  price_vs_sma20?: "above" | "below";
  price_vs_sma50?: "above" | "below";
  golden_cross?: boolean;
  volume_trend?: "surging" | "rising" | "neutral" | "falling";
  volume_ratio?: number;
  momentum_5d?: number;
  momentum_20d?: number;
  pct_of_52w_range?: number;
  support?: number;
  resistance?: number;
}

// ── Quarterly results ─────────────────────────────────────────────────────────

export interface QuarterlyResult {
  period: string;              // e.g. "Sep 2024"
  revenue?: number | null;     // Cr for India, $M for US
  operating_profit?: number | null;
  opm_pct?: number | null;     // operating profit margin %
  net_profit?: number | null;  // PAT
  eps?: number | null;
  revenue_growth_yoy?: number | null;  // % vs same quarter last year
  pat_growth_yoy?: number | null;      // % vs same quarter last year
}

export interface QuarterlySnapshot {
  ticker: string;
  market: Market;
  quarters: QuarterlyResult[];  // most recent first, up to 6
  revenue_trend: string;   // accelerating | stable | decelerating | declining | recovering | unknown
  margin_trend: string;    // expanding | stable | compressing | unknown
  earnings_trend: string;  // accelerating | stable | decelerating | declining | recovering | unknown
  currency: string;
  unit: string;            // Cr for India, M for US
  quarterly_insight?: string | null;  // plain-English earnings verdict
}

/** Returned by GET /gainers/{market}/{ticker}/analyse — slow AI endpoint */
export interface StockAnalysisResponse {
  ticker: string;
  market: Market;
  analysis?: GainerAnalysis;
  prediction?: StockPrediction;
  technicals?: TechnicalSignals;
  quarterly?: QuarterlySnapshot | null;
  /** Deep fundamentals — null if enricher timed out or yfinance unavailable */
  enriched_fundamentals?: FundamentalsData | null;
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

// ── Conviction / Thesis types ─────────────────────────────────────────────────

export type ThesisRiskLevel = "lower" | "focused" | "higher";
export type ThesisConfirmerStatus = "confirmed" | "watch" | "risk";
export type EntrySignalLevel = "strong" | "fair" | "wait";

export interface ThesisInstrument {
  ticker: string;
  name: string;
  risk_level: ThesisRiskLevel;
  description: string;
  rationale: string;
}

export interface ThesisConfirmer {
  text: string;
  status: ThesisConfirmerStatus;
}

export interface ThesisConviction {
  belief: string;
  theme_label: string;
  conviction_score: number;
  thesis_summary: string;
  instruments: ThesisInstrument[];
  confirmers: ThesisConfirmer[];
  entry_signal: EntrySignalLevel;
  entry_explanation: string;
  exit_triggers: string[];
  time_horizon: string;
  disclaimer: string;
}

export interface ConvictionRequest {
  belief: string;
  market: Market;
}

export interface ConvictionResponse {
  conviction: ThesisConviction;
  from_cache: boolean;
  analysed_at?: string;
}

// ── Price history (candlestick) ───────────────────────────────────────────────

export interface Candle {
  time: number;   // Unix timestamp (seconds)
  open: number;
  high: number;
  low: number;
  close: number;
  volume: number;
}

export interface PriceHistory {
  ticker: string;
  period: string;
  candles: Candle[];
}

// ── Radar / catalyst-scanner ──────────────────────────────────────────────────

export interface RadarSignal {
  theme: string;
  narrative: string;
  tickers: string[];
  catalyst_type: CatalystType;
  conviction: number;       // 0–1
  time_frame: string;
  evidence: string;
  source_headlines: string[];
}

export interface RadarResponse {
  market: Market;
  signals: RadarSignal[];
  no_signals_reason?: string | null;
  from_cache: boolean;
  generated_at: string;
}

// ── Growth Triggers ───────────────────────────────────────────────────────────

export type TriggerConviction = "HIGH" | "MEDIUM" | "OPTIONALITY";

export interface GrowthTrigger {
  name: string;
  what: string;
  p_and_l_impact: string;
  timeline: string;
  conviction: TriggerConviction;
  watch_for: string;
}

export interface RiskItem {
  name: string;
  what: string;
  why_it_matters: string;
}

export interface ScorecardRow {
  dimension: string;
  rating: string;
  note: string;
}

export interface GrowthTriggersReport {
  ticker: string;
  market: Market;
  company_snapshot: string;
  triggers: GrowthTrigger[];
  already_in_price: string;
  upside_scenario: string;
  key_risks: RiskItem[];
  scorecard: ScorecardRow[];
  is_error: boolean;   // true when AI call failed — shows retry button, not cached
  from_cache: boolean;
  generated_at: string;
  disclaimer: string;
}

// ── Catalyst Scanner ──────────────────────────────────────────────────────────

export type CatalystSignal = "strong_move" | "emerging" | "noise" | "potential";

// ── Portfolio tracker ─────────────────────────────────────────────────────────

export type PortfolioEntryType = "holding" | "watchlist";
export type PortfolioStatus = "active" | "win" | "loss" | "expired";

export interface PortfolioEntry {
  id: string;
  ticker: string;
  market: Market;
  type: PortfolioEntryType;
  entry_price: number;
  purchase_avg?: number | null;      // holdings only — real cost basis
  shares?: number | null;
  stock_name?: string | null;
  ai_predicted_change_pct?: number | null;
  ai_confidence?: number | null;
  catalyst_type?: string | null;
  ai_outlook?: string | null;
  entry_date: string;               // YYYY-MM-DD
  target_date: string;              // YYYY-MM-DD
  status: PortfolioStatus;
  actual_price?: number | null;
  actual_change_pct?: number | null;
  direction_correct?: boolean | null;
  resolved_at?: string | null;
  created_at: string;
}

export interface AddPortfolioEntryRequest {
  ticker: string;
  market: Market;
  type: PortfolioEntryType;
  entry_price: number;
  purchase_avg?: number;
  shares?: number;
  stock_name?: string;
  ai_predicted_change_pct?: number;
  ai_confidence?: number;
  catalyst_type?: string;
  ai_outlook?: string;
}

export interface PortfolioSummary {
  entries: PortfolioEntry[];
  total_active: number;
  total_resolved: number;
  wins: number;
  losses: number;
  win_rate?: number | null;
}

/** Returned by GET /portfolio/prices */
export interface PortfolioPricesResponse {
  prices: Record<string, number>;
}

// ── Dip Scanner ───────────────────────────────────────────────────────────────

export type DipQuality = "prime" | "watch";

export interface DipStock {
  ticker: string;
  name: string;
  market: Market;
  sector?: string;
  price: number;
  change_pct_1d: number;
  change_pct_from_high: number;   // negative, e.g. -18.4 means 18.4% below recent high
  three_month_high: number;
  fifty_two_week_high?: number;
  fifty_two_week_low?: number;
  pct_of_52w_range?: number;      // 0 = at 52w low, 100 = at 52w high
  rsi_14?: number;
  analyst_consensus?: string;
  analyst_target?: number;
  upside_to_target?: number;      // % upside from current to analyst target
  revenue_growth_yoy?: number;    // decimal, 0.15 = 15% growth
  dip_quality: DipQuality;
  dip_score: number;              // 0-100
  dip_reason: string;
  avg_volume?: number;
}

export interface DipScanResponse {
  market: Market;
  dips: DipStock[];
  from_cache: boolean;
  scanned_at: string;
}

// ── Catalyst Scanner ──────────────────────────────────────────────────────────

export interface CatalystPlay {
  ticker: string;
  name: string;
  market: Market;
  sector?: string;
  price: number;
  change_pct: number;
  change_abs: number;
  volume: number;
  avg_volume?: number;
  volume_ratio?: number;      // current / 20-day avg
  momentum_score: number;     // 0-100
  catalyst_type: CatalystType;
  signal: CatalystSignal;
  headline_catalyst?: string;
  ai_verdict: string;
  /** Enriched from analysis cache — undefined if stock hasn't been analysed yet */
  ai_prediction_pct?: number;
  ai_prediction_confidence?: number;
}

export interface CatalystScanResponse {
  market: Market;
  plays: CatalystPlay[];
  from_cache: boolean;
  scanned_at: string;
}
