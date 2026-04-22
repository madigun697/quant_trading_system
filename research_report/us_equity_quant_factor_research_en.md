# Research Report: Candidate Factors for a New U.S. Equity Quant Strategy

## 1. Purpose and Scope
This report outlines factor and multi-factor candidates worth backtesting for a new long-only U.S. equity quant strategy. The target market is U.S. equities, with the universe limited to common stocks listed on NYSE, Nasdaq, and AMEX. ETFs, ADRs, preferred shares, and ultra-illiquid names are excluded. The purpose of this report is to propose candidate hypotheses that are immediately testable in backtesting, rather than to make stock-specific recommendations.

## 2. Baseline Assumptions
- Universe: NYSE, Nasdaq, and AMEX common stocks
- Exclusions: ETFs, ADRs, preferred shares, and ultra-illiquid names
- Portfolio construction: long-only, equal weight
- Rebalancing: monthly
- Holdings: 20 to 30 names
- Execution assumption: month-end signal, next-day open execution
- Cost assumption: fees and slippage included
- Fundamental data handling: apply filing/reporting lag to avoid look-ahead bias
- Operational guardrails: include trading halts, delistings, missing data, and point-in-time universe construction

## 3. Candidate Selection Criteria
The candidates in this report were selected using the following criteria.
- Clear and explainable economic intuition
- Practical data availability and maintenance
- Feasible implementation under monthly rebalancing and equal weighting
- A realistic chance of surviving fees, slippage, and reporting lag
- Stronger signal quality as a combination than as a single factor
- Relatively clear failure conditions and limited overfitting risk

Combination factors are prioritized because single factors often come with structural weaknesses. Value can suffer from value traps, momentum can over-chase crowded moves, and low-volatility can become overly concentrated in defensive sectors. A combination approach is more likely to produce signals that are investable in a real strategy.

## 4. Detailed Review of Factor Candidates
### 4.1 Value + Quality
#### Factor Description
This combination looks for stocks that are cheap but also financially healthy and profitable. The goal is to avoid classic value traps by adding business quality to a valuation screen.

#### Concrete Rule Idea
- Value: build a composite value score from two or three of P/B, P/E, EV/EBITDA, and FCF Yield
- Quality: build a composite quality score from ROE, ROIC, Gross Margin, Accruals, Debt-to-Equity, and Interest Coverage
- Final score: combine Value and Quality using equal weighting or a 60/40 split
- Selection: include only top-ranked names that also pass a liquidity filter

#### Selection Rationale
Pure value strategies can capture stocks that are cheap for a good reason. Adding quality helps eliminate structurally weak businesses and improves practical investability.

#### Why It May Work
Markets can temporarily misprice high-quality businesses when short-term sentiment is weak. Quality reduces balance-sheet stress and bankruptcy risk, while Value provides valuation support. The combination is well suited to finding cheap companies that are still fundamentally viable.

#### When It May Fail
- Value can lag badly during growth-led or low-rate regimes
- Quality can push the portfolio toward expensive large-cap winners
- Accounting differences can distort value metrics across sectors
- In early recessions, cheap stocks can remain cheap while fundamentals keep deteriorating

#### Test Framing
- Compare Value-only, Quality-only, and Value + Quality using the same universe and cost assumptions
- Test both z-score and rank-sum scoring approaches
- Compare sector-neutral and non-sector-neutral implementations
- Verify whether the signal remains effective under strict reporting lag

#### Why the Combination Should Be Tested Before the Single Factor Alone
Value alone is vulnerable to traps, and Quality alone can drift toward already expensive defensives. Testing the combination first reveals whether there is a more investable balance between cheapness and business quality.

### 4.2 Value + Momentum
#### Factor Description
This combination targets stocks that are undervalued while still showing positive price trend. It seeks names that are cheap but already beginning to attract renewed market support.

#### Concrete Rule Idea
- Value: use a composite value score
- Momentum: use 6- to 12-month price return while excluding the most recent month
- Final score: either rank momentum within the top value bucket or combine the two scores directly
- Selection: choose the top 20 to 30 names by final score

#### Selection Rationale
Value captures mean-reversion potential, while momentum reflects the speed at which the market incorporates new information. Together they help focus on stocks that are cheap but no longer being ignored.

#### Why It May Work
Momentum can filter out value names that continue to break down, while Value can reduce the risk of blindly chasing expensive trend names. The two styles can complement each other meaningfully.

#### When It May Fail
- Both factors can struggle during sharp style reversals
- Momentum can become overheated after violent rebounds
- Event-driven price spikes can distort the signal

#### Test Framing
- Compare Value-only, Momentum-only, and Value + Momentum
- Test with and without the one-month exclusion rule
- Break results down across bull, bear, and high-volatility regimes
- Check turnover and cost sensitivity

#### Why the Combination Should Be Tested Before the Single Factor Alone
Momentum alone can become a chase strategy, while Value alone can leave the portfolio stuck in stocks that remain depressed. The combined test better shows whether valuation and timing improve each other in practice.

### 4.3 Quality + Low Volatility
#### Factor Description
This combination favors financially strong companies with relatively stable price behavior. It is a defensive candidate aimed at improving downside control and compounding stability.

#### Concrete Rule Idea
- Quality: create a composite score from profitability, cash-flow stability, and leverage measures
- Low Volatility: use the inverse of 6- to 12-month daily return volatility or beta
- Final score: rank low-volatility stocks within the high-quality group or combine both scores directly
- Selection: choose the top 20 to 30 names while monitoring defensive sector concentration

#### Selection Rationale
Reducing large drawdowns is critical for long-term compounding. The combination of Quality and Low Volatility is worth testing as a practical path toward stronger risk-adjusted returns.

#### Why It May Work
In risk-off regimes, investors often prefer stable cash flow and resilient balance sheets. This combination can help capture both business strength and price stability, which may improve drawdown control.

#### When It May Fail
- Defensive profiles can lag in strong risk-on markets
- Low Volatility can create heavy concentration in utilities, staples, or similar sectors
- High-quality companies may already trade at rich premiums

#### Test Framing
- Compare the risk-adjusted performance of Quality-only, Low Volatility-only, and the combined version
- Split results across up markets, down markets, and high-volatility periods
- Test the impact of sector caps versus no sector caps
- Compare the signal against a simple low-volatility benchmark concept

#### Why the Combination Should Be Tested Before the Single Factor Alone
Low Volatility alone can turn into a plain defensive basket, while Quality alone may not provide enough downside control. Testing both together shows whether the portfolio can gain both business quality and risk control at the same time.

### 4.4 Small/Mid Cap + Earnings Revision
#### Factor Description
This combination looks for small- and mid-cap stocks with improving earnings expectations. It is designed to capture cases where fundamentals are getting better before the market fully prices in the change.

#### Concrete Rule Idea
- Restrict the universe to small-cap and mid-cap names
- Earnings Revision: combine recent EPS estimate upgrades, upgrade magnitude, and positive surprise direction
- Supporting filters: minimum dollar volume, minimum market cap, and reporting lag
- Final score: combine Size and Revision signals
- Selection: choose the top 20 to 30 names

#### Selection Rationale
Small and mid caps often receive thinner analyst coverage, which can leave room for informational inefficiency. Earnings revisions can serve as an early signal of improving fundamentals.

#### Why It May Work
Upward estimate revisions can reflect future earnings improvement before the market fully reacts. This effect may be more persistent in less efficiently priced small- and mid-cap stocks.

#### When It May Fail
- Revision data can be sparse and noisy
- Smaller names can carry high slippage and trading costs
- One-time events can look like durable earnings improvement
- Liquidity can be too weak for clean execution

#### Test Framing
- Compare Small-only, Mid-only, and Small/Mid combined implementations
- Test revision windows of 1, 3, and 6 months
- Compare results with and without excluding low-coverage names
- Run stress tests with higher assumed costs and stricter liquidity filters

#### Why the Combination Should Be Tested Before the Single Factor Alone
Size alone can be unstable and overly noisy. Combining it with earnings revisions focuses the strategy on names that are not just small, but small and improving.

### 4.5 Shareholder Yield + Profitability
#### Factor Description
This combination favors companies that both return cash to shareholders and generate strong profitability in the core business. It aims to identify firms with strong capital allocation through dividends, buybacks, and net debt reduction.

#### Concrete Rule Idea
- Shareholder Yield: Dividend Yield + Net Buyback Yield + Net Debt Paydown Yield
- Profitability: build a composite score from ROIC, Operating Margin, and FCF Margin
- Final score: combine Shareholder Yield and Profitability
- Selection: choose the top 20 to 30 names while excluding highly levered firms
- Additional filter: review payout sustainability and consider excluding clearly loss-making firms

#### Selection Rationale
Strong shareholder yield can indicate durable cash generation and disciplined capital allocation. Adding profitability reduces the risk of falling into simple high-yield traps.

#### Why It May Work
Businesses with durable free cash flow are more likely to sustain dividends and buybacks. Markets may reward that consistency in capital return over time.

#### When It May Fail
- Dividends or buybacks may be temporary
- Shareholder return can decline quickly during economic slowdowns
- Capital-intensive sectors can distort interpretation
- The importance of net debt reduction may vary by rate regime

#### Test Framing
- Compare Shareholder Yield-only, Profitability-only, and the combined version
- Separate dividend-driven and buyback-driven effects
- Test with and without the net debt reduction component
- Review defensive behavior during balance-sheet stress periods

#### Why the Combination Should Be Tested Before the Single Factor Alone
Shareholder Yield alone can be noisy and influenced by temporary capital-structure changes, while Profitability alone can miss the capital-return dimension. The combined signal is closer to “businesses that both earn well and return cash well.”

## 5. Priority Recommendation
The first three combinations to backtest should be:

1. `Value + Quality`
2. `Value + Momentum`
3. `Quality + Low Volatility`

These come first because:
- they are easy to explain and interpret
- they are practical under a monthly rebalance structure
- they are well suited for comparing combination effects against single-factor baselines
- they rely on relatively accessible and scalable data in the U.S. equity market

## 6. Backtest Design
- Sample period: use a long horizon that spans multiple market regimes whenever possible
- Benchmarks: compare against each single-factor version, an equal-weight universe portfolio, and major index benchmarks
- Scoring: start with z-score combination and rank-sum combination
- Evaluation metrics: CAGR, Volatility, Sharpe, MDD, Turnover, Hit Rate, and improvement versus single-factor baselines
- Implementation checks: month-end signal, next-day open execution, and post-cost performance
- Risk checks: sector neutrality, size concentration, downside resilience, and subperiod dependence

## 7. Risks and Cautions
- Look-ahead bias and survivorship bias must be explicitly prevented
- Ignoring reporting lag will overstate fundamental factor performance
- Small-cap and low-liquidity names may look attractive in theory but fail after costs
- Sector concentration and style crowding require separate monitoring
- A short validation window is not enough to approve a factor
- Equal-weight portfolios can drive turnover high, so cost sensitivity matters

## 8. Next Actions
1. Run a first-pass backtest on all five candidates using the same data pipeline
2. Compare `Value + Quality`, `Value + Momentum`, and `Quality + Low Volatility` first
3. Review turnover, post-cost returns, and sector concentration together
4. Run parameter sensitivity and subperiod tests on the candidates that pass the first screen
5. Narrow the list to one or two combinations that are practical to implement
