import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# --- CONFIG & STYLING ---
st.set_page_config(page_title="Macro Terminal: Semi Cycle V2", layout="wide")
st.markdown("""
<style>
    .stApp { background-color: #0b0f19; color: #e2e8f0; font-family: 'Courier New', monospace; }
    h1, h2, h3, h4 { color: #38bdf8; }
    .stDataFrame { border: 1px solid #1e293b; }
</style>
""", unsafe_allow_html=True)

st.title("⚡ MACRO TERMINAL // SEMI CYCLE MONITOR (V2)")
st.markdown("**Hedge-Fund Grade | Automated Forensics, Liquidity, and Macro Triggers**")

# --- DATA FETCHING ---
@st.cache_data(ttl=3600)
def fetch_capex_and_rev():
    tickers = ['MSFT', 'GOOGL', 'META', 'AMZN']
    capex_data = {}
    rev_data = {}
    
    for t in tickers:
        try:
            # Capex
            cf = yf.Ticker(t).quarterly_cashflow
            cap_idx = [i for i in cf.index if 'Capital Expenditure' in str(i) or 'Property Plant' in str(i)]
            if cap_idx:
                s_cap = cf.loc[cap_idx[0]].dropna().abs()
                capex_data[t] = s_cap[~s_cap.index.duplicated()]
            
            # Revenue
            inc = yf.Ticker(t).quarterly_financials
            rev_idx = [i for i in inc.index if 'Total Revenue' in str(i) or 'Operating Revenue' in str(i)]
            if rev_idx:
                s_rev = inc.loc[rev_idx[0]].dropna()
                rev_data[t] = s_rev[~s_rev.index.duplicated()]
        except: pass
        
    df_capex = pd.DataFrame()
    df_rev = pd.DataFrame()
    
    if capex_data:
        df_capex = pd.DataFrame(capex_data).sort_index().ffill(limit=1).fillna(0)
        df_capex['Total CapEx ($B)'] = df_capex.sum(axis=1) / 1e9
        df_capex['CapEx YoY (%)'] = df_capex['Total CapEx ($B)'].pct_change(periods=4) * 100
        
    if rev_data:
        df_rev = pd.DataFrame(rev_data).sort_index().ffill(limit=1).fillna(0)
        df_rev['Total Rev ($B)'] = df_rev.sum(axis=1) / 1e9
        df_rev['Rev YoY (%)'] = df_rev['Total Rev ($B)'].pct_change(periods=4) * 100
        
    return df_capex.dropna().tail(12), df_rev.dropna().tail(12)

@st.cache_data(ttl=3600)
def fetch_bellwethers():
    tickers = ['NVDA', 'TSM', 'ASML', 'AVGO', 'MU', 'MSFT', 'META']
    data = []
    for t in tickers:
        try:
            info = yf.Ticker(t).info
            data.append({
                'Ticker': t, 
                'Price': info.get('currentPrice', 0),
                'Fwd P/E': info.get('forwardPE', 0), 
                'Trailing P/E': info.get('trailingPE', 0),
                'Rev Growth YoY (%)': (info.get('revenueGrowth', 0) or 0) * 100,
                'Gross Margin (%)': (info.get('grossMargins', 0) or 0) * 100
            })
        except: pass
    if data:
        df = pd.DataFrame(data).set_index('Ticker')
        return df.dropna(subset=['Fwd P/E'])
    return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_dso_data():
    tickers = ['NVDA', 'AMD', 'MU']
    dso_data = {}
    for t in tickers:
        try:
            tkr = yf.Ticker(t)
            bs = tkr.quarterly_balance_sheet
            inc = tkr.quarterly_financials
            
            rec_idx = [i for i in bs.index if 'Receivable' in str(i)]
            rev_idx = [i for i in inc.index if 'Total Revenue' in str(i) or 'Operating Revenue' in str(i)]
            
            if rec_idx and rev_idx:
                rec = bs.loc[rec_idx[0]].dropna()
                rev = inc.loc[rev_idx[0]].dropna()
                df = pd.DataFrame({'Receivables': rec, 'Revenue': rev}).dropna()
                dso_data[t] = (df['Receivables'] / df['Revenue']) * 90
        except: pass
    return pd.DataFrame(dso_data).sort_index().tail(12) if dso_data else pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_fred_data():
    try:
        ip = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=IPG33441S", index_col='DATE', parse_dates=True)
        ip.columns = ['Semi_Production']
        ip['Semi_Prod_YoY (%)'] = pd.to_numeric(ip['Semi_Production'], errors='coerce').pct_change(12) * 100
        
        inv = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=ISRATIO", index_col='DATE', parse_dates=True)
        inv.columns = ['Inventory_to_Sales']
        
        hy = pd.read_csv("https://fred.stlouisfed.org/graph/fredgraph.csv?id=BAMLH0A0HYM2", index_col='DATE', parse_dates=True)
        hy.columns = ['Credit_Spread']
        
        return ip.join(inv, how='outer').join(hy, how='outer').ffill().tail(120)
    except: return pd.DataFrame()

@st.cache_data(ttl=3600)
def fetch_prices():
    prices = pd.DataFrame()
    for t in ['SOXX', 'MU', 'ASML']:
        try:
            # Squeeze to handle potential multi-index arrays from newer versions of yf
            p = yf.download(t, period='2y', progress=False)['Close']
            if isinstance(p, pd.DataFrame):
                p = p.squeeze()
            prices[t] = p
        except: pass
    return prices

# --- LOAD DATA ---
with st.spinner("Compiling V2 Institutional Data (YFinance + FRED)..."):
    df_capex, df_rev = fetch_capex_and_rev()
    df_bells = fetch_bellwethers()
    df_dso = fetch_dso_data()
    df_fred = fetch_fred_data()
    df_prices = fetch_prices()

# --- LAYOUT ---
st.subheader("1. Bellwether Fundamentals Matrix")
if not df_bells.empty:
    st.dataframe(df_bells.style.format({'Price': '${:.2f}', 'Fwd P/E': '{:.1f}x', 'Trailing P/E': '{:.1f}x', 
                                        'Rev Growth YoY (%)': '{:.1f}%', 'Gross Margin (%)': '{:.1f}%'})
                 .background_gradient(cmap='RdYlGn_r', subset=['Fwd P/E']), use_container_width=True)

col1, col2 = st.columns(2)
with col1:
    st.subheader("2. Hyperscaler ROI Death Cross")
    st.caption("CapEx Growth (Green) vs Cloud Rev Growth (Blue). Danger if CapEx > Rev.")
    if not df_capex.empty and not df_rev.empty:
        fig1 = go.Figure()
        fig1.add_trace(go.Scatter(x=df_capex.index, y=df_capex['CapEx YoY (%)'], name='CapEx YoY %', line=dict(color='#10b981', width=3)))
        common_idx = df_capex.index.intersection(df_rev.index)
        fig1.add_trace(go.Scatter(x=common_idx, y=df_rev.loc[common_idx, 'Rev YoY (%)'], name='Rev YoY %', line=dict(color='#3b82f6', width=3, dash='dot')))
        fig1.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01))
        st.plotly_chart(fig1, use_container_width=True)

with col2:
    st.subheader("3. US Semi Production YoY (SIA Proxy)")
    st.caption("Physical output volume (FRED IPG33441S)")
    if not df_fred.empty and 'Semi_Prod_YoY (%)' in df_fred:
        clean_fred = df_fred.dropna(subset=['Semi_Prod_YoY (%)'])
        fig2 = px.bar(clean_fred, x=clean_fred.index, y='Semi_Prod_YoY (%)', template="plotly_dark")
        fig2.update_traces(marker_color=clean_fred['Semi_Prod_YoY (%)'].apply(lambda x: '#10b981' if x > 0 else '#ef4444'))
        fig2.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig2, use_container_width=True)

col3, col4 = st.columns(2)
with col3:
    st.subheader("4. Total Inventory-to-Sales Ratio")
    st.caption("FRED ISRATIO: Bottoming out and spiking = Demand evaporation.")
    if not df_fred.empty and 'Inventory_to_Sales' in df_fred:
        clean_inv = df_fred.dropna(subset=['Inventory_to_Sales'])
        fig3 = px.line(clean_inv, x=clean_inv.index, y='Inventory_to_Sales', template="plotly_dark")
        fig3.update_traces(line_color='#f59e0b', line_width=3)
        fig3.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig3, use_container_width=True)

with col4:
    st.subheader("5. Memory Canary (MU vs 200-DMA)")
    st.caption("Memory rolls over 3-6 months before Logic/AI.")
    if not df_prices.empty and 'MU' in df_prices:
        mu = df_prices['MU'].dropna()
        mu_sma = mu.rolling(200).mean()
        fig4 = go.Figure()
        fig4.add_trace(go.Scatter(x=mu.index, y=mu, name='MU Price', line=dict(color='#38bdf8')))
        fig4.add_trace(go.Scatter(x=mu_sma.index, y=mu_sma, name='200-DMA', line=dict(color='#ef4444', dash='dash')))
        fig4.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig4, use_container_width=True)

st.divider()
st.subheader("🚨 Advanced Warning Indicators (Forensics & Credit)")
col5, col6, col7 = st.columns(3)

with col5:
    st.markdown("**6. Channel Stuffing (DSO)**")
    st.caption("(Receivables/Revenue)*90. Upward spikes = Danger.")
    if not df_dso.empty:
        fig5 = px.line(df_dso, x=df_dso.index, y=df_dso.columns, template="plotly_dark", markers=True)
        fig5.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis_title="Days Sales Outstanding")
        st.plotly_chart(fig5, use_container_width=True)

with col6:
    st.markdown("**7. SME vs SOXX (Book-to-Bill Proxy)**")
    st.caption("Ratio of ASML to SOXX. Breaking down = CapEx Cuts.")
    if not df_prices.empty and 'ASML' in df_prices and 'SOXX' in df_prices:
        ratio = (df_prices['ASML'] / df_prices['SOXX']).dropna()
        ratio_sma = ratio.rolling(20).mean()
        fig6 = go.Figure()
        fig6.add_trace(go.Scatter(x=ratio.index, y=ratio, name='ASML/SOXX', line=dict(color='#8b5cf6')))
        fig6.add_trace(go.Scatter(x=ratio_sma.index, y=ratio_sma, name='20-DMA', line=dict(color='#94a3b8', dash='dot')))
        fig6.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)')
        st.plotly_chart(fig6, use_container_width=True)

with col7:
    st.markdown("**8. High Yield Spreads (CDS Proxy)**")
    st.caption("Cost of debt. Spiking = CapEx funding freezes.")
    if not df_fred.empty and 'Credit_Spread' in df_fred:
        clean_hy = df_fred.dropna(subset=['Credit_Spread'])
        fig7 = px.area(clean_hy, x=clean_hy.index, y='Credit_Spread', template="plotly_dark")
        fig7.update_traces(line_color='#ef4444', fillcolor='rgba(239, 68, 68, 0.2)')
        fig7.update_layout(paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', yaxis_title="Spread (%)")
        st.plotly_chart(fig7, use_container_width=True)