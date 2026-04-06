"""
📊 APEX 시장 신호등 + 종목 스캐너 v2.0 (모바일 최적화)
────────────────────────────────────────────────────
핵심 원칙: 신호등 모두 초록일 때만 진입.
MOM: RVOL > 1.2 (거래량 동반 상승 확인)
MR : RVOL < 0.8 (과열 아님, 조용한 눌림목)

설치: pip install streamlit yfinance pandas plotly finvizfinance requests
실행: streamlit run APEX_modification_v2.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import requests
import datetime

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False

# ══════════════════════════════════════════════════════════
# 페이지 설정 — 모바일 최적화
# ══════════════════════════════════════════════════════════
st.set_page_config(
    page_title="🚦 APEX 신호등",
    layout="centered",
    page_icon="🚦",
    initial_sidebar_state="collapsed"
)

st.markdown("""
<style>
    html, body, [class*="css"] { font-size: 16px; }
    .stButton > button {
        height: 3.5rem;
        font-size: 1.1rem;
        font-weight: bold;
        border-radius: 12px;
    }
    [data-testid="stMetric"] {
        background: #1E1E2E;
        border-radius: 12px;
        padding: 12px;
    }
    .signal-box {
        border-radius: 16px;
        padding: 16px;
        margin: 8px 0;
        font-size: 1.1rem;
    }
    .block-container { padding-top: 1rem; }
    .stSelectbox > div > div { font-size: 1rem; }
    .sentiment-bar {
        height: 24px;
        border-radius: 8px;
        margin: 6px 0;
        transition: width 0.3s ease;
    }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════
# 캐시 함수
# ══════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def get_index_signal(ticker: str):
    """SPY 또는 QQQ 신호 반환: (price, sma200, chg)"""
    try:
        hist = yf.Ticker(ticker).history(period="300d", interval="1d")
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

@st.cache_data(ttl=900, show_spinner=False)
def get_social_sentiment(ticker: str):
    """
    소셜미디어 감성지수 추정 (StockTwits 공개 API 사용)
    bullish_count / (bullish_count + bearish_count) × 100
    API 실패 시 None 반환 → UI에서 안내 표시
    """
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        resp = requests.get(url, timeout=5)
        if resp.status_code != 200:
            return None
        data = resp.json()
        messages = data.get("messages", [])
        if not messages:
            return None
        bull = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}) and
                   m["entities"]["sentiment"].get("basic") == "Bullish")
        bear = sum(1 for m in messages if m.get("entities", {}).get("sentiment", {}) and
                   m["entities"]["sentiment"].get("basic") == "Bearish")
        total = bull + bear
        if total == 0:
            return None
        return round(bull / total * 100, 1)
    except Exception:
        return None


# ══════════════════════════════════════════════════════════
# ① 타이틀
# ══════════════════════════════════════════════════════════
st.markdown("# 🚦 APEX 시장 신호등 v2")
st.caption("신호등 모두 초록 → 진입 / 하나라도 빨강 → 오늘 쉬기")

if st.button("🔄 신호 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()


# ══════════════════════════════════════════════════════════
# ② 데이터 로드
# ══════════════════════════════════════════════════════════
with st.spinner("시장 데이터 확인 중..."):
    spy_price, spy_sma200, spy_chg = get_index_signal("SPY")
    qqq_price, qqq_sma200, qqq_chg = get_index_signal("QQQ")
    vix_now = get_vix_signal()


# ══════════════════════════════════════════════════════════
# ③ 신호등
# ══════════════════════════════════════════════════════════

# 신호 1-A: SPY
if spy_price and spy_sma200:
    spy_ok  = spy_price > spy_sma200
    spy_gap = (spy_price - spy_sma200) / spy_sma200 * 100
    # "오늘 등락"은 당일 종가 기준 전일 대비 변동률
    chg_note = "📈 상승" if spy_chg > 0 else "📉 하락"
    if spy_ok:
        st.success(
            f"**① 시장 추세 (SPY) 🟢 GO**\n\n"
            f"SPY ${spy_price:.1f} > SMA200 ${spy_sma200:.1f} ({spy_gap:+.1f}%)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** {chg_note} ← 전일 대비 당일 종가 변동"
        )
    else:
        st.error(
            f"**① 시장 추세 (SPY) 🔴 주의**\n\n"
            f"SPY ${spy_price:.1f} < SMA200 ${spy_sma200:.1f} ({spy_gap:.1f}%)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** {chg_note} — 종목별 확인 필요"
        )
else:
    st.warning("**① 시장 추세 (SPY) ⚪ 데이터 없음** — 새로고침 해보세요")
    spy_ok = False

# 신호 1-B: QQQ (나스닥 기술주 추세 확인용)
if qqq_price and qqq_sma200:
    qqq_ok  = qqq_price > qqq_sma200
    qqq_gap = (qqq_price - qqq_sma200) / qqq_sma200 * 100
    qqq_note = "📈 상승" if qqq_chg > 0 else "📉 하락"
    if qqq_ok:
        st.success(
            f"**① 시장 추세 (QQQ) 🟢 GO**\n\n"
            f"QQQ ${qqq_price:.1f} > SMA200 ${qqq_sma200:.1f} ({qqq_gap:+.1f}%)\n\n"
            f"오늘 등락: **{qqq_chg:+.2f}%** {qqq_note}"
        )
    else:
        st.error(
            f"**① 시장 추세 (QQQ) 🔴 주의**\n\n"
            f"QQQ ${qqq_price:.1f} < SMA200 ${qqq_sma200:.1f} ({qqq_gap:.1f}%)\n\n"
            f"오늘 등락: **{qqq_chg:+.2f}%** {qqq_note} — 기술주 주의"
        )
else:
    st.warning("**① 시장 추세 (QQQ) ⚪ 데이터 없음**")
    qqq_ok = False

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
# ④ 최종 판정
# ══════════════════════════════════════════════════════════
spy_ok_val  = spy_price is not None and spy_price > (spy_sma200 or 0)
qqq_ok_val  = qqq_price is not None and qqq_price > (qqq_sma200 or 0)
vix_ok_val  = vix_now is not None and vix_now <= 25
all_green = spy_ok_val and qqq_ok_val and vix_ok_val and not event_risk

if all_green:
    st.markdown("""
    <div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">✅</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#00C853">GO — 진입 가능</div>
        <div style="color:#aaa;margin-top:8px">SPY·QQQ·VIX·이벤트 모두 충족</div>
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
elif not spy_ok_val or not qqq_ok_val:
    idx_warn = []
    if not spy_ok_val: idx_warn.append("SPY")
    if not qqq_ok_val: idx_warn.append("QQQ")
    st.markdown(f"""
    <div style="background:#2d2d00;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🟡</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FFD700">{"/".join(idx_warn)} 주의</div>
        <div style="color:#aaa;margin-top:8px">스캔 가능 — 종목별 SMA200 확인 필수</div>
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

# 전략 선택 — RVOL 기준이 MOM/MR에 따라 달라짐
strategy_mode = st.radio(
    "전략 모드",
    ["MOM (모멘텀)", "MR (평균회귀)"],
    horizontal=True,
    help="MOM: RVOL > 1.2 (거래량 동반 강세) | MR: RVOL < 0.8 (과열 없는 눌림목)"
)
is_mom = strategy_mode == "MOM (모멘텀)"

if "scan_result" not in st.session_state:
    st.session_state.scan_result = None
if "scan_sector" not in st.session_state:
    st.session_state.scan_sector = "Technology"

sector = st.selectbox(
    "섹터",
    ["Technology", "Healthcare", "Energy",
     "Consumer Cyclical", "Industrials", "전체"],
    index=0,
    key="sector_select"
)

if not all_green:
    if event_risk:
        st.error("⚠️ 이벤트 있음 — 스캔 비권장")
    elif not spy_ok_val or not qqq_ok_val:
        st.warning("⚠️ SPY/QQQ SMA200 아래 — 종목별 SMA200 확인 필수")
    elif not vix_ok_val:
        st.warning("⚠️ VIX 높음 — 포지션 50% 줄이기")

col_scan1, col_scan2 = st.columns([3, 1])
with col_scan1:
    run_scan = st.button("🔍 스캔 실행", type="primary", use_container_width=True)
with col_scan2:
    clear_scan = st.button("🗑️ 초기화", use_container_width=True)

if clear_scan:
    st.session_state.scan_result = None
    st.rerun()

if run_scan:
    with st.spinner("Finviz 스크리닝 중..."):
        result = run_screener(sector)
    st.session_state.scan_result = result
    st.session_state.scan_sector = sector

result = st.session_state.scan_result

if result is not None:
    if isinstance(result, str):
        err = result
        if any(k in err for k in ["ProxyError", "ConnectionError", "403"]):
            st.error("🌐 Finviz 접속 실패. 1~2분 후 재시도.")
        else:
            st.error(f"❌ 오류: {err[:200]}")

    elif result is None or (hasattr(result, "empty") and result.empty):
        st.warning("⚠️ 조건 충족 종목 없음\n\n섹터를 '전체'로 바꿔보세요")
    else:
        st.success(f"✅ {len(result)}개 종목 발견!")

        # RVOL 컬럼 없으면 yfinance로 직접 계산해서 추가
        if "Relative Volume" not in result.columns and "Ticker" in result.columns:
            rvol_map = {}
            for tk in result["Ticker"].tolist():
                try:
                    h = yf.Ticker(tk).history(period="25d", interval="1d")
                    if not h.empty and len(h) >= 2:
                        avg = float(h["Volume"].iloc[:-1].mean())
                        last = float(h["Volume"].iloc[-1])
                        rvol_map[tk] = round(last / avg, 2) if avg > 0 else None
                except Exception:
                    rvol_map[tk] = None
            result = result.copy()
            result["RVOL"] = result["Ticker"].map(rvol_map)

        # 표시 컬럼 — RVOL 우선순위로
        show_cols = [c for c in ["Ticker","Company","Price","Change","RVOL","Relative Volume"] if c in result.columns]
        st.dataframe(result[show_cols], use_container_width=True, hide_index=True)

        if "Ticker" in result.columns:
            tickers = result["Ticker"].tolist()
            st.markdown("#### 발견 종목")
            st.code(", ".join(tickers))

        st.divider()

        # ── 종목 체크리스트 ──
        st.markdown("#### 📈 종목 체크리스트")
        if "Ticker" in result.columns:
            selected = st.selectbox(
                "종목 선택",
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

                    chg_3m = None
                    if len(hist) >= 63:
                        chg_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-63] - 1) * 100

                    avg_vol  = hist["Volume"].tail(20).mean()
                    rvol_now = hist["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0

                    # ── 체크카드 ──
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

                    mc1, mc2 = st.columns(2)
                    with mc1:
                        if chg_3m is not None:
                            if chg_3m >= 10:
                                st.success(f"📈 3개월 수익률\n+{chg_3m:.1f}% ✅")
                            else:
                                st.warning(f"📈 3개월 수익률\n{chg_3m:+.1f}%")

                    with mc2:
                        # ── RVOL: MOM vs MR 분기 ──
                        if is_mom:
                            # MOM: RVOL > 1.2 = 거래량 동반 상승 → 긍정
                            if rvol_now > 1.2:
                                st.success(f"✅ RVOL {rvol_now:.1f}x\n[MOM] 거래량 동반 ↑")
                            elif rvol_now > 0.8:
                                st.warning(f"🟡 RVOL {rvol_now:.1f}x\n[MOM] 거래량 보통")
                            else:
                                st.error(f"❌ RVOL {rvol_now:.1f}x\n[MOM] 거래량 부족")
                        else:
                            # MR: RVOL < 0.8 = 조용한 눌림목 → 긍정
                            if rvol_now < 0.8:
                                st.success(f"✅ RVOL {rvol_now:.1f}x\n[MR] 조용한 눌림목 ↓")
                            elif rvol_now < 1.2:
                                st.warning(f"🟡 RVOL {rvol_now:.1f}x\n[MR] 보통 수준")
                            else:
                                st.error(f"❌ RVOL {rvol_now:.1f}x\n[MR] 과열, 눌림목 아님")

                    # ── 소셜미디어 감성지수 ──
                    st.divider()
                    st.markdown(f"#### 💬 소셜미디어 감성지수 — {selected}")
                    st.caption("StockTwits 최근 메시지 기반 | 새로고침마다 업데이트")

                    with st.spinner("감성 분석 중..."):
                        sentiment_pct = get_social_sentiment(selected)

                    if sentiment_pct is not None:
                        # 색상 결정
                        if sentiment_pct >= 65:
                            bar_color = "#00C853"
                            label = "🟢 긍정 신호"
                            desc  = "투자자 심리 강세 — 모멘텀 뒷받침"
                        elif sentiment_pct >= 45:
                            bar_color = "#FFD700"
                            label = "🟡 중립"
                            desc  = "방향성 불분명 — 추가 확인 필요"
                        else:
                            bar_color = "#FF5252"
                            label = "🔴 부정 신호"
                            desc  = "투자자 심리 약세 — 진입 주의"

                        neg_pct = 100 - sentiment_pct

                        # 게이지 바
                        st.markdown(f"""
                        <div style="margin:8px 0">
                            <div style="display:flex;justify-content:space-between;font-size:0.85rem;color:#aaa">
                                <span>부정 {neg_pct:.0f}%</span>
                                <span>긍정 {sentiment_pct:.0f}%</span>
                            </div>
                            <div style="background:#333;border-radius:8px;height:22px;overflow:hidden">
                                <div style="width:{sentiment_pct}%;background:{bar_color};
                                            height:100%;border-radius:8px;
                                            transition:width 0.4s ease"></div>
                            </div>
                            <div style="text-align:center;font-size:1.1rem;font-weight:bold;
                                        margin-top:6px;color:{bar_color}">{label}</div>
                            <div style="text-align:center;color:#aaa;font-size:0.85rem">{desc}</div>
                        </div>
                        """, unsafe_allow_html=True)

                        # 판단 기준 안내
                        with st.expander("감성지수 판단 기준"):
                            st.markdown("""
                            | 수치 | 의미 |
                            |------|------|
                            | **65% 이상** | 🟢 긍정 — MOM 진입 뒷받침 |
                            | **45~64%** | 🟡 중립 — 단독 판단 금물 |
                            | **44% 이하** | 🔴 부정 — 진입 재검토 |

                            ※ 수치가 높을수록 긍정(Bullish) 비율 높음  
                            ※ 단독 지표로 사용 금지 — SMA/RSI/RVOL과 종합 판단
                            """)
                    else:
                        st.info(
                            "⚪ 감성 데이터 없음\n\n"
                            "StockTwits에 해당 종목 최근 메시지가 부족하거나 API 일시 제한 상태입니다.\n"
                            "1~2분 후 새로고침 해보세요."
                        )

                    # ── 차트 ──
                    st.divider()
                    if PLOTLY_OK:
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

                    st.markdown(
                        f"[👉 Finviz {selected} 차트 열기]"
                        f"(https://finviz.com/quote.ashx?t={selected})"
                    )

                    # ── 손절/목표가 ──
                    st.divider()
                    # 손절: SMA20 기준 (추세 기반 논리적 손절)
                    s20 = float(df60["SMA20"].iloc[-1]) if not pd.isna(df60["SMA20"].iloc[-1]) else None
                    tgt1 = curr * 1.03
                    tgt2 = curr * 1.07
                    sc1, sc2, sc3 = st.columns(3)
                    with sc1:
                        if s20:
                            stop_pct = (s20 - curr) / curr * 100
                            st.error(f"🛑 손절 (SMA20)\n${s20:.2f}\n({stop_pct:.1f}%)\n종가 이탈 시 청산")
                        else:
                            st.error(f"🛑 손절\nSMA20 계산 불가")
                    with sc2:
                        st.success(f"🎯 목표1\n${tgt1:.2f}\n(+3%)")
                    with sc3:
                        st.success(f"🎯 목표2\n${tgt2:.2f}\n(+7%)")
                    st.caption("⚠️ 손절 기준: SMA20 아래 종가 마감 시 청산 — 장중 노이즈에 흔들리지 말 것")

st.divider()


# ══════════════════════════════════════════════════════════
# ⑥ 핵심 체크리스트
# ══════════════════════════════════════════════════════════
st.markdown("### 📋 진입 체크리스트")
st.markdown("""
□ SPY + QQQ 신호등 초록?  
□ VIX 25 이하?  
□ 이벤트 없음?  
□ 종목 SMA200 위?  
□ 종목 SMA50 위?  
□ RSI 60 미만?  
□ RVOL 전략 기준 충족? (MOM > 1.2 / MR < 0.8)  
□ 소셜 감성지수 45% 이상?  
□ 손절가 설정 완료? (SMA20 아래 종가 마감 시 청산)  
→ 전부 ✅면 진입
""")
st.error("**손절 원칙: SMA20 아래 종가 마감 = 즉시 청산 / 장중 노이즈에 흔들리지 말 것**")
