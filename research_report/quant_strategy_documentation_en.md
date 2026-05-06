# Quant Strategy & Backtesting Detailed Guide (Documentation)

This document provides a detailed explanation of the core strategies, overlays, and backtesting simulation environment of the current quantitative backtesting data pipeline.

## 1. Strategy Presets
The current platform offers 3 core quantitative strategy presets composed of specific factor combinations. 

### 💡 Common Factor Scoring and Ranking Method
Each preset selects the Top N stocks based on the Composite Score of individual stocks.
1. **Individual Factor Percentile Score (Z-Score Rank)**: Each factor value is sorted across all stocks in the universe.
   - `Score = 1.0 - (Stock's Rank / (Total Number of Valid Stocks - 1))` (In case of a tie, the average rank is applied)
   - For indicators where higher is better (e.g., ROE), they are sorted in descending order. For indicators where lower is better (e.g., PER), they are sorted in ascending order to assign scores (range 0.0 ~ 1.0).
2. **Composite Score**: The individual factor scores obtained by each stock are summed with equal weights and averaged.
3. **Final Ranking**: Stocks are sorted in descending order of their Composite Score. If there is a tie, the stock with higher liquidity (`liquidity_rank`, which means a lower rank number) is selected first, followed by alphabetical order of the ticker symbol.

---

### 1) Value + Quality
- **Logic & Description**: A traditional and stable factor combination that simultaneously considers valuation metrics and the financial quality (profitability, financial health) of a company. It aims to avoid the Value Trap by selecting "companies with strong earnings power among cheap stocks".
- **Key Factors & Formulas**:
  - **Value Indicators (Lower is better)**:
    - `PER` = Current Close Price / (Net Income / Shares Outstanding)
    - `PBR` = Market Cap / Total Equity
    - `EV/EBITDA` = (Market Cap + Total Debt - Cash & Equivalents) / EBITDA (or Operating Income)
  - **Financial Health Indicators (Lower is better)**:
    - `Debt to Equity` = Total Debt / Total Equity
    - `Accruals Ratio` = (Net Income - Operating Cash Flow) / Total Assets
  - **Profitability/Efficiency Indicators (Higher is better)**:
    - `FCF Yield` = (Operating Cash Flow - CAPEX) / Market Cap
    - `Sales Yield` = Revenue / Market Cap
    - `ROE` = Net Income / Total Equity
    - `ROIC Proxy` = Operating Income / (Total Assets - Cash & Equivalents)
    - `Gross Margin` = Gross Profit / Revenue
    - `Operating Margin` = Operating Income / Revenue
    - `Interest Coverage` = Operating Income / Interest Expense
- **Operational Characteristics**: Can be calculated using only the most recent financial disclosure data and current prices without requiring past long-term price data (Look-back). It has the weakness of potentially underperforming the market benchmark during periods when value stocks are out of favor.

### 2) Value + Momentum
- **Logic & Description**: A strategy that rides on "stocks that already have strong market supply/demand and trends" among cheap stocks. It aims for the continuation of an upward trend rather than a simple price rebound.
- **Key Factors & Formulas**:
  - **Momentum Indicators (Higher is better)**: Measured based on the stock price 1 month ago to avoid short-term Reversal noise.
    - `12-1 Month Momentum` = (Adjusted Close 1 month ago / Adjusted Close 13 months ago) - 1
    - `6 Month Momentum` = (Current Adjusted Close / Adjusted Close 6 months (126 days) ago) - 1
    - `3 Month Momentum` = (Current Adjusted Close / Adjusted Close 3 months (63 days) ago) - 1
  - **Value Indicators**: Uses the same core Value indicators from the Value + Quality preset: `PER`, `PBR`, `EV/EBITDA` (Lower is better) and `FCF Yield`, `Sales Yield` (Higher is better).
- **Operational Characteristics**: Requires a past price history of at least 13 months since it references prices from 13 months ago. Frequent trading in volatile markets where trends reverse quickly can increase the portfolio Turnover rate.

### 3) Quality + Low Volatility
- **Logic & Description**: A strategy that maximizes portfolio defense by selecting "stocks with the least price fluctuation (volatility)" among profitable and financially healthy stocks.
- **Key Factors & Formulas**:
  - **Volatility Indicators (Lower is better)**: Calculates the sample standard deviation of daily log returns over a specific past period.
    - `63-Day Price Volatility` = Standard deviation of returns over the last 63 trading days
    - `126-Day Price Volatility` = Standard deviation of returns over the last 126 trading days
    - `252-Day Price Volatility` = Standard deviation of returns over the last 252 trading days
  - **Quality Indicators**: Uses the same core Quality indicators from the Value + Quality preset: `ROE`, `Gross Margin`, `Operating Margin` (Higher is better) and `Debt to Equity` (Lower is better).
- **Operational Characteristics**: Requires a past price history of at least 1 year (252 trading days). Because of its highly defensive nature, it may lag behind more aggressive strategies during strong Bull Markets.

---

## 2. Market Timing Overlays
A defensive mechanism (Risk-Off) overlaid on the basic factor portfolio strategy to survive extreme volatility in the stock market.

### 1) None
- **Description**: Does not use any market timing filters and only performs the basic month-end rebalancing of the factor strategy. It continues to hold stocks even in bear markets and serves as a baseline to measure the strategy's intrinsic performance.

### 2) Emergency Brake (Asymmetric Moving Average)
- **Description**: An "asymmetric" overlay strategy that quickly escapes on a daily basis during market plunges and cautiously confirms reentry at month-end. The goal is to escape early in a downturn while reducing frequent Whipsaws.
- **Logic (Risk-Off)**: If the index (SPY) stays below its 50-day moving average for 3 consecutive trading days based on the daily close, all stocks are sold on the next trading day and moved to safe assets.
- **Logic (Risk-On)**: Reenters the factor stock portfolio only if, on the "last day of the month", SPY is above its 200-day moving average AND the return over the recent 20 trading days is positive (+).

### 3) Canary Asset Signal
- **Description**: A momentum strategy that follows the flow of macroeconomic risk preference of global funds instead of internal stock market noise.
- **Logic**: Compares the 84-trading-day (approx. 4 months) returns of the global stock market (VT) and a safe asset, US mid-term treasuries (IEF).
  - `VT 84-day return > IEF 84-day return`: Risk-On state. Invest in the factor portfolio.
  - `VT 84-day return < IEF 84-day return`: Risk-Off state. Immediately escape to safe assets. This assessment is made at the end of every month.

### 4) Graduated Position Sizing
- **Description**: Instead of selling/buying 100% at once when risk is detected, it flexibly adjusts the "weight" of strategy assets and safe assets in 4 stages according to the strength of the market trend.
- **Month-end Rebalancing Weight Determination** (Based on SPY and 200-day moving average):
  - `SPY > 200d SMA × 1.02`: 100% Strategy Assets
  - `200d SMA < SPY ≤ 200d SMA × 1.02`: 70% Strategy + 30% Safe
  - `200d SMA × 0.98 ≤ SPY ≤ 200d SMA`: 50% Strategy + 50% Safe
  - `SPY < 200d SMA × 0.98`: 0% Strategy + 100% Safe (Full Escape)
- **Daily Defensive Logic**: Even in the middle of the month, if the daily close of SPY stays below the 50-day moving average for 3 consecutive trading days, an "additional 30%" is immediately converted to safe assets for preemptive defense.

---

## 3. Safe Assets
Parking assets to hold instead of cash when stocks are sold via Market Timing Overlays (Risk-Off). Multiple safe assets can be selected and allocated in desired percentages (%).

- **SGOV (US Ultra-Short Treasury ETF)**: A parking asset with almost no interest rate sensitivity, defending price most similarly to cash. (Disadvantage: short listing history)
- **JPST (Ultra-Short Corporate Bond ETF)**: Close to a cash equivalent but offers slightly higher yields from a minor credit spread compared to SGOV. Has a relatively longer listing history.
- **SHY (US 1-3 Year Treasury ETF)**: Provides decent and stable defense as the impact of interest rate fluctuations on price is limited.
- **IEF (US 7-10 Year Treasury ETF)**: Mid-term treasury bond. Advantageous for offsetting portfolio drawdowns by anticipating bond price increases (capital gains) from expected interest rate cuts during economic downturns or stock price declines. Conversely, incurs losses during periods of rising interest rates.
- **TLT (US 20+ Year Treasury ETF)**: Shows explosive price increases during economic crisis (Crash) phases, providing an inverse correlation (strong hedge) with stocks. However, it experiences extreme price fluctuations due to interest rate changes in normal times.
- **GLD (Gold Spot ETF)**: A representative inflation hedge and safe asset influenced by real interest rates and dollar weakness. Provides a diversification effect different from bonds.
- **XLE (Energy Sector ETF)**: Can be used as a strategic safe haven to defend against market declines during oil price surges or commodity-driven inflation shocks.

---

## 4. Backtesting Methodology and Results (Parameters & Metrics)

### 4.1 Backtest Input Parameters
- **Investment Period (Start / End Date)**: Simulation start and end dates. (Version v1 supports up to 15 years at once)
- **Initial Capital**: The starting seed money for the backtest (e.g., $100,000).
- **Number of Holdings (Top N)**: Select one of the top 10, 20, or 30 stocks based on the factor ranking. Each stock is included with an **Equal Weight** upon purchase.
- **Transaction Cost Preset**:
  - `Low (10bp round trip)`: A cheap cost assuming highly liquid, large-cap dominant trading.
  - `Base (25bp round trip)`: The default value assuming a standard stock rebalancing execution cost.
  - `Conservative (50bp round trip)`: A conservative, defensive assumption generously reflecting slippage and unfavorable executions.
- **Rebalancing Frequency and Execution Mechanism**:
  - Basically, entry/exit signals are confirmed based on the **"Month-end (Monthly)"** closing price.
  - Actual stock trading execution takes place at the "Open Price of the first normal index (SPY) trading day of the following month".
  - If a currently held stock is also a target for inclusion in the next month, the strategy does not sell and buy the entire position. Instead, it trades only the **difference (buy shortfall, sell excess)** to match the target equal weight, thereby saving unnecessary replacement costs.

### 4.2 Key Backtest Performance Metrics
All return-related metrics are strictly separated into Gross (before fees) and Net (after execution costs).
- **Total Return / CAGR (Compound Annual Growth Rate)**: The final return level of asset growth over the simulation period.
- **Max Drawdown (MDD)**: The deepest loss percentage experienced from the highest peak to the lowest trough during the investment period. The most important metric for measuring risk.
- **Sharpe Ratio**: A risk-adjusted return metric indicating how much excess return was achieved per unit of volatility (risk) of the portfolio.
- **Win Rate / Expected Value**: The percentage of profitable trades out of the total number of trades, and the average expected profit amount (or percentage) per single trade.
- **Turnover**: Indicates how often the portfolio was replaced over a year or the entire backtest period. High turnover accumulates fees, eroding the Net Return.
- **Average Holding Period**: Measures how many days, on average, a specific stock is held from purchase to sale.
- **Total Fees**: The total cumulative trading fees incurred during the period under the set Transaction Cost Preset (bp).

---

## 5. Core Data Infrastructure Principles for Strategy Understanding
- **Universe Construction (Liquidity Cohort)**: Does not include random stocks. Compresses the targets by building a cohort using only the top 700+ highly liquid "Common Stocks" based on ADV60 (past 60-day average daily dollar volume). Penny stocks, ETFs, ADRs, etc., are fundamentally excluded.
- **Strict Prevention of Look-ahead Bias (PIT Principle)**: A company's financial statements are mapped to be used in strategy calculations only after the **Filing Date** when those statements were actually disclosed to the SEC, not the end date of the quarter (or year). This Point-in-Time design prevents the error of peeking at future information.
- **Prevention of Survivorship Bias**: The historical database includes stock prices and financial records of delisted or merged/acquired companies, preventing the phenomenon where backtest performance is inflated because only the winners remain.
