import io
import warnings

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

warnings.filterwarnings("ignore")

st.set_page_config(page_title="Macro Terminal: Semi Cycle V2", layout="wide")
st.markdown("""
<style>
    .stApp { font-family: 'Courier New', monospace; }
    h1 { color: #ef4444; }
    h2, h3, h4 { color: #38bdf8; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ MACRO TERMINAL // SEMI CYCLE MONITOR (V2)")
st.markdown("**Automated forensics, liquidity and macro triggers** | Data: Yahoo Finance + FRED, refreshed hourly")

HYPERSCALERS = ['MSFT', 'GOOGL', 'META', 'AMZN']
TRANSPARENT = dict(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')


def pick_row(df, *names):
    for name in names:
        for idx in df.index:
            if str(idx) == name:
                return df.loc[idx].dropna()
    return None


@st.cache_data(ttl=3600)
def fetch_capex_and_rev():
    capex, rev = {}, {}
    for t in HYPERSCALERS:
        tkr = yf.Ticker(t)
        c = pick_row(tkr.quarterly_cashflow, 'Capital Expenditure')
        r = pick_row(tkr.quarterly_financials, 'Total Revenue', 'Operating Revenue')
        if c is not None:
            capex[t] = c.abs()
        if r is not None:
            rev[t] = r
    if len(capex) < len(HYPERSCALERS) or len(rev) < len(HYPERSCALERS):
        raise ValueError("Missing CapEx/revenue for one or more hyperscalers")
    # Only quarters reported by every company, otherwise totals drop artificially
    capex_total = pd.DataFrame(capex).sort_index().dropna().sum(axis=1) / 1e9
    rev_total = pd.DataFrame(rev).sort_index().dropna().sum(axis=1) / 1e9
    out = pd.DataFrame({'CapEx ($B)': capex_total, 'Revenue ($B)': rev_total}).dropna()
    out['CapEx / Revenue (%)'] = out['CapEx ($B)'] / out['Revenue ($B)'] * 100
    return out


@st.cache_data(ttl=3600)
def fetch_bellwethers():
    rows = []
    for t in ['NVDA', 'TSM', 'ASML', 'AVGO', 'MU', 'MSFT', 'META']:
        info = yf.Ticker(t).info
        rg, gm = info.get('revenueGrowth'), info.get('grossMargins')
        rows.append({
            'Ticker': t,
            'Price': info.get('currentPrice') or info.get('regularMarketPrice'),
            'Fwd P/E': info.get('forwardPE'),
            'Trailing P/E': info.get('trailingPE'),
            'Rev Growth YoY (%)': rg * 100 if rg is not None else None,
            'Gross Margin (%)': gm * 100 if gm is not None else None,
        })
    df = pd.DataFrame(rows).set_index('Ticker')
    if df['Price'].isna().all():
        raise ValueError("No bellwether data returned")
    return df.apply(pd.to_numeric, errors='coerce')


@st.cache_data(ttl=3600)
def fetch_dso():
    out = {}
    for t in ['NVDA', 'AMD', 'MU']:
        tkr = yf.Ticker(t)
        rec = pick_row(tkr.quarterly_balance_sheet, 'Accounts Receivable', 'Receivables')
        rev = pick_row(tkr.quarterly_financials, 'Total Revenue', 'Operating Revenue')
        if rec is None or rev is None:
            continue
        df = pd.DataFrame({'rec': rec, 'rev': rev}).dropna()
        out[t] = df['rec'] / df['rev'] * 90
    if not out:
        raise ValueError("No receivables data returned")
    return pd.DataFrame(out).sort_index()


def fred_series(series_id, name):
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={series_id}", timeout=20)
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text), index_col=0, parse_dates=True)
    return pd.to_numeric(df.iloc[:, 0], errors='coerce').dropna().rename(name)


@st.cache_data(ttl=3600)
def fetch_fred():
    prod = fred_series('IPG3344S', 'Semi_Production')
    return {
        'prod_yoy': (prod.pct_change(12) * 100).dropna().tail(120).rename('Semi Production YoY (%)'),
        'inventory': fred_series('ISRATIO', 'Inventory_to_Sales').tail(120),
        'hy': fred_series('BAMLH0A0HYM2', 'Credit_Spread'),
    }


@st.cache_data(ttl=3600)
def fetch_prices():
    px_df = yf.download(['SOXX', 'MU', 'ASML'], period='2y', progress=False, auto_adjust=True)['Close']
    if px_df.empty:
        raise ValueError("No price data returned")
    return px_df


def load(fn, label):
    try:
        return fn()
    except Exception as e:
        st.warning(f"{label} unavailable: {e}")
        return None


with st.spinner("Loading data (first load takes up to a minute)..."):
    capex = load(fetch_capex_and_rev, "Hyperscaler CapEx/revenue")
    bells = load(fetch_bellwethers, "Bellwether fundamentals")
    dso = load(fetch_dso, "DSO data")
    fred = load(fetch_fred, "FRED data")
    prices = load(fetch_prices, "Price history")


def style(fig, **kw):
    fig.update_layout(template="plotly_dark", **TRANSPARENT, **kw)
    return fig


st.subheader("1. Bellwether Fundamentals Matrix")
if bells is not None:
    st.dataframe(
        bells.style.format({'Price': '${:.2f}', 'Fwd P/E': '{:.1f}x', 'Trailing P/E': '{:.1f}x',
                            'Rev Growth YoY (%)': '{:.1f}%', 'Gross Margin (%)': '{:.1f}%'}, na_rep='n/a')
        .background_gradient(cmap='RdYlGn_r', subset=['Fwd P/E']),
        width='stretch')

col1, col2 = st.columns(2)
with col1:
    st.subheader("2. Hyperscaler CapEx Intensity")
    st.caption("MSFT+GOOGL+META+AMZN combined. Rising CapEx / Revenue = ROI risk. "
               "Yahoo only provides ~4 comparable quarters, too few for YoY growth.")
    if capex is not None:
        fig = go.Figure()
        fig.add_trace(go.Bar(x=capex.index, y=capex['CapEx ($B)'], name='CapEx ($B)', marker_color='#10b981'))
        fig.add_trace(go.Scatter(x=capex.index, y=capex['CapEx / Revenue (%)'], name='CapEx / Revenue (%)',
                                 yaxis='y2', mode='lines+markers', line=dict(color='#f59e0b', width=3)))
        st.plotly_chart(style(fig, legend=dict(orientation='h', y=-0.2), yaxis=dict(title='$B'),
                              yaxis2=dict(title='% of revenue', overlaying='y', side='right')), width='stretch')

with col2:
    st.subheader("3. US Semi Production YoY")
    st.caption("Physical output of semiconductors and electronic components (FRED IPG3344S)")
    if fred is not None:
        s = fred['prod_yoy']
        fig = px.bar(x=s.index, y=s.values, template="plotly_dark", labels={'x': '', 'y': 'YoY (%)'})
        fig.update_traces(marker_color=['#10b981' if v > 0 else '#ef4444' for v in s.values])
        st.plotly_chart(style(fig), width='stretch')

col3, col4 = st.columns(2)
with col3:
    st.subheader("4. Total Inventory-to-Sales Ratio")
    st.caption("FRED ISRATIO: a sharp rise from a trough = demand evaporating.")
    if fred is not None:
        s = fred['inventory']
        fig = px.line(x=s.index, y=s.values, template="plotly_dark", labels={'x': '', 'y': 'Ratio'})
        fig.update_traces(line_color='#f59e0b', line_width=3)
        st.plotly_chart(style(fig), width='stretch')

with col4:
    st.subheader("5. Memory Canary (MU vs 200-DMA)")
    st.caption("Memory rolls over 3-6 months before Logic/AI.")
    if prices is not None and 'MU' in prices:
        mu = prices['MU'].dropna()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=mu.index, y=mu, name='MU Price', line=dict(color='#38bdf8')))
        fig.add_trace(go.Scatter(x=mu.index, y=mu.rolling(200).mean(), name='200-DMA',
                                 line=dict(color='#ef4444', dash='dash')))
        st.plotly_chart(style(fig), width='stretch')

st.divider()
st.subheader("🚨 Advanced Warning Indicators (Forensics & Credit)")
col5, col6, col7 = st.columns(3)

with col5:
    st.markdown("**6. Channel Stuffing (DSO)**")
    st.caption("(Receivables / Revenue) x 90. Upward spikes = danger.")
    if dso is not None:
        long = dso.rename_axis('date').reset_index().melt('date', var_name='Ticker', value_name='DSO').dropna()
        fig = px.line(long, x='date', y='DSO', color='Ticker', template="plotly_dark", markers=True,
                      labels={'DSO': 'Days Sales Outstanding', 'date': ''})
        st.plotly_chart(style(fig), width='stretch')

with col6:
    st.markdown("**7. SME vs SOXX (Book-to-Bill Proxy)**")
    st.caption("ASML / SOXX ratio. Breaking down = tool order cuts.")
    if prices is not None and {'ASML', 'SOXX'} <= set(prices.columns):
        ratio = (prices['ASML'] / prices['SOXX']).dropna()
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=ratio.index, y=ratio, name='ASML/SOXX', line=dict(color='#8b5cf6')))
        fig.add_trace(go.Scatter(x=ratio.index, y=ratio.rolling(20).mean(), name='20-DMA',
                                 line=dict(color='#94a3b8', dash='dot')))
        st.plotly_chart(style(fig), width='stretch')

with col7:
    st.markdown("**8. High Yield Spreads (CDS Proxy)**")
    st.caption("ICE BofA US HY OAS (FRED shows ~3 years). Spiking = funding freezes.")
    if fred is not None:
        s = fred['hy']
        fig = px.area(x=s.index, y=s.values, template="plotly_dark", labels={'x': '', 'y': 'Spread (%)'})
        fig.update_traces(line_color='#ef4444', fillcolor='rgba(239, 68, 68, 0.2)')
        st.plotly_chart(style(fig), width='stretch')
