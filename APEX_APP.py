"""
📊 시장 신호등 + 상승 종목 스캐너 (모바일 최적화)
────────────────────────────────────────────
핵심 원칙: 3가지 신호등 모두 초록일 때만 진입.

설치: pip install streamlit yfinance pandas plotly finvizfinance
실행: streamlit run market_scanner.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd

try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# ══════════════════════════════════════════════════════════
# 페이지 설정 — 모바일 최적화
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="🚦 시장 신호등",
    layout="centered",   # 모바일: wide 대신 centered
    page_icon="🚦",
    initial_sidebar_state="collapsed"
)

# 모바일 CSS 최적화
st.markdown("""
<style>
    /* 전체 폰트 크기 */
    html, body, [class*="css"] { font-size: 16px; }

    /* 버튼 크게 */
    .stButton > button {
        height: 3.5rem;
        font-size: 1.1rem;
        font-weight: bold;
        border-radius: 12px;
    }

    /* 메트릭 카드 */
    [data-testid="stMetric"] {
        background: #1E1E2E;
        border-radius: 12px;
        padding: 12px;
    }

    /* 신호등 박스 */
    .signal-box {
        border-radius: 16px;
        padding: 16px;
        margin: 8px 0;
        font-size: 1.1rem;
    }

    /* 상단 여백 줄이기 */
    .block-container { padding-top: 1rem; }

    /* selectbox 크게 */
    .stSelectbox > div > div { font-size: 1rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 캐시 함수
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def get_spy_signal():
    try:
        hist = yf.Ticker("SPY").history(period="300d", interval="1d")
        if hist.empty or len(hist) < 200:
            return None, None, None
        price  = float(hist["Close"].iloc[-1])
        sma200 = float(hist["Close"].rolling(200).mean().iloc[-1])
        chg    = float(hist["Close"].pct_change().iloc[-1] * 100)
        return price, sma200, chg
    except Exception:
        return None, None, None

@st.cache_data(ttl=300, show_spinner=False)
def get_vix_signal():
    try:
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None

@st.cache_data(ttl=600, show_spinner=False)
def get_spy_chart():
    try:
        return yf.Ticker("SPY").history(period="300d", interval="1d")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def get_stock_data(ticker: str):
    try:
        return yf.Ticker(ticker).history(period="300d", interval="1d")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def run_screener(sector: str):
    try:
        from finvizfinance.screener.overview import Overview
        filters = {
            "200-Day Simple Moving Average": "Price above SMA200",
            "50-Day Simple Moving Average":  "Price above SMA50",
            "RSI (14)":                      "Not Overbought (<60)",
            "Performance":                   "Quarter +10%",
            "Average Volume":                "Over 500K",
        }
        if sector != "전체":
            filters["Sector"] = sector
        fov = Overview()
        fov.set_filter(filters_dict=filters)
        return fov.screener_view()
    except Exception as e:
        return str(e)


# ══════════════════════════════════════════════════════════
# ① 타이틀
# ══════════════════════════════════════════════════════════
st.markdown("# 🚦 시장 신호등")
st.caption("3개 모두 초록 → 진입 / 하나라도 빨강 → 오늘 쉬기")

# 새로고침 버튼 (상단 고정)
if st.button("🔄 신호 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()


# ══════════════════════════════════════════════════════════
# ② 데이터 로드
# ══════════════════════════════════════════════════════════
with st.spinner("시장 데이터 확인 중..."):
    spy_price, spy_sma200, spy_chg = get_spy_signal()
    vix_now = get_vix_signal()


# ══════════════════════════════════════════════════════════
# ③ 신호등 3개 — 세로 배치 (모바일 최적화)
# ══════════════════════════════════════════════════════════

# 신호 1: SPY
if spy_price and spy_sma200:
    spy_ok  = spy_price > spy_sma200
    spy_gap = (spy_price - spy_sma200) / spy_sma200 * 100
    if spy_ok:
        st.success(
            f"**① 시장 추세 🟢 GO**\n\n"
            f"SPY ${spy_price:.1f} > SMA200 ${spy_sma200:.1f} ({spy_gap:+.1f}%)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%**"
        )
    else:
        st.error(
            f"**① 시장 추세 🔴 주의**\n\n"
            f"SPY ${spy_price:.1f} < SMA200 ${spy_sma200:.1f} ({spy_gap:.1f}%)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** — 종목별 확인 필요"
        )
else:
    st.warning("**① 시장 추세 ⚪ 데이터 없음** — 새로고침 해보세요")
    spy_ok = False

# 신호 2: VIX
if vix_now:
    if vix_now <= 15:
        vix_ok = True
        st.success(f"**② VIX 공포지수 🟢 매우 안정**\n\nVIX **{vix_now:.1f}** — 최적 환경")
    elif vix_now <= 20:
        vix_ok = True
        st.success(f"**② VIX 공포지수 🟢 안정**\n\nVIX **{vix_now:.1f}** — 양호")
    elif vix_now <= 25:
        vix_ok = True
        st.warning(f"**② VIX 공포지수 🟡 약간 불안**\n\nVIX **{vix_now:.1f}** — 포지션 줄이기")
    else:
        vix_ok = False
        st.error(f"**② VIX 공포지수 🔴 공포 구간**\n\nVIX **{vix_now:.1f}** — 진입 자제")
else:
    st.warning("**② VIX ⚪ 데이터 없음**")
    vix_ok = False
    vix_now = 0

# 신호 3: 이벤트 (수동)
st.markdown("**③ 오늘 주요 이벤트**")
c1, c2 = st.columns(2)
with c1:
    has_fed   = st.checkbox("🏦 Fed 금리")
    has_trade = st.checkbox("📢 관세 발표")
with c2:
    has_cpi   = st.checkbox("📊 CPI/PPI")
    has_other = st.checkbox("⚠️ 기타 이벤트")

event_risk = has_fed or has_trade or has_cpi or has_other
if event_risk:
    st.error("**이벤트 🔴 — 오늘은 쉬세요**")
else:
    st.success("**이벤트 🟢 없음 — 정상 매매 가능**")

st.divider()


# ══════════════════════════════════════════════════════════
# ④ 최종 판정 — 크고 명확하게
# ══════════════════════════════════════════════════════════
all_green = (
    spy_price is not None and spy_price > (spy_sma200 or 0) and
    vix_now is not None and vix_now <= 25 and
    not event_risk
)

if all_green:
    st.markdown("""
    <div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">✅</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#00C853">GO — 진입 가능</div>
        <div style="color:#aaa;margin-top:8px">3가지 조건 모두 충족</div>
    </div>
    """, unsafe_allow_html=True)
elif event_risk:
    st.markdown("""
    <div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🔴</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FF5252">이벤트 주의</div>
        <div style="color:#aaa;margin-top:8px">내일 다시 확인하세요</div>
    </div>
    """, unsafe_allow_html=True)
elif not spy_ok:
    st.markdown("""
    <div style="background:#2d2d00;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🟡</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FFD700">SPY 주의</div>
        <div style="color:#aaa;margin-top:8px">스캔 가능 — 종목별 SMA200 확인</div>
    </div>
    """, unsafe_allow_html=True)
else:
    st.markdown("""
    <div style="background:#2d2d00;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🟡</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FFD700">VIX 주의</div>
        <div style="color:#aaa;margin-top:8px">포지션 50% 줄이고 진입</div>
    </div>
    """, unsafe_allow_html=True)

st.divider()


# ══════════════════════════════════════════════════════════
# ⑤ 종목 스캐너
# ══════════════════════════════════════════════════════════
st.markdown("## 🔍 종목 스캔")
st.caption("필터: SMA200위 + SMA50위 + RSI<60 + 3개월+10% + 거래량500K+")

sector = st.selectbox(
    "섹터",
    ["Technology", "Healthcare", "Energy",
     "Consumer Cyclical", "Industrials", "전체"],
    index=0
)

# 조건 경고
if not all_green:
    if event_risk:
        st.error("⚠️ 이벤트 있음 — 스캔 비권장")
    elif not spy_ok:
        st.warning("⚠️ SPY SMA200 아래 — 종목별 SMA200 확인 필수")
    elif not vix_ok:
        st.warning("⚠️ VIX 높음 — 포지션 50% 줄이기")

run_scan = st.button("🔍 스캔 실행", type="primary", use_container_width=True)

if run_scan:
    with st.spinner("Finviz 스크리닝 중..."):
        result = run_screener(sector)

    if isinstance(result, str):
        err = result
        if any(k in err for k in ["ProxyError", "ConnectionError", "403"]):
            st.error("🌐 Finviz 접속 실패. 1~2분 후 재시도.")
        else:
            st.error(f"❌ 오류: {err[:200]}")

    elif result is None or (hasattr(result, "empty") and result.empty):
        st.warning(
            "⚠️ 조건 충족 종목 없음\n\n"
            "섹터를 '전체'로 바꿔보세요"
        )
    else:
        st.success(f"✅ {len(result)}개 종목 발견!")

        # 모바일용 간략 테이블
        show_cols = [c for c in ["Ticker","Company","Price","Change","Relative Volume"] if c in result.columns]
        st.dataframe(result[show_cols], use_container_width=True, hide_index=True)

        # 티커 목록
        if "Ticker" in result.columns:
            tickers = result["Ticker"].tolist()
            st.markdown("#### 발견 종목")
            st.code(", ".join(tickers))

        st.divider()

        # 종목 선택 → 차트
        st.markdown("#### 📈 종목 차트 확인")
        if "Ticker" in result.columns:
            selected = st.selectbox(
                "종목 선택 (목록에서 고르세요)",
                options=tickers,
                index=0
            )

            if selected:
                with st.spinner(f"{selected} 로딩..."):
                    hist = get_stock_data(selected)

                if not hist.empty:
                    hist["SMA20"]  = hist["Close"].rolling(20).mean()
                    hist["SMA50"]  = hist["Close"].rolling(50).mean()
                    hist["SMA200"] = hist["Close"].rolling(200).mean()

                    d = hist["Close"].diff()
                    g = d.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    l = (-d.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    hist["RSI14"] = 100 - 100/(1 + g/l.replace(0, 1e-10))

                    df60 = hist.tail(60)
                    curr  = float(df60["Close"].iloc[-1])
                    s200  = float(df60["SMA200"].iloc[-1]) if not pd.isna(df60["SMA200"].iloc[-1]) else None
                    s50   = float(df60["SMA50"].iloc[-1])  if not pd.isna(df60["SMA50"].iloc[-1])  else None
                    rsi_v = float(df60["RSI14"].iloc[-1])  if not pd.isna(df60["RSI14"].iloc[-1])  else None

                    # 3개월 수익률
                    chg_3m = None
                    if len(hist) >= 63:
                        chg_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-63] - 1) * 100

                    # 거래량 배율
                    avg_vol  = hist["Volume"].tail(20).mean()
                    rvol_now = hist["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0

                    # 체크 카드 2열
                    cc1, cc2 = st.columns(2)
                    with cc1:
                        if s200 and curr > s200:
                            st.success(f"✅ SMA200\n${s200:.1f} 위")
                        else:
                            st.error(f"❌ SMA200\n{'$'+f'{s200:.1f}' if s200 else 'N/A'} 아래")
                        if rsi_v and rsi_v < 60:
                            st.success(f"✅ RSI {rsi_v:.0f}\n과매수 아님")
                        elif rsi_v:
                            st.error(f"❌ RSI {rsi_v:.0f}\n과매수")
                    with cc2:
                        if s50 and curr > s50:
                            st.success(f"✅ SMA50\n${s50:.1f} 위")
                        else:
                            st.error(f"❌ SMA50\n{'$'+f'{s50:.1f}' if s50 else 'N/A'} 아래")
                        st.info(f"💲 현재가\n${curr:.2f}")

                    # 3개월 수익률 + 거래량
                    mc1, mc2 = st.columns(2)
                    with mc1:
                        if chg_3m is not None:
                            if chg_3m >= 10:
                                st.success(f"📈 3개월 수익률\n+{chg_3m:.1f}% ✅")
                            else:
                                st.warning(f"📈 3개월 수익률\n{chg_3m:+.1f}%")
                    with mc2:
                        if rvol_now >= 1.5:
                            st.success(f"📊 RVOL {rvol_now:.1f}x\n거래 활발")
                        else:
                            st.info(f"📊 RVOL {rvol_now:.1f}x")

                    # 차트 (캔들 + SMA + 볼륨)
                    if PLOTLY_OK:
                        from plotly.subplots import make_subplots
                        fig = make_subplots(
                            rows=2, cols=1,
                            shared_xaxes=True,
                            vertical_spacing=0.03,
                            row_heights=[0.70, 0.30],
                        )
                        fig.add_trace(go.Candlestick(
                            x=df60.index,
                            open=df60["Open"], high=df60["High"],
                            low=df60["Low"],   close=df60["Close"],
                            name=selected,
                            increasing_line_color="#00C853",
                            decreasing_line_color="#FF5252",
                            increasing_fillcolor="#00C853",
                            decreasing_fillcolor="#FF5252",
                        ), row=1, col=1)
                        for col_n, color, nm in [
                            ("SMA50",  "#42A5F5", "SMA50"),
                            ("SMA200", "#FF7043", "SMA200 ★"),
                        ]:
                            fig.add_trace(go.Scatter(
                                x=df60.index, y=df60[col_n],
                                name=nm, line=dict(color=color, width=2)
                            ), row=1, col=1)
                        vol_colors = [
                            "#00C853" if c >= o else "#FF5252"
                            for c, o in zip(df60["Close"], df60["Open"])
                        ]
                        fig.add_trace(go.Bar(
                            x=df60.index, y=df60["Volume"],
                            name="거래량", marker_color=vol_colors,
                            opacity=0.7, showlegend=False,
                        ), row=2, col=1)
                        avg_vol_line = df60["Volume"].rolling(20).mean()
                        fig.add_trace(go.Scatter(
                            x=df60.index, y=avg_vol_line,
                            name="평균거래량",
                            line=dict(color="#AAAAAA", width=1, dash="dot"),
                            showlegend=False,
                        ), row=2, col=1)
                        fig.update_layout(
                            title=f"{selected} — SMA50·SMA200·거래량",
                            height=420,
                            paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                            font=dict(color="#E0E0E0", size=11),
                            xaxis_rangeslider_visible=False,
                            margin=dict(l=30, r=10, t=45, b=20),
                            legend=dict(orientation="h", y=1.06, font=dict(size=10)),
                            hovermode="x unified",
                        )
                        for r in [1, 2]:
                            fig.update_xaxes(gridcolor="#1E1E2E", row=r, col=1)
                            fig.update_yaxes(gridcolor="#1E1E2E", row=r, col=1)
                        st.plotly_chart(fig, use_container_width=True)
                    else:
                        st.line_chart(df60[["Close","SMA50","SMA200"]])
                        st.bar_chart(df60["Volume"])


                    # Finviz 차트 링크
                    st.markdown(
                        f"[👉 Finviz {selected} 차트 열기]"
                        f"(https://finviz.com/quote.ashx?t={selected})"
                    )

                    # 손절/목표가
                    st.divider()
                    stop   = curr * 0.95
                    tgt1   = curr * 1.03
                    tgt2   = curr * 1.07
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        st.error(f"🛑 손절\n${stop:.2f}\n(-5%)")
                    with sc2:
                        st.success(f"🎯 목표1\n${tgt1:.2f}\n(+3%)")
                    with sc3:
                        st.success(f"🎯 목표2\n${tgt2:.2f}\n(+7%)")

st.divider()

# ══════════════════════════════════════════════════════════
# ⑥ 핵심 원칙 (항상 보이게)
# ══════════════════════════════════════════════════════════
st.markdown("### 📋 체크리스트")
st.markdown("""
□ 신호등 3개 초록?  
□ 종목 SMA200 위?  
□ 종목 SMA50 위?  
□ RSI 60 미만?  
□ 손절가 설정?  
→ 전부 ✅면 진입
""")
st.error("**손절가 미설정 = 진입 금지**")
