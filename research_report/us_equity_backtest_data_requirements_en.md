# Data Requirements Report for Backtesting Three U.S. Equity Strategies

## 1. Purpose and Scope
This document defines the data requirements for backtesting the following three U.S. equity strategies:

- `Value + Quality`
- `Value + Momentum`
- `Quality + Low Volatility`

The goal is not to restate the strategy thesis, but to provide an engineering-ready view of which raw datasets are required, how they should be collected, and how those raw datasets map into derived factors. The intended audience is the engineer who will later implement the data ingestion pipeline in code.

The baseline assumptions are:

- The universe is U.S. common stocks listed on NYSE, Nasdaq, and AMEX.
- ETFs, ADRs, preferred shares, and ultra-illiquid names are excluded.
- Rebalancing is monthly.
- Backtests must be point-in-time correct.
- Filing lag, delisting coverage, symbol-change handling, and corporate action handling are mandatory.

## 2. Strategy-Level Data Overview
All three strategies share the same core data layers:

- security master and identifier mapping
- listing, delisting, and symbol-change history
- daily prices, volume, dividends, splits, and other corporate actions
- raw financial statements and filing metadata
- sector and industry classification
- trading calendar
- benchmark returns and risk-free rates

The main differences by strategy are:

- `Value + Quality`
  - highest dependence on raw financial statement coverage
  - requires value, profitability, leverage, and earnings-quality calculations
- `Value + Momentum`
  - requires value inputs plus adjusted daily total-return series
  - must support explicit skip-month rules such as 12-1 momentum
- `Quality + Low Volatility`
  - requires quality inputs plus realized volatility from daily returns
  - `beta` is an optional extension, not the default low-volatility definition

## 3. Shared Data Layers
### 3.1 Security Master
Required fields:

- `ticker`
- `CIK`
- `exchange`
- `security_type`
- `primary_listing_flag`
- `active_delisted_status`
- `listing_date`
- `delisting_date`
- `symbol_change_history`
- when available, additional identifiers such as `CUSIP`, `ISIN`, and `FIGI`

Why this layer is needed:

- It is the base join layer across prices, filings, fundamentals, and corporate actions.
- `ticker` is not stable over time, so a durable identifier is required.
- Delisted names must remain in the historical universe to avoid survivorship bias.

Collection caveats:

- The center of identity management should be `CIK` or an internal `stable_id`, not the ticker alone.
- Symbol-change history should be stored as an event log, not overwritten in place.
- Listing status should ideally be stored both as a snapshot and as an event stream.

### 3.2 Listing and Delisting History
Required fields:

- `symbol`
- `status`
- `listing_date`
- `delisting_date`
- `delisting_reason` when available
- `status_effective_date`

Why this layer is needed:

- Historical universes require knowledge of which names were actually tradable at a given time.
- Final trade date and status-transition timing matter for backtest exits and survivorship control.

Collection caveats:

- Vendor delisting coverage can vary materially and should be cross-checked.
- The delisting date and final trade date are not always identical.

### 3.3 Daily Prices, Volume, and Corporate Actions
Required fields:

- `trade_date`
- `open`, `high`, `low`, `close`
- `adjusted_close` or `adjustment_factor`
- `volume`
- `dividend_amount`
- `split_factor`
- `corporate_action_type`

Why this layer is needed:

- It drives momentum, realized volatility, beta, return calculation, dollar-volume filters, and rebalance execution prices.
- Missing dividend or split adjustments will distort total-return-based signals.
- Keeping both raw and adjusted price series makes internal validation possible.

Collection caveats:

- Adjustment logic differs across vendors and should be standardized internally.
- The month-end signal timestamp and next-day-open execution rule must remain consistent.
- Trading halts, outliers, and split-related discontinuities should be explicit quality checks.

### 3.4 Financial Statements and Filing Metadata
Required fields:

- Income statement
  - `revenue`
  - `gross_profit`
  - `operating_income`
  - `EBITDA`
  - `interest_expense`
  - `net_income`
  - `basic_eps`
  - `diluted_eps`
  - `weighted_average_shares`
- Balance sheet
  - `total_assets`
  - `total_liabilities`
  - `total_equity`
  - `cash_and_equivalents`
  - `short_term_debt`
  - `long_term_debt`
- Cash flow statement
  - `operating_cash_flow`
  - `capex`
  - `dividends_paid`
  - `share_repurchases` when available
- Filing metadata
  - `period_end`
  - `fiscal_year`
  - `fiscal_quarter`
  - `filing_date`
  - `accepted_datetime` or `effective_as_of`
  - `accession_number`
  - `restatement_flag`

Why this layer is needed:

- It is the source of value, profitability, financial-strength, and earnings-quality factors.
- For point-in-time backtests, the data values alone are not enough; the market availability timestamp is equally important.

Collection caveats:

- Data eligibility should be based on `filing_date` or actual market availability, not just `period_end`.
- Restated filings should be versioned, not overwritten.
- Raw XBRL ingestion may require normalization across company-specific taxonomy extensions.

### 3.5 Sector and Industry Classification
Required fields:

- `sector`
- `industry`
- `sic` or `gics_like_classification`
- `classification_effective_date`

Why this layer is needed:

- Value and quality ratios often have large cross-industry distribution differences.
- `Quality + Low Volatility` needs monitoring for defensive sector concentration.

Collection caveats:

- Classification systems vary by vendor and may need internal standardization.
- Sector and industry can change through time and should keep effective dates.

### 3.6 Trading Calendar
Required fields:

- `trade_date`
- `is_open`
- `session_type`
- `market_open_time`
- `market_close_time`

Why this layer is needed:

- It is required for month-end rebalance logic, filing-lag enforcement, and next-trading-day execution.

### 3.7 Benchmarks and Risk-Free Rates
Required fields:

- `benchmark_price` or `benchmark_return`
- `risk_free_rate`
- `market_return_series` if beta is used

Why this layer is needed:

- Excess return, Sharpe, and beta require benchmark and risk-free inputs.
- The optional beta version of `Quality + Low Volatility` depends on a benchmark return series.

Collection caveats:

- Risk-free rates should be aligned to daily or holding-period frequency.
- Benchmark returns and stock returns must be matched on the same trading calendar.
- If the optional beta extension is enabled, the default benchmark should be a daily `SPY` adjusted-price total-return proxy collected from the same price-vendor family as the stock universe whenever possible.

## 4. Strategy-by-Strategy Data Requirements
### 4.1 Value + Quality
#### Required Raw Fields
- Price and market-value fields
  - `close`
  - `adjusted_close`
  - `shares_outstanding` or fields sufficient to compute market cap
- Financial statement fields
  - `net_income`
  - `total_equity`
  - `total_assets`
  - `gross_profit`
  - `operating_income`
  - `EBITDA`
  - `revenue`
  - `cash_and_equivalents`
  - `short_term_debt`
  - `long_term_debt`
  - `operating_cash_flow`
  - `capex`
  - `interest_expense`
  - working-capital-related fields or inputs sufficient to compute accruals
- Metadata
  - `period_end`
  - `filing_date`
  - `effective_as_of`

#### Why the Fields Are Needed
- Value requires price, market cap, enterprise-value inputs, and earnings or cash-flow line items.
- Quality requires profitability, margin, leverage, earnings-quality, and coverage-related fields.

#### Derived Factors
- Value
  - `P/E`
  - `P/B`
  - `EV/EBITDA`
  - `FCF Yield`
  - `Sales Yield`
- Quality
  - `ROE`
  - `ROIC`
  - `Gross Margin`
  - `Operating Margin`
  - `Debt-to-Equity`
  - `Interest Coverage`
  - `Accruals`

#### Point-in-Time Notes
- Enterprise value should use market cap close to the time the filing became usable.
- `weighted_average_shares` and `shares_outstanding` are not the same field and require a fixed internal convention.
- Sector-aware normalization or winsorization may be necessary because ratio distributions vary across industries.

### 4.2 Value + Momentum
#### Required Raw Fields
- Value side
  - the minimum value-calculation set used in `Value + Quality`
- Momentum side
  - at least 13 months of daily `adjusted_close`, or enough history to cover `252 trading days + the skip-month rule`
  - dividend and split adjustments
  - trading calendar

#### Why the Fields Are Needed
- Value captures valuation support.
- Momentum captures trend and total-return strength.

#### Derived Factors
- `12M total return`
- `6M total return`
- `3M total return`
- `12-1 momentum`
- `relative strength`

#### Point-in-Time Notes
- Momentum should be calculated from adjusted prices or total return.
- The skip-month rule should be explicitly defined in trading-day terms, and the history window must be long enough to support `12-1 momentum` without empty signals.
- Missing corporate action adjustments can materially distort the signal.

### 4.3 Quality + Low Volatility
#### Required Raw Fields
- Quality side
  - the core quality-calculation set from `Value + Quality`
- Low-volatility side
  - at least 12 months of daily `adjusted_close`
  - trading calendar for return calculation
- Beta extension
  - `benchmark_return_series`
  - regression-window metadata

#### Why the Fields Are Needed
- Quality measures balance-sheet and earnings strength.
- Low volatility measures realized stability in market prices.
- Beta is only needed for an optional market-sensitivity extension.

#### Derived Factors
- Quality
  - `ROE`
  - `ROA`
  - `Gross Margin`
  - `Operating Margin`
  - `Debt-to-Equity`
- Low Volatility
  - `63d rolling volatility`
  - `126d rolling volatility`
  - `252d rolling volatility`
- Optional
  - `beta`

#### Point-in-Time Notes
- The default low-volatility definition is `rolling daily return volatility`.
- `beta` is an optional extension or secondary filter, not a required baseline.
- If `beta` is enabled, the default benchmark should be a daily `SPY` adjusted-price total-return proxy, and benchmark returns must be aligned to the same trading calendar as security returns.

## 5. Data Source and Collection Matrix
| Data Category | Required Fields | Free Source | Free Collection Method | Paid Source | Paid Collection Method | Selection Rationale | Caveats |
|---|---|---|---|---|---|---|---|
| Security master / listing status / symbol mapping | ticker, CIK, exchange, status, listing date, delisting date, symbol history | SEC EDGAR submissions, Alpha Vantage LISTING_STATUS | Build a CIK-centered master, run daily or weekly incremental refreshes, and periodic full refreshes | EODHD fundamentals/delisted/reference, Polygon reference | Daily increments plus scheduled full reconciliation | Free sources are accessible and official enough for prototypes; paid sources are stronger for delisting and symbol-change coverage | Vendor identifier schemes differ, and delisting date may differ from final trade date |
| Daily prices / volume / dividends / splits | OHLCV, adjusted close, dividend, split factor | Alpha Vantage TIME_SERIES_DAILY_ADJUSTED | Symbol-by-symbol API pulls, retry missing symbols, maintain daily increments | Polygon Stocks REST/Flat Files | Initial flat-file backfill, then REST-based daily increments | Free source is good for prototypes; paid source is more robust in quality and scalability | Alpha Vantage rate limits and differing adjustment methodologies across vendors |
| Raw financial statements | revenue, gross profit, operating income, EBITDA, net income, assets, liabilities, equity, cash, debt, OCF, capex | SEC EDGAR companyfacts, SEC bulk ZIP | Filing-event-based ingestion with accession-number versioning | Polygon financial statement endpoints, EODHD fundamentals | Incremental collection after filings plus periodic snapshots | SEC is the primary source of truth; paid vendors reduce normalization effort | XBRL normalization is required, and vendors can define fields differently |
| Filing metadata | period_end, filing_date, accepted_datetime, accession_number, restatement_flag | SEC EDGAR submissions | Event-driven filing ingestion | Polygon financial statement metadata, EODHD metadata | Filing-based incremental sync | Filing metadata is the core of point-in-time correctness | Accepted time may be missing and require an internal availability rule |
| Sector / industry classification | sector, industry, sic/gics-like code, effective date | Alpha Vantage OVERVIEW, limited SEC SIC metadata | Periodic snapshot pulls | Polygon ticker overview/reference, EODHD fundamentals | Weekly or monthly incremental pulls | Needed for normalization and sector exposure controls | Classification systems vary, and classifications can change through time |
| Trading calendar | trade_date, market_open, market_close, session status | Price-source-derived trading calendar, with exchange calendar validation if needed | Derive from open trading dates and validate against official market holidays | Polygon market status/calendar style endpoints | Daily incremental refresh | Required for rebalance timing and filing-lag alignment | Half-days, holidays, and irregular sessions require explicit handling |
| Benchmarks / risk-free rates | benchmark return, risk-free rate, optional market return series | FRED API + Alpha Vantage SPY adjusted series | Use FRED for risk-free series and a daily SPY adjusted-price series for the beta benchmark | Nasdaq Data Link premium or Polygon SPY series | Scheduled incremental sync | FRED is appropriate for risk-free data, while a daily SPY total-return proxy from the same vendor family as equity prices is more reproducible for beta | FRED alone is not an ideal market-return proxy for beta, and SPY should be documented as an ETF-based benchmark proxy |
| Delisting / reference enrichment | delisting status, delisting date, reference history | SEC submissions, Alpha Vantage LISTING_STATUS | Event-driven incremental collection | EODHD delisted/reference, Polygon reference | Daily snapshots plus event-log storage | Critical for survivorship control | Free sources alone may leave gaps in delisting coverage |

## 6. Recommended Source Stacks
### 6.1 Free-First Stack
- `SEC EDGAR submissions/companyfacts/bulk ZIP`
- `Alpha Vantage TIME_SERIES_DAILY_ADJUSTED`
- `Alpha Vantage OVERVIEW`
- `Alpha Vantage LISTING_STATUS`
- `FRED API`

Best fit:

- prototype backtests
- smaller universes
- early-stage research with low budget

Advantages:

- low barrier to entry
- direct use of public and official data sources

Limits:

- weaker delisting and symbol-history coverage
- heavier normalization burden
- less operationally stable for large universes

### 6.2 Paid-First Stack
- `Polygon Stocks REST/Flat Files`
- `Polygon financial statement endpoints`
- `EODHD fundamentals/delisted/reference`
- `FRED API`
- `SEC EDGAR` retained as an authoritative archive

Best fit:

- larger-scale backtesting
- recurring research operations
- long-history reconstruction including delisted names

Advantages:

- stronger price and corporate action quality
- better reference and delisting coverage
- simpler incremental sync operations

Limits:

- licensing and vendor cost
- more normalization discipline required across providers

### 6.3 Practical Hybrid Recommendation
- filings and authoritative company facts: `SEC`
- prices and corporate actions: `Polygon`
- delisting and reference enrichment: `EODHD`
- risk-free and macro support: `FRED`
- institutional secondary alternative: `Nasdaq Data Link premium`

Why this is the recommended default:

- it balances source-of-truth quality with engineering convenience
- responsibilities are separated cleanly by data layer
- it offers the best tradeoff across quality, operability, and cost

## 7. Engineering Handoff Notes
Recommended canonical entities:

- `security_master`
- `daily_prices`
- `corporate_actions`
- `fundamentals_income_statement`
- `fundamentals_balance_sheet`
- `fundamentals_cash_flow`
- `filing_metadata`
- `benchmark_series`

Each entity should include at least the following metadata:

- `symbol`
- `stable_id` or `CIK`
- `trade_date` or `period_end`
- `filing_date`
- `effective_as_of`
- `source`

Recommended storage and ingestion rules:

- separate raw ingestion tables from normalized analytics tables
- store `source_id`, `ingested_at`, and `available_at` in the raw layer
- enforce point-in-time access using `available_at`
- apply filing lag based on actual market availability, not just fiscal period end
- for month-end rebalancing, allow only data available before the rebalance cutoff

Recommended collection patterns:

- prices and corporate actions
  - initial backfill via bulk or long-history download
  - daily incremental sync afterward
- filings and fundamentals
  - filing-event-based incremental sync
  - periodic full reconciliation
- security master and listing status
  - daily or weekly incremental refresh
  - periodic full refresh

Minimum quality checks:

- missing symbols
- duplicate filings
- price discontinuities around splits
- statement roll-up mismatches
- incorrect final trade dates for delisted names
- broken joins after symbol changes

## 8. Risks and Implementation Notes
- `survivorship bias`
  - Dropping delisted names will overstate historical performance.
- `look-ahead bias`
  - Using filing values before they became available to the market will distort the signal.
- `ticker drift`
  - Symbol changes and relistings can break joins between prices and fundamentals.
- `restatement bias`
  - Backfilling revised filings into the historical past can create unrealistic results.
- `split/dividend drift`
  - Inconsistent adjustment logic across vendors changes momentum and volatility signals.
- `vendor mismatch`
  - The same field name may not mean the same thing across vendors.
- `low-volatility mis-specification`
  - The default should be realized volatility; beta is only an optional extension.
- `momentum distortion`
  - Using unadjusted prices instead of total-return-aware prices will produce incorrect momentum signals.

## 9. Conclusion
Across all three strategies, the data pipeline must support point-in-time access, filing lag, stable identifier management, delisting and symbol-change handling, and reliable incremental sync. A free-first prototype can be built with `SEC + Alpha Vantage + FRED`, but the most practical operational setup is a hybrid of `SEC + Polygon + EODHD + FRED`. For `Quality + Low Volatility`, the recommended default low-volatility definition is `rolling daily return volatility`, while `beta` should be treated as an optional extension only.
