// ── Auth ─────────────────────────────────────────────────────────────────────
export interface TokenResponse {
  access_token: string;
  token_type: string;
  user_id: string;
  username: string;
}

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

// ── Fund Scanner (ETFs + India mutual funds) ──────────────────────────────────

export type FundType = "mutual_fund" | "etf";
export type FundEntrySignal = "strong_entry" | "watch" | "avoid";
export type FundTrackRecord = "established" | "emerging" | "new";

export interface FundScheme {
  scheme_code: string;
  name: string;
  fund_house?: string;
  category?: string;
  fund_type: FundType;
  market: Market;
  nav?: number;
  nav_date?: string;
  // Rolling returns (%)
  returns_1m?: number;
  returns_3m?: number;
  returns_6m?: number;
  returns_1y?: number;
  returns_3y_cagr?: number;
  returns_5y_cagr?: number;
  since_inception_cagr?: number;
  // Risk metrics
  volatility?: number;
  sharpe?: number;
  max_drawdown?: number;
  // Enrichment (None until an AMFI/Kuvera adapter is wired)
  expense_ratio?: number;
  aum?: number;
  // Advisor context
  track_record: FundTrackRecord;
  category_rank?: number;
  category_size?: number;
  active_return_3y?: number;
  benchmark_name?: string;
  // Rule-out / discovery flags
  is_closet_index: boolean;
  is_decaying: boolean;
  is_discovery: boolean;
  // Verdicts
  fund_score: number;
  long_term_score: number;
  entry_signal: FundEntrySignal;
  entry_reason: string;
}

export interface FundScanResponse {
  market: Market;
  funds: FundScheme[];
  category?: string;
  universe_size: number;
  from_cache: boolean;
  scanned_at: string;
}

// ── Model portfolio ("the 5 funds you should own") ────────────────────────────

export type RiskProfile = "conservative" | "balanced" | "aggressive";

export interface ModelHolding {
  role: string;
  weight_pct: number;
  why: string;
  fund: FundScheme;
}

export interface ModelPortfolioResponse {
  market: Market;
  risk: RiskProfile;
  holdings: ModelHolding[];
  rationale: string;
  blended_expense_ratio?: number;
  universe_size: number;
  from_cache: boolean;
  generated_at: string;
}

// ── Portfolio backtest comparison (your funds vs the model) ────────────────────

export interface CompareFundInput {
  code: string;
  name: string;
  weight?: number;
}

export interface CompareRequest {
  market: Market;
  risk: RiskProfile;
  amount: number;            // monthly SIP amount
  user_funds: CompareFundInput[];
}

export interface CompareFundReturn {
  code: string;
  name: string;
  weight: number;
  returns_1y?: number;
  returns_3y?: number;
  returns_5y?: number;
}

export interface CompareWindow {
  years: number;
  invested?: number;
  user_value?: number;
  user_gain_pct?: number;
  model_value?: number;
  model_gain_pct?: number;
  user_coverage: number;
  model_coverage: number;
}

export interface CompareResponse {
  market: Market;
  risk: RiskProfile;
  amount: number;
  windows: CompareWindow[];
  user_funds: CompareFundReturn[];
  model_funds: CompareFundReturn[];
  generated_at: string;
}

// ── Investor Profile (Bucket 1 — personal context) ────────────────────────────

export type InvestorHorizon  = "short" | "medium" | "long" | "very_long";
export type RiskTolerance    = "conservative" | "moderate" | "aggressive";
export type RiskCapacity     = "low" | "medium" | "high";
export type InvestmentGoal   = "capital_appreciation" | "income" | "tax_efficiency" | "balanced";
export type TaxResidency     = "india" | "us" | "other";
export type AdvisorVerdict   = "buy" | "pass" | "conditional";
export type AdvisorConfidence = "high" | "medium" | "low";

export interface AllocationSlice {
  asset_class: string;   // "India Equity", "US Equity", "Debt", "Gold", etc.
  percentage: number;    // 0-100
}

export interface InvestorProfile {
  horizon_years: number;
  horizon_label: InvestorHorizon;
  risk_tolerance: RiskTolerance;
  risk_capacity: RiskCapacity;
  emergency_fund_months: number;
  primary_goal: InvestmentGoal;
  tax_residency: TaxResidency;
  existing_allocation: AllocationSlice[];
  age?: number;
  monthly_invest_amount?: number;
  monthly_surplus?: number;
  updated_at: string;
}

// ── Allocation Plan (cross-asset AI plan) ─────────────────────────────────────

export type AllocationInstrumentType = "mutual_fund" | "etf" | "stock" | "bond" | "gold" | "reit";

export interface AllocationInstrument {
  name: string;
  instrument_type: AllocationInstrumentType;
  weight_pct: number;
  why: string;
}

export interface AllocationBucket {
  asset_class: string;
  percentage: number;
  monthly_amount: number;
  rationale: string;
  instruments: AllocationInstrument[];
}

export interface AllocationPlanResponse {
  monthly_invest_amount: number;
  currency: string;
  buckets: AllocationBucket[];
  rebalance_tip: string;
  key_principles: string[];
  disclaimer: string;
  from_cache: boolean;
  generated_at?: string;
  user_preferences_applied?: Record<string, number>;
}

export type AllocationPreferences = Record<string, number>;

export const ASSET_CLASSES = ["India Equity", "US Equity", "Debt", "Gold", "Real Estate"] as const;
export type AssetClass = typeof ASSET_CLASSES[number];

export interface AdvisorRecommendation {
  verdict: AdvisorVerdict;
  confidence: AdvisorConfidence;
  investor_match_score: number;
  horizon_fit: string;
  risk_fit: string;
  allocation_fit: string;
  reasons_for: string[];
  reasons_against: string[];
  suggested_sizing?: string | null;
  caveats?: string | null;
  summary: string;
  disclaimer: string;
}

export interface AdvisorEvaluateRequest {
  asset_type: "stock" | "fund";
  ticker: string;
  market: Market;
  name?: string;
  context?: Record<string, unknown>;
}

export interface AdvisorEvaluateResponse {
  recommendation: AdvisorRecommendation;
  ticker: string;
  asset_type: string;
  profile_horizon_years: number;
  from_cache: boolean;
  evaluated_at?: string;
}

// ── Portfolio X-ray (analyse your funds) ──────────────────────────────────────

export interface XrayFundInput {
  market: Market;
  code: string;
  name: string;
  weight?: number;
}

export interface XrayRequest {
  risk: RiskProfile;
  funds: XrayFundInput[];
}

export interface AllocSlice { label: string; pct: number; }
export interface SectorSlice { sector: string; pct: number; }
export interface CompanyHolding { name: string; symbol?: string; pct: number; }

export interface XrayFundLine {
  market: Market;
  code: string;
  name: string;
  category?: string;
  weight: number;
  fund_score?: number;
  flag?: string;   // "decaying" | "closet" | "avoid"
}

export interface PortfolioXrayResponse {
  risk: RiskProfile;
  geography: AllocSlice[];
  caps: AllocSlice[];
  sectors: SectorSlice[];
  top_companies: CompanyHolding[];
  sector_coverage: number;
  redundancies: string[];
  gaps: string[];
  flagged_funds: string[];
  narrative: string;
  funds: XrayFundLine[];
  generated_at: string;
}
