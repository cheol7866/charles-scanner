"""
📊 시장 신호등 + 상승 종목 스캐너
────────────────────────────────────────────
핵심 원칙: 단순하게. 3가지만 확인하고 GO면 진입.

설치: pip install streamlit yfinance pandas plotly finvizfinance
실행: streamlit run market_scanner.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
from datetime import datetime, date
import time

try:
    import plotly.graph_objects as go
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# ══════════════════════════════════════════════════════════
# 페이지 설정
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="시장 신호등 + 상승 종목 스캐너",
    layout="wide",
    page_icon="🚦"
)

st.title("🚦 시장 신호등 + 상승 종목 스캐너")
st.caption("**3가지 신호등이 모두 초록일 때만 진입. 하나라도 빨강이면 오늘은 쉬는 날.**")

# ══════════════════════════════════════════════════════════
# 캐시 함수
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def get_spy_signal():
    """SPY > SMA200 체크"""
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
    """VIX 수치 가져오기"""
    try:
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None

@st.cache_data(ttl=600, show_spinner=False)
def get_spy_chart():
    """SPY 최근 60일 차트용"""
    try:
        return yf.Ticker("SPY").history(period="90d", interval="1d")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def get_stock_data(ticker: str):
    """개별 종목 60일 데이터"""
    try:
        return yf.Ticker(ticker).history(period="90d", interval="1d")
    except Exception:
        return pd.DataFrame()

@st.cache_data(ttl=600, show_spinner=False)
def run_screener(sector: str, extra_filters: dict):
    """Finviz 스크리너 실행"""
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
        filters.update(extra_filters)
        fov = Overview()
        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        return df
    except Exception as e:
        return str(e)


# ══════════════════════════════════════════════════════════
# ① 3가지 시장 신호등
# ══════════════════════════════════════════════════════════
st.markdown("## 🚦 시장 신호등 — 지금 들어가도 되나?")

with st.spinner("시장 데이터 확인 중..."):
    spy_price, spy_sma200, spy_chg = get_spy_signal()
    vix_now = get_vix_signal()

sig1, sig2, sig3 = st.columns(3)

# ── 신호 1: SPY vs SMA200 ──────────────────────────────
with sig1:
    st.markdown("### 📈 신호 1: 시장 추세")
    if spy_price and spy_sma200:
        spy_ok = spy_price > spy_sma200
        gap    = (spy_price - spy_sma200) / spy_sma200 * 100
        if spy_ok:
            st.success(
                f"🟢 **GO**\n\n"
                f"SPY **${spy_price:.1f}** > SMA200 **${spy_sma200:.1f}**\n\n"
                f"장기 상승 구조 위 (+{gap:.1f}%)"
            )
        else:
            st.error(
                f"🔴 **STOP**\n\n"
                f"SPY **${spy_price:.1f}** < SMA200 **${spy_sma200:.1f}**\n\n"
                f"Bear 시장 — 오늘은 쉬세요 ({gap:.1f}%)"
            )
        st.metric("SPY 오늘 등락", f"{spy_chg:+.2f}%" if spy_chg else "N/A")
    else:
        st.warning("⚠️ SPY 데이터 없음 — 잠시 후 새로고침")
        spy_ok = False

# ── 신호 2: VIX ────────────────────────────────────────
with sig2:
    st.markdown("### 😨 신호 2: 시장 공포 (VIX)")
    if vix_now:
        vix_ok = vix_now <= 25
        if vix_now <= 15:
            vix_label = "매우 안정 — 최적 진입 환경"
            color = "success"
        elif vix_now <= 20:
            vix_label = "안정 — 양호한 환경"
            color = "success"
        elif vix_now <= 25:
            vix_label = "약간 불안 — 신중하게"
            color = "warning"
        else:
            vix_label = "공포 — 오늘은 쉬세요"
            color = "error"

        if color == "success":
            st.success(f"🟢 **GO**\n\nVIX **{vix_now:.1f}**\n\n{vix_label}")
        elif color == "warning":
            st.warning(f"🟡 **주의**\n\nVIX **{vix_now:.1f}**\n\n{vix_label}")
        else:
            st.error(f"🔴 **STOP**\n\nVIX **{vix_now:.1f}**\n\n{vix_label}")
            vix_ok = False
    else:
        st.warning("⚠️ VIX 데이터 없음")
        vix_ok = False
        vix_now = 0

# ── 신호 3: 주요 이벤트 (수동 체크) ──────────────────────
with sig3:
    st.markdown("### 📅 신호 3: 오늘 주요 이벤트")
    st.caption("아래 이벤트가 있으면 체크하세요")
    has_fed   = st.checkbox("🏦 Fed 금리 결정 발표")
    has_trade = st.checkbox("📢 관세/무역 발표")
    has_cpi   = st.checkbox("📊 CPI/PPI 물가 발표")
    has_other = st.checkbox("⚠️ 기타 대형 이벤트")

    event_risk = has_fed or has_trade or has_cpi or has_other
    if event_risk:
        st.error(
            "🔴 **STOP**\n\n"
            "대형 이벤트 당일은\n"
            "어떤 필터도 소용없음\n\n"
            "내일 다시 확인하세요"
        )
    else:
        st.success("🟢 **GO**\n\n이벤트 없음\n\n정상 매매 가능")

# ══════════════════════════════════════════════════════════
# ② 최종 GO / NO-GO 판정
# ══════════════════════════════════════════════════════════
st.divider()

all_green = (
    spy_price is not None and spy_price > (spy_sma200 or 0) and
    vix_now is not None and vix_now <= 25 and
    not event_risk
)

if spy_price and spy_sma200 and vix_now:
    if all_green:
        st.success(
            "## ✅ 오늘은 GO — 종목 스캔을 시작하세요\n\n"
            f"SPY 상승 구조 ✅ | VIX {vix_now:.1f} ✅ | 이벤트 없음 ✅"
        )
    elif event_risk:
        st.error("## 🔴 오늘은 NO-GO — 대형 이벤트 당일. 내일 다시 오세요.")
    elif vix_now > 25:
        st.error(f"## 🔴 오늘은 NO-GO — VIX {vix_now:.1f} 공포 구간. 시장이 안정될 때까지 대기.")
    elif spy_price <= (spy_sma200 or 0):
        st.error("## 🔴 오늘은 NO-GO — SPY Bear 시장. 롱 포지션 금지.")
    else:
        st.warning("## 🟡 오늘은 주의 — 조건 일부 미충족. 포지션 50% 축소.")

st.divider()

# ══════════════════════════════════════════════════════════
# ③ SPY 차트 (60일)
# ══════════════════════════════════════════════════════════
with st.expander("📈 SPY 60일 차트 보기", expanded=False):
    spy_hist = get_spy_chart()
    if not spy_hist.empty and PLOTLY_OK:
        spy_hist["SMA200"] = spy_hist["Close"].rolling(200).mean()
        spy_hist["SMA50"]  = spy_hist["Close"].rolling(50).mean()
        df60 = spy_hist.tail(60)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=df60.index, y=df60["Close"],
            name="SPY", line=dict(color="#00C853", width=2)
        ))
        fig.add_trace(go.Scatter(
            x=df60.index, y=df60["SMA50"],
            name="SMA50", line=dict(color="#42A5F5", width=1.5, dash="dash")
        ))
        fig.add_trace(go.Scatter(
            x=df60.index, y=df60["SMA200"],
            name="SMA200", line=dict(color="#FF7043", width=2)
        ))
        fig.update_layout(
            height=300, paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
            font=dict(color="#E0E0E0"), margin=dict(l=40, r=20, t=30, b=30),
            legend=dict(orientation="h", y=1.05),
            hovermode="x unified"
        )
        fig.update_xaxes(gridcolor="#1E1E1E")
        fig.update_yaxes(gridcolor="#1E1E1E")
        st.plotly_chart(fig, use_container_width=True)
    elif not spy_hist.empty:
        spy_hist["SMA200"] = spy_hist["Close"].rolling(200).mean()
        st.line_chart(spy_hist[["Close", "SMA200"]].tail(60))

st.divider()

# ══════════════════════════════════════════════════════════
# ④ Finviz 상승 종목 스캐너
# ══════════════════════════════════════════════════════════
st.markdown("## 🔍 상승 종목 스캐너")
st.caption(
    "SMA200 위 + SMA50 위 + RSI<60 + 3개월 +10% + 거래량 500K+  |  "
    "**GO 신호일 때만 의미 있습니다**"
)

sc1, sc2 = st.columns([1, 2])
with sc1:
    sector = st.selectbox(
        "📂 섹터 선택",
        ["Technology", "Healthcare", "Energy",
         "Consumer Cyclical", "Industrials", "전체"],
        index=0
    )
with sc2:
    st.markdown("**현재 고정 필터 (변경 불필요):**")
    st.markdown(
        "✅ SMA200 위  ✅ SMA50 위  ✅ RSI < 60  "
        "✅ 3개월 +10%  ✅ 거래량 500K+"
    )

run_scan = st.button(
    "🔍 종목 스캔 실행",
    type="primary",
    use_container_width=True,
    disabled=not all_green  # GO 아니면 버튼 비활성화
)

if not all_green:
    st.warning("⚠️ 신호등이 NO-GO입니다. 오늘은 스캔해도 의미가 없습니다.")

if run_scan and all_green:
    with st.spinner("Finviz 스크리닝 중..."):
        result = run_screener(sector, {})

    if isinstance(result, str):
        err = result
        if "ProxyError" in err or "ConnectionError" in err or "403" in err:
            st.error("🌐 Finviz 접속 실패. 1~2분 후 재시도하세요.")
        else:
            st.error(f"❌ 오류: {err[:200]}")
    elif result is None or (hasattr(result, 'empty') and result.empty):
        st.warning(
            "⚠️ 조건 충족 종목 없음.\n\n"
            "**가능한 이유:**\n"
            "- 오늘 시장이 전반적으로 부진\n"
            "- 섹터를 '전체'로 바꿔보세요\n"
            "- Quarter +10% 조건이 현재 시장에서 드문 상태"
        )
    else:
        st.success(f"✅ {len(result)}개 종목 발견!")

        # 표시 컬럼
        show_cols = [c for c in [
            "Ticker", "Company", "Sector", "Price", "Change",
            "Volume", "Relative Volume", "Market Cap", "P/E"
        ] if c in result.columns]

        st.dataframe(
            result[show_cols],
            use_container_width=True,
            hide_index=True
        )

        # 티커 목록
        if "Ticker" in result.columns:
            tickers = result["Ticker"].tolist()
            st.markdown("#### 🎯 발견 종목")
            st.code(", ".join(tickers[:20]))

        st.divider()

        # ── 개별 종목 차트 ─────────────────────────────────
        st.markdown("### 📈 개별 종목 차트 확인")
        st.caption("종목 선택 → 차트로 SMA200/50 정배열 + 패턴 눈으로 확인 → 최종 진입 결정")

        if "Ticker" in result.columns:
            selected = st.selectbox(
                "종목 선택",
                result["Ticker"].tolist()[:20]
            )

            if selected:
                with st.spinner(f"{selected} 차트 로딩..."):
                    stock_hist = get_stock_data(selected)

                if not stock_hist.empty:
                    stock_hist["SMA20"]  = stock_hist["Close"].rolling(20).mean()
                    stock_hist["SMA50"]  = stock_hist["Close"].rolling(50).mean()
                    stock_hist["SMA200"] = stock_hist["Close"].rolling(200).mean()

                    # 지표 계산
                    delta = stock_hist["Close"].diff()
                    g = delta.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    l = (-delta.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    stock_hist["RSI14"] = 100 - 100/(1 + g/l.replace(0, 1e-10))

                    df_show = stock_hist.tail(60)
                    curr    = df_show["Close"].iloc[-1]
                    s200    = df_show["SMA200"].iloc[-1]
                    s50     = df_show["SMA50"].iloc[-1]
                    rsi_now = df_show["RSI14"].iloc[-1]

                    # 간단 체크리스트
                    ck1, ck2, ck3, ck4 = st.columns(4)
                    with ck1:
                        if not pd.isna(s200) and curr > s200:
                            st.success(f"✅ SMA200 위\n${curr:.1f} > ${s200:.1f}")
                        else:
                            st.error(f"❌ SMA200 아래")
                    with ck2:
                        if not pd.isna(s50) and curr > s50:
                            st.success(f"✅ SMA50 위\n${curr:.1f} > ${s50:.1f}")
                        else:
                            st.error(f"❌ SMA50 아래")
                    with ck3:
                        if not pd.isna(rsi_now) and rsi_now < 60:
                            st.success(f"✅ RSI {rsi_now:.0f}\n과매수 아님")
                        elif not pd.isna(rsi_now) and rsi_now >= 70:
                            st.error(f"❌ RSI {rsi_now:.0f}\n과매수 — 추격 금지")
                        else:
                            st.warning(f"⚠️ RSI {rsi_now:.0f}\n주의")
                    with ck4:
                        # Finviz 링크
                        st.markdown(
                            f"**[👉 Finviz {selected} 차트]"
                            f"(https://finviz.com/quote.ashx?t={selected})**\n\n"
                            f"차트 패턴 눈으로 확인"
                        )

                    # 차트
                    if PLOTLY_OK:
                        fig2 = go.Figure()
                        # 캔들
                        fig2.add_trace(go.Candlestick(
                            x=df_show.index,
                            open=df_show["Open"], high=df_show["High"],
                            low=df_show["Low"],   close=df_show["Close"],
                            name=selected,
                            increasing_line_color="#00C853",
                            decreasing_line_color="#FF5252",
                            increasing_fillcolor="#00C853",
                            decreasing_fillcolor="#FF5252",
                        ))
                        for col, color, nm in [
                            ("SMA20",  "#FFD700", "SMA20"),
                            ("SMA50",  "#42A5F5", "SMA50"),
                            ("SMA200", "#FF7043", "SMA200"),
                        ]:
                            fig2.add_trace(go.Scatter(
                                x=df_show.index, y=df_show[col],
                                name=nm, line=dict(color=color, width=1.5)
                            ))
                        fig2.update_layout(
                            title=f"{selected} — 60일 캔들 차트",
                            height=400,
                            paper_bgcolor="#0E1117", plot_bgcolor="#0E1117",
                            font=dict(color="#E0E0E0"),
                            xaxis_rangeslider_visible=False,
                            margin=dict(l=40, r=20, t=50, b=30),
                            hovermode="x unified",
                            legend=dict(orientation="h", y=1.05)
                        )
                        fig2.update_xaxes(gridcolor="#1E1E1E")
                        fig2.update_yaxes(gridcolor="#1E1E1E")
                        st.plotly_chart(fig2, use_container_width=True)
                    else:
                        st.line_chart(df_show[["Close", "SMA20", "SMA50", "SMA200"]])

                    # 진입 가이드
                    st.divider()
                    g1, g2, g3 = st.columns(3)
                    with g1:
                        st.info(
                            "**📥 진입 조건**\n\n"
                            "① 신호등 3개 모두 초록\n"
                            "② SMA200·50 위 확인\n"
                            "③ 차트 상승 패턴 확인\n"
                            "④ RSI 60 미만 확인\n"
                            "⑤ 반등 양봉 캔들 후 진입"
                        )
                    with g2:
                        if not pd.isna(s50):
                            stop = curr * 0.95
                            st.warning(
                                f"**🛡️ 손절 설정**\n\n"
                                f"기본: 현재가 -5%\n"
                                f"= ${stop:.2f}\n\n"
                                f"SMA50(${s50:.1f}) 이탈 시\n"
                                f"즉시 손절"
                            )
                    with g3:
                        target1 = curr * 1.03
                        target2 = curr * 1.07
                        st.success(
                            f"**🎯 목표가**\n\n"
                            f"1차: ${target1:.2f} (+3%)\n"
                            f"2차: ${target2:.2f} (+7%)\n\n"
                            f"1차 도달 시 50% 청산"
                        )

# ══════════════════════════════════════════════════════════
# ⑤ 핵심 원칙 박스
# ══════════════════════════════════════════════════════════
st.divider()
st.markdown("### 📋 핵심 원칙 (항상 보이게)")
st.error(
    "**절대 원칙 3가지**\n\n"
    "① 신호등 하나라도 빨강 → 오늘 쉰다. 예외 없음.\n"
    "② 종목이 아무리 좋아도 시장이 NO-GO면 진입 금지.\n"
    "③ 손절가 미리 설정 안 하면 진입 금지."
)
st.info(
    "**매매 전 30초 체크리스트**\n\n"
    "□ SPY SMA200 위?  □ VIX 25 이하?  □ 오늘 이벤트 없음?\n"
    "□ 종목 SMA200 위?  □ SMA50 위?  □ RSI 60 이하?\n"
    "□ 손절가 설정했나?  → 전부 YES면 진입"
)
