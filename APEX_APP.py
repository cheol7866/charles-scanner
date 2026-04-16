"""
📊 APEX 5.0 — 장기 모멘텀 전략 (1~3개월 보유)
────────────────────────────────────────────────
핵심 원리: 시장(SPY)보다 강한 종목은 계속 강하다
학술 근거: Jegadeesh & Titman 모멘텀 프리미엄 (1927~2024, 150년 검증)

전략:
  ① 3개월 + 6개월 수익률이 SPY를 이긴 종목만 선별
  ② EPS 성장 확인 (실적이 뒷받침되는 모멘텀)
  ③ 월 1회 리밸런싱 (매월 첫째 주)
  ④ 3~5개 종목 집중 보유

청산 규칙:
  - +20% 익절 목표
  - -10% 절대 손절
  - SPY 대비 상대강도 꺾이면 다음 리밸런싱에서 교체

설치: pip install streamlit yfinance pandas plotly finvizfinance requests
실행: streamlit run APEX_APP_v5.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import numpy as np
import datetime
import requests

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

st.set_page_config(
    page_title="APEX 5.0 장기 모멘텀",
    layout="centered",
    page_icon="🚀",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    html, body, [class*="css"] { font-size: 16px; }
    .stButton > button {
        height: 3.5rem; font-size: 1.1rem;
        font-weight: bold; border-radius: 12px;
    }
    [data-testid="stMetric"] {
        background: #1E1E2E; border-radius: 12px;
        padding: 12px; color: #FFFFFF;
    }
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #FFFFFF !important;
    }
    .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════
# 유틸리티 함수
# ══════════════════════════════════════════════

@st.cache_data(ttl=3600, show_spinner=False)
def get_spy_returns():
    """SPY 기준 수익률 계산"""
    try:
        spy = yf.Ticker("SPY").history(period="1y", interval="1d")
        if spy.empty:
            return None, None, None
        close = spy["Close"]
        r1m  = float(close.iloc[-1] / close.iloc[-21] - 1) * 100  if len(close) >= 21  else None
        r3m  = float(close.iloc[-1] / close.iloc[-63] - 1) * 100  if len(close) >= 63  else None
        r6m  = float(close.iloc[-1] / close.iloc[-126] - 1) * 100 if len(close) >= 126 else None
        return r1m, r3m, r6m
    except Exception:
        return None, None, None

@st.cache_data(ttl=300, show_spinner=False)
def get_market_regime():
    """레짐 판단 — SPY+QQQ vs SMA200"""
    try:
        spy_hist = yf.Ticker("SPY").history(period="300d", interval="1d")
        qqq_hist = yf.Ticker("QQQ").history(period="300d", interval="1d")
        spy_price = float(spy_hist["Close"].iloc[-1])
        spy_sma200 = float(spy_hist["Close"].rolling(200).mean().iloc[-1])
        qqq_price = float(qqq_hist["Close"].iloc[-1])
        qqq_sma200 = float(qqq_hist["Close"].rolling(200).mean().iloc[-1])
        spy_margin = (spy_price - spy_sma200) / spy_sma200 * 100
        qqq_margin = (qqq_price - qqq_sma200) / qqq_sma200 * 100
        spy_sma50 = float(spy_hist["Close"].rolling(50).mean().iloc[-1])
        qqq_sma50 = float(qqq_hist["Close"].rolling(50).mean().iloc[-1])
        if spy_margin >= 3 and qqq_margin >= 3 and spy_price > spy_sma50 and qqq_price > qqq_sma50:
            regime = "STRONG_BULL"
        elif spy_margin >= 3 and qqq_margin >= 3:
            regime = "BULL"
        elif spy_margin >= 0 or qqq_margin >= 0:
            regime = "NEUTRAL"
        else:
            regime = "BEAR"
        return regime, round(spy_margin, 1), round(qqq_margin, 1), round(spy_price, 1), round(qqq_price, 1)
    except Exception:
        return "UNKNOWN", 0, 0, 0, 0

@st.cache_data(ttl=3600, show_spinner=False)
def analyze_momentum(ticker: str, spy_r3m: float, spy_r6m: float):
    """
    개별 종목 모멘텀 분석
    반환: dict 또는 None
    """
    try:
        df = yf.Ticker(ticker).history(period="1y", interval="1d")
        if df.empty or len(df) < 130:
            return None

        close = df["Close"]
        volume = df["Volume"]
        price = float(close.iloc[-1])

        # 수익률 계산
        r1m  = float(close.iloc[-1] / close.iloc[-21] - 1) * 100  if len(close) >= 21  else None
        r3m  = float(close.iloc[-1] / close.iloc[-63] - 1) * 100  if len(close) >= 63  else None
        r6m  = float(close.iloc[-1] / close.iloc[-126] - 1) * 100 if len(close) >= 126 else None

        # SPY 대비 초과수익률
        excess_3m = (r3m - spy_r3m) if (r3m is not None and spy_r3m is not None) else None
        excess_6m = (r6m - spy_r6m) if (r6m is not None and spy_r6m is not None) else None

        # 이동평균
        sma50  = float(close.rolling(50).mean().iloc[-1])  if len(close) >= 50  else None
        sma200 = float(close.rolling(200).mean().iloc[-1]) if len(close) >= 200 else None

        # 상대강도선 (RS Line) 추세
        spy_close = yf.Ticker("SPY").history(period="1y", interval="1d")["Close"]
        if len(spy_close) >= 20 and len(close) >= 20:
            rs_now  = float(close.iloc[-1] / spy_close.iloc[-1])
            rs_20d  = float(close.iloc[-20] / spy_close.iloc[-20]) if len(spy_close) >= 20 else None
            rs_rising = rs_now > rs_20d if rs_20d else False
        else:
            rs_rising = False

        # 거래량
        avg_vol = float(volume.tail(20).mean())
        rvol    = float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 0

        # EPS 성장 (yfinance)
        try:
            info = yf.Ticker(ticker).info
            eps_growth = info.get("earningsGrowth", None)
            if eps_growth is not None:
                eps_growth = float(eps_growth) * 100
        except Exception:
            eps_growth = None

        # 52주 고저점
        high52 = float(df["High"].tail(252).max())
        low52  = float(df["Low"].tail(252).min())
        from_high = (price - high52) / high52 * 100

        # 점수 계산 (핵심 기준)
        score = 0
        reasons = []

        # ① 3개월 SPY 초과 (핵심 - 40점)
        beat_3m = excess_3m is not None and excess_3m > 0
        if beat_3m:
            score += 40
            reasons.append(f"✅ 3M SPY 초과 +{excess_3m:.1f}%p")
        else:
            reasons.append(f"❌ 3M SPY 미달 ({excess_3m:.1f}%p)" if excess_3m is not None else "❌ 3M 데이터 없음")

        # ② 6개월 SPY 초과 (핵심 - 30점)
        beat_6m = excess_6m is not None and excess_6m > 0
        if beat_6m:
            score += 30
            reasons.append(f"✅ 6M SPY 초과 +{excess_6m:.1f}%p")
        else:
            reasons.append(f"❌ 6M SPY 미달 ({excess_6m:.1f}%p)" if excess_6m is not None else "❌ 6M 데이터 없음")

        # ③ RS선 상승 (20점)
        if rs_rising:
            score += 20
            reasons.append("✅ RS선 상승 중")
        else:
            reasons.append("❌ RS선 하락/횡보")

        # ④ EPS 성장 (10점)
        if eps_growth is not None and eps_growth > 0:
            score += 10
            reasons.append(f"✅ EPS 성장 +{eps_growth:.1f}%")
        elif eps_growth is not None:
            reasons.append(f"❌ EPS 감소 {eps_growth:.1f}%")
        else:
            reasons.append("⚪ EPS 정보 없음")

        # 등급
        if score >= 90:
            grade = "A"
        elif score >= 70:
            grade = "B+"
        elif score >= 50:
            grade = "B-"
        else:
            grade = "FAIL"

        # 진입 적합성 (3M+6M 모두 SPY 초과가 핵심)
        is_enterable = beat_3m and beat_6m

        return {
            "ticker":     ticker,
            "price":      round(price, 2),
            "r1m":        round(r1m,  1) if r1m  is not None else None,
            "r3m":        round(r3m,  1) if r3m  is not None else None,
            "r6m":        round(r6m,  1) if r6m  is not None else None,
            "excess_3m":  round(excess_3m, 1) if excess_3m is not None else None,
            "excess_6m":  round(excess_6m, 1) if excess_6m is not None else None,
            "rs_rising":  rs_rising,
            "sma50":      round(sma50,  2) if sma50  is not None else None,
            "sma200":     round(sma200, 2) if sma200 is not None else None,
            "avg_vol":    int(avg_vol),
            "rvol":       round(rvol, 2),
            "eps_growth": round(eps_growth, 1) if eps_growth is not None else None,
            "from_high":  round(from_high, 1),
            "high52":     round(high52, 2),
            "score":      score,
            "grade":      grade,
            "reasons":    reasons,
            "is_enterable": is_enterable,
        }
    except Exception:
        return None

@st.cache_data(ttl=3600, show_spinner=False)
def get_finviz_candidates(sectors: list):
    """Finviz 프리필터 — 3개월 강세 종목"""
    try:
        from finvizfinance.screener.overview import Overview
        fov = Overview()
        filters = {
            "Performance":    "Quarter +10%",
            "Average Volume": "Over 500K",
            "Industry":       "Stocks only (ex-Funds)",
            "Price":          "Over $10",
        }
        if sectors and "전체" not in sectors and len(sectors) == 1:
            filters["Sector"] = sectors[0]
        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        if df is None or df.empty:
            return []
        if sectors and "전체" not in sectors and len(sectors) > 1 and "Sector" in df.columns:
            df = df[df["Sector"].isin(sectors)]
        return df["Ticker"].tolist() if "Ticker" in df.columns else []
    except Exception as e:
        return f"오류: {e}"


# ══════════════════════════════════════════════
# 헤더
# ══════════════════════════════════════════════
st.markdown("# 🚀 APEX 5.0 — 장기 모멘텀")
st.caption("시장보다 강한 종목 | 1~3개월 보유 | 월 1회 리밸런싱 | 150년 검증 전략")

if st.button("🔄 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()

# ══════════════════════════════════════════════
# 시장 레짐
# ══════════════════════════════════════════════
with st.spinner("시장 상태 확인 중..."):
    regime, spy_margin, qqq_margin, spy_price, qqq_price = get_market_regime()
    spy_r1m, spy_r3m, spy_r6m = get_spy_returns()

regime_color = {
    "STRONG_BULL": "#00C853", "BULL": "#69F0AE",
    "NEUTRAL": "#FFD740", "BEAR": "#FF5252", "UNKNOWN": "#aaa"
}
regime_label = {
    "STRONG_BULL": "🟢 STRONG BULL — 풀포지션",
    "BULL":        "🟢 BULL — 정상 진입",
    "NEUTRAL":     "🟡 NEUTRAL — 선별 진입",
    "BEAR":        "🔴 BEAR — 진입 최소화",
    "UNKNOWN":     "⚪ 데이터 없음"
}
regime_pos = {"STRONG_BULL": "3~5종목", "BULL": "3~4종목", "NEUTRAL": "2~3종목", "BEAR": "1~2종목", "UNKNOWN": "—"}

st.markdown(f"""
<div style="background:#1e1e2e;border-radius:16px;padding:20px;margin-bottom:16px">
    <div style="font-size:1.4rem;font-weight:bold;color:{regime_color.get(regime,'#aaa')}">
        {regime_label.get(regime, regime)}
    </div>
    <div style="color:#aaa;margin-top:8px;font-size:0.95rem">
        SPY {spy_margin:+.1f}% vs SMA200 &nbsp;|&nbsp; QQQ {qqq_margin:+.1f}% vs SMA200
        &nbsp;|&nbsp; 권장 보유 종목 수: <b>{regime_pos.get(regime,'—')}</b>
    </div>
</div>
""", unsafe_allow_html=True)

# SPY 기준 수익률 표시
if spy_r3m is not None:
    sc1, sc2, sc3 = st.columns(3)
    with sc1: st.metric("SPY 1개월", f"{spy_r1m:+.1f}%" if spy_r1m else "—", "기준선")
    with sc2: st.metric("SPY 3개월", f"{spy_r3m:+.1f}%" if spy_r3m else "—", "기준선")
    with sc3: st.metric("SPY 6개월", f"{spy_r6m:+.1f}%" if spy_r6m else "—", "기준선")

st.caption("📌 위 수치를 넘는 종목만 진입 대상 — 이게 전부입니다")
st.divider()

# ══════════════════════════════════════════════
# 탭
# ══════════════════════════════════════════════
tab_scan, tab_hold, tab_guide = st.tabs(["🔍 종목 스캔", "📌 보유 모니터", "📖 전략 가이드"])


# ──────────────────────────────────────────
# TAB 1: 종목 스캔
# ──────────────────────────────────────────
with tab_scan:
    st.markdown("### 🔍 SPY 초과 모멘텀 종목 스캔")
    st.caption("3개월 + 6개월 수익률이 SPY를 이긴 종목만 추출 — 조건 2개")

    with st.expander("⚙️ 스캔 설정", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            scan_sectors = st.multiselect(
                "섹터",
                ["전체", "Technology", "Healthcare", "Industrials",
                 "Consumer Cyclical", "Financial", "Energy",
                 "Communication Services", "Basic Materials"],
                default=["전체"], key="scan_sectors"
            )
            if "전체" in scan_sectors:
                scan_sectors = ["전체"]
        with c2:
            min_excess = st.slider("최소 SPY 초과수익률 (3M)", 0, 20, 5,
                                   help="SPY 3개월 수익률보다 얼마나 더 올랐는지")

    if st.button("🚀 스캔 실행", type="primary", use_container_width=True):
        with st.spinner("Finviz 프리필터 → SPY 상대강도 분석 중... (2~5분)"):
            tickers_raw = get_finviz_candidates(scan_sectors)
            if isinstance(tickers_raw, str):
                st.error(tickers_raw)
            elif not tickers_raw:
                st.warning("Finviz 프리필터 결과 없음 — 섹터를 '전체'로 변경해보세요")
            else:
                st.info(f"Finviz 통과: {len(tickers_raw)}개 → SPY 비교 분석 중...")
                prog = st.progress(0)
                results = []
                for i, t in enumerate(tickers_raw):
                    r = analyze_momentum(t, spy_r3m or 0, spy_r6m or 0)
                    if r and r["is_enterable"] and r.get("excess_3m", 0) >= min_excess:
                        results.append(r)
                    prog.progress((i + 1) / len(tickers_raw))
                prog.empty()
                results.sort(key=lambda x: (
                    -(x.get("excess_3m") or 0) + -(x.get("excess_6m") or 0)
                ))
                st.session_state["scan_results"] = results

    if "scan_results" in st.session_state and st.session_state["scan_results"]:
        results = st.session_state["scan_results"]
        grade_a  = [r for r in results if r["grade"] == "A"]
        grade_bp = [r for r in results if r["grade"] == "B+"]

        st.success(
            f"✅ SPY 초과 종목: **{len(results)}개** | "
            f"A등급: **{len(grade_a)}개** | B+등급: **{len(grade_bp)}개**"
        )

        for r in results:
            emj = {"A": "🟢", "B+": "🔵", "B-": "🟡"}.get(r["grade"], "⚪")
            excess_3m_str = f"+{r['excess_3m']:.1f}%p" if r.get('excess_3m') and r['excess_3m'] > 0 else f"{r.get('excess_3m', 0):.1f}%p"
            excess_6m_str = f"+{r['excess_6m']:.1f}%p" if r.get('excess_6m') and r['excess_6m'] > 0 else f"{r.get('excess_6m', 0):.1f}%p"

            with st.expander(
                f"{emj} **{r['ticker']}** ${r['price']} — [{r['grade']}] "
                f"3M SPY초과 {excess_3m_str} | 6M SPY초과 {excess_6m_str}"
            ):
                m1, m2, m3, m4 = st.columns(4)
                with m1: st.metric("3M 수익률", f"{r['r3m']:+.1f}%" if r['r3m'] else "—",
                                   f"SPY {excess_3m_str}")
                with m2: st.metric("6M 수익률", f"{r['r6m']:+.1f}%" if r['r6m'] else "—",
                                   f"SPY {excess_6m_str}")
                with m3: st.metric("RS선", "↑ 상승" if r['rs_rising'] else "↓ 하락",
                                   "강세 신호" if r['rs_rising'] else "주의")
                with m4: st.metric("EPS 성장",
                                   f"+{r['eps_growth']:.1f}%" if r['eps_growth'] and r['eps_growth'] > 0
                                   else (f"{r['eps_growth']:.1f}%" if r['eps_growth'] else "—"))

                # 이평선 위치
                if r['sma50'] and r['sma200']:
                    bg50  = "#1a4731" if r['price'] > r['sma50']  else "#3d1a1a"
                    bg200 = "#1a4731" if r['price'] > r['sma200'] else "#3d1a1a"
                    st.markdown(f"""
<div style="background:#1e1e2e;border-radius:12px;padding:12px;margin:8px 0">
    <div style="font-size:0.85rem;color:#aaa;margin-bottom:6px">📐 이평선 위치</div>
    <div style="display:flex;gap:8px;flex-wrap:wrap">
        <span style="background:{bg50};border-radius:8px;padding:4px 10px">
            SMA50 ${r['sma50']:.1f} ({(r['price']-r['sma50'])/r['sma50']*100:+.1f}%)
        </span>
        <span style="background:{bg200};border-radius:8px;padding:4px 10px">
            SMA200 ${r['sma200']:.1f} ({(r['price']-r['sma200'])/r['sma200']*100:+.1f}%)
        </span>
        <span style="background:#2a2a3e;border-radius:8px;padding:4px 10px">
            52주고점 ${r['high52']:.1f} ({r['from_high']:+.1f}%)
        </span>
    </div>
</div>
""", unsafe_allow_html=True)

                # 체크 항목
                st.markdown("**분석 결과:**")
                for reason in r["reasons"]:
                    st.markdown(f"&nbsp;&nbsp;{reason}")

                # 진입 가이드
                if r["grade"] in ["A", "B+"]:
                    st.divider()
                    g1, g2, g3 = st.columns(3)
                    with g1:
                        st.success(f"🎯 **목표가**\n\n+20% → ${r['price']*1.20:.2f}\n+30% → ${r['price']*1.30:.2f}")
                    with g2:
                        st.error(f"🛑 **손절가**\n\n-10% → ${r['price']*0.90:.2f}\n반드시 지키기")
                    with g3:
                        st.warning(f"📅 **보유 기간**\n\n1~3개월\n매월 RS선 재확인")
                    st.info(
                        f"📐 **레짐 {regime}** → {regime_pos.get(regime, '—')} 보유 분산\n\n"
                        f"⏰ **리밸런싱:** 매월 첫째 주 — RS선 꺾인 종목은 교체"
                    )


# ──────────────────────────────────────────
# TAB 2: 보유 모니터
# ──────────────────────────────────────────
with tab_hold:
    st.markdown("### 📌 보유 종목 모니터")
    st.caption("청산 신호만 체크 — 스크리너 탈락은 청산 사유 아님")

    st.info(
        "💡 **청산 규칙 3가지만**\n\n"
        "① +20% 익절 목표 도달\n"
        "② -10% 손절 (절대 원칙)\n"
        "③ RS선(SPY 대비 상대강도)이 하락 전환 → 다음 리밸런싱에서 교체"
    )

    h1, h2 = st.columns(2)
    with h1:
        h_ticker = st.text_input("보유 종목 티커", placeholder="예: NVDA", key="h_ticker").upper().strip()
    with h2:
        h_entry  = st.number_input("진입가 (USD)", min_value=0.01, value=50.0, step=0.01, key="h_entry")

    h3, h4 = st.columns(2)
    with h3:
        h_date = st.date_input("진입일", value=datetime.date.today(), key="h_date")
    with h4:
        h_target_pct = st.slider("익절 목표 (%)", 10, 40, 20, key="h_target")

    if h_ticker and st.button("🔍 청산 신호 체크", type="primary", use_container_width=True, key="h_check"):
        with st.spinner(f"{h_ticker} 분석 중..."):
            try:
                hdf = yf.Ticker(h_ticker).history(period="1y", interval="1d")
                spy_hist = yf.Ticker("SPY").history(period="1y", interval="1d")

                if hdf.empty or len(hdf) < 5:
                    st.error(f"❌ {h_ticker} 데이터 없음")
                else:
                    if isinstance(hdf.columns, pd.MultiIndex):
                        hdf.columns = hdf.columns.get_level_values(0)

                    h_close   = hdf["Close"]
                    h_curr    = float(h_close.iloc[-1])
                    h_pnl     = (h_curr - h_entry) / h_entry * 100
                    h_days    = (datetime.date.today() - h_date).days

                    # RS선 계산
                    spy_close = spy_hist["Close"]
                    rs_series = h_close / spy_close.reindex(h_close.index, method="ffill")
                    rs_now    = float(rs_series.iloc[-1])
                    rs_20d    = float(rs_series.iloc[-20]) if len(rs_series) >= 20 else rs_now
                    rs_rising = rs_now > rs_20d
                    rs_chg    = (rs_now - rs_20d) / rs_20d * 100 if rs_20d != 0 else 0

                    # SPY 대비 수익률
                    entry_spy = float(spy_close.iloc[-(h_days if h_days < len(spy_close) else len(spy_close)-1)-1]) if h_days > 0 else float(spy_close.iloc[-1])
                    curr_spy  = float(spy_close.iloc[-1])
                    spy_ret   = (curr_spy - entry_spy) / entry_spy * 100 if entry_spy > 0 else 0
                    rel_perf  = h_pnl - spy_ret

                    # 청산 신호
                    tp_hit   = h_pnl >= h_target_pct
                    sl_hit   = h_pnl <= -10.0
                    rs_warn  = not rs_rising and h_days > 20

                    st.divider()
                    st.markdown(f"#### {h_ticker} 보유 현황")

                    m1, m2, m3, m4 = st.columns(4)
                    with m1:
                        color = "normal" if h_pnl >= 0 else "inverse"
                        st.metric("현재 수익률", f"{h_pnl:+.1f}%", f"${h_curr:.2f}", delta_color=color)
                    with m2:
                        st.metric("보유 일수", f"{h_days}일")
                    with m3:
                        color_rel = "normal" if rel_perf >= 0 else "inverse"
                        st.metric("SPY 대비", f"{rel_perf:+.1f}%p", "아웃퍼폼" if rel_perf >= 0 else "언더퍼폼", delta_color=color_rel)
                    with m4:
                        st.metric("RS선", "↑ 상승" if rs_rising else "↓ 하락",
                                  f"20일 대비 {rs_chg:+.1f}%")

                    st.divider()
                    st.markdown("#### 🚦 청산 신호")

                    sell_signals = []
                    s1, s2, s3 = st.columns(3)

                    with s1:
                        if tp_hit:
                            st.error(f"🔴 **①익절 신호**\n\n수익 {h_pnl:+.1f}% ≥ +{h_target_pct}%\n**매도 실행**")
                            sell_signals.append(f"+{h_target_pct}% 익절")
                        else:
                            remaining = h_target_pct - h_pnl
                            st.success(f"🟢 ①익절 대기\n\n목표까지 +{remaining:.1f}%\n목표가 ${h_entry*(1+h_target_pct/100):.2f}")

                    with s2:
                        if sl_hit:
                            st.error(f"🔴 **②손절 신호**\n\n손실 {h_pnl:.1f}% ≤ -10%\n**즉시 매도**")
                            sell_signals.append("-10% 손절")
                        else:
                            st.success(f"🟢 ②손절 안전\n\n손절선 ${h_entry*0.90:.2f}\n현재 여유 {h_pnl+10:.1f}%")

                    with s3:
                        if rs_warn:
                            st.warning(f"🟡 **③RS선 주의**\n\nRS선 하락 전환\n다음 리밸런싱 교체 검토")
                            sell_signals.append("RS선 하락 — 교체 검토")
                        else:
                            st.success(f"🟢 ③RS선 정상\n\n{'상승 중' if rs_rising else '보유 20일 미만'}")

                    st.divider()
                    if sell_signals:
                        is_hard_sell = any(s in sell_signals for s in [f"+{h_target_pct}% 익절", "-10% 손절"])
                        if is_hard_sell:
                            st.markdown(f"""
<div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center">
    <div style="font-size:2.5rem">🔴</div>
    <div style="font-size:1.4rem;font-weight:bold;color:#FF5252">매도 실행 — {' + '.join(sell_signals)}</div>
    <div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | 수익률 {h_pnl:+.1f}% | 보유 {h_days}일</div>
</div>
""", unsafe_allow_html=True)
                        else:
                            st.markdown(f"""
<div style="background:#2d2d00;border-radius:16px;padding:20px;text-align:center">
    <div style="font-size:2.5rem">🟡</div>
    <div style="font-size:1.4rem;font-weight:bold;color:#FFD700">주의 — {' + '.join(sell_signals)}</div>
    <div style="color:#aaa;margin-top:8px">다음 리밸런싱에서 교체 검토</div>
</div>
""", unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
<div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center">
    <div style="font-size:2.5rem">🟢</div>
    <div style="font-size:1.4rem;font-weight:bold;color:#00C853">홀드 — 청산 조건 없음</div>
    <div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | 수익률 {h_pnl:+.1f}% | SPY 대비 {rel_perf:+.1f}%p | 보유 {h_days}일</div>
</div>
""", unsafe_allow_html=True)

            except Exception as e:
                st.error(f"❌ 오류: {e}")


# ──────────────────────────────────────────
# TAB 3: 전략 가이드
# ──────────────────────────────────────────
with tab_guide:
    st.markdown("### 📖 APEX 5.0 전략 가이드")

    st.markdown("#### 왜 이 전략인가")
    st.markdown("""
시장보다 강한 종목은 계속 강하다는 **모멘텀 프리미엄**은 1927년부터 2024년까지
97년간, 전 세계 31개국에서 검증된 유일한 전략입니다.

**핵심 원리:**
- 기업 실적이 뒷받침되는 모멘텀 = 지속 가능한 상승
- SPY보다 강하다 = 지금 시장이 이 종목에 돈을 몰아주고 있다는 증거
- 기술 지표(RSI, SMA) 없음 = 후행 신호 없음
    """)

    st.markdown("#### 진입 기준 (단 2가지)")
    st.markdown("""
    | 조건 | 기준 | 이유 |
    |------|------|------|
    | 3개월 수익률 | SPY 3개월 수익률 초과 | 단기 모멘텀 확인 |
    | 6개월 수익률 | SPY 6개월 수익률 초과 | 중기 추세 확인 |

    **이 2가지만 충족하면 진입합니다. 더 이상 조건 없습니다.**
    """)

    st.markdown("#### 청산 규칙")
    st.markdown("""
    | 규칙 | 기준 | 특이사항 |
    |------|------|----------|
    | ①익절 | +20% 도달 시 | 목표가 미달이어도 3개월 후 재평가 |
    | ②손절 | -10% 도달 시 | 절대 원칙, 예외 없음 |
    | ③교체 | RS선 하락 전환 | 즉시 아닌 다음 리밸런싱 시 |
    """)

    st.markdown("#### 리밸런싱 규칙")
    st.markdown("""
    **매월 첫째 주:**
    1. 보유 종목의 RS선(SPY 대비) 확인
    2. RS선이 꺾인 종목 → 새 후보로 교체
    3. RS선 유지 종목 → 계속 보유
    4. 스캔 새로 실행 → 새 후보 발굴

    **보유 종목 수:**
    - Strong Bull: 3~5개 | Bull: 3~4개 | Neutral: 2~3개 | Bear: 1~2개
    """)

    st.markdown("#### 이전 APEX와 다른 점")
    st.markdown("""
    | 항목 | APEX 1~4 | APEX 5.0 |
    |------|----------|----------|
    | 보유 기간 | 5~20일 | 1~3개월 |
    | 진입 기준 | RSI, SMA 기술지표 | SPY 대비 실제 성과 |
    | 문제 | 올라가면 과열, 내려가면 미달 | 올라가는 게 진입 신호 |
    | 리밸런싱 | 매일 스캔 | 월 1회 |
    | 경쟁 | 알고리즘과 초단기 싸움 | 기업 성장에 올라타기 |
    """)

    st.warning("""
    **반드시 지켜야 할 것 하나:**
    -10% 손절은 절대 원칙입니다. 어떤 이유도 예외가 없습니다.
    이것 하나가 이 전략의 생존을 결정합니다.
    """)
