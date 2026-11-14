# Autonomous AI Paper Trading Lab

A beginner-friendly, browser-based research simulator that combines actual historical market-price data with 10 evolving paper-trading agents.

## What is included
- $1,000 default virtual capital, split across 10 agents.
- Selectable symbols: AAPL, MSFT, NVDA, SPY, AMZN.
- Historical market data retrieved through Yahoo Finance (`yfinance`).
- Evolutionary strategy search: agents are ranked and their strategy parameters are mutated every 20 price bars by default.
- Dashboard with market prices, agent leaderboard, portfolio curves, evolution history, and simulated trade log.
- Estimated trading fees and slippage.

## Important limitations
- This is a paper-trading research project only. It has no brokerage integration and cannot place real orders.
- Yahoo Finance data is not an exchange-certified real-time feed. It may be delayed or incomplete.
- The dashboard refreshes every 5 seconds, while downloaded price data is cached for 60 seconds. A screen refresh does not mean a new market quote arrives every 5 seconds.
- The experiment is rerun over the selected historical price window on refresh. It is not yet a continuously running agent process with durable learning across sessions.
- The agents use simple technical-rule parameters and evolutionary search. This is not a predictive oracle and can overfit historical data.
- Historical simulation results do not predict future results.

## Run on a computer
1. Install Python 3.10 or newer.
2. Unzip this folder.
3. Open a terminal in the unzipped folder.
4. Install dependencies:
   `python -m pip install -r requirements.txt`
5. Start the dashboard:
   `streamlit run app.py`
6. Open the local web address printed by Streamlit.

## iPad note
The app is a Python/Streamlit project and is not a native iPad app. To use it from an iPad, run it on a computer or supported cloud Python host, then open the dashboard link in Safari. Do not enter brokerage passwords or API secrets into this demo.
