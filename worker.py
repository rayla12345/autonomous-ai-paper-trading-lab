
import os
import requests
import yfinance as yf
import numpy as np
from datetime import datetime, timezone

# ---------------- CONFIGURATION ----------------

SUPABASE_URL = os.environ["SUPABASE_URL"].rstrip("/")
SUPABASE_KEY = os.environ["SUPABASE_KEY"]

TABLE_URL = f"{SUPABASE_URL}/rest/v1/paper_trading_state"

HEADERS = {
    "apikey": SUPABASE_KEY,
    "Authorization": f"Bearer {SUPABASE_KEY}",
    "Content-Type": "application/json",
    "Prefer": "resolution=merge-duplicates,return=minimal",
}

TICKER = "AAPL"
TOTAL_CAPITAL = 1000.0
AGENT_COUNT = 10
EVOLVE_EVERY = 20
FEE_RATE = 0.001
HISTORY_LIMIT = 300


# ---------------- AGENTS ----------------

def new_agent(i):
    rng = np.random.default_rng(100 + i)
    capital = TOTAL_CAPITAL / AGENT_COUNT

    return {
        "name": f"Agent {i + 1:02d}",
        "generation": 0,
        "fast": int(rng.integers(4, 13)),
        "slow": int(rng.integers(18, 45)),
        "momentum": int(rng.integers(3, 15)),
        "buy_threshold": float(rng.uniform(0.001, 0.015)),
        "sell_threshold": float(rng.uniform(-0.015, -0.001)),
        "cash": capital,
        "shares": 0.0,
        "peak": capital,
        "max_drawdown": 0.0,
        "trades": 0,
    }


def agent_value(agent, price):
    return agent["cash"] + agent["shares"] * price


def score(agent, price):
    starting = TOTAL_CAPITAL / AGENT_COUNT
    result = (agent_value(agent, price) / starting - 1) * 100
    return result - 0.65 * abs(agent["max_drawdown"])


# ---------------- DATABASE ----------------

def load_state():
    response = requests.get(
        TABLE_URL,
        headers=HEADERS,
        params={
            "id": "eq.main",
            "select": "state",
        },
        timeout=30,
    )
    response.raise_for_status()

    rows = response.json()

    if rows:
        state = rows[0]["state"]
        print("Existing simulation loaded.")
        return state

    print("Creating new simulation.")

    return {
        "ticker": TICKER,
        "agents": [new_agent(i) for i in range(AGENT_COUNT)],
        "prices": [],
        "last_bar": None,
        "bars_seen": 0,
        "generation": 0,
        "evolution_log": [],
        "trade_log": [],
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def save_state(state):
    response = requests.post(
        TABLE_URL,
        headers=HEADERS,
        params={"on_conflict": "id"},
        json={
            "id": "main",
            "state": state,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        },
        timeout=30,
    )
    response.raise_for_status()
    print("Simulation saved to Supabase.")


# ---------------- MARKET DATA ----------------

def get_market_data():
    data = yf.Ticker(TICKER).history(
        period="5d",
        interval="15m",
        auto_adjust=True,
    )

    if data.empty:
        raise RuntimeError("No market data received.")

    bars = []

    for timestamp, row in data.iterrows():
        price = float(row["Close"])

        if price > 0 and np.isfinite(price):
            bars.append({
                "time": timestamp.isoformat(),
                "price": price,
            })

    # Avoid processing the newest potentially incomplete candle.
    if len(bars) > 1:
        bars = bars[:-1]

    return bars


# ---------------- STRATEGY ----------------

def strategy_signal(prices, agent):
    fast = agent["fast"]
    slow = agent["slow"]
    momentum = agent["momentum"]

    if len(prices) < max(slow, momentum) + 1:
        return 0.0

    fast_avg = float(np.mean(prices[-fast:]))
    slow_avg = float(np.mean(prices[-slow:]))

    momentum_value = (
        prices[-1] / prices[-1 - momentum] - 1
    )

    trend = fast_avg / slow_avg - 1

    return 0.65 * trend + 0.35 * momentum_value


# ---------------- SIMULATION ----------------

def process_bar(state, bar, history):
    price = bar["price"]

    for agent in state["agents"]:
        signal = strategy_signal(history, agent)

        if agent["shares"] <= 1e-12:
            if signal > agent["buy_threshold"] and agent["cash"] > 1:

                spend = agent["cash"] * 0.95
                cost = spend * (1 + FEE_RATE)

                if cost <= agent["cash"]:
                    quantity = spend / price

                    agent["cash"] -= cost
                    agent["shares"] += quantity
                    agent["trades"] += 1

                    state["trade_log"].append({
                        "time": bar["time"],
                        "agent": agent["name"],
                        "action": "BUY",
                        "price": price,
                    })

        elif signal < agent["sell_threshold"]:
            quantity = agent["shares"]

            agent["cash"] += quantity * price * (1 - FEE_RATE)
            agent["shares"] = 0.0
            agent["trades"] += 1

            state["trade_log"].append({
                "time": bar["time"],
                "agent": agent["name"],
                "action": "SELL",
                "price": price,
            })

        value = agent_value(agent, price)

        agent["peak"] = max(agent["peak"], value)

        drawdown = (
            value / max(agent["peak"], 1e-9) - 1
        ) * 100

        agent["max_drawdown"] = min(
            agent["max_drawdown"],
            drawdown,
        )

    state["bars_seen"] += 1

    if state["bars_seen"] % EVOLVE_EVERY == 0:
        evolve_agents(state, price, bar["time"])


# ---------------- EVOLUTION ----------------

def evolve_agents(state, price, timestamp):
    agents = state["agents"]

    ranked = sorted(
        agents,
        key=lambda agent: score(agent, price),
        reverse=True,
    )

    parents = ranked[:max(2, len(ranked) // 2)]

    # Copy parent parameters before modifying any agents.
    parent_params = [
        {
            "fast": p["fast"],
            "slow": p["slow"],
            "momentum": p["momentum"],
            "buy_threshold": p["buy_threshold"],
            "sell_threshold": p["sell_threshold"],
        }
        for p in parents
    ]

    best_name = ranked[0]["name"]
    best_score = score(ranked[0], price)

    state["generation"] += 1
    rng = np.random.default_rng()

    for index, child in enumerate(agents):
        parent = parent_params[index % len(parent_params)]

        # Only strategy parameters change.
        # Each agent keeps its own virtual portfolio.
        child["fast"] = int(np.clip(
            parent["fast"] + rng.integers(-2, 3),
            3, 20,
        ))

        child["slow"] = int(np.clip(
            parent["slow"] + rng.integers(-4, 5),
            child["fast"] + 5, 60,
        ))

        child["momentum"] = int(np.clip(
            parent["momentum"] + rng.integers(-2, 3),
            2, 25,
        ))

        child["buy_threshold"] = float(np.clip(
            parent["buy_threshold"] + rng.normal(0, 0.002),
            0.0005, 0.04,
        ))

        child["sell_threshold"] = float(np.clip(
            parent["sell_threshold"] + rng.normal(0, 0.002),
            -0.04, -0.0005,
        ))

        child["generation"] = state["generation"]

    state["evolution_log"].append({
        "time": timestamp,
        "generation": state["generation"],
        "best_agent": best_name,
        "best_score": best_score,
    })

    print(f"Evolution cycle {state['generation']} completed.")


# ---------------- MAIN WORKER ----------------

def main():
    print("Starting paper trading worker...")

    state = load_state()

    if state["ticker"] != TICKER:
        raise RuntimeError(
            "Ticker configuration differs from saved simulation."
        )

    print("Downloading market data...")

    new_bars = get_market_data()

    combined = {
        bar["time"]: bar
        for bar in state["prices"]
    }

    for bar in new_bars:
        combined[bar["time"]] = bar

    all_bars = sorted(
        combined.values(),
        key=lambda bar: bar["time"],
    )

    if state["last_bar"] is None:
        history = []
        bars_to_process = all_bars
    else:
        history = [
            bar["price"]
            for bar in all_bars
            if bar["time"] <= state["last_bar"]
        ]

        bars_to_process = [
            bar
            for bar in all_bars
            if bar["time"] > state["last_bar"]
        ]

    if not bars_to_process:
        print("No new completed market candles.")
        return

    print(f"Processing {len(bars_to_process)} new candles.")

    for bar in bars_to_process:
        history.append(bar["price"])

        process_bar(
            state,
            bar,
            history,
        )

        state["last_bar"] = bar["time"]

    state["prices"] = all_bars[-HISTORY_LIMIT:]
    state["last_run"] = datetime.now(timezone.utc).isoformat()

    save_state(state)

    latest_price = bars_to_process[-1]["price"]

    ranked = sorted(
        state["agents"],
        key=lambda agent: score(agent, latest_price),
        reverse=True,
    )

    print("\nSIMULATION RESULTS")
    print("------------------")
    print(f"Ticker: {TICKER}")
    print(f"Latest processed price: {latest_price:.2f}")
    print(f"Evolution cycles: {state['generation']}")

    for agent in ranked[:3]:
        print(
            f"{agent['name']} | "
            f"Value: ${agent_value(agent, latest_price):.2f} | "
            f"Score: {score(agent, latest_price):.2f}"
        )

    print("\nWorker completed successfully.")


if __name__ == "__main__":
    main()
