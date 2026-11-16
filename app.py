import os

import pandas as pd
import requests
import streamlit as st
import streamlit_autorefresh

st.set_page_config(
    page_title="Autonomous AI Paper Trading Lab",
    page_icon="🧪",
    layout="wide",
)

st.title("🧪 Autonomous AI Paper Trading Lab")
st.caption(
    "Cloud paper-trading dashboard • Virtual money only • "
    "No brokerage connection or real orders"
)

# The dashboard uses a read-only publishable/anon key.
# Never put the Supabase service-role/secret key in Streamlit.
try:
    SUPABASE_URL = st.secrets.get("SUPABASE_URL", os.getenv("SUPABASE_URL", "")).rstrip("/")
    SUPABASE_KEY = st.secrets.get(
        "SUPABASE_PUBLISHABLE_KEY",
        os.getenv("SUPABASE_PUBLISHABLE_KEY", ""),
    )
except Exception:
    SUPABASE_URL = os.getenv("SUPABASE_URL", "").rstrip("/")
    SUPABASE_KEY = os.getenv("SUPABASE_PUBLISHABLE_KEY", "")

if not SUPABASE_URL or not SUPABASE_KEY:
    st.error("Supabase connection is not configured.")
    st.info(
        "In Streamlit Community Cloud, open the app settings → Secrets and add "
        "SUPABASE_URL and SUPABASE_PUBLISHABLE_KEY. Use the project's URL and "
        "publishable/anon key. Do not use the service-role/secret key here."
    )
    st.stop()

TABLE_URL = f"{SUPABASE_URL}/rest/v1/paper_trading_state"


@st.cache_data(ttl=60, show_spinner="Loading saved simulation...")
def load_saved_state():
    response = requests.get(
        TABLE_URL,
        headers={
            "apikey": SUPABASE_KEY,
            "Authorization": f"Bearer {SUPABASE_KEY}",
        },
        params={"id": "eq.main", "select": "state,updated_at"},
        timeout=20,
    )
    response.raise_for_status()
    rows = response.json()
    return rows[0] if rows else None


if st.button("Refresh saved data"):
    load_saved_state.clear()
    st.rerun()

streamlit_autorefresh.st_autorefresh(interval=60_000, key="cloud_state_refresh")

try:
    record = load_saved_state()
except Exception as exc:
    st.error(f"Could not read the saved simulation: {exc}")
    st.info(
        "Check the Streamlit Secrets values and confirm that the Supabase table "
        "has a SELECT policy for the anon role."
    )
    st.stop()

if record is None:
    st.warning("No saved simulation was found yet. Run the GitHub Actions worker first.")
    st.stop()

state = record.get("state") or {}
agents = state.get("agents", [])
price_history = state.get("prices", [])
trade_log = state.get("trade_log", [])
evolution_log = state.get("evolution_log", [])

if not agents or not price_history:
    st.warning("The saved simulation does not contain enough data to display yet.")
    st.stop()

latest_price = float(price_history[-1]["price"])
ticker = state.get("ticker", "AAPL")

rows = []
for agent in agents:
    value = float(agent.get("cash", 0.0)) + float(agent.get("shares", 0.0)) * latest_price
    starting_value = 100.0  # $1,000 virtual starting capital divided among 10 agents
    return_pct = (value / starting_value - 1.0) * 100.0
    max_drawdown = float(agent.get("max_drawdown", 0.0))
    score = return_pct - 0.65 * abs(max_drawdown)
    rows.append(
        {
            "Agent": agent.get("name", "Unknown"),
            "Generation": int(agent.get("generation", 0)),
            "Portfolio value ($)": value,
            "Return (%)": return_pct,
            "Max drawdown (%)": max_drawdown,
            "Trades": int(agent.get("trades", 0)),
            "Research score": score,
            "Fast window": int(agent.get("fast", 0)),
            "Slow window": int(agent.get("slow", 0)),
            "Momentum window": int(agent.get("momentum", 0)),
        }
    )

leaderboard = pd.DataFrame(rows).sort_values(
    "Research score", ascending=False
).reset_index(drop=True)

prices_df = pd.DataFrame(price_history)
prices_df["time"] = pd.to_datetime(prices_df["time"], errors="coerce")
prices_df["price"] = pd.to_numeric(prices_df["price"], errors="coerce")
prices_df = prices_df.dropna(subset=["time", "price"]).sort_values("time")

top_return = leaderboard.iloc[0]["Return (%)"]
metrics = st.columns(4)
metrics[0].metric(f"{ticker} last processed price", f"${latest_price:,.2f}")
metrics[1].metric("Agents", str(len(agents)))
metrics[2].metric("Evolution cycles", str(state.get("generation", 0)))
metrics[3].metric("Top agent return", f"{top_return:+.2f}%")

st.caption(f"Last saved: {record.get('updated_at', state.get('last_run', 'Not available'))}")
st.caption(f"Last processed market candle: {state.get('last_bar') or 'Not available'}")

st.subheader("Agent leaderboard")
st.dataframe(
    leaderboard.style.format(
        {
            "Portfolio value ($)": "${:,.2f}",
            "Return (%)": "{:+.2f}%",
            "Max drawdown (%)": "{:.2f}%",
            "Research score": "{:.2f}",
        }
    ),
    use_container_width=True,
    hide_index=True,
)

left, right = st.columns(2)
with left:
    st.subheader("Market price history")
    if not prices_df.empty:
        st.line_chart(prices_df.set_index("time")["price"])
with right:
    st.subheader("Evolution history")
    if evolution_log:
        evolution_df = pd.DataFrame(evolution_log)
        st.dataframe(evolution_df.tail(30), use_container_width=True, hide_index=True)
    else:
        st.write("No evolution cycles recorded yet.")

st.subheader("Virtual portfolio values")
st.bar_chart(leaderboard.set_index("Agent")["Portfolio value ($)"])

st.subheader("Simulated trade log")
if trade_log:
    st.dataframe(
        pd.DataFrame(trade_log).tail(200),
        use_container_width=True,
        hide_index=True,
    )
else:
    st.write("No simulated trades have been recorded yet.")

st.caption(
    "The cloud worker checks for completed 15-minute market candles on its schedule. "
    "Updates are periodic, not continuous; market data may be delayed or incomplete."
)
st.warning(
    "Educational paper-trading simulation only. Virtual funds only; no broker connection, "
    "real orders, or real money. Simulation results do not predict future performance."
)
