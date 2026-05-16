create schema if not exists raw;
create schema if not exists stg;
create schema if not exists mart;
create schema if not exists meta;

create table if not exists meta.ingestion_watermarks (
  source_name text not null,
  resource_name text not null,
  cursor_value text,
  updated_at timestamptz not null default now(),
  primary key (source_name, resource_name)
);

create table if not exists meta.universe_members (
  symbol text not null,
  cohort text not null default 'prototype',
  is_active boolean not null default true,
  effective_date date not null default current_date,
  source text not null default 'seed',
  primary key (symbol, cohort, effective_date)
);

create table if not exists meta.universe_rank_snapshots (
  snapshot_date date not null,
  cohort text not null,
  symbol text not null,
  rank integer not null,
  adv60 numeric,
  eligibility_status text not null,
  source text not null default 'pipeline',
  updated_at timestamptz not null default now(),
  primary key (snapshot_date, cohort, symbol)
);

create table if not exists meta.universe_build_runs (
  build_run_id bigserial primary key,
  cohort text not null,
  buffer_cohort text not null,
  status text not null,
  params jsonb not null default '{}'::jsonb,
  candidate_count integer,
  buffer_count integer,
  target_count integer,
  metadata jsonb not null default '{}'::jsonb,
  started_at timestamptz not null default now(),
  completed_at timestamptz,
  updated_at timestamptz not null default now()
);

create table if not exists meta.fred_series_config (
  series_id text primary key,
  description text not null,
  is_active boolean not null default true
);

create table if not exists mart.backtest_run_summary (
  run_id text primary key,
  created_at timestamptz not null default now(),
  start_date date not null,
  end_date date not null,
  strategy_preset text not null,
  market_timing_overlay text not null,
  safe_asset_summary text not null default '',
  initial_capital numeric not null,
  top_n integer not null,
  transaction_cost_preset text not null,
  final_gross_equity numeric,
  final_net_equity numeric,
  final_benchmark_equity numeric,
  gross_total_return numeric,
  net_total_return numeric,
  gross_cagr numeric,
  net_cagr numeric,
  max_drawdown_net numeric,
  sharpe numeric,
  trade_count integer not null default 0,
  win_rate numeric,
  expected_value numeric,
  turnover numeric,
  total_fees numeric,
  average_holding_period numeric,
  metrics jsonb not null default '{}'::jsonb,
  form_values jsonb not null default '{}'::jsonb,
  config jsonb not null default '{}'::jsonb,
  warnings jsonb not null default '[]'::jsonb,
  data_quality_flags jsonb not null default '[]'::jsonb
);

create table if not exists mart.backtest_equity_curve (
  id bigserial primary key,
  run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
  equity_date date not null,
  gross_equity numeric not null,
  net_equity numeric not null,
  benchmark_equity numeric,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now(),
  unique (run_id, equity_date)
);

create table if not exists mart.backtest_rebalance_summary (
  id bigserial primary key,
  run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
  signal_date date not null,
  execution_date date not null,
  selected_count integer not null,
  sold_count integer not null,
  buy_notional numeric not null,
  sell_notional numeric not null,
  fees numeric not null,
  turnover numeric not null,
  notes text,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists mart.backtest_fill_log (
  id bigserial primary key,
  run_id text not null references mart.backtest_run_summary(run_id) on delete cascade,
  execution_date date not null,
  signal_date date not null,
  symbol text not null,
  action text not null,
  shares numeric not null,
  execution_price numeric not null,
  fees numeric not null,
  net_cash_flow numeric not null,
  realized_pnl numeric,
  holding_days integer,
  details jsonb not null default '{}'::jsonb,
  created_at timestamptz not null default now()
);

create table if not exists raw.ingestion_artifacts (
  artifact_id bigserial primary key,
  source text not null,
  dataset text not null,
  source_key text,
  symbol text,
  cik text,
  object_key text not null,
  payload_sha256 text,
  available_at timestamptz,
  ingested_at timestamptz not null default now(),
  metadata jsonb not null default '{}'::jsonb,
  unique (source, dataset, source_key, available_at)
);

create table if not exists raw.alpha_vantage_listing_status (
  symbol text not null,
  name text,
  exchange text,
  asset_type text,
  ipo_date date,
  delisting_date date,
  status text not null,
  source_file_date date not null,
  ingested_at timestamptz not null default now(),
  primary key (symbol, source_file_date)
);

create table if not exists raw.alpha_vantage_overview (
  symbol text not null,
  as_of_date date not null,
  cik text,
  name text,
  exchange text,
  sector text,
  industry text,
  asset_type text,
  market_cap numeric,
  shares_outstanding numeric,
  overview_json jsonb not null,
  ingested_at timestamptz not null default now(),
  primary key (symbol, as_of_date)
);

create table if not exists raw.alpha_vantage_daily_prices (
  symbol text not null,
  trade_date date not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  adjusted_close numeric,
  volume bigint,
  dividend_amount numeric,
  split_coefficient numeric,
  source text not null default 'alpha_vantage',
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);

create table if not exists raw.alpha_vantage_corporate_actions (
  symbol text not null,
  trade_date date not null,
  action_type text not null,
  action_value numeric,
  source text not null default 'alpha_vantage',
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date, action_type)
);

create table if not exists raw.tiingo_daily_prices (
  symbol text not null,
  trade_date date not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  adjusted_open numeric,
  adjusted_high numeric,
  adjusted_low numeric,
  adjusted_close numeric,
  volume bigint,
  adjusted_volume numeric,
  dividend_amount numeric,
  split_coefficient numeric,
  source text not null default 'tiingo',
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date)
);

create table if not exists raw.tiingo_corporate_actions (
  symbol text not null,
  trade_date date not null,
  action_type text not null,
  action_value numeric,
  source text not null default 'tiingo',
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date, action_type)
);

create table if not exists raw.market_daily_prices (
  symbol text not null,
  trade_date date not null,
  source text not null,
  open numeric,
  high numeric,
  low numeric,
  close numeric,
  adjusted_open numeric,
  adjusted_high numeric,
  adjusted_low numeric,
  adjusted_close numeric,
  volume bigint,
  adjusted_volume numeric,
  dividend_amount numeric,
  split_coefficient numeric,
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date, source)
);

create table if not exists raw.market_corporate_actions (
  symbol text not null,
  trade_date date not null,
  action_type text not null,
  source text not null,
  action_value numeric,
  ingested_at timestamptz not null default now(),
  primary key (symbol, trade_date, action_type, source)
);

create table if not exists raw.sec_submissions (
  cik text primary key,
  entity_name text,
  primary_ticker text,
  tickers text[],
  exchanges text[],
  sic text,
  sic_description text,
  fetched_at timestamptz not null default now(),
  submission_json jsonb not null
);

create table if not exists raw.sec_ticker_reference (
  symbol_alias text not null,
  source_ticker text not null,
  cik text not null,
  entity_name text,
  exchange text,
  as_of_date date not null,
  fetched_at timestamptz not null default now(),
  primary key (symbol_alias, as_of_date)
);

create table if not exists raw.sec_filing_metadata (
  cik text not null,
  accession_number text not null,
  form text,
  filing_date date,
  accepted_at timestamptz,
  period_end date,
  fiscal_year int,
  fiscal_period text,
  primary_document text,
  filing_href text,
  is_xbrl boolean,
  available_at timestamptz,
  ingested_at timestamptz not null default now(),
  primary key (cik, accession_number)
);

create table if not exists raw.sec_companyfacts_facts (
  cik text not null,
  accession_number text not null,
  taxonomy text not null,
  concept text not null,
  unit text not null,
  frame text not null default '',
  period_start date,
  period_end date not null,
  fiscal_year int,
  fiscal_period text,
  filing_date date,
  accepted_at timestamptz,
  available_at timestamptz,
  value numeric,
  raw_fact jsonb not null,
  ingested_at timestamptz not null default now(),
  primary key (cik, accession_number, taxonomy, concept, unit, frame, period_end)
);

create table if not exists raw.fred_series_observations (
  series_id text not null,
  observation_date date not null,
  realtime_start date not null,
  realtime_end date not null,
  value numeric,
  ingested_at timestamptz not null default now(),
  primary key (series_id, observation_date, realtime_start)
);
