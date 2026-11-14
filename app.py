import streamlit as st
import streamlit_autorefresh
import yfinance as yf
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
from dataclasses import dataclass, asdict
from datetime import datetime, timezone

st.set_page_config(page_title="Autonomous AI Paper Trading Lab", page_icon="🧪", layout="wide")
st.title("🧪 Autonomous AI Paper Trading Lab")
st.caption("Research simulator only • Virtual money only • No brokerage connection or real orders")

@dataclass
class Agent:
    name: str
    generation: int
    fast: int
    slow: int
    momentum: int
    buy_threshold: float
    sell_threshold: float
    cash: float = 100.0
    shares: float = 0.0
    peak: float = 100.0
    max_drawdown: float = 0.0
    trades: int = 0

    def equity(self, price):
        return self.cash + self.shares * price

def create_agents(count, cash_each, seed=17):
    rng = np.random.default_rng(seed)
    agents = []
    for i in range(count):
        fast = int(rng.integers(4, 13))
        slow = int(rng.integers(max(fast + 5, 18), 45))
        agents.append(Agent(
            name=f"Agent {i+1:02d}", generation=0,
            fast=fast, slow=slow, momentum=int(rng.integers(3, 15)),
            buy_threshold=float(rng.uniform(0.001, 0.015)),
            sell_threshold=float(rng.uniform(-0.015, -0.001)),
            cash=float(cash_each), peak=float(cash_each)
        ))
    return agents

def signal(prices, i, a):
    start_fast = max(0, i - a.fast + 1)
    start_slow = max(0, i - a.slow + 1)
    fast = float(np.mean(prices[start_fast:i+1]))
    slow = float(np.mean(prices[start_slow:i+1]))
    mom_idx = max(0, i - a.momentum)
    momentum = prices[i] / prices[mom_idx] - 1.0 if prices[mom_idx] else 0.0
    trend = fast / slow - 1.0 if slow else 0.0
    return 0.65 * trend + 0.35 * momentum

def score(a, price, starting_cash):
    ret = (a.equity(price) / starting_cash - 1.0) * 100
    return ret - 0.65 * abs(a.max_drawdown)

def mutate(parent, name, generation, cash, shares, peak, drawdown, trades, rng):
    fast = int(np.clip(parent.fast + rng.integers(-2, 3), 3, 20))
    slow = int(np.clip(parent.slow + rng.integers(-4, 5), fast + 5, 60))
    return Agent(
        name=name, generation=generation, fast=fast, slow=slow,
        momentum=int(np.clip(parent.momentum + rng.integers(-2, 3), 2, 25)),
        buy_threshold=float(np.clip(parent.buy_threshold + rng.normal(0, 0.002), 0.0005, 0.04)),
        sell_threshold=float(np.clip(parent.sell_threshold + rng.normal(0, 0.002), -0.04, -0.0005)),
        cash=cash, shares=shares, peak=peak, max_drawdown=drawdown, trades=trades
    )

def run_evolution(df, total_capital, count, evolve_every, fee_bps, slippage_bps, seed=2026):
    prices = df["Close"].to_numpy(dtype=float)
    starting_each = total_capital / count
    agents = create_agents(count, starting_each, seed)
    rng = np.random.default_rng(seed + 1)
    fee_rate = (fee_bps + slippage_bps) / 10000.0
    trade_log, evolution_log = [], []
    equity_rows = []
    generation = 0

    for i, price in enumerate(prices):
        for a in agents:
            s = signal(prices, i, a)
            if a.shares <= 1e-12 and s > a.buy_threshold and a.cash > 1:
                spend = a.cash * 0.95
                cost = spend * (1 + fee_rate)
                if cost <= a.cash:
                    qty = spend / price
                    a.cash -= cost
                    a.shares += qty
                    a.trades += 1
                    trade_log.append({"Date": df.iloc[i]["Date"], "Agent": a.name,
                                      "Action": "BUY", "Price": price, "Shares": qty})
            elif a.shares > 1e-12 and s < a.sell_threshold:
                qty = a.shares
                gross = qty * price
                a.cash += gross * (1 - fee_rate)
                a.shares = 0.0
                a.trades += 1
                trade_log.append({"Date": df.iloc[i]["Date"], "Agent": a.name,
                                  "Action": "SELL", "Price": price, "Shares": qty})

            value = a.equity(price)
            a.peak = max(a.peak, value)
            dd = (value / max(a.peak, 1e-9) - 1) * 100
            a.max_drawdown = min(a.max_drawdown, dd)

        equity_rows.append({"Date": df.iloc[i]["Date"], **{a.name: a.equity(price) for a in agents}})

        if i > 0 and (i + 1) % evolve_every == 0 and i < len(prices) - 1:
            ranked = sorted(agents, key=lambda x: score(x, price, starting_each), reverse=True)
            parents = ranked[:max(2, count // 2)]
            generation += 1
            evolution_log.append({
                "Date": df.iloc[i]["Date"], "Generation": generation,
                "Best agent": parents[0].name,
                "Best score": round(score(parents[0], price, starting_each), 3)
            })
            # Each parent's current portfolio is divided between its children,
            # so evolution never duplicates virtual money.
            children = []
            for p_idx, p in enumerate(parents):
                child_count = 2 if len(children) + 2 <= count else 1
                cash_piece = p.cash / child_count
                shares_piece = p.shares / child_count
                peak_piece = max(p.peak / child_count, 1e-9)
                dd = p.max_drawdown
                for _ in range(child_count):
                    child_no = len(children) + 1
                    children.append(mutate(
                        p, f"Agent {child_no:02d}", generation,
                        cash_piece, shares_piece, peak_piece, dd, p.trades, rng
                    ))
                    if len(children) == count:
                        break
                if len(children) == count:
                    break
            agents = children

    final_price = float(prices[-1])
    summary = []
    for a in agents:
        ending = a.equity(final_price)
        ret = (ending / starting_each - 1) * 100
        summary.append({
            "Agent": a.name, "Generation": a.generation,
            "Ending value ($)": ending, "Return (%)": ret,
            "Max drawdown (%)": a.max_drawdown, "Trades": a.trades,
            "Research score": ret - 0.65 * abs(a.max_drawdown),
            "Fast window": a.fast, "Slow window": a.slow,
            "Momentum window": a.momentum
        })
    return pd.DataFrame(summary).sort_values("Research score", ascending=False), pd.DataFrame(trade_log), pd.DataFrame(evolution_log), pd.DataFrame(equity_rows)

@st.cache_data(ttl=60, show_spinner="Loading market prices...")
def load_prices(ticker, period, interval):
    raw = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
    if raw is None or raw.empty:
        raise ValueError("No prices returned by the data provider.")
    raw = raw.reset_index()
    date_col = "Datetime" if "Datetime" in raw.columns else "Date"
    if date_col not in raw.columns:
        date_col = raw.columns[0]
    out = raw[[date_col, "Close"]].rename(columns={date_col: "Date"}).dropna()
    out["Date"] = pd.to_datetime(out["Date"])
    out["Close"] = pd.to_numeric(out["Close"], errors="coerce")
    return out.dropna().sort_values("Date").reset_index(drop=True)

with st.sidebar:
    st.header("Experiment settings")
    ticker = st.selectbox("Market symbol", ["AAPL", "MSFT", "NVDA", "SPY", "AMZN"], index=0)
    period = st.selectbox("History", ["5d", "1mo", "3mo", "6mo", "1y"], index=2)
    interval = st.selectbox("Price interval", ["5m", "15m", "30m", "1h", "1d"], index=1)
    capital = st.number_input("Total virtual capital ($)", min_value=100, max_value=100000, value=1000, step=100)
    agent_count = st.number_input("Starting agents", min_value=4, max_value=30, value=10, step=1)
    evolve_every = st.number_input("Evolution frequency (price bars)", min_value=5, max_value=100, value=20, step=5)
    fee_bps = st.slider("Estimated fee per trade (basis points)", 0, 30, 5)
    slippage_bps = st.slider("Estimated slippage per trade (basis points)", 0, 30, 5)
    st.caption("Dashboard refresh: 5 seconds. Market data cache: 60 seconds.")
    if st.button("Force market-data refresh"):
        load_prices.clear()
        st.rerun()

streamlit_autorefresh.st_autorefresh(interval=5000, key="auto_refresh")

try:
    prices = load_prices(ticker, period, interval)
except Exception as exc:
    st.error(f"Could not load market data: {exc}")
    st.info("Try another ticker or a different time interval. Some providers limit intraday history.")
    st.stop()

if len(prices) < 40:
    st.warning(f"Only {len(prices)} price bars were returned. Choose a longer history.")
    st.stop()

summary, trades, evolution, curves = run_evolution(
    prices, float(capital), int(agent_count), int(evolve_every),
    float(fee_bps), float(slippage_bps)
)

last_price = float(prices.iloc[-1]["Close"])
latest_date = prices.iloc[-1]["Date"]
c1, c2, c3, c4 = st.columns(4)
c1.metric(f"{ticker} latest close", f"${last_price:,.2f}")
c2.metric("Price bars", f"{len(prices):,}")
c3.metric("Top agent return", f"{summary.iloc[0]['Return (%)']:+.2f}%")
c4.metric("Evolution cycles", len(evolution))
st.caption(f"Last price bar: {latest_date}. Dashboard checked at {datetime.now().astimezone().strftime('%Y-%m-%d %H:%M:%S %Z')}.")

st.subheader("Agent leaderboard")
st.dataframe(summary, use_container_width=True, hide_index=True)

left, right = st.columns(2)
with left:
    st.subheader("Market price history")
    st.line_chart(prices.set_index("Date")["Close"].tail(500))
with right:
    st.subheader("Evolution history")
    if evolution.empty:
        st.write("No evolution cycle in this selected data range.")
    else:
        st.dataframe(evolution, use_container_width=True, hide_index=True)

st.subheader("Virtual portfolio values")
curve_cols = [c for c in curves.columns if c != "Date"]
if curve_cols:
    st.line_chart(curves.set_index("Date")[curve_cols].tail(500))

st.subheader("Simulated trade log")
if trades.empty:
    st.write("No simulated trades occurred in this run.")
else:
    st.dataframe(trades.tail(200), use_container_width=True, hide_index=True)

with st.expander("What does the AI actually do?"):
    st.markdown("""
    - Each agent has a different set of simple trading-rule parameters.
    - Agents test those rules against historical market-price bars.
    - Every selected number of bars, stronger agents are retained and their parameters are mutated to create a new generation.
    - Virtual cash and shares are divided among offspring; evolution does not create extra money.
    - This is evolutionary strategy search, not a human-level AI or a guarantee of learning profitable behavior.
    """)

st.warning(
    "Important: this is a historical paper-trading experiment, not live autonomous trading. "
    "Yahoo Finance data can be delayed, incomplete, or unavailable; a 5-second dashboard refresh "
    "does not mean exchange prices update every 5 seconds. The simulator reruns its historical "
    "experiment when the app refreshes. No real orders, broker connection, leverage, or real-money "
    "trading are enabled. Historical results do not predict future performance."
)
