# Pillar 5: Pre-Computed Metrics Catalog

**Global Financial Intelligence - Comprehensive Metrics Reference**

**Version:** 1.0.0  
**Date:** 2026  
**Author:** Ideotion  

---

## 📋 Overview

This document provides a **comprehensive catalog** of all pre-computed metrics available in Pillar 5’s financial intelligence system. Each metric is:

- **Grouped by theme** (Trend, Momentum, Volatility, Volume, Fundamental, Statistical, Pattern, Custom).
- **Fully documented** with definitions, formulas, use cases, and visualization recommendations.
- **Stored in the `financial_metrics` table** with full audit trails (source, calculation method, parameters, timestamp).
- **Visualization-ready** for integration into dashboards and analysis tools.

---

## 🎯 How to Use This Catalog

1. **For Developers**:
   - Use this as a reference for implementing the `MetricCalculator` class.
   - Each metric includes **pseudocode** for calculation.
   - Parameters are **configurable** (e.g., `period=20` for SMA).

2. **For Analysts**:
   - Understand what each metric **measures** and how to **interpret** it.
   - Learn **use cases** for different metrics (e.g., RSI for overbought/oversold conditions).

3. **For GUI Designers**:
   - Group metrics by **theme** in dropdown menus.
   - Use **recommended visualizations** (e.g., line chart for SMA, histogram for MACD).
   - Add **tooltips** with definitions and formulas.

---

## 📊 Metric Groups

| Group | Description | Key Metrics | Best For |
|-------|-------------|-------------|----------|
| **[Trend](#-group-1-trend-metrics)** | Identify direction and strength of price movements | SMA, EMA, MACD, Bollinger Bands, ADX | Trend following, support/resistance |
| **[Momentum](#-group-2-momentum-metrics)** | Measure speed of price changes | RSI, Stochastic Oscillator, ROC, CCI | Overbought/oversold conditions |
| **[Volatility](#-group-3-volatility-metrics)** | Measure price variability | ATR, Standard Deviation, Beta, Historical Volatility | Risk assessment |
| **[Volume](#-group-4-volume-metrics)** | Analyze trading activity | OBV, Volume Spike, Chaikin Money Flow, VWAP | Confirming trends, liquidity |
| **[Fundamental](#-group-5-fundamental-metrics)** | Company health metrics | P/E, P/B, Dividend Yield, ROE, Debt-to-Equity | Valuation, profitability |
| **[Statistical](#-group-6-statistical-metrics)** | Statistical properties | Z-Score, Sharpe Ratio, Correlation, Percentile | Performance analysis |
| **[Pattern](#-group-7-pattern-metrics)** | Chart patterns | Head & Shoulders, Double Top, Support/Resistance | Predicting reversals |
| **[Custom](#-group-8-customcomposite-metrics)** | Composite signals | Golden Cross, Death Cross, Bullish Engulfing | Trading signals |

---

## 🔹 Group 1: Trend Metrics
**Purpose**: Identify the direction and strength of price trends.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **SMA** | Simple Moving Average: Smooths price data to identify trends. | `SMA = (P1 + P2 + ... + Pn) / n` | Identify trend direction, support/resistance levels. | Line chart (overlaid on price) | `period` (e.g., 20, 50, 200) | `SMA(prices, period=20)` |
| **EMA** | Exponential Moving Average: Weighted average where recent prices matter more. | `EMA = (P * k) + (EMA_prev * (1 - k))` where `k = 2/(n+1)` | Faster reaction to price changes than SMA. | Line chart | `period` (e.g., 12, 26) | `EMA(prices, period=12)` |
| **MACD** | Moving Average Convergence Divergence: Trend-following momentum indicator. | `MACD = EMA(12) - EMA(26)`, `Signal = EMA(9) of MACD`, `Histogram = MACD - Signal` | Identify trend reversals, momentum shifts. | Histogram + Line chart | `fast_period=12`, `slow_period=26`, `signal_period=9` | `MACD(prices, fast=12, slow=26, signal=9)` |
| **Bollinger Bands** | Volatility bands around a moving average. | `Upper = SMA + (k * σ)`, `Lower = SMA - (k * σ)` where `σ` = standard deviation | Identify overbought/oversold conditions. | Band chart | `period=20`, `k=2` | `BB(prices, period=20, k=2)` |
| **ADX** | Average Directional Index: Measures trend strength (not direction). | `ADX = 100 * SMA(\|+DI - -DI\| / (+DI + -DI))` | Determine if a trend is strong (`ADX > 25`) or weak (`ADX < 20`). | Line chart | `period=14` | `ADX(highs, lows, closes, period=14)` |
| **Ichimoku Cloud** | Comprehensive trend indicator with multiple components. | `Conversion Line = (9P High + 9P Low)/2`, `Base Line = (26P High + 26P Low)/2`, `Span A = (Conversion + Base)/2`, `Span B = (52P High + 52P Low)/2` | Identify support/resistance, trend direction. | Cloud chart | `conversion_period=9`, `base_period=26`, `lagging_span=52` | `Ichimoku(highs, lows, conversion=9, base=26, lagging=52)` |
| **Parabolic SAR** | Time/price-based trailing stop. | `SAR = Prior SAR + AF * (EP - Prior SAR)` where `AF` = acceleration factor, `EP` = extreme price. | Identify potential reversals, set stop-loss levels. | Dots on price chart | `af_start=0.02`, `af_increment=0.02`, `af_max=0.2` | `PSAR(highs, lows, af_start=0.02, af_max=0.2)` |
| **Linear Regression** | Fits a linear trendline to price data. | `y = mx + b` where `m` = slope, `b` = intercept. | Identify long-term trends, predict future prices. | Line chart | `period=50` | `LinearRegression(prices, period=50)` |
| **Donchian Channels** | Price range over a period. | `Upper = Highest High (n)`, `Lower = Lowest Low (n)` | Identify breakouts, volatility. | Band chart | `period=20` | `Donchian(highs, lows, period=20)` |
| **Keltner Channels** | Volatility-based bands around an EMA. | `Middle = EMA`, `Upper = EMA + (ATR * k)`, `Lower = EMA - (ATR * k)` | Identify overbought/oversold conditions. | Band chart | `ema_period=20`, `atr_period=10`, `k=2` | `Keltner(prices, atr_period=10, k=2)` |

---

### 📌 Trend Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Identify Uptrend** | SMA(50), EMA(20), ADX | Price > SMA(50) + EMA(20), ADX > 25 |
| **Identify Downtrend** | SMA(50), EMA(20), ADX | Price < SMA(50) + EMA(20), ADX > 25 |
| **Trend Reversal** | MACD, Parabolic SAR | MACD crosses Signal line, SAR flips |
| **Support/Resistance** | Bollinger Bands, Donchian Channels | Price touches Upper/Lower band |
| **Trend Strength** | ADX | ADX > 25 = Strong trend, ADX < 20 = Weak trend |

---

## 🔹 Group 2: Momentum Metrics
**Purpose**: Measure the speed of price changes to identify overbought/oversold conditions.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **RSI** | Relative Strength Index: Measures speed and change of price movements. | `RSI = 100 - (100 / (1 + RS))` where `RS = Avg Gain / Avg Loss` | Identify overbought (`RSI > 70`) or oversold (`RSI < 30`) conditions. | Line chart (0-100 scale) | `period=14` | `RSI(prices, period=14)` |
| **Stochastic Oscillator** | Compares closing price to price range over a period. | `%K = (Current Close - Lowest Low) / (Highest High - Lowest Low) * 100`, `%D = SMA(%K, 3)` | Identify overbought (`%K > 80`) or oversold (`%K < 20`) conditions. | Line chart (0-100 scale) | `k_period=14`, `d_period=3`, `smooth_k=3` | `Stochastic(highs, lows, closes, k=14, d=3)` |
| **ROC** | Rate of Change: Percentage change in price over a period. | `ROC = (Current Price - Price n periods ago) / Price n periods ago * 100` | Measure momentum, identify divergences. | Line chart | `period=12` | `ROC(prices, period=12)` |
| **CCI** | Commodity Channel Index: Measures deviation from statistical mean. | `CCI = (Typical Price - SMA) / (0.015 * Mean Deviation)` where `Typical Price = (High + Low + Close)/3` | Identify overbought (`CCI > 100`) or oversold (`CCI < -100`) conditions. | Line chart | `period=20` | `CCI(highs, lows, closes, period=20)` |
| **Williams %R** | Williams Percent Range: Momentum oscillator. | `%R = (Highest High - Close) / (Highest High - Lowest Low) * -100` | Identify overbought (`%R > -20`) or oversold (`%R < -80`) conditions. | Line chart (-100 to 0) | `period=14` | `WilliamsR(highs, lows, closes, period=14)` |
| **Awesome Oscillator** | Measures market momentum using median prices. | `AO = SMA(Median Price, 5) - SMA(Median Price, 34)` where `Median Price = (High + Low)/2` | Confirm trends, identify reversals. | Histogram | `fast_period=5`, `slow_period=34` | `AO(highs, lows, fast=5, slow=34)` |
| **Ultimate Oscillator** | Combines multiple timeframes for momentum. | `UO = 100 * [(4*BP7 + 2*BP14 + BP28) / (4*TR7 + 2*TR14 + TR28)]` where `BP` = Buying Pressure, `TR` = True Range | Identify overbought/oversold conditions across timeframes. | Line chart (0-100) | `period1=7`, `period2=14`, `period3=28` | `UltimateOscillator(highs, lows, closes, p1=7, p2=14, p3=28)` |
| **Momentum** | Simple momentum indicator. | `Momentum = Current Price - Price n periods ago` | Identify trend strength, divergences. | Line chart | `period=10` | `Momentum(prices, period=10)` |

---

### 📌 Momentum Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Overbought Condition** | RSI, Stochastic, CCI | RSI > 70, %K > 80, CCI > 100 |
| **Oversold Condition** | RSI, Stochastic, CCI | RSI < 30, %K < 20, CCI < -100 |
| **Bullish Divergence** | RSI, MACD, ROC | Price makes lower low, metric makes higher low |
| **Bearish Divergence** | RSI, MACD, ROC | Price makes higher high, metric makes lower high |
| **Momentum Shift** | ROC, Awesome Oscillator | ROC crosses 0, AO changes direction |

---

## 🔹 Group 3: Volatility Metrics
**Purpose**: Measure price variability to assess risk.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **ATR** | Average True Range: Measures market volatility. | `ATR = SMA(True Range)` where `True Range = max(High-Low, \|High-Prev Close\|, \|Low-Prev Close\|)` | Assess risk, set stop-loss levels. | Line chart | `period=14` | `ATR(highs, lows, closes, period=14)` |
| **Standard Deviation** | Measures price dispersion from the mean. | `σ = sqrt(Σ(Pi - μ)² / n)` where `μ` = mean price | Measure volatility, risk assessment. | Line chart | `period=20` | `StdDev(prices, period=20)` |
| **Beta** | Measures volatility relative to a benchmark. | `β = Cov(Ri, Rm) / Var(Rm)` where `Ri` = instrument returns, `Rm` = market returns | Assess risk relative to market (β > 1 = more volatile). | Single value | `benchmark` (e.g., "SPY") | `Beta(instrument_returns, market_returns)` |
| **Historical Volatility** | Annualized standard deviation of returns. | `HV = σ * sqrt(252)` (for daily data) | Measure long-term volatility. | Line chart | `period=30`, `annualize=True` | `HistoricalVolatility(returns, period=30)` |
| **Donchian Channels** | Price range over a period. | `Upper = Highest High (n)`, `Lower = Lowest Low (n)` | Identify breakouts, volatility. | Band chart | `period=20` | `Donchian(highs, lows, period=20)` |
| **Keltner Channels** | Volatility-based bands around an EMA. | `Middle = EMA`, `Upper = EMA + (ATR * k)`, `Lower = EMA - (ATR * k)` | Identify overbought/oversold conditions. | Band chart | `ema_period=20`, `atr_period=10`, `k=2` | `Keltner(prices, atr_period=10, k=2)` |
| **Average True Range Percent** | ATR as a percentage of price. | `ATR% = (ATR / Close) * 100` | Normalized volatility for comparison across instruments. | Line chart | `period=14` | `ATRPercent(highs, lows, closes, period=14)` |
| **Volatility Ratio** | Ratio of current volatility to historical volatility. | `VR = Current ATR / Historical ATR` | Identify periods of unusually high/low volatility. | Line chart | `current_period=14`, `historical_period=100` | `VolatilityRatio(prices, current=14, historical=100)` |

---

### 📌 Volatility Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **High Volatility** | ATR, Standard Deviation, Historical Volatility | ATR > 2x average, σ > historical σ |
| **Low Volatility** | ATR, Standard Deviation | ATR < 0.5x average, σ < historical σ |
| **Volatility Breakout** | ATR%, Volatility Ratio | ATR% spikes, VR > 1.5 |
| **Risk Assessment** | Beta, Historical Volatility | β > 1 = Higher risk than market |
| **Stop-Loss Placement** | ATR | Stop-loss = Close - (2 * ATR) |

---

## 🔹 Group 4: Volume Metrics
**Purpose**: Analyze trading activity to confirm trends.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **OBV** | On-Balance Volume: Cumulative volume based on price changes. | `OBV = OBV_prev + Volume` (if Close > Close_prev), `OBV = OBV_prev - Volume` (if Close < Close_prev), `OBV = OBV_prev` (if Close = Close_prev) | Confirm trends, identify divergences. | Line chart | None | `OBV(volumes, closes)` |
| **Volume Spike** | Unusual volume compared to average. | `Spike = Volume / SMA(Volume, n)` | Identify unusual trading activity. | Bar chart | `period=20`, `threshold=2.0` | `VolumeSpike(volumes, period=20, threshold=2.0)` |
| **Chaikin Money Flow** | Measures money flow volume. | `CMF = (Money Flow Multiplier * Volume) / Total Volume` where `Money Flow Multiplier = (Close - Low) - (High - Close) / (High - Low)` | Identify buying/selling pressure. | Line chart | `period=20` | `ChaikinMoneyFlow(highs, lows, closes, volumes, period=20)` |
| **VWAP** | Volume Weighted Average Price: Average price weighted by volume. | `VWAP = Σ(Price * Volume) / Σ(Volume)` | Identify fair value, institutional activity. | Line chart | None | `VWAP(prices, volumes)` |
| **Accumulation/Distribution Line** | Cumulative volume flow. | `A/D = A/D_prev + ((Close - Low) - (High - Close)) / (High - Low) * Volume` | Identify accumulation/distribution. | Line chart | None | `AccumulationDistribution(highs, lows, closes, volumes)` |
| **Money Flow Index (MFI)** | Measures money flow in/out of an asset. | `MFI = 100 - (100 / (1 + MR))` where `MR = Positive Money Flow / Negative Money Flow` | Identify overbought (`MFI > 80`) or oversold (`MFI < 20`) conditions. | Line chart (0-100) | `period=14` | `MFI(highs, lows, closes, volumes, period=14)` |
| **Volume Weighted MACD** | MACD weighted by volume. | `VW-MACD = VW-EMA(12) - VW-EMA(26)` where `VW-EMA` = Volume-weighted EMA | Identify trend reversals with volume confirmation. | Histogram + Line chart | `fast_period=12`, `slow_period=26`, `signal_period=9` | `VWMACD(prices, volumes, fast=12, slow=26, signal=9)` |
| **Ease of Movement** | Measures how easily price moves. | `EoM = (Distance Moved) / (Box Ratio)` where `Distance Moved = (High + Low)/2 - (Prior High + Prior Low)/2`, `Box Ratio = Volume / (High - Low)` | Identify low-effort price movements. | Line chart | `period=1` | `EaseOfMovement(highs, lows, volumes)` |

---

### 📌 Volume Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Volume Confirmation** | OBV, Chaikin Money Flow | OBV rises with price = Bullish confirmation |
| **Volume Divergence** | OBV, Volume Spike | Price rises but volume falls = Weak trend |
| **Breakout Confirmation** | Volume Spike, VWAP | Volume > 2x average = Strong breakout |
| **Institutional Activity** | VWAP, Ease of Movement | Price > VWAP = Bullish, EoM > 0 = Easy upward movement |
| **Accumulation** | Accumulation/Distribution Line | A/D rises while price flat = Accumulation |

---

## 🔹 Group 5: Fundamental Metrics
**Purpose**: Assess company health (primarily for stocks/ETFs).

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **P/E Ratio (Trailing)** | Price relative to trailing earnings. | `P/E = Price / EPS` | Assess valuation (high P/E = overvalued). | Bar chart (vs. peers) | None | `PERatio(price, eps)` |
| **P/E Ratio (Forward)** | Price relative to projected earnings. | `P/E = Price / Forward EPS` | Assess future valuation. | Bar chart | None | `ForwardPERatio(price, forward_eps)` |
| **P/B Ratio** | Price relative to book value. | `P/B = Price / Book Value per Share` | Assess valuation vs. assets (P/B < 1 = undervalued). | Bar chart | None | `PBRatio(price, book_value_per_share)` |
| **P/S Ratio** | Price relative to revenue. | `P/S = Price / Revenue per Share` | Assess valuation vs. sales. | Bar chart | None | `PSRatio(price, revenue_per_share)` |
| **Dividend Yield** | Annual dividend relative to price. | `Yield = Annual Dividend / Price * 100` | Assess income potential. | Bar chart | None | `DividendYield(annual_dividend, price)` |
| **ROE** | Return on Equity: Profitability relative to equity. | `ROE = Net Income / Shareholders' Equity` | Assess profitability efficiency (ROE > 15% = Good). | Bar chart | None | `ROE(net_income, shareholders_equity)` |
| **ROA** | Return on Assets: Profitability relative to assets. | `ROA = Net Income / Total Assets` | Assess asset efficiency (ROA > 5% = Good). | Bar chart | None | `ROA(net_income, total_assets)` |
| **Debt-to-Equity** | Leverage ratio. | `D/E = Total Debt / Shareholders' Equity` | Assess financial risk (D/E > 1 = High leverage). | Bar chart | None | `DebtToEquity(total_debt, shareholders_equity)` |
| **Current Ratio** | Liquidity ratio. | `Current Ratio = Current Assets / Current Liabilities` | Assess short-term solvency (Current Ratio > 1.5 = Good). | Bar chart | None | `CurrentRatio(current_assets, current_liabilities)` |
| **Profit Margin** | Profitability per dollar of revenue. | `Margin = Net Income / Revenue * 100` | Assess profitability (Margin > 10% = Good). | Bar chart | None | `ProfitMargin(net_income, revenue)` |
| **PEG Ratio** | P/E relative to growth rate. | `PEG = P/E / Growth Rate` | Assess valuation vs. growth (PEG < 1 = Undervalued). | Bar chart | None | `PEGRatio(pe_ratio, growth_rate)` |
| **Free Cash Flow Yield** | Free cash flow relative to market cap. | `FCF Yield = Free Cash Flow / Market Cap * 100` | Assess cash generation (FCF Yield > 5% = Good). | Bar chart | None | `FCFYield(free_cash_flow, market_cap)` |

---

### 📌 Fundamental Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Undervalued Stock** | P/E, P/B, PEG Ratio | P/E < Industry Avg, P/B < 1, PEG < 1 |
| **Overvalued Stock** | P/E, P/B, PEG Ratio | P/E > Industry Avg, P/B > 3, PEG > 1.5 |
| **Profitable Company** | ROE, ROA, Profit Margin | ROE > 15%, ROA > 5%, Margin > 10% |
| **High Risk** | Debt-to-Equity, Current Ratio | D/E > 2, Current Ratio < 1 |
| **Income Stock** | Dividend Yield, Payout Ratio | Yield > 3%, Payout Ratio < 60% |

---

## 🔹 Group 6: Statistical Metrics
**Purpose**: Statistical properties of price data.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **Z-Score** | Standard deviations from mean. | `Z = (X - μ) / σ` where `μ` = mean, `σ` = standard deviation | Identify outliers. | Scatter plot | `period=20` | `ZScore(prices, period=20)` |
| **Percentile Rank** | Percentage of values below a given value. | `Percentile = (Number of Values Below X / Total Values) * 100` | Assess relative performance. | Line chart | `period=100` | `PercentileRank(prices, period=100)` |
| **Sharpe Ratio** | Risk-adjusted return. | `Sharpe = (Rp - Rf) / σp` where `Rp` = portfolio return, `Rf` = risk-free rate, `σp` = standard deviation of returns | Assess risk-adjusted performance (Sharpe > 1 = Good). | Bar chart | `risk_free_rate=0.02` | `SharpeRatio(returns, risk_free_rate=0.02)` |
| **Sortino Ratio** | Risk-adjusted return (downside deviation). | `Sortino = (Rp - Rf) / σd` where `σd` = downside deviation | Assess risk-adjusted performance (focus on downside risk). | Bar chart | `risk_free_rate=0.02` | `SortinoRatio(returns, risk_free_rate=0.02)` |
| **Correlation** | Relationship between two instruments. | `Corr(X,Y) = Cov(X,Y) / (σX * σY)` | Identify related instruments. | Heatmap | `pair` (e.g., "AAPL,MSFT") | `Correlation(returns_x, returns_y)` |
| **Beta (vs. Benchmark)** | Volatility relative to benchmark. | `β = Cov(Ri, Rm) / Var(Rm)` where `Ri` = instrument returns, `Rm` = market returns | Assess market risk. | Single value | `benchmark` (e.g., "SPY") | `Beta(instrument_returns, market_returns)` |
| **Alpha** | Excess return relative to benchmark. | `α = Rp - (Rf + β * (Rm - Rf))` where `Rp` = portfolio return, `Rm` = market return | Measure outperformance. | Single value | `benchmark` (e.g., "SPY"), `risk_free_rate=0.02` | `Alpha(instrument_returns, market_returns, risk_free_rate=0.02)` |
| **R-Squared** | Explains how much of the variance is explained by the benchmark. | `R² = 1 - (SS_res / SS_tot)` where `SS_res` = residual sum of squares, `SS_tot` = total sum of squares | Measure how closely instrument follows benchmark (R² > 0.8 = Strong fit). | Single value | `benchmark` (e.g., "SPY") | `RSquared(instrument_returns, market_returns)` |
| **Value at Risk (VaR)** | Maximum loss over a period with a given confidence level. | `VaR = μ - (σ * Z)` where `μ` = mean return, `σ` = standard deviation, `Z` = Z-score for confidence level | Assess worst-case loss. | Single value | `confidence=0.95`, `period=1` | `VaR(returns, confidence=0.95)` |
| **Conditional VaR (CVaR)** | Expected loss beyond VaR. | `CVaR = Average of returns < VaR` | Assess tail risk. | Single value | `confidence=0.95` | `CVaR(returns, confidence=0.95)` |

---

### 📌 Statistical Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Outperformance** | Sharpe Ratio, Alpha, R-Squared | Sharpe > 1, Alpha > 0, R² < 0.8 |
| **Risk Assessment** | VaR, CVaR, Beta | VaR(95%) = -5%, CVaR(95%) = -7% |
| **Diversification** | Correlation | Low correlation (e.g., < 0.3) = Good diversification |
| **Benchmark Comparison** | Beta, Alpha, R-Squared | Beta = 1.2, Alpha = 2%, R² = 0.9 |
| **Extreme Events** | Z-Score, Percentile Rank | Z > 2 or Z < -2 = Outlier |

---

## 🔹 Group 7: Pattern Metrics
**Purpose**: Detect chart patterns for technical analysis.

| Metric | Definition | Detection Method | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|-------------------|----------|---------------|-------------|------------|
| **Head & Shoulders** | Reversal pattern with 3 peaks (higher high in the middle). | Identify higher high (head) between two lower highs (shoulders) with similar price levels. | Predict bearish reversal. | Price chart overlay | `lookback=50`, `tolerance=2%` | `HeadAndShoulders(highs, lows, lookback=50, tolerance=0.02)` |
| **Inverse Head & Shoulders** | Reversal pattern with 3 troughs (lower low in the middle). | Identify lower low (head) between two higher lows (shoulders) with similar price levels. | Predict bullish reversal. | Price chart overlay | `lookback=50`, `tolerance=2%` | `InverseHeadAndShoulders(lows, highs, lookback=50, tolerance=0.02)` |
| **Double Top** | Reversal pattern with 2 peaks at similar price level. | Identify two peaks at similar price level (±tolerance) with a trough in between. | Predict bearish reversal. | Price chart overlay | `lookback=30`, `tolerance=2%` | `DoubleTop(highs, lookback=30, tolerance=0.02)` |
| **Double Bottom** | Reversal pattern with 2 troughs at similar price level. | Identify two troughs at similar price level (±tolerance) with a peak in between. | Predict bullish reversal. | Price chart overlay | `lookback=30`, `tolerance=2%` | `DoubleBottom(lows, lookback=30, tolerance=0.02)` |
| **Triple Top** | Reversal pattern with 3 peaks at similar price level. | Identify three peaks at similar price level (±tolerance). | Predict bearish reversal. | Price chart overlay | `lookback=40`, `tolerance=2%` | `TripleTop(highs, lookback=40, tolerance=0.02)` |
| **Triple Bottom** | Reversal pattern with 3 troughs at similar price level. | Identify three troughs at similar price level (±tolerance). | Predict bullish reversal. | Price chart overlay | `lookback=40`, `tolerance=2%` | `TripleBottom(lows, lookback=40, tolerance=0.02)` |
| **Support Level** | Price level where buying interest emerges. | Identify price bounces at a specific level (±tolerance) at least `min_touches` times. | Identify entry points. | Horizontal line | `lookback=50`, `tolerance=1%`, `min_touches=2` | `SupportLevel(lows, lookback=50, tolerance=0.01, min_touches=2)` |
| **Resistance Level** | Price level where selling interest emerges. | Identify price rejections at a specific level (±tolerance) at least `min_touches` times. | Identify exit points. | Horizontal line | `lookback=50`, `tolerance=1%`, `min_touches=2` | `ResistanceLevel(highs, lookback=50, tolerance=0.01, min_touches=2)` |
| **Trendline** | Line connecting price extremes. | Linear regression or manual drawing (connect at least `min_points` extremes). | Identify trend direction. | Line overlay | `min_points=2` | `Trendline(prices, min_points=2)` |
| **Channel** | Parallel trendlines connecting price extremes. | Identify two parallel trendlines (upper and lower) with at least `min_touches` each. | Identify trading range. | Band chart | `min_points=2`, `min_touches=2` | `Channel(highs, lows, min_points=2, min_touches=2)` |
| **Gap** | Price gap between two periods. | Identify `gap_pct` > `min_gap` between `Close_prev` and `Open_current`. | Identify breakaway or exhaustion gaps. | Price chart overlay | `min_gap=2%` | `Gap(opens, closes, min_gap=0.02)` |

---

### 📌 Pattern Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Bearish Reversal** | Head & Shoulders, Double Top, Shooting Star | Pattern confirmed = Sell signal |
| **Bullish Reversal** | Inverse Head & Shoulders, Double Bottom, Hammer | Pattern confirmed = Buy signal |
| **Breakout** | Support/Resistance, Channel | Price breaks above resistance = Bullish breakout |
| **Trend Continuation** | Trendline, Channel | Price bounces off trendline = Trend continues |
| **Exhaustion Gap** | Gap | Gap after strong move = Trend reversal |

---

## 🔹 Group 8: Custom/Composite Metrics
**Purpose**: User-defined or composite metrics that combine multiple signals.

| Metric | Definition | Formula | Use Case | Visualization | Parameters | Pseudocode |
|--------|------------|---------|----------|---------------|-------------|------------|
| **Golden Cross** | Bullish signal when short-term MA crosses above long-term MA. | `SMA(short) > SMA(long)` and `SMA(short)_prev < SMA(long)_prev` | Predict bullish trend. | Price chart overlay | `short_period=50`, `long_period=200` | `GoldenCross(prices, short=50, long=200)` |
| **Death Cross** | Bearish signal when short-term MA crosses below long-term MA. | `SMA(short) < SMA(long)` and `SMA(short)_prev > SMA(long)_prev` | Predict bearish trend. | Price chart overlay | `short_period=50`, `long_period=200` | `DeathCross(prices, short=50, long=200)` |
| **Bullish Engulfing** | Reversal pattern: Small bearish candle followed by large bullish candle. | `Close > Open` and `Close > Prior Open` and `Open < Prior Close` and `Body > Prior Body` | Predict bullish reversal. | Candlestick chart | `body_multiplier=1.5` | `BullishEngulfing(opens, highs, lows, closes, body_multiplier=1.5)` |
| **Bearish Engulfing** | Reversal pattern: Small bullish candle followed by large bearish candle. | `Close < Open` and `Close < Prior Open` and `Open > Prior Close` and `Body > Prior Body` | Predict bearish reversal. | Candlestick chart | `body_multiplier=1.5` | `BearishEngulfing(opens, highs, lows, closes, body_multiplier=1.5)` |
| **Hammer** | Reversal pattern: Small body, long lower wick, little/no upper wick. | `Body < Wick` and `Close > Open` and `(Close - Low) > 2 * (High - Close)` | Predict bullish reversal. | Candlestick chart | `body_ratio=0.3`, `wick_ratio=2` | `Hammer(opens, highs, lows, closes, body_ratio=0.3, wick_ratio=2)` |
| **Shooting Star** | Reversal pattern: Small body, long upper wick, little/no lower wick. | `Body < Wick` and `Close < Open` and `(High - Open) > 2 * (Close - Low)` | Predict bearish reversal. | Candlestick chart | `body_ratio=0.3`, `wick_ratio=2` | `ShootingStar(opens, highs, lows, closes, body_ratio=0.3, wick_ratio=2)` |
| **Morning Star** | Reversal pattern: 3 candles (large bearish, small body, large bullish). | `Close1 < Open1` and `\|Close2 - Open2\| < (High1 - Low1) * 0.5` and `Close3 > Open3` and `Close3 > Close1` | Predict bullish reversal. | Candlestick chart | None | `MorningStar(opens, highs, lows, closes)` |
| **Evening Star** | Reversal pattern: 3 candles (large bullish, small body, large bearish). | `Close1 > Open1` and `\|Close2 - Open2\| < (High1 - Low1) * 0.5` and `Close3 < Open3` and `Close3 < Close1` | Predict bearish reversal. | Candlestick chart | None | `EveningStar(opens, highs, lows, closes)` |
| **Three White Soldiers** | Continuation pattern: 3 consecutive bullish candles. | `Close1 > Open1` and `Close2 > Open2` and `Close3 > Open3` and `Close1 < Close2 < Close3` | Predict bullish continuation. | Candlestick chart | None | `ThreeWhiteSoldiers(opens, closes)` |
| **Three Black Crows** | Continuation pattern: 3 consecutive bearish candles. | `Close1 < Open1` and `Close2 < Open2` and `Close3 < Open3` and `Close1 > Close2 > Close3` | Predict bearish continuation. | Candlestick chart | None | `ThreeBlackCrows(opens, closes)` |

---

### 📌 Custom/Composite Metrics Use Cases

| Scenario | Recommended Metrics | Interpretation |
|----------|--------------------|----------------|
| **Strong Bullish Signal** | Golden Cross, Bullish Engulfing, Morning Star | Multiple confirmations = Strong buy signal |
| **Strong Bearish Signal** | Death Cross, Bearish Engulfing, Evening Star | Multiple confirmations = Strong sell signal |
| **Trend Confirmation** | Three White Soldiers, Three Black Crows | Continuation of current trend |
| **Reversal Confirmation** | Hammer, Shooting Star, Morning/Evening Star | Trend likely to reverse |

---

## 📈 Metric Group Summary Table

| Group | Count | Key Use Cases | Recommended Timeframes |
|-------|-------|---------------|------------------------|
| **Trend** | 10 | Trend following, support/resistance | 1D, 1W, 1M |
| **Momentum** | 8 | Overbought/oversold, divergences | 1D, 1W |
| **Volatility** | 8 | Risk assessment, stop-loss placement | 1D, 1W, 1M |
| **Volume** | 8 | Trend confirmation, breakouts | 1D |
| **Fundamental** | 14 | Valuation, profitability | Quarterly, Annual |
| **Statistical** | 10 | Performance analysis, risk | 1D, 1W, 1M |
| **Pattern** | 12 | Reversal/continuation signals | 1D, 1W |
| **Custom** | 10 | Composite signals | 1D |
| **Total** | **80+** | - | - |

---

## 🎨 Visualization Recommendations

### By Metric Group

| Group | Recommended Chart Types | Example |
|-------|-------------------------|---------|
| **Trend** | Line chart, Band chart | SMA overlay on price chart |
| **Momentum** | Line chart, Histogram | RSI below price chart |
| **Volatility** | Line chart, Band chart | ATR below price chart |
| **Volume** | Bar chart, Line chart | Volume bars with OBV overlay |
| **Fundamental** | Bar chart, Table | P/E ratio vs. peers |
| **Statistical** | Scatter plot, Heatmap, Bar chart | Correlation heatmap |
| **Pattern** | Price chart overlay | Head & Shoulders pattern |
| **Custom** | Candlestick chart, Price chart overlay | Golden Cross |

---

### Example Dashboard Layouts

#### 1. **Instrument Overview Dashboard**
```
┌───────────────────────────────────────────────────────┐
│  [Instrument Name] (Type: Stock/ETF/...)                │
│  Price: $XXX | Change: +X% | Volume: XM                        │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌─────────────────────┐  │
│  │  Price Chart             │  │  Fundamentals        │  │
│  │  • OHLC Candlesticks     │  │  • P/E: X            │  │
│  │  • SMA(20, 50, 200)      │  │  • Market Cap: $X    │  │
│  │  • Bollinger Bands       │  │  • Dividend Yield: X%│  │
│  │  • Volume Bars           │  │  • ROE: X%           │  │
│  └─────────────────────────┘  └─────────────────────┘  │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌─────────────────────┐  │
│  │  Momentum                │  │  Volatility          │  │
│  │  • RSI(14)               │  │  • ATR(14)           │  │
│  │  • MACD                  │  │  • Beta: X           │  │
│  │  • Stochastic Oscillator │  │  • Historical Vol    │  │
│  └─────────────────────────┘  └─────────────────────┘  │
├───────────────────────────────────────────────────────┤
│  [Correlated Articles] (Linked via hybrid correlation)   │
└───────────────────────────────────────────────────────┘
```

#### 2. **Metric Explorer Dashboard**
```
┌───────────────────────────────────────────────────────┐
│  Metric Explorer                                           │
├───────────────────────────────────────────────────────┤
│  Group: [Trend ▼]  Metric: [SMA ▼]  Timeframe: [1D ▼]     │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐  │
│  │  Definition: Smooths price data to identify trends. │  │
│  │  Formula: SMA = (P1 + P2 + ... + Pn) / n              │  │
│  │  Use Case: Identify trend direction, support/resistance│  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌─────────────────────┐  │
│  │  Chart                  │  │  Parameters          │  │
│  │  [Interactive Chart]    │  │  • Period: [20 ▼]    │  │
│  │  • Line: SMA(20)        │  │  • Color: [Blue ▼]   │  │
│  │  • Line: SMA(50)        │  │  • Style: [Solid ▼] │  │
│  │  • Line: Price          │  └─────────────────────┘  │
│  └─────────────────────────┘                              │
├───────────────────────────────────────────────────────┤
│  [Add to Dashboard] [Compare Metrics] [Export Data]      │
└───────────────────────────────────────────────────────┘
```

#### 3. **Correlation View Dashboard**
```
┌───────────────────────────────────────────────────────┐
│  Correlation View: [Article Title]                        │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────────────────────────────┐  │
│  │  Article Text:                                       │  │
│  │  "Apple Inc. announced a new iPhone with AI..."    │  │
│  └─────────────────────────────────────────────────┘  │
├───────────────────────────────────────────────────────┤
│  Matched Keywords: [apple, iphone, ai, announced]         │
│  Matched Sector: Technology                              │
├───────────────────────────────────────────────────────┤
│  ┌─────────────────────────┐  ┌─────────────────────┐  │
│  │  Linked Instruments      │  │  Timeline             │  │
│  │  1. AAPL (Apple)         │  │  [Article]────[AAPL]  │  │
│  │     • Score: 0.95        │  │    10:00 AM    11:00  │  │
│  │     • Type: Mention      │  │                     AM │  │
│  │  2. MSFT (Microsoft)     │  │  [AAPL +5%]           │  │
│  │     • Score: 0.60        │  │    11:30 AM           │  │
│  │     • Type: Keyword      │  │                     │  │
│  │  3. GOOGL (Alphabet)     │  │                     │  │
│  │     • Score: 0.50        │  │                     │  │
│  │     • Type: Sector       │  │                     │  │
│  └─────────────────────────┘  └─────────────────────┘  │
└───────────────────────────────────────────────────────┘
```

---

## 🔧 Implementation Notes

### Metric Calculation Engine

The `MetricCalculator` class will:

1. **Fetch Data**: Retrieve OHLC/volume data for the instrument from `financial_data_points`.
2. **Validate Inputs**: Ensure sufficient data points are available for the metric’s `period`.
3. **Compute Metric**: Use the formula defined in the catalog.
4. **Store Result**: Save to `financial_metrics` with:
   - `instrument_id`, `metric_name`, `metric_group`, `metric_value`.
   - `timeframe`, `timestamp`, `calculation_method`, `parameters`.
   - `source` (e.g., "yahoo_finance"), `is_real_time`, `confidence`.
5. **Handle Errors**: Log failures and skip invalid calculations.

### Example Implementation (Pseudocode)

```python
class MetricCalculator:
    def __init__(self, session):
        self.session = session  # SQLAlchemy session
        self.metrics = {
            "sma": self._calculate_sma,
            "ema": self._calculate_ema,
            "rsi": self._calculate_rsi,
            # ... all other metrics
        }
    
    def calculate_all(self, instrument_id, timeframe="1D"):
        """Calculate all metrics for an instrument."""
        # Fetch OHLC data
        data_points = self.session.query(FinancialDataPoint).filter_by(
            instrument_id=instrument_id
        ).order_by(FinancialDataPoint.timestamp).all()
        
        if not data_points:
            return []
        
        # Extract prices, volumes, etc.
        closes = [dp.close for dp in data_points]
        highs = [dp.high for dp in data_points]
        lows = [dp.low for dp in data_points]
        volumes = [dp.volume for dp in data_points]
        timestamps = [dp.timestamp for dp in data_points]
        
        results = []
        for metric_name, metric_func in self.metrics.items():
            try:
                metric_value = metric_func(closes, highs, lows, volumes, timestamps)
                if metric_value is not None:
                    results.append({
                        "instrument_id": instrument_id,
                        "metric_name": metric_name,
                        "metric_group": self._get_group(metric_name),
                        "metric_value": metric_value,
                        "timeframe": timeframe,
                        "timestamp": timestamps[-1],
                        "calculation_method": self._get_method(metric_name),
                        "parameters": self._get_parameters(metric_name),
                        "source": "open_omniscience",
                        "is_real_time": False,
                        "confidence": 1.0,
                    })
            except Exception as e:
                log_error(f"Failed to calculate {metric_name}: {e}")
        
        return results
    
    def _calculate_sma(self, closes, **kwargs):
        period = kwargs.get("period", 20)
        if len(closes) < period:
            return None
        return sum(closes[-period:]) / period
    
    def _calculate_rsi(self, closes, **kwargs):
        period = kwargs.get("period", 14)
        if len(closes) < period + 1:
            return None
        gains = []
        losses = []
        for i in range(1, len(closes)):
            change = closes[i] - closes[i-1]
            if change > 0:
                gains.append(change)
                losses.append(0)
            else:
                gains.append(0)
                losses.append(abs(change))
        avg_gain = sum(gains[-period:]) / period
        avg_loss = sum(losses[-period:]) / period
        rs = avg_gain / avg_loss if avg_loss != 0 else 0
        return 100 - (100 / (1 + rs))
    
    def _get_group(self, metric_name):
        groups = {
            "sma": "Trend",
            "ema": "Trend",
            "rsi": "Momentum",
            # ... all other mappings
        }
        return groups.get(metric_name, "Unknown")
    
    def _get_method(self, metric_name):
        methods = {
            "sma": "Simple Moving Average",
            "ema": "Exponential Moving Average",
            "rsi": "Relative Strength Index",
            # ... all other mappings
        }
        return methods.get(metric_name, metric_name)
    
    def _get_parameters(self, metric_name):
        params = {
            "sma": {"period": 20},
            "ema": {"period": 12},
            "rsi": {"period": 14},
            # ... all other mappings
        }
        return params.get(metric_name, {})
```

---

### Scheduling Metric Updates

- **Daily**: Compute all **Trend, Momentum, Volatility, Volume, and Statistical** metrics for all instruments.
- **Weekly**: Compute **Fundamental** metrics (updated less frequently).
- **On-Demand**: Allow users to trigger metric calculation for specific instruments via API.
- **Incremental**: Only recompute metrics for instruments with **new data points** since the last calculation.

---

## 📚 References

1. **Technical Analysis Books**:
   - *Technical Analysis of the Financial Markets* by John J. Murphy
   - *Trading in the Zone* by Mark Douglas
   - *The Definitive Guide to Point and Figure* by Jeremy du Plessis

2. **Online Resources**:
   - [Investopedia Technical Indicators](https://www.investopedia.com/technical-indicators-4689638)
   - [StockCharts Technical Indicators](https://school.stockcharts.com/doku.php?id=technical_indicators)
   - [TA-Lib Documentation](https://github.com/mrjbq7/ta-lib)

3. **Libraries**:
   - [pandas-ta](https://github.com/twopirllc/pandas-ta) (Python)
   - [TA-Lib](https://github.com/mrjbq7/ta-lib) (C/Python)
   - [scipy.stats](https://docs.scipy.org/doc/scipy/reference/stats.html) (Statistical functions)

---

## 📜 License

This document and the associated code are licensed under the **GNU GPLv3 License**. See the [LICENSE](../../../LICENSE) file for details.

---

*© 2026 Ideotion. All rights reserved.*
*Built with ❤️ for investigative journalism and ethical financial analysis.*
