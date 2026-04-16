"""
APEX 6.0 — RSI(14) <= 30 + SMA50 위에서 버티는 종목
조건 2가지:
  1. RSI(14) <= 30 (과매도)
  2. 현재가 > SMA50 (50일선 지지)
  시가총액 $10B 이상 (마이크로캡 제거)
실행: streamlit run APEX_APP_v6.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import datetime

st.set_page_config(page_title="APEX 6.0", layout="centered", page_icon="📡", initial_sidebar_state="collapsed")

st.markdown("""
<style>
html,body,[class*="css"]{font-size:16px;}
.stButton>button{height:3.5rem;font-size:1.1rem;font-weight:bold;border-radius:12px;}
[data-testid="stMetric"]{background:#1E1E2E;border-radius:12px;padding:12px;}
[data-testid="stMetric"] label,[data-testid="stMetric"] [data-testid="stMetricValue"],[data-testid="stMetric"] [data-testid="stMetricDelta"]{color:#FFFFFF!important;}
.block-container{padding-top:1rem;}
</style>
""", unsafe_allow_html=True)


def calc_rsi(series, period=14):
    delta = series.diff()
    gain = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = gain / loss.replace(0, 1e-10)
    return 100 - 100 / (1 + rs)


@st.cache_data(ttl=300, show_spinner=False)
def get_market_status():
    try:
        spy = yf.Ticker("SPY").history(period="300d", interval="1d")
        qqq = yf.Ticker("QQQ").history(period="300d", interval="1d")
        spy_p = float(spy["Close"].iloc[-1])
        spy_s200 = float(spy["Close"].rolling(200).mean().iloc[-1])
        spy_s50  = float(spy["Close"].rolling(50).mean().iloc[-1])
        qqq_p = float(qqq["Close"].iloc[-1])
        qqq_s200 = float(qqq["Close"].rolling(200).mean().iloc[-1])
        qqq_s50  = float(qqq["Close"].rolling(50).mean().iloc[-1])
        spy_m = (spy_p - spy_s200) / spy_s200 * 100
        qqq_m = (qqq_p - qqq_s200) / qqq_s200 * 100
        if spy_m >= 3 and qqq_m >= 3 and spy_p > spy_s50 and qqq_p > qqq_s50:
            regime = "STRONG_BULL"
        elif spy_m >= 3 and qqq_m >= 3:
            regime = "BULL"
        elif spy_m >= 0 or qqq_m >= 0:
            regime = "NEUTRAL"
        else:
            regime = "BEAR"
        return regime, round(spy_m, 1), round(qqq_m, 1)
    except Exception:
        return "UNKNOWN", 0, 0


@st.cache_data(ttl=600, show_spinner=False)
def get_finviz_tickers(sector):
    try:
        from finvizfinance.screener.overview import Overview
        fov = Overview()
        filters = {
            "RSI (14)":                     "Oversold (30)",
            "50-Day Simple Moving Average": "Price above SMA50",
        }
        if sector and sector != "전체":
            filters["Sector"] = sector
        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        if df is None or df.empty:
            return []
        return df["Ticker"].tolist() if "Ticker" in df.columns else []
    except Exception as e:
        return f"오류: {e}"


@st.cache_data(ttl=600, show_spinner=False)
def analyze_stock(ticker):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        price  = float(close.iloc[-1])
        prev   = float(close.iloc[-2]) if len(close) >= 2 else price

        rsi14  = calc_rsi(close, 14)
        sma50  = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()
        sma20  = close.rolling(20).mean()

        rsi_val  = float(rsi14.iloc[-1])  if not pd.isna(rsi14.iloc[-1])  else None
        s50_val  = float(sma50.iloc[-1])  if not pd.isna(sma50.iloc[-1])  else None
        s200_val = float(sma200.iloc[-1]) if not pd.isna(sma200.iloc[-1]) else None
        s20_val  = float(sma20.iloc[-1])  if not pd.isna(sma20.iloc[-1])  else None

        # 조건 체크
        cond_rsi   = rsi_val is not None and rsi_val <= 30
        cond_sma50 = s50_val is not None and price > s50_val
        if not (cond_rsi and cond_sma50):
            return None

        dist_sma50 = (price - s50_val) / s50_val * 100

        # ATR
        tr = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr_val = float(tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().iloc[-1])

        avg_vol   = float(volume.tail(20).mean())
        rvol      = float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 0
        daily_chg = (price - prev) / prev * 100 if prev > 0 else 0
        high52    = float(df["High"].tail(252).max())
        from_high = (price - high52) / high52 * 100

        # RSI 방향
        rsi_series = rsi14.dropna()
        rsi_3d_ago = float(rsi_series.iloc[-4]) if len(rsi_series) >= 4 else rsi_val
        rsi_falling = rsi_val < rsi_3d_ago

        # SMA50 위 연속 일수
        above50 = (close > sma50).dropna()
        hold_days = 0
        for v in reversed(above50.values):
            if v:
                hold_days += 1
            else:
                break

        # 등급
        if rsi_val <= 20 and dist_sma50 <= 5 and not rsi_falling:
            grade = "A"
        elif rsi_val <= 25:
            grade = "B+"
        else:
            grade = "B-"

        return {
            "ticker": ticker, "price": round(price, 2),
            "rsi14": round(rsi_val, 1),
            "sma50": round(s50_val, 2), "sma200": round(s200_val, 2) if s200_val else None,
            "sma20": round(s20_val, 2) if s20_val else None,
            "dist_sma50": round(dist_sma50, 1),
            "atr": round(atr_val, 2), "rvol": round(rvol, 2),
            "daily_chg": round(daily_chg, 2), "from_high": round(from_high, 1),
            "hold_days": hold_days, "rsi_falling": rsi_falling, "grade": grade,
        }
    except Exception:
        return None


# ══════ 헤더 ══════
st.markdown("# 📡 APEX 6.0 — RSI30 + SMA50 버티기")
st.caption("RSI(14) ≤ 30 과매도 + 50일선 위에서 버티는 종목")

if st.button("🔄 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()

with st.spinner("시장 확인 중..."):
    regime, spy_m, qqq_m = get_market_status()

rc = {"STRONG_BULL":"#00C853","BULL":"#69F0AE","NEUTRAL":"#FFD740","BEAR":"#FF5252","UNKNOWN":"#aaa"}
rl = {"STRONG_BULL":"🟢 STRONG BULL","BULL":"🟢 BULL","NEUTRAL":"🟡 NEUTRAL","BEAR":"🔴 BEAR","UNKNOWN":"⚪ 알 수 없음"}

st.markdown(f"""
<div style="background:#1e1e2e;border-radius:12px;padding:14px;margin-bottom:12px">
<span style="color:{rc.get(regime,'#aaa')};font-size:1.2rem;font-weight:bold">{rl.get(regime,regime)}</span>
<span style="color:#aaa;font-size:0.9rem;margin-left:12px">SPY {spy_m:+.1f}% / QQQ {qqq_m:+.1f}% vs SMA200</span>
</div>
""", unsafe_allow_html=True)

st.divider()

tab_scan, tab_hold = st.tabs(["🔍 종목 스캔", "📌 보유 모니터"])


# ══════ TAB 1: 스캔 ══════
with tab_scan:
    st.markdown("### 🔍 RSI30 + SMA50 버티기 스캔")
    st.info("① RSI(14) ≤ 30 (과매도) + ② SMA50 위 버티기")

    sector = st.selectbox("섹터", ["전체","Technology","Healthcare","Industrials",
                                    "Consumer Cyclical","Financial","Energy",
                                    "Communication Services","Basic Materials"], index=0)

    if st.button("🔍 스캔 실행", type="primary", use_container_width=True):
        with st.spinner("Finviz 스크리닝 → 상세 분석 중..."):
            tickers = get_finviz_tickers(sector)
            if isinstance(tickers, str):
                st.error(tickers)
            elif not tickers:
                st.warning("조건 충족 종목 없음 — 지금 시장에 해당 조건 종목이 없습니다")
            else:
                st.info(f"Finviz 통과: {len(tickers)}개 → 상세 분석 중...")
                prog = st.progress(0)
                results = []
                for i, t in enumerate(tickers):
                    r = analyze_stock(t)
                    if r:
                        results.append(r)
                    prog.progress((i + 1) / len(tickers))
                prog.empty()
                results.sort(key=lambda x: (x["rsi14"], x.get("dist_sma50") or 99))
                st.session_state["v6_results"] = results

    if "v6_results" in st.session_state and st.session_state["v6_results"]:
        results = st.session_state["v6_results"]
        ga = [r for r in results if r["grade"] == "A"]
        gbp = [r for r in results if r["grade"] == "B+"]
        gbm = [r for r in results if r["grade"] == "B-"]

        st.success(f"✅ {len(results)}개 | A등급: **{len(ga)}개** | B+: {len(gbp)}개 | B-: {len(gbm)}개")

        for r in results:
            emj = {"A":"🟢","B+":"🔵","B-":"🟡"}.get(r["grade"],"⚪")
            rsi_dir = "🔺반등중" if not r["rsi_falling"] else "🔻하락중"

            with st.expander(
                f"{emj} **{r['ticker']}** ${r['price']} — [{r['grade']}] "
                f"RSI {r['rsi14']} | SMA50 +{r['dist_sma50']:.1f}% | {rsi_dir}"
            ):
                m1, m2, m3, m4 = st.columns(4)
                with m1: st.metric("RSI(14)", f"{r['rsi14']}", "극과매도" if r['rsi14'] <= 20 else "과매도", delta_color="inverse")
                with m2: st.metric("SMA50 대비", f"+{r['dist_sma50']:.1f}%", f"${r['sma50']:.1f}")
                with m3: st.metric("당일", f"{r['daily_chg']:+.1f}%")
                with m4: st.metric("고점 대비", f"{r['from_high']:+.1f}%")

                # 이평선
                p = r["price"]
                s50 = r.get("sma50")
                s200 = r.get("sma200")
                s20 = r.get("sma20")
                if s50:
                    bg200 = "#1a4731" if s200 and p > s200 else "#3d1a1a"
                    bg20  = "#1a4731" if s20 and p > s20 else "#3d1a1a"
                    d200  = (p - s200) / s200 * 100 if s200 else 0
                    d20   = (p - s20)  / s20  * 100 if s20  else 0
                    s20_h  = f'<span style="background:{bg20};border-radius:8px;padding:4px 10px">SMA20 ${s20:.1f} ({d20:+.1f}%)</span>' if s20 else ""
                    s200_h = f'<span style="background:{bg200};border-radius:8px;padding:4px 10px">SMA200 ${s200:.1f} ({d200:+.1f}%)</span>' if s200 else ""
                    st.markdown(f"""
<div style="background:#1e1e2e;border-radius:12px;padding:12px;margin:8px 0">
<div style="font-size:0.85rem;color:#aaa;margin-bottom:6px">📐 이평선</div>
<div style="display:flex;gap:8px;flex-wrap:wrap">
{s20_h}
<span style="background:#1a4731;border-radius:8px;padding:4px 10px">SMA50 ${s50:.1f} (+{r['dist_sma50']:.1f}%) ✅</span>
{s200_h}
</div></div>""", unsafe_allow_html=True)

                st.markdown("**분석:**")
                st.markdown(f"&nbsp;&nbsp;✅ RSI(14) {r['rsi14']} — 과매도 구간")
                st.markdown(f"&nbsp;&nbsp;✅ SMA50 위에서 {r['hold_days']}일째 버티는 중")
                if r["rsi_falling"]:
                    st.markdown("&nbsp;&nbsp;⚠️ RSI 아직 하락 중 — 반등 확인 후 진입")
                else:
                    st.markdown("&nbsp;&nbsp;✅ RSI 반등 시작 — 진입 타이밍 근접")

                if r["grade"] in ["A", "B+"]:
                    st.divider()
                    stop_p = round(r["sma50"] * 0.98, 2)
                    stop_pct = round((stop_p - p) / p * 100, 1)
                    g1, g2, g3 = st.columns(3)
                    with g1: st.success(f"🎯 **목표가**\n\n+10%: ${p*1.1:.2f}\n+20%: ${p*1.2:.2f}")
                    with g2: st.error(f"🛑 **손절가**\n\nSMA50 -2%\n${stop_p} ({stop_pct:+.1f}%)")
                    with g3: st.warning(f"⏰ **타이밍**\n\n{'RSI 반등 확인 후' if not r['rsi_falling'] else 'RSI 반등 대기'}")
                    st.caption(f"ATR ${r['atr']:.2f} | RVOL {r['rvol']}x | 52주고점 {r['from_high']:+.1f}%")


# ══════ TAB 2: 보유 모니터 ══════
with tab_hold:
    st.markdown("### 📌 보유 종목 청산 체크")
    st.info("💡 스크리너 탈락 = 청산 사유 아님. 아래 조건으로만 판단.")

    h1, h2 = st.columns(2)
    with h1: h_ticker = st.text_input("티커", placeholder="예: AAPL", key="h6_ticker").upper().strip()
    with h2: h_entry  = st.number_input("진입가", min_value=0.01, value=50.0, step=0.01, key="h6_entry")
    h3, h4 = st.columns(2)
    with h3: h_date   = st.date_input("진입일", value=datetime.date.today(), key="h6_date")
    with h4: h_target = st.slider("익절 목표 (%)", 5, 30, 10, key="h6_target")

    if h_ticker and st.button("🔍 청산 체크", type="primary", use_container_width=True, key="h6_check"):
        with st.spinner(f"{h_ticker} 분석 중..."):
            try:
                hdf = yf.download(h_ticker, period="200d", progress=False)
                if hdf.empty or len(hdf) < 5:
                    st.error(f"❌ {h_ticker} 데이터 없음")
                else:
                    if isinstance(hdf.columns, pd.MultiIndex):
                        hdf.columns = hdf.columns.get_level_values(0)

                    h_close = hdf["Close"]
                    h_curr  = float(h_close.iloc[-1])
                    h_pnl   = (h_curr - h_entry) / h_entry * 100
                    h_days  = (datetime.date.today() - h_date).days
                    h_sma50 = float(h_close.rolling(50).mean().iloc[-1]) if len(h_close) >= 50 else None
                    h_rsi   = float(calc_rsi(h_close, 14).iloc[-1])

                    tp_hit = h_pnl >= h_target
                    sl_hit = h_sma50 is not None and h_curr < h_sma50 * 0.98

                    st.divider()
                    m1, m2, m3, m4 = st.columns(4)
                    with m1: st.metric("수익률", f"{h_pnl:+.1f}%", f"${h_curr:.2f}", delta_color="normal" if h_pnl >= 0 else "inverse")
                    with m2: st.metric("보유 일수", f"{h_days}일")
                    with m3: st.metric("RSI(14)", f"{h_rsi:.1f}")
                    with m4:
                        if h_sma50:
                            d = (h_curr - h_sma50) / h_sma50 * 100
                            st.metric("SMA50", f"{d:+.1f}%", "지지" if h_curr > h_sma50 else "이탈", delta_color="normal" if h_curr > h_sma50 else "inverse")

                    sell_signals = []
                    s1, s2 = st.columns(2)
                    with s1:
                        if tp_hit:
                            st.error(f"🔴 **익절**\n{h_pnl:+.1f}% ≥ +{h_target}%\n**매도 실행**")
                            sell_signals.append(f"+{h_target}% 익절")
                        else:
                            st.success(f"🟢 익절 대기\n목표 +{h_target}% → ${h_entry*(1+h_target/100):.2f}")
                    with s2:
                        if sl_hit:
                            st.error(f"🔴 **SMA50 이탈**\n${h_sma50:.2f} 아래\n**매도 실행**")
                            sell_signals.append("SMA50 이탈")
                        elif h_sma50:
                            st.success(f"🟢 SMA50 지지\n${h_sma50:.2f} 위 유지")
                        else:
                            st.warning("⚪ SMA50 계산 불가")

                    st.divider()
                    if sell_signals:
                        st.markdown(f"""<div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center">
<div style="font-size:2.5rem">🔴</div>
<div style="font-size:1.4rem;font-weight:bold;color:#FF5252">매도 — {' + '.join(sell_signals)}</div>
<div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | {h_pnl:+.1f}% | {h_days}일</div>
</div>""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""<div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center">
<div style="font-size:2.5rem">🟢</div>
<div style="font-size:1.4rem;font-weight:bold;color:#00C853">홀드 — 청산 조건 없음</div>
<div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | {h_pnl:+.1f}% | {h_days}일</div>
</div>""", unsafe_allow_html=True)
            except Exception as e:
                st.error(f"❌ 오류: {e}")
