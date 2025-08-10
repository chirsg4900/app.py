# app.py
import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import time
import io
from datetime import datetime, timedelta

st.set_page_config(layout="wide", page_title="Equities Screener")

# -------------------------
# Helper functions
# -------------------------
@st.cache_data(show_spinner=False)
def load_sp500_tickers():
    url = 'https://en.wikipedia.org/wiki/List_of_S%26P_500_companies'
    tables = pd.read_html(url)
    return sorted(tables[0]['Symbol'].tolist())

@st.cache_data(show_spinner=False)
def load_nasdaq100_tickers():
    url = 'https://en.wikipedia.org/wiki/Nasdaq-100'
    tables = pd.read_html(url)
    # Try to find the table with tickers
    for t in tables:
        if 'Ticker' in t.columns or 'Symbol' in t.columns:
            if 'Ticker' in t.columns:
                return sorted(t['Ticker'].tolist())
            elif 'Symbol' in t.columns:
                return sorted(t['Symbol'].tolist())
    return []

def safe_get(d, key):
    return d.get(key) if d and key in d else None

@st.cache_data(show_spinner=False)
def fetch_fundamentals(tickers):
    """Fetch fundamentals/info for list of tickers using yfinance."""
    rows = []
    total = len(tickers)
    for i, t in enumerate(tickers):
        # small progress published by caller; do not st.write here in cached func
        try:
            tk = yf.Ticker(t)
            info = tk.info or {}
            row = {
                "Ticker": t,
                "Long Name": safe_get(info, 'longName'),
                "Price": safe_get(info, 'currentPrice') or safe_get(info, 'previousClose'),
                "Market Cap": safe_get(info, 'marketCap'),
                "Sector": safe_get(info, 'sector'),
                "Industry": safe_get(info, 'industry'),
                "Trailing P/E": safe_get(info, 'trailingPE'),
                "Forward P/E": safe_get(info, 'forwardPE'),
                "EPS (TTM)": safe_get(info, 'trailingEps'),
                "EBITDA": safe_get(info, 'ebitda'),
                "Revenue (TTM)": safe_get(info, 'totalRevenue'),
                "Gross Margins": safe_get(info, 'grossMargins'),
                "Profit Margins": safe_get(info, 'profitMargins'),
                "Return on Assets": safe_get(info, 'returnOnAssets'),
                "Return on Equity": safe_get(info, 'returnOnEquity'),
                "Debt to Equity": safe_get(info, 'debtToEquity'),
                "Quick Ratio": safe_get(info, 'quickRatio'),
                "Current Ratio": safe_get(info, 'currentRatio'),
                "Price to Book": safe_get(info, 'priceToBook'),
                "Price to Sales": safe_get(info, 'priceToSalesTrailing12Months'),
                "Dividend Yield": safe_get(info, 'dividendYield'),
                "52w High": safe_get(info, 'fiftyTwoWeekHigh'),
                "52w Low": safe_get(info, 'fiftyTwoWeekLow'),
                "Beta": safe_get(info, 'beta'),
                "Average Volume": safe_get(info, 'averageVolume'),
            }
            rows.append(row)
        except Exception:
            rows.append({"Ticker": t})
        # polite pause
        time.sleep(0.12)
    df = pd.DataFrame(rows).set_index('Ticker', drop=False)
    return df

@st.cache_data(show_spinner=False)
def fetch_price_history(tickers, period='1y', interval='1d'):
    """Fetch historical close prices for performance calculation."""
    # yfinance supports batch fetching with yf.download
    try:
        data = yf.download(tickers, period=period, interval=interval, group_by='ticker', threads=True, progress=False)
    except Exception:
        data = None
    return data

def compute_performance(prices_df, ticker):
    """Given a multi-ticker downloaded structure or single series, compute returns."""
    # prices_df can be multiindex columns when multiple tickers; handle both
    try:
        if isinstance(prices_df.columns, pd.MultiIndex):
            series = prices_df[ticker]['Close'].dropna()
        else:
            # single ticker download
            series = prices_df['Close'].dropna() if 'Close' in prices_df.columns else prices_df.dropna()
        if series.empty:
            return {}
        last = series.iloc[-1]
        def pct_return(days):
            if len(series) <= days:
                return np.nan
            past = series.shift(days).iloc[-1]
            return (last - past) / past * 100 if past and past != 0 else np.nan

        # Work with business-day offsets approximations
        # 1D, 5D, 21D (approx 1m), 63D (~3m), YTD, 252D (~1y)
        returns = {
            "Price (Last)": last,
            "1D %": pct_return(1),
            "5D %": pct_return(5),
            "1M % (21bd)": pct_return(21),
            "3M % (63bd)": pct_return(63),
            "YTD %": np.nan,
            "1Y %": pct_return(252)
        }
        # YTD special: compare to price on Jan 1 of current year (or first trading day after)
        today = series.index[-1]
        ystart = datetime(today.year, 1, 1)
        # find first index >= ystart
        try:
            past_idx = series.index.get_indexer_for([x for x in series.index if x >= pd.Timestamp(ystart)])
            if len(past_idx) > 0:
                first_pos = past_idx[0]
                if first_pos is not None and first_pos < len(series):
                    ystart_price = series.iloc[first_pos]
                    returns["YTD %"] = (last - ystart_price) / ystart_price * 100 if ystart_price != 0 else np.nan
        except Exception:
            returns["YTD %"] = np.nan

        return returns
    except Exception:
        return {}

def to_excel_bytes(df):
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine='xlsxwriter') as writer:
        df.to_excel(writer, index=False, sheet_name='Screener')
        writer.close()
    return output.getvalue()

# -------------------------
# App UI
# -------------------------
st.title("Equities Screener — Full Metrics")
st.write("A powerful equities screener: pick a universe, choose filters and toggle columns. Data via Yahoo Finance (yfinance).")

# Universe selection
univ = st.radio("Universe", ('S&P 500', 'Nasdaq 100', 'Custom (paste tickers)'), index=0)

if univ == 'S&P 500':
    tickers = load_sp500_tickers()
elif univ == 'Nasdaq 100':
    tickers = load_nasdaq100_tickers()
else:
    txt = st.text_area("Paste tickers separated by commas or spaces", value="AAPL MSFT GOOGL AMZN")
    # normalize
    tickers = [t.strip().upper().replace('.', '-') for t in txt.replace(',', ' ').split() if t.strip()]

# Sidebar filters
st.sidebar.header("Filters & Options")
max_rows = st.sidebar.slider("Limit number of tickers to fetch (for speed)", 10, 500, 200, step=10)
tickers = tickers[:max_rows]

# Which metrics to fetch: fundamentals + performance toggles
fetch_hist = st.sidebar.checkbox("Fetch price history for performance (slower)", value=True)
period_choice = st.sidebar.selectbox("Price history period for calculations", ['1y', '6mo', '2y'], index=0)

# Column selector
all_columns = [
    "Ticker","Long Name","Sector","Industry","Price (Last)","Price","Market Cap",
    "1D %","5D %","1M % (21bd)","3M % (63bd)","YTD %","1Y %",
    "Trailing P/E","Forward P/E","EPS (TTM)","EBITDA","Revenue (TTM)","Price to Book","Price to Sales",
    "Profit Margins","Gross Margins","Return on Assets","Return on Equity",
    "Debt to Equity","Quick Ratio","Current Ratio","Dividend Yield","52w High","52w Low","Beta","Average Volume"
]

default_cols = ["Ticker","Long Name","Price (Last)","Market Cap","1Y %","Trailing P/E","EPS (TTM)","Dividend Yield","Debt to Equity","Profit Margins"]
visible_cols = st.multiselect("Columns to display", options=all_columns, default=default_cols)

# Filtering widgets (example filters)
st.sidebar.subheader("Quick filters")
min_mktcap = st.sidebar.number_input("Min Market Cap (billion USD)", min_value=0.0, value=1.0)
max_pe = st.sidebar.number_input("Max Trailing P/E (set 0 for no limit)", min_value=0.0, value=0.0)
min_div_yield = st.sidebar.number_input("Min Dividend Yield (%)", min_value=0.0, value=0.0)
min_profit_margin = st.sidebar.number_input("Min Profit Margin (%)", value=-100.0)
max_debt_equity = st.sidebar.number_input("Max Debt/Equity", value=10.0)

# Start button
if st.button("Run screener"):
    status = st.empty()
    status.info(f"Fetching fundamentals for {len(tickers)} tickers...")
    fundamentals = fetch_fundamentals(tickers)  # cached function

    # convert certain fields: many returned as decimal -> convert to %
    for col in ['Dividend Yield','Profit Margins','Gross Margins','Return on Assets','Return on Equity']:
        if col in fundamentals.columns:
            fundamentals[col] = fundamentals[col].apply(lambda x: x*100 if pd.notnull(x) else x)

    perf_rows = []
    if fetch_hist:
        status.info("Fetching historical prices (this will take longer)...")
        # fetch in batches of up to 50 tickers to avoid giant requests
        batch_size = 50
        price_hist = {}
        for i in range(0, len(tickers), batch_size):
            batch = tickers[i:i+batch_size]
            status.info(f"Downloading price history for tickers {i+1}-{min(i+batch_size, len(tickers))}...")
            hist = fetch_price_history(batch, period=period_choice, interval='1d')
            price_hist.update({t: hist for t in batch})  # store reference; compute later
            time.sleep(0.5)
    else:
        price_hist = None

    # compute performance per ticker
    merged_rows = []
    pb = st.progress(0)
    for idx, t in enumerate(tickers):
        pb.progress(int((idx+1)/len(tickers)*100))
        row = {}
        fund_row = fundamentals.loc[t].to_dict() if t in fundamentals.index else {}
        row.update(fund_row)
        # calculate performance
        perf = {}
        if fetch_hist:
            try:
                hist = yf.download(t, period=period_choice, interval='1d', progress=False)
                perf = compute_performance(hist, t)
                # sometimes compute_performance returns Price (Last) key
                if "Price (Last)" in perf and (not row.get("Price") or pd.isna(row.get("Price"))):
                    row["Price"] = perf.get("Price (Last)")
            except Exception:
                perf = {}
            time.sleep(0.12)
        # merge perf into row
        row.update({k:perf.get(k) for k in ["Price (Last)","1D %","5D %","1M % (21bd)","3M % (63bd)","YTD %","1Y %"]})
        merged_rows.append(row)

    # Final DataFrame
    df = pd.DataFrame(merged_rows).set_index('Ticker', drop=False)

    # Ensure numeric types where possible
    numeric_cols = ["Price","Market Cap","1D %","5D %","1M % (21bd)","3M % (63bd)","YTD %","1Y %",
                    "Trailing P/E","Forward P/E","EPS (TTM)","EBITDA","Revenue (TTM)",
                    "Price to Book","Price to Sales","Profit Margins","Gross Margins",
                    "Return on Assets","Return on Equity","Debt to Equity","Quick Ratio",
                    "Current Ratio","Dividend Yield","52w High","52w Low","Beta","Average Volume"]
    for c in numeric_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors='coerce')

    # Apply quick filters
    mask = pd.Series(True, index=df.index)
    mask &= df['Market Cap'].fillna(0) >= (min_mktcap * 1e9)
    if max_pe > 0:
        mask &= df['Trailing P/E'].fillna(np.inf) <= max_pe
    if min_div_yield > 0:
        mask &= df['Dividend Yield'].fillna(0) >= min_div_yield
    mask &= df['Profit Margins'].fillna(-9999) >= min_profit_margin
    mask &= df['Debt to Equity'].fillna(np.inf) <= max_debt_equity

    filtered = df[mask].copy()

    # Reorder columns according to visible_cols
    # If user selected Price (Last) but we have "Price" keep both
    final_cols = [c for c in visible_cols if c in filtered.columns]
    # always include Ticker first
    if "Ticker" not in final_cols:
        final_cols.insert(0, "Ticker")
    filtered_display = filtered.reset_index(drop=True)[final_cols]

    st.write(f"Found {len(filtered_display)} results after filters.")
    st.dataframe(filtered_display, use_container_width=True)

    # Download buttons
    csv = filtered_display.to_csv(index=False).encode('utf-8')
    st.download_button("Download CSV", data=csv, file_name="screener_results.csv", mime="text/csv")

    excel_bytes = to_excel_bytes(filtered_display)
    st.download_button("Download Excel", data=excel_bytes, file_name="screener_results.xlsx",
                       mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")
