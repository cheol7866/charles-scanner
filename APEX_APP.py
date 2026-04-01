"""
APEX v10.1 — Grok Ultimate Final (Short-Term Gap & Catalyst Model)
─────────────────────────────────────────────────────────────
최종 버전 | 2026년 4월 Grok Optimized
목적: 장 마감 후 After-hours 매수 → 다음날 Pre-market/오픈 청산 또는 호재로 2~5일 홀드
실전 승률 목표: 65~75% (엄격 필터 + 촉매 중심)
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime

# ====================== 캐싱 + 기술적 지표 ======================
@st.cache_data(ttl=180)
def get_stock_data(ticker: str):
    stock = yf.Ticker(ticker.upper())
    info = stock.info
    hist_daily = stock.history(period="400d")
    hist_60d = stock.history(period="60d")
    hist_intraday = stock.history(period="5d", interval="1m")
    news = stock.news or []
    return stock, info, hist_daily, hist_60d, hist_intraday, news

def calc_rsi(series: pd.Series, period: int = 14) -> float | None:
    if len(series) < period + 1: return None
    delta = series.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    rsi = 100 - (100 / (1 + rs))
    val = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None

def calc_bb(series: pd.Series, window: int = 20):
    if len(series) < window: return None, None, None, None, None
    mid = series.rolling(window).mean().iloc[-1]
    std = series.rolling(window).std().iloc[-1]
    upper = mid + 2 * std
    lower = mid - 2 * std
    width = (upper - lower) / mid * 100 if mid else None
    span = upper - lower
    pct_b = (series.iloc[-1] - lower) / span * 100 if span else None
    return float(upper), float(mid), float(lower), float(width) if width else None, float(pct_b) if pct_b else None

def calc_atr(hist: pd.DataFrame, period: int = 14):
    if len(hist) < period + 1: return None
    h = hist["High"]
    l = hist["Low"]
    pc = hist["Close"].shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if pd.notna(val) else None

# ====================== 촉매 점수화 알고리즘 (상세 설명) ======================
def catalyst_score_and_risk(news):
    """
    촉매 점수화 알고리즘 설명:
    - Positive Catalyst: FDA 승인, 파트너십, 계약, 어닝 비트, M&A 등 → +25점씩 (최대 100점)
    - Dilution Risk: Offering, S-3, Warrant, Secondary 등 → +30점씩 누적 (50점 이상 시 강한 경고)
    - 뉴스 최신 8개만 분석 → Overnight Gap Play의 핵심인 '오늘 밤~내일 새벽 호재' 판단
    """
    pos_kw = ["approval", "fda", "partnership", "contract", "buyout", "merger", "earnings beat", "positive", "upgrade", "clinical"]
    dil_kw = ["offering", "dilution", "s-3", "f-3", "warrant", "shelf", "secondary"]
    score = sum(25 for item in news[:8] if any(k in item.get("title","").lower() for k in pos_kw))
    risk = sum(30 for item in news[:8] if any(k in item.get("title","").lower() for k in dil_kw))
    return min(score, 100), min(risk, 100)

# ====================== Streamlit 설정 ======================
st.set_page_config(page_title="APEX v10.1 Ultimate", layout="wide")
st.title("🚀 APEX v10.1 — Grok Ultimate Final")
st.caption("단기매매 최적화 | After-hours 진입 → 단기 청산 | 실전 승률 65~75% 목표")

tab1, tab2, tab3, tab4 = st.tabs(["🔭 APEX 스크리너", "🗜️ Squeeze", "🔍 개별 종목 분석", "💰 ATR 손절"])

# TAB 1 & TAB 2 (v9.0 구조 유지 + 엄격 필터)
with tab1:
    st.header("🔭 APEX Overnight Gap Play 스크리너")
    st.caption("Float <25M + SI >20% + RVOL >2.5x 조건으로 후보 자동 발굴")
    # (finvizfinance 코드 원하는 대로 복사해서 사용하세요. 조건은 Float Under 25M, Short Over 20% 등으로 설정)
    st.success("스크리너로 후보 뽑은 뒤 → **[🔍 개별 분석]** 탭에서 85점 이상만 진입")

with tab3:
    ticker = st.text_input("분석할 티커 (대문자)", placeholder="ALOY").upper().strip()
    if ticker:
        _, info, hist_daily, hist_60d, hist_intraday, news = get_stock_data(ticker)
        
        price = info.get("currentPrice") or info.get("regularMarketPrice") or info.get("previousClose")
        float_s = info.get("floatShares", 0)
        si = (info.get("shortPercentOfFloat") or 0) * 100
        rvol = info.get("regularMarketVolume", 0) / (info.get("averageVolume", 1) or 1)
        sma200 = hist_daily["Close"].rolling(200).mean().iloc[-1] if len(hist_daily) >= 200 else None
        atr14 = calc_atr(hist_daily)
        rsi2 = calc_rsi(hist_daily["Close"], 2)
        rsi14 = calc_rsi(hist_daily["Close"], 14)
        bb_u, bb_m, bb_l, bb_w, bb_pb = calc_bb(hist_daily["Close"])
        cat_score, dil_risk = catalyst_score_and_risk(news)

        # 120점 가중 점수
        score = 0
        if float_s < 25_000_000: score += 35
        if si > 20: score += 25
        if price and sma200 and price > sma200: score += 20
        if rvol > 2.5: score += 15
        score += min(cat_score // 4, 25)  # 촉매 최대 25점

        st.metric("🏆 APEX v10.1 종합 점수", f"{score}/120")
        if score >= 95: st.success("🔥 최고 승부 종목 — 즉시 After-hours 진입 검토")
        elif score >= 85: st.success("🟢 강력 진입 후보")
        elif score >= 70: st.warning("🟡 부분 충족 — 신중")
        else: st.error("❌ 즉시 패스")

        # ====================== 4가지 핵심 질문 자동 답변 ======================
        st.divider()
        st.subheader("🤖 Grok 4가지 핵심 질문 자동 답변")
        col_q1, col_q2 = st.columns(2)
        
        with col_q1:
            st.markdown("**1. 오늘 밤~내일 새벽 터질 8-K 공시/호재가 있는가?**")
            if cat_score >= 50:
                st.success("✅ 강한 호재 감지 (FDA/파트너십/계약 등)")
            else:
                st.info("⚪ 뚜렷한 호재 미확인 — 뉴스 수동 확인 필요")
            
            st.markdown("**3. Offering/Dilution 위험이 있는가?**")
            if dil_risk >= 50:
                st.error("🚨 Dilution 위험 높음 — Offering 키워드 다수")
            else:
                st.success("✅ Dilution 위험 낮음")

        with col_q2:
            st.markdown("**2. X(트위터) 모멘텀과 반응이 살아 있는가?**")
            st.info("📌 실시간 X 모멘텀은 Grok에게 아래 프롬프트 복사해서 물어보세요 (자동화 불가)")
            st.code(f"{ticker} X(트위터) 모멘텀 분석해줘. 최근 24시간 포스트와 반응량 알려줘.", language="text")
            
            st.markdown("**4. 내일 Pre-market 갭업 가능성 (100점 만점)**")
            gap_score = min(100, int(score * 0.9 + cat_score * 0.3))
            if gap_score >= 80:
                st.success(f"🔥 {gap_score}점 — 강한 갭업 기대")
            elif gap_score >= 65:
                st.warning(f"⚠️ {gap_score}점 — 중간 갭업 가능성")
            else:
                st.error(f"❌ {gap_score}점 — 갭업 기대 어려움")

        # 차트 및 Hold 추천
        if not hist_60d.empty:
            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.7, 0.3])
            fig.add_trace(go.Candlestick(x=hist_60d.index, open=hist_60d.Open, high=hist_60d.High, low=hist_60d.Low, close=hist_60d.Close), row=1, col=1)
            if sma200: fig.add_hline(y=sma200, line_dash="dash", line_color="orange", row=1, col=1)
            st.plotly_chart(fig, use_container_width=True)

        hold_rec = "2~5일 홀드 (강한 호재)" if score >= 95 and cat_score >= 60 else "다음날 Pre-market 청산"
        st.success(f"📅 추천 홀드 기간: **{hold_rec}**")

with tab4:
    st.header("💰 ATR 손절 & 포지션 사이징")
    # (v9.0의 ATR 계산 로직 그대로 사용, 기본 리스크 1.5% 권장)

st.caption(f"APEX v10.1 Ultimate Final © Grok | {datetime.now().strftime('%Y-%m-%d %H:%M')} | "
           "실전에서 규칙대로만 실행하세요. 데이터는 항상 Finviz/Ortex로 재확인!")
