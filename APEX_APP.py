"""
📊 APEX 시장 신호등 + 종목 스캐너 v3.0
═══════════════════════════════════════
핵심 원칙: 신호등 모두 초록일 때만 진입.
MOM: RVOL > 1.2 | MR : RVOL < 0.8

설치: pip install streamlit yfinance pandas plotly finvizfinance requests
실행: streamlit run APEX_APP.py
"""

from __future__ import annotations
import datetime
from typing import Optional
import pandas as pd
import streamlit as st
import yfinance as yf

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# ══════════════════════════════════════════
# 지표 계산
# ══════════════════════════════════════════
def calc_rsi(series, period):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def calc_sma(series, period):
    return series.rolling(window=period).mean()

def calc_bollinger(series, period=20, std_mult=2):
    sma = calc_sma(series, period)
    std = series.rolling(window=period).std()
    return sma, sma + std_mult * std, sma - std_mult * std

def calc_atr(high, low, close, period=14):
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def calc_rvol(volume, period=20):
    avg = volume.rolling(window=period).mean()
    return float(volume.iloc[-1] / avg.iloc[-1]) if avg.iloc[-1] > 0 else 0.0

def consec_down(close):
    count = 0
    for i in range(len(close) - 1, 0, -1):
        if close.iloc[i] < close.iloc[i - 1]: count += 1
        else: break
    return count

# ══════════════════════════════════════════
# 시장 데이터
# ══════════════════════════════════════════
def get_index_data(ticker):
    try:
        hist = yf.Ticker(ticker).history(period="300d", interval="1d")
        if hist.empty or len(hist) < 200: return None, None, None
        p = float(hist["Close"].iloc[-1])
        s = float(hist["Close"].rolling(200).mean().iloc[-1])
        c = float(hist["Close"].pct_change().iloc[-1] * 100)
        return p, s, c
    except Exception: return None, None, None

def get_vix():
    try:
        h = yf.Ticker("^VIX").history(period="5d")
        return float(h["Close"].iloc[-1]) if not h.empty else None
    except Exception: return None

def get_spy_rsi2():
    try:
        h = yf.Ticker("SPY").history(period="30d")
        return float(calc_rsi(h["Close"], 2).iloc[-1])
    except Exception: return None

def get_earnings_info(ticker):
    today = datetime.date.today()
    result = {"date": None, "days_away": None, "within_3d": False, "label": "어닝 정보 없음", "source": "none"}
    try:
        tk = yf.Ticker(ticker); cal = tk.calendar; earn_date = None
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if raw:
                if isinstance(raw, (list, tuple)) and len(raw) > 0: earn_date = pd.Timestamp(raw[0]).date()
                elif hasattr(raw, "date"): earn_date = raw.date()
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index: earn_date = pd.Timestamp(cal.loc["Earnings Date"].iloc[0]).date()
        if earn_date:
            d = (earn_date - today).days
            result.update({"date": earn_date, "days_away": d, "within_3d": -1 <= d <= 3, "label": f"{earn_date.strftime('%Y-%m-%d')} (D{d:+d})", "source": "calendar"})
            return result
        fi = tk.fast_info
        if hasattr(fi, "next_earnings_date") and fi.next_earnings_date:
            earn_date = pd.Timestamp(fi.next_earnings_date).date()
            d = (earn_date - today).days
            result.update({"date": earn_date, "days_away": d, "within_3d": -1 <= d <= 3, "label": f"{earn_date.strftime('%Y-%m-%d')} (D{d:+d})", "source": "fast_info"})
            return result
    except Exception: pass
    return result

# ══════════════════════════════════════════
# 레짐
# ══════════════════════════════════════════
def get_regime(sp, ss, qp, qs):
    if None in (sp, ss, qp, qs): return "UNKNOWN"
    sm = (sp - ss) / ss * 100; qm = (qp - qs) / qs * 100
    if sm >= 5 and qm >= 5: return "STRONG_BULL"
    if sm >= 3 and qm >= 3: return "WEAK_BULL"
    return "BEAR"

def calc_margins(sp, ss, qp, qs):
    return ((sp-ss)/ss*100 if sp and ss else -99, (qp-qs)/qs*100 if qp and qs else -99)

SCORE_ORDER = {"A": 0, "B+": 1, "B-": 2, "FAIL": 3}
SCORE_EMOJI = {"A": "🟢", "B+": "🔵", "B-": "🟡", "FAIL": "🔴"}
REGIME_EMOJI = {"STRONG_BULL": "🟢", "WEAK_BULL": "🟡", "BEAR": "🔴", "UNKNOWN": "⚪"}

# ══════════════════════════════════════════
# Finviz
# ══════════════════════════════════════════
def run_finviz_screen(mode, sectors=None):
    try:
        from finvizfinance.screener.overview import Overview
        if mode == "MOM":
            f = {"200-Day Simple Moving Average": "Price above SMA200", "50-Day Simple Moving Average": "Price above SMA50", "RSI (14)": "Not Overbought (<60)", "Performance": "Quarter +10%", "Average Volume": "Over 500K", "Industry": "Stocks only (ex-Funds)", "Relative Volume": "Over 1.5", "Current Volume": "Over 500K", "Price": "Over $10"}
        else:
            f = {"200-Day Simple Moving Average": "Price above SMA200", "RSI (14)": "Oversold (40)", "Average Volume": "Over 500K", "Industry": "Stocks only (ex-Funds)", "Price": "Over $10"}
        if sectors and len(sectors) == 1 and sectors[0] != "전체": f["Sector"] = sectors[0]
        fov = Overview(); fov.set_filter(filters_dict=f); df = fov.screener_view()
        if df is None or df.empty: return []
        if sectors and "전체" not in sectors and len(sectors) > 1 and "Sector" in df.columns:
            df = df[df["Sector"].isin(sectors)]
        return df["Ticker"].tolist()
    except Exception as e: return f"오류: {e}"

# ══════════════════════════════════════════
# 종목 분석
# ══════════════════════════════════════════
def analyze_stock(ticker, mode, spy_rsi2_val, mom_ok, vix_ok, account_size=5000, risk_pct=1.0):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 200: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        close, high, low, volume = df["Close"], df["High"], df["Low"], df["Volume"]
        price = float(close.iloc[-1])
        sma200 = calc_sma(close, 200); sma150 = calc_sma(close, 150); sma50 = calc_sma(close, 50); sma20 = calc_sma(close, 20)
        rsi2 = calc_rsi(close, 2); rsi14 = calc_rsi(close, 14)
        _, _, bb_lower = calc_bollinger(close); atr = calc_atr(high, low, close)
        rvol = calc_rvol(volume); consec = consec_down(close); earn = get_earnings_info(ticker)
        s200 = float(sma200.iloc[-1]); s150 = float(sma150.iloc[-1]) if not pd.isna(sma150.iloc[-1]) else None
        s50 = float(sma50.iloc[-1]); s20 = float(sma20.iloc[-1])
        rsi2_v = float(rsi2.iloc[-1]); rsi14_v = float(rsi14.iloc[-1])
        bb_low_v = float(bb_lower.iloc[-1]); atr_v = float(atr.iloc[-1])
        sepa = s150 is not None and s50 > s150 > s200
        sma200_rising = len(sma200) >= 21 and float(sma200.iloc[-1]) > float(sma200.iloc[-21])
        h252 = df.tail(252); w52_high = float(h252["High"].max()); w52_low = float(h252["Low"].min())
        from_high = (price - w52_high) / w52_high * 100; from_low = (price - w52_low) / w52_low * 100
        perf_3m = ((price / float(close.iloc[-63])) - 1) * 100 if len(close) >= 63 else 0

        if mode == "MR":
            required = {"SMA200 위": price > s200, "RSI(2) ≤ 15": rsi2_v <= 15, "어닝 3일내 없음": not earn["within_3d"], "SPY RSI(2) > 10": spy_rsi2_val is not None and spy_rsi2_val > 10}
            preferred = {"BB 하단 터치": price <= bb_low_v * 1.005, "RVOL < 1.2": rvol < 1.2, "연속 하락 3일+": consec >= 3, "VIX ≤ 25": vix_ok}
        else:
            required = {"시장 레짐 Bull": mom_ok, "RSI(14) 50~70": 50 <= rsi14_v <= 70, "어닝 3일내 없음": not earn["within_3d"], "SMA200 상승 중": sma200_rising}
            preferred = {"SEPA 정렬": sepa, "RVOL ≥ 1.2": rvol >= 1.2, "3개월 +10%": perf_3m >= 10, "52주고점 -25%이내": from_high >= -25, "52주저점 +30%이상": from_low >= 30, "RSI(2) < 80": rsi2_v < 80}

        req_pass = sum(required.values()); pref_pass = sum(preferred.values())
        pref_pct = pref_pass / len(preferred) if preferred else 0
        if req_pass < len(required): score, win_rate = "FAIL", "—"
        elif pref_pct >= 1.0: score, win_rate = ("A", "75~82%") if mode == "MR" else ("A", "70~78%")
        elif pref_pct >= 0.7: score, win_rate = ("B+", "68~75%") if mode == "MR" else ("B+", "63~70%")
        else: score, win_rate = ("B-", "60~65%") if mode == "MR" else ("B-", "55~63%")
        risk_dollar = account_size * (risk_pct / 100); shares = int(risk_dollar / atr_v) if atr_v > 0 else 0; pos_value = shares * price

        return {"ticker": ticker, "price": round(price, 2), "sma200": round(s200, 2), "sma50": round(s50, 2), "sma20": round(s20, 2),
                "rsi2": round(rsi2_v, 1), "rsi14": round(rsi14_v, 1), "rvol": round(rvol, 2), "consec": consec, "atr": round(atr_v, 2),
                "perf_3m": round(perf_3m, 1), "sepa": sepa, "sma200_rising": sma200_rising,
                "from_high": round(from_high, 1), "from_low": round(from_low, 1),
                "earn_label": earn["label"], "earn_blocked": earn["within_3d"],
                "required": required, "req_pass": req_pass, "req_total": len(required),
                "preferred": preferred, "pref_pass": pref_pass, "pref_total": len(preferred), "pref_pct": round(pref_pct * 100),
                "score": score, "win_rate": win_rate, "shares": shares, "pos_value": round(pos_value),
                "pos_pct": round(pos_value / account_size * 100, 1) if account_size > 0 else 0,
                "stop_3atr": round(price - 3 * atr_v, 2), "target_8pct": round(price * 1.08, 2)}
    except Exception: return None

def sort_results(results, mode):
    if mode == "MR": return sorted(results, key=lambda x: (SCORE_ORDER.get(x["score"], 9), x["rsi2"]))
    return sorted(results, key=lambda x: (SCORE_ORDER.get(x["score"], 9), -x.get("perf_3m", 0)))

# ══════════════════════════════════════════
# 보유 종목 청산 체크
# ══════════════════════════════════════════
def check_exit_signals(ticker, strategy, entry_price, entry_date):
    try:
        hdf = yf.download(ticker, period="60d", progress=False)
        if hdf.empty or len(hdf) < 5: return None
        if isinstance(hdf.columns, pd.MultiIndex): hdf.columns = hdf.columns.get_level_values(0)
        c = hdf["Close"]; curr = float(c.iloc[-1]); pnl = (curr - entry_price) / entry_price * 100
        r2 = float(calc_rsi(c, 2).iloc[-1]); r14 = float(calc_rsi(c, 14).iloc[-1])
        a = float(calc_atr(hdf["High"], hdf["Low"], c).iloc[-1])
        hd = (datetime.date.today() - entry_date).days; stop = entry_price - 3 * a; sigs = []
        if strategy == "MR":
            tp = r2 > 70; tm = hd >= 10; st_hit = curr <= stop
            if tp: sigs.append("RSI(2)>70 익절")
            if tm: sigs.append("10일 타임스탑")
            if st_hit: sigs.append("3ATR 재난손절")
        else:
            tp = pnl >= 8.0; tm = hd >= 15; st_hit = False
            if tp: sigs.append("+8% 익절")
            if tm: sigs.append("15일 타임스탑")
        return {"ticker": ticker, "curr": round(curr, 2), "pnl": round(pnl, 1), "hold_days": hd, "rsi2": round(r2, 1), "rsi14": round(r14, 1), "atr": round(a, 2), "stop_3atr": round(stop, 2), "sell_signals": sigs, "tp_hit": tp, "time_hit": tm, "stop_hit": st_hit}
    except Exception: return None


# ══════════════════════════════════════════════════════════
# ═══════════ Streamlit UI ═══════════
# ══════════════════════════════════════════════════════════
st.set_page_config(page_title="🚦 APEX 신호등", layout="centered", page_icon="🚦", initial_sidebar_state="collapsed")
st.markdown("""<style>
html, body, [class*="css"] { font-size: 16px; }
.stButton > button { height: 3.5rem; font-size: 1.1rem; font-weight: bold; border-radius: 12px; }
[data-testid="stMetric"] { background: #1E1E2E; border-radius: 12px; padding: 12px; color: #FFFFFF; }
[data-testid="stMetric"] label, [data-testid="stMetric"] [data-testid="stMetricValue"], [data-testid="stMetric"] [data-testid="stMetricDelta"] { color: #FFFFFF !important; }
.block-container { padding-top: 1rem; }
</style>""", unsafe_allow_html=True)

@st.cache_data(ttl=300, show_spinner=False)
def _ci(t): return get_index_data(t)
@st.cache_data(ttl=300, show_spinner=False)
def _cv(): return get_vix()
@st.cache_data(ttl=600, show_spinner=False)
def _cs(t):
    try: return yf.Ticker(t).history(period="300d")
    except: return pd.DataFrame()
@st.cache_data(ttl=3600, show_spinner=False)
def _ce(t): return get_earnings_info(t)
@st.cache_data(ttl=600, show_spinner=False)
def _cf(m, s): return run_finviz_screen(m, list(s))
@st.cache_data(ttl=600, show_spinner=False)
def _ca(t, m, sr, mo, vo, ac, rp): return analyze_stock(t, m, sr, mo, vo, ac, rp)

st.markdown("# 🚦 APEX 신호등 v3")
st.caption("신호등 모두 초록 → 진입 / 하나라도 빨강 → 오늘 쉬기")
if st.button("🔄 새로고침", use_container_width=True): st.cache_data.clear(); st.rerun()
st.divider()

with st.spinner("시장 데이터..."):
    spy_price, spy_sma200, spy_chg = _ci("SPY")
    qqq_price, qqq_sma200, qqq_chg = _ci("QQQ")
    vix_now = _cv()

def _sig(label, price, sma200, chg):
    if price and sma200:
        gap = (price - sma200) / sma200 * 100; n = "📈" if chg > 0 else "📉"
        if gap >= 3: st.success(f"**{label} 🟢** ${price:.1f} > SMA200 ${sma200:.1f} ({gap:+.1f}%) | {chg:+.2f}% {n}")
        elif gap > 0: st.warning(f"**{label} 🟡** ${price:.1f} ({gap:+.1f}% < 3%) | {chg:+.2f}% {n}")
        else: st.error(f"**{label} 🔴** ${price:.1f} < SMA200 ${sma200:.1f} ({gap:.1f}%) | {chg:+.2f}% {n}")
        return gap >= 3
    st.warning(f"**{label} ⚪**"); return False

spy_ok = _sig("① SPY", spy_price, spy_sma200, spy_chg)
qqq_ok = _sig("① QQQ", qqq_price, qqq_sma200, qqq_chg)

if vix_now:
    if vix_now <= 20: vix_ok = True; st.success(f"**② VIX 🟢** {vix_now:.1f}")
    elif vix_now <= 25: vix_ok = True; st.warning(f"**② VIX 🟡** {vix_now:.1f}")
    else: vix_ok = False; st.error(f"**② VIX 🔴** {vix_now:.1f}")
else: st.warning("**② VIX ⚪**"); vix_ok = False; vix_now = 0

st.markdown("**③ 이벤트**")
c1, c2 = st.columns(2)
with c1: has_fed = st.checkbox("🏦 Fed"); has_trade = st.checkbox("📢 관세")
with c2: has_cpi = st.checkbox("📊 CPI/PPI"); has_other = st.checkbox("⚠️ 기타")
event_risk = has_fed or has_trade or has_cpi or has_other
if event_risk: st.error("**이벤트 🔴**")
else: st.success("**이벤트 🟢 없음**")
st.divider()

vix_ok_val = vix_now is not None and vix_now <= 25
all_green = spy_ok and qqq_ok and vix_ok_val and not event_risk

def _box(e, t, s, bg):
    c = "#00C853" if bg == "#1a4731" else "#FF5252" if bg == "#3d1a1a" else "#FFD700"
    return f'<div style="background:{bg};border-radius:16px;padding:20px;text-align:center;margin:8px 0"><div style="font-size:3rem">{e}</div><div style="font-size:1.6rem;font-weight:bold;color:{c}">{t}</div><div style="color:#aaa;margin-top:8px">{s}</div></div>'

if all_green: st.markdown(_box("✅", "GO — 진입 가능", "모두 충족", "#1a4731"), unsafe_allow_html=True)
elif event_risk: st.markdown(_box("🔴", "이벤트 주의", "내일 다시", "#3d1a1a"), unsafe_allow_html=True)
else: st.markdown(_box("🟡", "주의", "종목별 확인", "#2d2d00"), unsafe_allow_html=True)
st.divider()

_spy_rsi2 = get_spy_rsi2()
_sm, _qm = calc_margins(spy_price, spy_sma200, qqq_price, qqq_sma200)
_regime = get_regime(spy_price, spy_sma200, qqq_price, qqq_sma200)
_mom_ok = _regime in ["STRONG_BULL", "WEAK_BULL"]
_mr_ok = _spy_rsi2 is not None and _spy_rsi2 > 10
_vix_ok = vix_now is not None and vix_now <= 25
if _spy_rsi2 is not None and _spy_rsi2 <= 10: st.error(f"⛔ SPY RSI(2) {_spy_rsi2:.1f} ≤ 10")
st.divider()

tab_report, tab_manual, tab_hold = st.tabs(["📊 Daily Report", "🔍 수동 분석", "📌 보유 모니터"])

with tab_report:
    st.markdown("### 📊 Daily Report")
    with st.expander("⚙️ 설정"):
        dc1, dc2 = st.columns(2)
        with dc1: dr_acc = st.number_input("💰 계좌", 500, 500000, 5000, 500, key="dr_acc"); dr_rsk = st.slider("🎯 리스크%", 0.5, 3.0, 1.0, 0.5, key="dr_rsk")
        with dc2:
            dr_sec = st.multiselect("📂 섹터", ["전체", "Technology", "Industrials", "Healthcare", "Consumer Cyclical", "Communication Services", "Financial", "Energy", "Basic Materials"], default=["전체"], key="dr_sec")
            if "전체" in dr_sec: dr_sec = ["전체"]
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1: st.metric("레짐", f"{REGIME_EMOJI.get(_regime, '⚪')} {_regime}")
    with rc2: st.metric("SPY RSI(2)", f"{_spy_rsi2:.1f}" if _spy_rsi2 else "N/A")
    with rc3: st.metric("MOM", "✅" if _mom_ok else "🚫")
    with rc4: st.metric("MR", "✅" if _mr_ok else "🚫")
    st.markdown("---")
    dr_mr, dr_mom = st.tabs(["🔄 MR", "🚀 MOM"])

    def _rdr(results, mode):
        ent = [r for r in results if r["score"] in ["A", "B+"]]
        st.success(f"✅ 후보 {len(results)}개 | 진입 **{len(ent)}개**")
        for r in results:
            with st.expander(f"{SCORE_EMOJI.get(r['score'], '⚪')} **{r['ticker']}** ${r['price']} [{r['score']}] {r['win_rate']}"):
                m1, m2, m3, m4 = st.columns(4)
                if mode == "MR":
                    with m1: st.metric("RSI(2)", f"{r['rsi2']}");
                    with m2: st.metric("RVOL", f"{r['rvol']}x")
                    with m3: st.metric("ATR", f"${r['atr']}");
                    with m4: st.metric("연속↓", f"{r['consec']}일")
                else:
                    with m1: st.metric("RSI(14)", f"{r['rsi14']}");
                    with m2: st.metric("RVOL", f"{r['rvol']}x")
                    with m3: st.metric("3M", f"+{r['perf_3m']}%");
                    with m4: st.metric("52주", f"{r['from_high']}%")
                ch1, ch2 = st.columns(2)
                with ch1:
                    st.markdown(f"**필수 ({r['req_pass']}/{r['req_total']})**")
                    for n, ok in r["required"].items(): st.markdown(f"{'✅' if ok else '❌'} {n}")
                with ch2:
                    st.markdown(f"**선호 ({r['pref_pass']}/{r['pref_total']} = {r['pref_pct']}%)**")
                    for n, ok in r["preferred"].items(): st.markdown(f"{'✅' if ok else '❌'} {n}")
                if r["score"] in ["A", "B+"]:
                    st.divider()
                    if mode == "MR":
                        g1, g2, g3, g4 = st.columns(4)
                        with g1: st.info(f"⏰ 05:30\n${r['price']*0.998:.2f}")
                        with g2: st.success("🎯 RSI>70")
                        with g3: st.warning("⏱️ 10일")
                        with g4: st.error(f"🛑 ${r['price']-r['atr']*3:.2f}")
                    else:
                        g1, g2, g3 = st.columns(3)
                        with g1: st.info("⏰ 23:00")
                        with g2: st.success("🎯 +8%")
                        with g3: st.warning("⏱️ 15일")
                    st.markdown(f"📐 {r['shares']}주 × ${r['price']} = **${r['pos_value']:,}** ({r['pos_pct']}%)")
                if r["earn_blocked"]: st.error("🚨 어닝 — 금지")

    def _dscan(mode, key):
        if st.button(f"{'🔄' if mode=='MR' else '🚀'} {mode} 스캔", key=f"dr_{key}_btn", type="primary", use_container_width=True):
            with st.spinner("분석 중..."):
                tk = _cf(mode, tuple(dr_sec))
                if isinstance(tk, str): st.error(tk)
                elif not tk: st.warning("종목 없음")
                else:
                    st.info(f"Finviz {len(tk)}개"); prog = st.progress(0); res = []
                    for i, t in enumerate(tk):
                        r = _ca(t, mode, _spy_rsi2, _mom_ok, _vix_ok, dr_acc, dr_rsk)
                        if r: res.append(r)
                        prog.progress((i+1)/len(tk))
                    prog.empty(); st.session_state[f"dr_{key}"] = sort_results(res, mode)
        k = f"dr_{key}"
        if k in st.session_state and st.session_state[k]: _rdr(st.session_state[k], mode)

    with dr_mr:
        if not _mr_ok: st.error("🚫 MR 금지 — SPY RSI(2) ≤ 10")
        else: _dscan("MR", "mr")
    with dr_mom:
        if not _mom_ok: st.error("🚫 MOM 금지 — Bear")
        else: _dscan("MOM", "mom")

    st.divider()
    tc1, tc2 = st.columns(2)
    with tc1: st.info("**🔄 MR**\n\n⏰ 05:30 KST\n🎯 RSI(2)>70\n📅 2~5일")
    with tc2: st.success("**🚀 MOM**\n\n⏰ 23:00 KST\n🎯 +8%\n📅 5~15일")

with tab_manual:
    st.markdown("## 🔍 종목 스캔")
    stm = st.radio("전략", ["MOM (모멘텀)", "MR (평균회귀)"], horizontal=True)
    is_mom = stm == "MOM (모멘텀)"
    if "scan_result" not in st.session_state: st.session_state.scan_result = None
    sector = st.selectbox("섹터", ["Technology", "Healthcare", "Energy", "Consumer Cyclical", "Industrials", "전체"])
    cs1, cs2 = st.columns([3, 1])
    with cs1: run_scan = st.button("🔍 스캔", type="primary", use_container_width=True)
    with cs2:
        if st.button("🗑️"): st.session_state.scan_result = None; st.rerun()
    if run_scan:
        with st.spinner("Finviz..."):
            try:
                from finvizfinance.screener.overview import Overview
                from finvizfinance.screener.technical import Technical
                m = "MOM" if is_mom else "MR"
                if m == "MOM": ff = {"200-Day Simple Moving Average": "Price above SMA200", "50-Day Simple Moving Average": "Price above SMA50", "RSI (14)": "Not Overbought (<60)", "Performance": "Quarter +10%", "Average Volume": "Over 500K", "Industry": "Stocks only (ex-Funds)", "Relative Volume": "Over 1.5", "Current Volume": "Over 500K", "Price": "Over $10"}
                else: ff = {"200-Day Simple Moving Average": "Price above SMA200", "RSI (14)": "Oversold (40)", "Average Volume": "Over 500K", "Industry": "Stocks only (ex-Funds)", "Price": "Over $10"}
                if sector != "전체": ff["Sector"] = sector
                fov = Overview(); fov.set_filter(filters_dict=ff); df_overview = fov.screener_view()
                # Technical 뷰에서 Rel Volume 가져오기
                try:
                    ftc = Technical(); ftc.set_filter(filters_dict=ff); df_tech = ftc.screener_view()
                    if df_tech is not None and not df_tech.empty and "Rel Volume" in df_tech.columns:
                        rvol_map = dict(zip(df_tech["Ticker"], df_tech["Rel Volume"]))
                        if df_overview is not None and not df_overview.empty:
                            df_overview["RVOL"] = df_overview["Ticker"].map(rvol_map)
                except Exception:
                    pass
                st.session_state.scan_result = df_overview
            except Exception as e: st.session_state.scan_result = str(e)
    result = st.session_state.scan_result
    if result is not None:
        if isinstance(result, str): st.error(f"❌ {result[:200]}")
        elif hasattr(result, "empty") and result.empty: st.warning("종목 없음")
        elif hasattr(result, "__len__") and len(result) > 0:
            st.success(f"✅ {len(result)}개 발견!")
            if hasattr(result, "columns") and "Ticker" in result.columns:
                show = [c for c in ["Ticker", "Company", "Price", "Change", "RVOL"] if c in result.columns]
                st.dataframe(result[show], use_container_width=True, hide_index=True)
                tickers = result["Ticker"].tolist(); st.code(", ".join(tickers))
                st.divider()
                sel = st.selectbox("종목 선택", tickers)
                if sel:
                    with st.spinner(f"{sel}..."):
                        hist = _cs(sel)
                    if not hist.empty:
                        hist["SMA50"] = calc_sma(hist["Close"], 50); hist["SMA150"] = calc_sma(hist["Close"], 150); hist["SMA200"] = calc_sma(hist["Close"], 200)
                        hist["RSI14"] = calc_rsi(hist["Close"], 14); hist["RSI2"] = calc_rsi(hist["Close"], 2)
                        bm, bu, bl = calc_bollinger(hist["Close"]); hist["BB_upper"] = bu; hist["BB_lower"] = bl; hist["BB_mid"] = bm
                        hist["ATR14"] = calc_atr(hist["High"], hist["Low"], hist["Close"])
                        spy_rsi2_val = get_spy_rsi2()
                        df60 = hist.tail(60); curr = float(df60["Close"].iloc[-1])
                        s200 = float(df60["SMA200"].iloc[-1]) if not pd.isna(df60["SMA200"].iloc[-1]) else None
                        s150 = float(df60["SMA150"].iloc[-1]) if not pd.isna(df60["SMA150"].iloc[-1]) else None
                        s50 = float(df60["SMA50"].iloc[-1]) if not pd.isna(df60["SMA50"].iloc[-1]) else None
                        rsi_v = float(df60["RSI14"].iloc[-1]) if not pd.isna(df60["RSI14"].iloc[-1]) else None
                        rsi2_v = float(df60["RSI2"].iloc[-1]) if not pd.isna(df60["RSI2"].iloc[-1]) else None
                        bb_low = float(df60["BB_lower"].iloc[-1]) if not pd.isna(df60["BB_lower"].iloc[-1]) else None
                        bb_up = float(df60["BB_upper"].iloc[-1]) if not pd.isna(df60["BB_upper"].iloc[-1]) else None
                        bb_mid_v = float(df60["BB_mid"].iloc[-1]) if not pd.isna(df60["BB_mid"].iloc[-1]) else None
                        atr_val = float(df60["ATR14"].iloc[-1]) if not pd.isna(df60["ATR14"].iloc[-1]) else None
                        sma200_now = hist["SMA200"].iloc[-1]; sma200_20d = hist["SMA200"].iloc[-21] if len(hist) >= 21 else None
                        sma200_rising = not pd.isna(sma200_now) and sma200_20d is not None and not pd.isna(sma200_20d) and float(sma200_now) > float(sma200_20d)
                        sepa = s50 is not None and s150 is not None and s200 is not None and s50 > s150 > s200
                        h252 = hist.tail(252); w52h = float(h252["High"].max()); w52l = float(h252["Low"].min())
                        w52fh = (curr - w52h) / w52h * 100; w52fl = (curr - w52l) / w52l * 100
                        earn_info = _ce(sel)

                        if is_mom:
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if s200 and curr > s200: st.success("✅ SMA200 위")
                                else: st.error("❌ SMA200 아래")
                            with cc2:
                                if s50 and curr > s50: st.success("✅ SMA50 위")
                                else: st.error("❌ SMA50 아래")
                        else:
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if s200 and curr > s200: st.success("✅ SMA200 위")
                                else: st.error("❌ SMA200 아래")
                            with cc2:
                                if rsi2_v is not None and rsi2_v <= 15: st.success(f"✅ RSI(2) {rsi2_v:.1f}")
                                elif rsi2_v is not None: st.warning(f"🟡 RSI(2) {rsi2_v:.1f}")

                        st.divider()
                        ta1, ta2 = st.columns(2)
                        with ta1:
                            if sma200_rising: st.success("✅ SMA200 상승")
                            else: st.error("❌ SMA200 하락")
                        with ta2:
                            if sepa: st.success("✅ SEPA 정렬")
                            else: st.error("❌ SEPA 미완")

                        st.divider()
                        w1, w2 = st.columns(2)
                        with w1: st.metric("고점 대비", f"{w52fh:+.1f}%")
                        with w2: st.metric("저점 대비", f"+{w52fl:.1f}%")

                        if earn_info["within_3d"]: st.error(f"🚨 어닝 {earn_info['label']} — 금지")
                        elif earn_info["source"] != "none": st.success(f"✅ 어닝 {earn_info['label']}")

                        if not is_mom:
                            st.divider(); st.markdown("#### 🎯 MR 신호")
                            mr1, mr2, mr3 = st.columns(3)
                            with mr1:
                                if rsi2_v is not None and rsi2_v <= 15: st.success(f"✅ RSI(2) {rsi2_v:.1f}")
                                elif rsi2_v is not None: st.error(f"❌ RSI(2) {rsi2_v:.1f}")
                            with mr2:
                                if bb_low and curr <= bb_low * 1.005: st.success("✅ BB터치")
                                else: st.error("❌ BB미접촉")
                            with mr3:
                                if spy_rsi2_val and spy_rsi2_val > 10: st.success(f"✅ SPY {spy_rsi2_val:.1f}")
                                else: st.error("❌ SPY 급락")

                        st.divider()
                        if PLOTLY_OK:
                            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.7, 0.3])
                            fig.add_trace(go.Candlestick(x=df60.index, open=df60["Open"], high=df60["High"], low=df60["Low"], close=df60["Close"], name=sel), row=1, col=1)
                            for cn, co in [("SMA50", "#42A5F5"), ("SMA150", "#FFA726"), ("SMA200", "#FF7043"), ("BB_upper", "#9C27B0"), ("BB_lower", "#9C27B0")]:
                                fig.add_trace(go.Scatter(x=df60.index, y=df60[cn], name=cn, line=dict(color=co, width=1)), row=1, col=1)
                            vc = ["#00C853" if c >= o else "#FF5252" for c, o in zip(df60["Close"], df60["Open"])]
                            fig.add_trace(go.Bar(x=df60.index, y=df60["Volume"], marker_color=vc, showlegend=False), row=2, col=1)
                            fig.update_layout(height=400, paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font=dict(color="#E0E0E0"), xaxis_rangeslider_visible=False, margin=dict(l=20, r=10, t=30, b=20))
                            st.plotly_chart(fig, use_container_width=True)

                        st.markdown(f"[Finviz {sel}](https://finviz.com/quote.ashx?t={sel})")
                        st.divider()
                        if is_mom:
                            sc1, sc2 = st.columns(2)
                            with sc1: st.success(f"🎯 +8% ${curr*1.08:.2f}")
                            with sc2: st.warning("⏱️ 15일")
                        else:
                            sc1, sc2, sc3 = st.columns(3)
                            with sc1: st.success("🎯 RSI>70")
                            with sc2: st.warning("⏱️ 10일")
                            with sc3:
                                if atr_val: st.error(f"🛑 ${curr-atr_val*3:.2f}")

                        if atr_val:
                            st.divider(); st.markdown("#### 📐 포지션")
                            p1, p2 = st.columns(2)
                            with p1: ac = st.number_input("💰 계좌", 500, 500000, 5000, 500, key="m_acc")
                            with p2: rk = st.slider("🎯 %", 0.5, 3.0, 1.0, 0.5, key="m_rsk")
                            rd = ac * (rk / 100); sh = int(rd / atr_val); pv = sh * curr
                            r1, r2, r3 = st.columns(3)
                            with r1: st.metric("주수", f"{sh:,}")
                            with r2: st.metric("금액", f"${pv:,.0f}")
                            with r3: st.metric("비중", f"{pv/ac*100:.1f}%")

    st.divider()
    st.markdown("| | MR | MOM |\n|---|---|---|\n| 익절 | RSI(2)>70 | +8% |\n| 타임스탑 | 10일 | 15일 |\n| 재난손절 | 3ATR | 없음 |")

with tab_hold:
    st.markdown("### 📌 보유 모니터")
    st.info("스크리너 사라짐 ≠ 매도")
    h1, h2 = st.columns(2)
    with h1: ht = st.text_input("티커", placeholder="AAOI", key="ht").upper().strip()
    with h2: hm = st.radio("전략", ["MR (평균회귀)", "MOM (모멘텀)"], horizontal=True, key="hm")
    h3, h4 = st.columns(2)
    with h3: hp = st.number_input("진입가", min_value=0.01, value=10.0, step=0.01, key="hp")
    with h4: hd = st.date_input("진입일", value=datetime.date.today(), key="hd")
    if ht and st.button("🔍 체크", type="primary", use_container_width=True, key="hc"):
        with st.spinner(f"{ht}..."):
            s = "MR" if hm == "MR (평균회귀)" else "MOM"
            ex = check_exit_signals(ht, s, hp, hd)
            if ex is None: st.error(f"❌ {ht} 없음")
            else:
                st.divider()
                m1, m2, m3, m4 = st.columns(4)
                with m1: st.metric("현재가", f"${ex['curr']}", f"{ex['pnl']:+.1f}%")
                with m2: st.metric("보유", f"{ex['hold_days']}일")
                with m3: st.metric("RSI(2)", f"{ex['rsi2']}")
                with m4: st.metric("RSI(14)", f"{ex['rsi14']}")
                st.divider()
                if s == "MR":
                    s1, s2, s3 = st.columns(3)
                    with s1:
                        if ex["tp_hit"]: st.error(f"🔴 RSI={ex['rsi2']}>70")
                        else: st.success(f"🟢 RSI={ex['rsi2']}")
                    with s2:
                        if ex["time_hit"]: st.error(f"🔴 {ex['hold_days']}일≥10")
                        else: st.success(f"🟢 {ex['hold_days']}일")
                    with s3:
                        if ex["stop_hit"]: st.error(f"🔴 ${ex['curr']}≤${ex['stop_3atr']}")
                        else: st.success(f"🟢 ${ex['stop_3atr']}")
                else:
                    s1, s2 = st.columns(2)
                    with s1:
                        if ex["tp_hit"]: st.error(f"🔴 {ex['pnl']:+.1f}%≥8%")
                        else: st.success(f"🟢 {ex['pnl']:+.1f}%")
                    with s2:
                        if ex["time_hit"]: st.error(f"🔴 {ex['hold_days']}일≥15")
                        else: st.success(f"🟢 {ex['hold_days']}일")
                st.divider()
                if ex["sell_signals"]:
                    st.markdown(f'<div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center"><div style="font-size:3rem">🔴</div><div style="font-size:1.6rem;font-weight:bold;color:#FF5252">매도 — {" + ".join(ex["sell_signals"])}</div><div style="color:#aaa">{ht} ${ex["curr"]} | {ex["pnl"]:+.1f}% | {ex["hold_days"]}일</div></div>', unsafe_allow_html=True)
                else:
                    st.markdown(f'<div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center"><div style="font-size:3rem">🟢</div><div style="font-size:1.6rem;font-weight:bold;color:#00C853">홀드</div><div style="color:#aaa">{ht} ${ex["curr"]} | {ex["pnl"]:+.1f}% | {ex["hold_days"]}일</div></div>', unsafe_allow_html=True)

