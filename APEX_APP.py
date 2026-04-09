"""
📊 APEX 시장 신호등 + 종목 스캐너 v3.0 (리팩토링 버전)
═══════════════════════════════════════════════════════════
핵심 원칙: 신호등 모두 초록일 때만 진입.
MOM: RVOL > 1.2 (거래량 동반 상승 확인)
MR : RVOL < 0.8 (과열 아님, 조용한 눌림목)

설치: pip install streamlit yfinance pandas plotly finvizfinance requests
실행: streamlit run apex_app.py

모든 지표·분석 로직은 apex_core.py 에 있습니다.
전략 수정 시 apex_core.py 만 변경하면 됩니다.
"""

import datetime

import pandas as pd
import streamlit as st
import yfinance as yf

# 공유 핵심 모듈 임포트
from apex_core import (
    calc_rsi, calc_sma, calc_bollinger, calc_atr, calc_rvol, consec_down,
    get_index_data, get_vix, get_spy_rsi2, get_stock_data,
    get_earnings_info,
    get_regime, calc_margins,
    run_finviz_screen, analyze_stock, check_exit_signals,
    sort_results, SCORE_ORDER, SCORE_EMOJI, REGIME_EMOJI,
)

try:
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots
    PLOTLY_OK = True
except ImportError:
    PLOTLY_OK = False


# ══════════════════════════════════════════════════════
# 페이지 설정
# ══════════════════════════════════════════════════════
st.set_page_config(page_title="🚦 APEX 신호등", layout="centered", page_icon="🚦", initial_sidebar_state="collapsed")

st.markdown("""
<style>
    html, body, [class*="css"] { font-size: 16px; }
    .stButton > button { height: 3.5rem; font-size: 1.1rem; font-weight: bold; border-radius: 12px; }
    [data-testid="stMetric"] { background: #1E1E2E; border-radius: 12px; padding: 12px; color: #FFFFFF; }
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricDelta"] { color: #FFFFFF !important; }
    .block-container { padding-top: 1rem; }
</style>
""", unsafe_allow_html=True)


# ══════════════════════════════════════════════════════
# 캐시 래퍼 (Streamlit 캐시 + apex_core 호출)
# ══════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False)
def _cached_index(ticker):
    return get_index_data(ticker)

@st.cache_data(ttl=300, show_spinner=False)
def _cached_vix():
    return get_vix()

@st.cache_data(ttl=600, show_spinner=False)
def _cached_stock(ticker):
    return get_stock_data(ticker)

@st.cache_data(ttl=3600, show_spinner=False)
def _cached_earnings(ticker):
    return get_earnings_info(ticker)

@st.cache_data(ttl=600, show_spinner=False)
def _cached_finviz(mode, sectors_tuple):
    return run_finviz_screen(mode, list(sectors_tuple))

@st.cache_data(ttl=600, show_spinner=False)
def _cached_analyze(ticker, mode, spy_rsi2_val, mom_ok_val, vix_ok_val, account_sz, risk_p):
    return analyze_stock(ticker, mode, spy_rsi2_val, mom_ok_val, vix_ok_val, account_sz, risk_p)

@st.cache_data(ttl=600, show_spinner=False)
def _cached_screener_simple(sector, mode):
    """수동 분석 탭용 단순 스크리닝 (섹터 1개)."""
    sectors = [sector] if sector != "전체" else ["전체"]
    return run_finviz_screen(mode, sectors)


# ══════════════════════════════════════════════════════
# ① 타이틀 + 새로고침
# ══════════════════════════════════════════════════════
st.markdown("# 🚦 APEX 시장 신호등 v3")
st.caption("신호등 모두 초록 → 진입 / 하나라도 빨강 → 오늘 쉬기")

if st.button("🔄 신호 새로고침", use_container_width=True):
    st.cache_data.clear()
    st.rerun()

st.divider()


# ══════════════════════════════════════════════════════
# ② 데이터 로드
# ══════════════════════════════════════════════════════
with st.spinner("시장 데이터 확인 중..."):
    spy_price, spy_sma200, spy_chg = _cached_index("SPY")
    qqq_price, qqq_sma200, qqq_chg = _cached_index("QQQ")
    vix_now = _cached_vix()


# ══════════════════════════════════════════════════════
# ③ 신호등 표시
# ══════════════════════════════════════════════════════

def _show_index_signal(label: str, price, sma200, chg):
    """SPY / QQQ 신호등 공통."""
    if price and sma200:
        gap = (price - sma200) / sma200 * 100
        chg_note = "📈 상승" if chg > 0 else "📉 하락"
        if gap >= 3:
            st.success(f"**{label} 🟢 GO**\n\n${price:.1f} > SMA200 ${sma200:.1f} (**{gap:+.1f}%** ≥ 3%)\n\n오늘: **{chg:+.2f}%** {chg_note}")
        elif gap > 0:
            st.warning(f"**{label} 🟡 경계**\n\n${price:.1f} > SMA200 ${sma200:.1f} (**{gap:+.1f}%** < 3%)\n\n오늘: **{chg:+.2f}%** {chg_note} — MOM 금지 구간")
        else:
            st.error(f"**{label} 🔴 주의**\n\n${price:.1f} < SMA200 ${sma200:.1f} ({gap:.1f}%)\n\n오늘: **{chg:+.2f}%** {chg_note}")
        return gap >= 3
    else:
        st.warning(f"**{label} ⚪ 데이터 없음** — 새로고침 해보세요")
        return False

spy_ok_val = _show_index_signal("① 시장 추세 (SPY)", spy_price, spy_sma200, spy_chg)
qqq_ok_val = _show_index_signal("① 시장 추세 (QQQ)", qqq_price, qqq_sma200, qqq_chg)

# VIX
if vix_now:
    if vix_now <= 15:
        vix_ok = True; st.success(f"**② VIX 🟢 매우 안정** — {vix_now:.1f}")
    elif vix_now <= 20:
        vix_ok = True; st.success(f"**② VIX 🟢 안정** — {vix_now:.1f}")
    elif vix_now <= 25:
        vix_ok = True; st.warning(f"**② VIX 🟡 약간 불안** — {vix_now:.1f} — 포지션 줄이기")
    else:
        vix_ok = False; st.error(f"**② VIX 🔴 공포** — {vix_now:.1f} — 진입 자제")
else:
    st.warning("**② VIX ⚪ 데이터 없음**")
    vix_ok = False
    vix_now = 0

# 이벤트 (수동)
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


# ══════════════════════════════════════════════════════
# ④ 최종 판정
# ══════════════════════════════════════════════════════
vix_ok_val = vix_now is not None and vix_now <= 25
all_green = spy_ok_val and qqq_ok_val and vix_ok_val and not event_risk

_spy_border = spy_price is not None and spy_sma200 is not None and spy_price > spy_sma200 and not spy_ok_val
_qqq_border = qqq_price is not None and qqq_sma200 is not None and qqq_price > qqq_sma200 and not qqq_ok_val
_is_border = (_spy_border or _qqq_border) and vix_ok_val and not event_risk

def _verdict_html(emoji, title, sub, bg):
    return f"""<div style="background:{bg};border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">{emoji}</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#{'00C853' if bg=='#1a4731' else 'FF5252' if bg=='#3d1a1a' else 'FFD700'}">{title}</div>
        <div style="color:#aaa;margin-top:8px">{sub}</div>
    </div>"""

if all_green:
    st.markdown(_verdict_html("✅", "GO — 진입 가능", "SPY·QQQ·VIX·이벤트 모두 충족", "#1a4731"), unsafe_allow_html=True)
elif event_risk:
    st.markdown(_verdict_html("🔴", "이벤트 주의", "내일 다시 확인하세요", "#3d1a1a"), unsafe_allow_html=True)
elif _is_border:
    st.markdown(_verdict_html("🟡", "경계 구간 — MR만 가능", "SPY/QQQ SMA200 위이나 3% 미달 → MOM 금지", "#2d2d00"), unsafe_allow_html=True)
elif not spy_ok_val or not qqq_ok_val:
    idx_warn = [x for x, ok in [("SPY", spy_ok_val), ("QQQ", qqq_ok_val)] if not ok]
    st.markdown(_verdict_html("🟡", f"{'/'.join(idx_warn)} 주의", "종목별 SMA200 확인 필수", "#2d2d00"), unsafe_allow_html=True)
else:
    st.markdown(_verdict_html("🟡", "VIX 주의", "포지션 50% 줄이고 진입", "#2d2d00"), unsafe_allow_html=True)

st.divider()


# ══════════════════════════════════════════════════════
# 공통 레짐 계산
# ══════════════════════════════════════════════════════
_spy_rsi2_dr = get_spy_rsi2()
_spy_margin_dr, _qqq_margin_dr = calc_margins(spy_price, spy_sma200, qqq_price, qqq_sma200)
_regime_dr = get_regime(spy_price, spy_sma200, qqq_price, qqq_sma200)
_mom_ok_dr = _regime_dr in ["STRONG_BULL", "WEAK_BULL"]
_mr_ok_dr = _spy_rsi2_dr is not None and _spy_rsi2_dr > 10
_vix_ok_dr = vix_now is not None and vix_now <= 25

if _spy_rsi2_dr is not None and _spy_rsi2_dr <= 10:
    st.error(f"⛔ SPY RSI(2) = {_spy_rsi2_dr:.1f} ≤ 10 — 시장 패닉, MR도 진입 금지")

st.divider()


# ══════════════════════════════════════════════════════
# 탭 구성
# ══════════════════════════════════════════════════════
tab_report, tab_manual, tab_hold = st.tabs(["📊 Daily Report (자동)", "🚦 신호등 + 수동 분석", "📌 보유 종목 모니터"])


# ──────────────────────────────────────────
# TAB 1: Daily Report
# ──────────────────────────────────────────
with tab_report:
    st.markdown("### 📊 APEX Daily Report — 자동 스크리닝")
    st.caption("버튼 한 번 → Finviz 프리필터 → 체크리스트 자동 채점 → 등급 + 매수 타이밍")

    with st.expander("⚙️ Daily Report 설정", expanded=False):
        dr_c1, dr_c2 = st.columns(2)
        with dr_c1:
            dr_account = st.number_input("💰 계좌 (USD)", 500, 500000, 5000, 500, key="dr_account")
            dr_risk = st.slider("🎯 1회 리스크 %", 0.5, 3.0, 1.0, 0.5, key="dr_risk")
        with dr_c2:
            dr_sectors = st.multiselect(
                "📂 섹터 필터",
                ["전체", "Technology", "Industrials", "Healthcare", "Consumer Cyclical",
                 "Communication Services", "Financial", "Energy", "Basic Materials"],
                default=["전체"], key="dr_sectors",
            )
            if "전체" in dr_sectors:
                dr_sectors = ["전체"]

    # 레짐 요약
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1: st.metric("레짐", f"{REGIME_EMOJI.get(_regime_dr, '⚪')} {_regime_dr}", f"SPY {_spy_margin_dr:+.1f}% / QQQ {_qqq_margin_dr:+.1f}%")
    with rc2: st.metric("SPY RSI(2)", f"{_spy_rsi2_dr:.1f}" if _spy_rsi2_dr else "N/A")
    with rc3: st.metric("MOM", "✅ 허용" if _mom_ok_dr else "🚫 금지")
    with rc4: st.metric("MR", "✅ 허용" if _mr_ok_dr else "🚫 금지")

    with st.expander("📈 승률 참고 (Connors RSI(2) 연구 기반)"):
        st.markdown("""
| 통과 수준 | 추정 승률 (2~5일) | 근거 |
|---|---|---|
| 필수만 통과 | 60~65% | RSI(2) 단독 |
| 필수 + 선호 70% | 68~75% | 복합 필터 |
| 필수 + 선호 100% | 75~82% | 최고 확신 |
        """)

    st.markdown("---")

    # ── MR / MOM 서브탭 ──
    dr_tab_mr, dr_tab_mom = st.tabs(["🔄 MR (평균회귀)", "🚀 MOM (모멘텀)"])

    def _render_dr_results(results, mode):
        """Daily Report 결과 렌더링 공통 함수."""
        enterable = [r for r in results if r["score"] in ["A", "B+"]]
        st.success(f"✅ 후보 {len(results)}개 | 진입 가능 **{len(enterable)}개**")
        for r in results:
            emj = SCORE_EMOJI.get(r["score"], "⚪")
            if mode == "MR":
                label = f"{emj} **{r['ticker']}** ${r['price']} — [{r['score']}] 승률 {r['win_rate']}  |  RSI2:{r['rsi2']}  RVOL:{r['rvol']}  연속↓:{r['consec']}일"
            else:
                label = f"{emj} **{r['ticker']}** ${r['price']} — [{r['score']}] 승률 {r['win_rate']}  |  RSI14:{r['rsi14']}  RVOL:{r['rvol']}  3M:+{r['perf_3m']}%"

            with st.expander(label):
                if mode == "MR":
                    m1, m2, m3, m4 = st.columns(4)
                    with m1: st.metric("RSI(2)", f"{r['rsi2']}", "≤15 ✓" if r['rsi2'] <= 15 else ">15 ✗")
                    with m2: st.metric("RVOL", f"{r['rvol']}x")
                    with m3: st.metric("ATR", f"${r['atr']}")
                    with m4: st.metric("연속↓", f"{r['consec']}일")
                else:
                    m1, m2, m3, m4 = st.columns(4)
                    with m1: st.metric("RSI(14)", f"{r['rsi14']}")
                    with m2: st.metric("RVOL", f"{r['rvol']}x")
                    with m3: st.metric("3M", f"+{r['perf_3m']}%")
                    with m4: st.metric("52주고점", f"{r['from_high']}%")

                ch1, ch2 = st.columns(2)
                with ch1:
                    st.markdown(f"**필수 ({r['req_pass']}/{r['req_total']})**")
                    for name, ok in r["required"].items():
                        st.markdown(f"{'✅' if ok else '❌'} {name}")
                with ch2:
                    st.markdown(f"**선호 ({r['pref_pass']}/{r['pref_total']} = {r['pref_pct']}%)**")
                    for name, ok in r["preferred"].items():
                        st.markdown(f"{'✅' if ok else '❌'} {name}")

                if r["score"] in ["A", "B+"]:
                    st.divider()
                    if mode == "MR":
                        g1, g2, g3, g4 = st.columns(4)
                        with g1: st.info(f"⏰ **매수**\n\n장 마감 30분전\nKST 05:30\n지정가 ${r['price']*0.998:.2f}")
                        with g2: st.success(f"🎯 **①익절**\n\nRSI(2)>70\n시 매도")
                        with g3: st.warning(f"⏱️ **②타임스탑**\n\n최대 10일\n보유 후 청산")
                        with g4: st.error(f"🛑 **③재난손절**\n\n진입가−3ATR\n${r['price'] - r['atr']*3:.2f}\n({-r['atr']*3/r['price']*100:.1f}%)")
                    else:
                        g1, g2, g3 = st.columns(3)
                        with g1: st.info("⏰ **매수**\n\n장 개장 30분~1시간 후\nKST 23:00~23:30")
                        with g2: st.success("🎯 **①익절**\n\n+8% 도달 시\n즉시 매도")
                        with g3: st.warning("⏱️ **②타임스탑**\n\n최대 15일\n보유 후 청산")
                        st.caption("⚠️ MOM 백테스트: +8% 익절 + 15일 타임스탑이 최적")
                    st.markdown(f"📐 **포지션:** {r['shares']}주 × ${r['price']} = **${r['pos_value']:,}** (계좌 {r['pos_pct']}%)")
                    if r['pos_pct'] > 25: st.error(f"⚠️ 과집중 {r['pos_pct']}%")
                if r["earn_blocked"]:
                    st.error("🚨 어닝 3일 이내 — 진입 금지")

    def _run_dr_scan(mode, key_prefix):
        """Daily Report 스캔 공통."""
        if st.button(f"{'🔄' if mode=='MR' else '🚀'} {mode} 자동 스캔", key=f"dr_{key_prefix}_scan", type="primary", use_container_width=True):
            with st.spinner("Finviz + yfinance 분석 중... (1~5분)"):
                tickers = _cached_finviz(mode, tuple(dr_sectors))
                if isinstance(tickers, str):
                    st.error(tickers)
                elif not tickers:
                    st.warning("조건 충족 종목 없음 — 섹터를 '전체'로 변경해보세요")
                else:
                    st.info(f"Finviz 프리필터 통과: {len(tickers)}개")
                    prog = st.progress(0)
                    results = []
                    for i, t in enumerate(tickers):
                        r = _cached_analyze(t, mode, _spy_rsi2_dr, _mom_ok_dr, _vix_ok_dr, dr_account, dr_risk)
                        if r:
                            results.append(r)
                        prog.progress((i + 1) / len(tickers))
                    prog.empty()
                    results = sort_results(results, mode)
                    st.session_state[f"dr_{key_prefix}"] = results

        key = f"dr_{key_prefix}"
        if key in st.session_state and st.session_state[key]:
            _render_dr_results(st.session_state[key], mode)

    with dr_tab_mr:
        if not _mr_ok_dr:
            st.error(f"🚫 MR 진입 금지 — SPY RSI(2) = {_spy_rsi2_dr:.1f} ≤ 10 (시장 패닉)")
        else:
            _run_dr_scan("MR", "mr")

    with dr_tab_mom:
        if not _mom_ok_dr:
            st.error("🚫 MOM 진입 금지 — Bear 레짐")
        else:
            _run_dr_scan("MOM", "mom")

    # 매수 타이밍 가이드
    st.divider()
    st.markdown("### ⏱️ 매수 타이밍 가이드")
    tc1, tc2 = st.columns(2)
    with tc1:
        st.info("**🔄 MR (평균회귀)**\n\n⏰ **최적:** 장 마감 30분전 (KST 05:30)\n- 당일 RSI(2)/BB 확정 후 진입\n- 패닉매도 장 초반 → 마감 안정화\n- 오버나이트 갭업 수혜\n\n⏰ **차선:** KST 23:00 지정가 걸고 취침\n🎯 **익절:** RSI(2) > 70 시 장중 매도\n📅 **홀딩:** 2~5일")
    with tc2:
        st.success("**🚀 MOM (모멘텀)**\n\n⏰ **최적:** 장 개장 30분~1시간 후 (KST 23:00)\n- 가짜 브레이크아웃 필터: 30분 관망\n- 볼륨 1.5배 이상 동반 확인\n\n⏰ **차선:** 전일 브레이크아웃 → 다음날 풀백\n🎯 **익절:** +8~12% 또는 RSI(14) > 75\n📅 **홀딩:** 5~15일")


# ──────────────────────────────────────────
# TAB 2: 수동 분석
# ──────────────────────────────────────────
with tab_manual:
    st.markdown("## 🔍 종목 스캔")
    st.caption("MOM: SMA200위+SMA50위+RSI<60+분기+10%+거래량500K+ | MR: SMA200위+RSI(14)<40+거래량500K+")

    strategy_mode = st.radio("전략 모드", ["MOM (모멘텀)", "MR (평균회귀)"], horizontal=True,
                             help="MOM: RVOL > 1.2 (거래량 동반 강세) | MR: RVOL < 0.8 (과열 없는 눌림목)")
    is_mom = strategy_mode == "MOM (모멘텀)"

    if "scan_result" not in st.session_state:
        st.session_state.scan_result = None

    sector = st.selectbox("섹터", ["Technology", "Healthcare", "Energy", "Consumer Cyclical", "Industrials", "전체"], index=0)

    if not all_green:
        if event_risk:
            st.error("⚠️ 이벤트 있음 — 스캔 비권장")
        elif not spy_ok_val or not qqq_ok_val:
            st.warning("⚠️ SPY/QQQ SMA200 아래 — 종목별 SMA200 확인 필수")
        elif not vix_ok_val:
            st.warning("⚠️ VIX 높음 — 포지션 50% 줄이기")

    col_s1, col_s2 = st.columns([3, 1])
    with col_s1: run_scan = st.button("🔍 스캔 실행", type="primary", use_container_width=True)
    with col_s2: clear_scan = st.button("🗑️ 초기화", use_container_width=True)

    if clear_scan:
        st.session_state.scan_result = None
        st.rerun()

    if run_scan:
        with st.spinner("Finviz 스크리닝 중..."):
            result = _cached_screener_simple(sector, "MOM" if is_mom else "MR")
        # _cached_screener_simple 은 list[str] 또는 str(에러)
        # 수동 탭은 DataFrame 스타일로도 처리해야 하므로 Finviz Overview 직접 호출
        try:
            from finvizfinance.screener.overview import Overview
            mode_str = "MOM" if is_mom else "MR"
            if mode_str == "MOM":
                filters = {
                    "200-Day Simple Moving Average": "Price above SMA200",
                    "50-Day Simple Moving Average": "Price above SMA50",
                    "RSI (14)": "Not Overbought (<60)",
                    "Performance": "Quarter +10%",
                    "Average Volume": "Over 500K",
                    "Industry": "Stocks only (ex-Funds)",
                    "Price": "Over $10",
                }
            else:
                filters = {
                    "200-Day Simple Moving Average": "Price above SMA200",
                    "RSI (14)": "Oversold (40)",
                    "Average Volume": "Over 500K",
                    "Industry": "Stocks only (ex-Funds)",
                    "Price": "Over $10",
                }
            if sector != "전체":
                filters["Sector"] = sector
            fov = Overview()
            fov.set_filter(filters_dict=filters)
            scan_df = fov.screener_view()
            st.session_state.scan_result = scan_df
        except Exception as e:
            st.session_state.scan_result = str(e)

    result = st.session_state.scan_result

    if result is not None:
        if isinstance(result, str):
            if any(k in result for k in ["ProxyError", "ConnectionError", "403"]):
                st.error("🌐 Finviz 접속 실패. 1~2분 후 재시도.")
            else:
                st.error(f"❌ 오류: {result[:200]}")
        elif hasattr(result, "empty") and result.empty:
            st.warning("⚠️ 조건 충족 종목 없음 — 섹터를 '전체'로 바꿔보세요")
        elif hasattr(result, "__len__") and len(result) > 0:
            st.success(f"✅ {len(result)}개 종목 발견!")

            # RVOL 컬럼 계산
            if hasattr(result, "columns") and "Relative Volume" not in result.columns and "Ticker" in result.columns:
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

            show_cols = [c for c in ["Ticker", "Company", "Price", "Change", "RVOL", "Relative Volume"] if c in result.columns]
            st.dataframe(result[show_cols], use_container_width=True, hide_index=True)

            if "Ticker" in result.columns:
                tickers = result["Ticker"].tolist()
                st.code(", ".join(tickers))

                st.divider()
                st.markdown("#### 📈 종목 체크리스트")
                selected = st.selectbox("종목 선택", options=tickers, index=0)

                if selected:
                    with st.spinner(f"{selected} 로딩..."):
                        hist = _cached_stock(selected)

                    if not hist.empty:
                        # 지표 계산
                        hist["SMA20"] = calc_sma(hist["Close"], 20)
                        hist["SMA50"] = calc_sma(hist["Close"], 50)
                        hist["SMA150"] = calc_sma(hist["Close"], 150)
                        hist["SMA200"] = calc_sma(hist["Close"], 200)
                        hist["RSI14"] = calc_rsi(hist["Close"], 14)
                        hist["RSI2"] = calc_rsi(hist["Close"], 2)
                        bb_mid, bb_upper, bb_lower = calc_bollinger(hist["Close"])
                        hist["BB_upper"] = bb_upper
                        hist["BB_lower"] = bb_lower
                        hist["BB_mid"] = bb_mid
                        hist["ATR14"] = calc_atr(hist["High"], hist["Low"], hist["Close"])

                        spy_rsi2_val = get_spy_rsi2()

                        df60 = hist.tail(60)
                        curr = float(df60["Close"].iloc[-1])
                        s200 = float(df60["SMA200"].iloc[-1]) if not pd.isna(df60["SMA200"].iloc[-1]) else None
                        s150 = float(df60["SMA150"].iloc[-1]) if not pd.isna(df60["SMA150"].iloc[-1]) else None
                        s50 = float(df60["SMA50"].iloc[-1]) if not pd.isna(df60["SMA50"].iloc[-1]) else None
                        rsi_v = float(df60["RSI14"].iloc[-1]) if not pd.isna(df60["RSI14"].iloc[-1]) else None
                        rsi2_v = float(df60["RSI2"].iloc[-1]) if not pd.isna(df60["RSI2"].iloc[-1]) else None
                        bb_low = float(df60["BB_lower"].iloc[-1]) if not pd.isna(df60["BB_lower"].iloc[-1]) else None
                        bb_up = float(df60["BB_upper"].iloc[-1]) if not pd.isna(df60["BB_upper"].iloc[-1]) else None
                        bb_mid_v = float(df60["BB_mid"].iloc[-1]) if not pd.isna(df60["BB_mid"].iloc[-1]) else None
                        atr_val = float(df60["ATR14"].iloc[-1]) if not pd.isna(df60["ATR14"].iloc[-1]) else None

                        sma200_now = hist["SMA200"].iloc[-1]
                        sma200_20d = hist["SMA200"].iloc[-21] if len(hist) >= 21 else None
                        sma200_rising = (not pd.isna(sma200_now) and sma200_20d is not None and not pd.isna(sma200_20d) and float(sma200_now) > float(sma200_20d))
                        sma200_slope_pct = ((float(sma200_now) - float(sma200_20d)) / float(sma200_20d) * 100 if sma200_20d is not None and not pd.isna(sma200_20d) and float(sma200_20d) != 0 else None)
                        sepa_aligned = s50 is not None and s150 is not None and s200 is not None and s50 > s150 > s200

                        hist_252 = hist.tail(252)
                        w52_high = float(hist_252["High"].max())
                        w52_low = float(hist_252["Low"].min())
                        w52_range = w52_high - w52_low
                        w52_pos = (curr - w52_low) / w52_range * 100 if w52_range > 0 else None
                        w52_from_high_pct = (curr - w52_high) / w52_high * 100
                        w52_from_low_pct = (curr - w52_low) / w52_low * 100
                        minv_high_ok = w52_from_high_pct >= -25.0
                        minv_low_ok = w52_from_low_pct >= 30.0
                        chg_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-63] - 1) * 100 if len(hist) >= 63 else None
                        avg_vol = hist["Volume"].tail(20).mean()
                        rvol_now = hist["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0
                        earn_info = _cached_earnings(selected)

                        # ── 체크카드 ──
                        if is_mom:
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if s200 and curr > s200:
                                    st.success(f"✅ SMA200\n${s200:.1f} 위")
                                else:
                                    st.error(f"❌ SMA200\n{'$'+f'{s200:.1f}' if s200 else 'N/A'} 아래")
                                if rsi_v and rsi_v < 60:
                                    st.success(f"✅ RSI(14) {rsi_v:.0f}\n과매수 아님")
                                elif rsi_v:
                                    st.error(f"❌ RSI(14) {rsi_v:.0f}\n과매수")
                            with cc2:
                                if s50 and curr > s50:
                                    st.success(f"✅ SMA50\n${s50:.1f} 위")
                                else:
                                    st.error(f"❌ SMA50\n{'$'+f'{s50:.1f}' if s50 else 'N/A'} 아래")
                                st.info(f"💲 현재가\n${curr:.2f}")
                        else:
                            cc1, cc2 = st.columns(2)
                            with cc1:
                                if s200 and curr > s200:
                                    st.success(f"✅ SMA200 위\n${s200:.1f}")
                                else:
                                    st.error(f"❌ SMA200 아래\n{'$'+f'{s200:.1f}' if s200 else 'N/A'}")
                                if rsi2_v is not None and rsi2_v <= 15:
                                    st.success(f"✅ RSI(2) {rsi2_v:.1f}\n≤15 진입신호")
                                elif rsi2_v is not None:
                                    st.warning(f"🟡 RSI(2) {rsi2_v:.1f}\n>15 대기")
                            with cc2:
                                if bb_low is not None and curr <= bb_low * 1.005:
                                    st.success(f"✅ BB하단 터치\nBB↓ ${bb_low:.2f}")
                                elif bb_low is not None:
                                    st.warning(f"🟡 BB하단 미접촉\nBB↓ ${bb_low:.2f}")
                                st.info(f"💲 현재가 ${curr:.2f}\n{'SMA50 위' if s50 and curr > s50 else 'SMA50 아래 (MR 정상)'}")

                        # ── 추세 구조 ──
                        st.divider()
                        st.markdown("#### 📈 추세 구조 분석")
                        ta1, ta2 = st.columns(2)
                        with ta1:
                            st.markdown("**SMA200 방향성**")
                            if sma200_slope_pct is not None:
                                if sma200_rising:
                                    st.success(f"✅ SMA200 **상승 중**\n\n20일 변화: **+{sma200_slope_pct:.2f}%**")
                                else:
                                    st.error(f"❌ SMA200 **하락/횡보**\n\n20일 변화: **{sma200_slope_pct:.2f}%**")
                            else:
                                st.warning("⚪ SMA200 방향 계산 불가")
                        with ta2:
                            st.markdown("**Minervini SEPA 정렬**")
                            if s50 and s150 and s200:
                                if sepa_aligned:
                                    st.success(f"✅ 정렬 완료\n\nSMA50 ${s50:.1f} > SMA150 ${s150:.1f} > SMA200 ${s200:.1f}")
                                else:
                                    st.error("❌ 정렬 미완성")
                            else:
                                st.warning("⚪ 데이터 부족")

                        trend_score = sum([sma200_rising, sepa_aligned, s200 is not None and curr > s200, s50 is not None and curr > s50])
                        trend_labels = {
                            4: ("🟢 추세 구조 최상", "4/4"), 3: ("🟡 추세 구조 양호", "3/4"),
                            2: ("🟠 추세 구조 혼조", "2/4"), 1: ("🔴 추세 구조 취약", "1/4"), 0: ("🔴 추세 구조 붕괴", "0/4"),
                        }
                        tlabel, tdesc = trend_labels[trend_score]
                        st.info(f"**{tlabel}** ({tdesc})")

                        # ── 52주 고저점 ──
                        st.divider()
                        st.markdown("#### 📊 52주 고저점 위치")
                        w1, w2, w3 = st.columns(3)
                        with w1: st.metric("52주 고점", f"${w52_high:.2f}", f"{w52_from_high_pct:+.1f}%")
                        with w2: st.metric("52주 저점", f"${w52_low:.2f}", f"+{w52_from_low_pct:.1f}%")
                        with w3:
                            if w52_pos is not None:
                                st.metric("레인지 위치", f"{w52_pos:.0f}%")

                        mc_a, mc_b = st.columns(2)
                        with mc_a:
                            if minv_high_ok:
                                st.success(f"✅ 고점 대비 {w52_from_high_pct:.1f}% (−25% 이내)")
                            else:
                                st.error(f"❌ 고점 대비 {w52_from_high_pct:.1f}% (−25% 초과)")
                        with mc_b:
                            if minv_low_ok:
                                st.success(f"✅ 저점 대비 +{w52_from_low_pct:.1f}% (+30% 이상)")
                            else:
                                st.error(f"❌ 저점 대비 +{w52_from_low_pct:.1f}% (+30% 미만)")

                        # ── 어닝 ──
                        st.divider()
                        st.markdown("#### 📅 어닝 일정")
                        if earn_info["source"] == "none":
                            st.warning(f"⚪ 어닝 정보 없음 — [Finviz {selected}](https://finviz.com/quote.ashx?t={selected}) 에서 확인")
                        elif earn_info["within_3d"]:
                            st.error(f"🚨 **어닝 3일 이내 — 진입 금지** | {earn_info['label']}")
                        else:
                            days = earn_info["days_away"]
                            if days is not None and days <= 14:
                                st.warning(f"🟡 어닝 {earn_info['label']} — 14일 이내")
                            else:
                                st.success(f"✅ 어닝 안전 구간 | {earn_info['label']}")

                        mc1, mc2 = st.columns(2)
                        with mc1:
                            if chg_3m is not None:
                                st.success(f"📈 3개월 +{chg_3m:.1f}%") if chg_3m >= 10 else st.warning(f"📈 3개월 {chg_3m:+.1f}%")
                        with mc2:
                            if is_mom:
                                if rvol_now > 1.2: st.success(f"✅ RVOL {rvol_now:.1f}x [MOM] 거래량↑")
                                elif rvol_now > 0.8: st.warning(f"🟡 RVOL {rvol_now:.1f}x [MOM] 보통")
                                else: st.error(f"❌ RVOL {rvol_now:.1f}x [MOM] 부족")
                            else:
                                if rvol_now < 0.8: st.success(f"✅ RVOL {rvol_now:.1f}x [MR] 조용한 눌림")
                                elif rvol_now < 1.2: st.warning(f"🟡 RVOL {rvol_now:.1f}x [MR] 보통")
                                else: st.error(f"❌ RVOL {rvol_now:.1f}x [MR] 과열")

                        # ── MR/MOM 전용 신호 ──
                        if not is_mom:
                            st.divider()
                            st.markdown("#### 🎯 APEX MR 진입 신호")
                            mr1, mr2, mr3 = st.columns(3)
                            with mr1:
                                if rsi2_v is not None:
                                    if rsi2_v <= 15: st.success(f"✅ RSI(2) **{rsi2_v:.1f}** ≤15")
                                    elif rsi2_v <= 30: st.warning(f"🟡 RSI(2) **{rsi2_v:.1f}** 대기")
                                    else: st.error(f"❌ RSI(2) **{rsi2_v:.1f}** 과열")
                            with mr2:
                                if bb_low is not None:
                                    if curr <= bb_low * 1.005: st.success(f"✅ BB 하단 터치\n${curr:.2f} ≤ ${bb_low:.2f}")
                                    elif curr <= bb_mid_v: st.warning(f"🟡 BB 중단 이하\n${curr:.2f}")
                                    else: st.error(f"❌ BB 중단 이상\n${curr:.2f}")
                            with mr3:
                                if spy_rsi2_val is not None:
                                    if spy_rsi2_val > 10: st.success(f"✅ SPY RSI(2) **{spy_rsi2_val:.1f}**")
                                    elif spy_rsi2_val > 5: st.warning(f"🟡 SPY RSI(2) **{spy_rsi2_val:.1f}** 약세")
                                    else: st.error(f"❌ SPY RSI(2) **{spy_rsi2_val:.1f}** 급락")

                            rsi2_ok = rsi2_v is not None and rsi2_v <= 15
                            bb_ok = bb_low is not None and curr <= bb_low * 1.005
                            spy_rsi2_ok = spy_rsi2_val is not None and spy_rsi2_val > 10
                            earn_ok = not earn_info["within_3d"]
                            mr_score = sum([rsi2_ok, bb_ok, spy_rsi2_ok])
                            if not earn_ok:
                                st.error("🚨 **어닝 3일 이내 — MR 진입 자동 차단**")
                            elif mr_score == 3:
                                st.success("🟢 **MR 진입 신호 FULL** — 3/3 충족")
                            elif mr_score == 2:
                                st.warning(f"🟡 **MR 신호 2/3** — {'RSI2✅' if rsi2_ok else 'RSI2❌'} | {'BB✅' if bb_ok else 'BB❌'} | {'SPY✅' if spy_rsi2_ok else 'SPY❌'}")
                            else:
                                st.error(f"🔴 **MR 신호 {mr_score}/3** — 미충족")
                        else:
                            st.divider()
                            st.markdown("#### 🚀 APEX MOM 보조 신호")
                            mom1, mom2 = st.columns(2)
                            with mom1:
                                if rsi2_v is not None:
                                    if rsi2_v >= 80: st.error(f"⚠️ RSI(2) {rsi2_v:.1f} 단기 과열")
                                    elif rsi2_v >= 50: st.success(f"✅ RSI(2) {rsi2_v:.1f} 모멘텀 지속")
                                    else: st.warning(f"🟡 RSI(2) {rsi2_v:.1f} 단기 약세")
                            with mom2:
                                if bb_up is not None:
                                    if curr >= bb_up * 0.995: st.error(f"⚠️ BB 상단 근접 ${curr:.2f}")
                                    elif curr >= bb_mid_v: st.success(f"✅ BB 중단 위 ${curr:.2f}")
                                    else: st.warning(f"🟡 BB 중단 아래 ${curr:.2f}")

                        # ── 차트 ──
                        st.divider()
                        if PLOTLY_OK:
                            fig = make_subplots(rows=2, cols=1, shared_xaxes=True, vertical_spacing=0.03, row_heights=[0.70, 0.30])
                            fig.add_trace(go.Candlestick(x=df60.index, open=df60["Open"], high=df60["High"], low=df60["Low"], close=df60["Close"], name=selected, increasing_line_color="#00C853", decreasing_line_color="#FF5252", increasing_fillcolor="#00C853", decreasing_fillcolor="#FF5252"), row=1, col=1)
                            for col_n, color, nm in [("SMA50", "#42A5F5", "SMA50"), ("SMA150", "#FFA726", "SMA150"), ("SMA200", "#FF7043", "SMA200 ★"), ("BB_upper", "#9C27B0", "BB상단"), ("BB_lower", "#9C27B0", "BB하단"), ("BB_mid", "#7B1FA2", "BB중단")]:
                                dash_style = "dot" if "BB" in col_n else "solid"
                                width_style = 1 if "BB" in col_n else 2
                                fig.add_trace(go.Scatter(x=df60.index, y=df60[col_n], name=nm, line=dict(color=color, width=width_style, dash=dash_style)), row=1, col=1)
                            vol_colors = ["#00C853" if c >= o else "#FF5252" for c, o in zip(df60["Close"], df60["Open"])]
                            fig.add_trace(go.Bar(x=df60.index, y=df60["Volume"], name="거래량", marker_color=vol_colors, opacity=0.7, showlegend=False), row=2, col=1)
                            fig.update_layout(title=f"{selected} — SMA·BB·거래량", height=420, paper_bgcolor="#0E1117", plot_bgcolor="#0E1117", font=dict(color="#E0E0E0", size=11), xaxis_rangeslider_visible=False, margin=dict(l=30, r=10, t=45, b=20), legend=dict(orientation="h", y=1.06, font=dict(size=10)), hovermode="x unified")
                            for r in [1, 2]:
                                fig.update_xaxes(gridcolor="#1E1E2E", row=r, col=1)
                                fig.update_yaxes(gridcolor="#1E1E2E", row=r, col=1)
                            st.plotly_chart(fig, use_container_width=True)
                        else:
                            st.line_chart(df60[["Close", "SMA50", "SMA200"]])
                            st.bar_chart(df60["Volume"])

                        st.markdown(f"[👉 Finviz {selected} 차트 열기](https://finviz.com/quote.ashx?t={selected})")

                        # ── 손절/목표가 ──
                        st.divider()
                        st.markdown("#### 🛑 손절 / 목표가")
                        if is_mom:
                            sc1, sc2 = st.columns(2)
                            with sc1: st.success(f"🎯 ①익절\n+8% 도달 시 매도\n목표 ${curr * 1.08:.2f}")
                            with sc2: st.warning("⏱️ ②타임스탑\n최대 15일 보유 후 청산")
                        else:
                            sc1, sc2, sc3 = st.columns(3)
                            with sc1: st.success("🎯 ①익절\nRSI(2)>70 시 매도")
                            with sc2: st.warning("⏱️ ②타임스탑\n최대 10일 보유 후 청산")
                            with sc3:
                                if atr_val:
                                    stop_3atr = curr - atr_val * 3
                                    st.error(f"🛑 ③재난손절\n${stop_3atr:.2f} ({-atr_val*3/curr*100:.1f}%)")
                                else:
                                    st.error("🛑 ③재난손절\nATR 계산 불가")

                        # ── ATR 포지션 사이징 ──
                        st.divider()
                        st.markdown("#### 📐 ATR 포지션 사이징")
                        if atr_val:
                            atr_pct = atr_val / curr * 100
                            ac1, ac2, ac3 = st.columns(3)
                            with ac1: st.metric("ATR(14)", f"${atr_val:.2f}", f"{atr_pct:.1f}%")
                            with ac2: st.metric("3ATR 재난손절", f"${curr - atr_val*3:.2f}", f"−{atr_pct*3:.1f}%")
                            with ac3: st.metric("2ATR 목표", f"${curr + atr_val*2:.2f}", f"+{atr_pct*2:.1f}%")

                            st.markdown("---")
                            ps1, ps2 = st.columns(2)
                            with ps1:
                                account_size = st.number_input("💰 계좌 금액 (USD)", 500, 500000, st.session_state.get("apex_account", 5000), 500, key="apex_account")
                            with ps2:
                                risk_pct = st.slider("🎯 1회 리스크 %", 0.5, 3.0, st.session_state.get("apex_risk_pct", 1.0), 0.5, key="apex_risk_pct")

                            risk_dollar = account_size * (risk_pct / 100)
                            shares_atr = int(risk_dollar / atr_val)
                            pos_value = shares_atr * curr
                            pos_pct = pos_value / account_size * 100

                            st.markdown("##### 📊 포지션 계산 결과")
                            res1, res2, res3 = st.columns(3)
                            with res1: st.metric("리스크 금액", f"${risk_dollar:,.0f}", f"계좌의 {risk_pct}%")
                            with res2: st.metric("권장 주수", f"{shares_atr:,} 주", f"${pos_value:,.0f} ({pos_pct:.1f}%)")
                            with res3: st.metric("매수금", f"${pos_value:,.0f}", f"비중 {pos_pct:.1f}%")

                            if pos_pct > 25:
                                st.error(f"⚠️ 포지션 비중 {pos_pct:.1f}% — 과집중 주의")
                            elif pos_pct > 15:
                                st.warning(f"🟡 포지션 비중 {pos_pct:.1f}% — 적정 상단")
                            else:
                                st.success(f"✅ 포지션 비중 {pos_pct:.1f}% — 적정")
                        else:
                            st.warning("⚠️ ATR 계산 불가 — 데이터 부족")

    st.divider()

    # ── 체크리스트 ──
    st.markdown("### 📋 진입 체크리스트")
    st.markdown("**🔵 공통 (MOM + MR)**\n\n□ SPY + QQQ 초록?  □ VIX ≤ 25?  □ 이벤트 없음?  □ SMA200 위?  □ SMA50 위?  □ RSI(14) < 60?  □ ATR 사이징 완료?")
    st.markdown("**🟠 MR 전용**\n\n□ RSI(2) ≤ 15?  □ BB 하단 터치?  □ SPY RSI(2) > 10?  □ 어닝 3일 이내 아님?")
    st.markdown("**🟢 MOM 전용**\n\n□ RSI(2) < 80?  □ BB 상단 근접 아님?  □ Bull Regime?  □ SMA200 상승 중?  □ SEPA 정렬?  □ 52주 고점 −25% 이내?  □ 52주 저점 +30% 이상?")
    st.markdown("""
**📌 청산 규칙 (백테스트 검증)**

| | MR (평균회귀) | MOM (모멘텀) |
|---|---|---|
| ①익절 | RSI(2)>70 매도 | +8% 도달 시 매도 |
| ②타임스탑 | 최대 10일 | 최대 15일 |
| ③재난손절 | 진입가−3ATR | 없음 |
    """)


# ──────────────────────────────────────────
# TAB 3: 보유 종목 모니터
# ──────────────────────────────────────────
with tab_hold:
    st.markdown("### 📌 보유 종목 모니터")
    st.caption("보유 중인 종목의 청산 조건만 체크 — 스크리너(진입용)와 별개")
    st.info("💡 **스크리너에서 종목이 사라졌다 = 팔아라가 아닙니다.**\n\n스크리너는 진입용이고, 청산은 아래 규칙으로만 판단하세요.")

    h_c1, h_c2 = st.columns(2)
    with h_c1:
        h_ticker = st.text_input("📌 보유 종목 티커", value="", placeholder="예: AAOI", key="hold_ticker").upper().strip()
    with h_c2:
        h_mode = st.radio("전략", ["MR (평균회귀)", "MOM (모멘텀)"], horizontal=True, key="hold_mode")

    h_c3, h_c4 = st.columns(2)
    with h_c3:
        h_entry_price = st.number_input("💰 진입가 (USD)", min_value=0.01, value=10.0, step=0.01, key="hold_entry")
    with h_c4:
        h_entry_date = st.date_input("📅 진입일", value=datetime.date.today(), key="hold_date")

    if h_ticker and st.button("🔍 청산 조건 체크", type="primary", use_container_width=True, key="hold_check"):
        with st.spinner(f"{h_ticker} 분석 중..."):
            strategy = "MR" if h_mode == "MR (평균회귀)" else "MOM"
            exit_data = check_exit_signals(h_ticker, strategy, h_entry_price, h_entry_date)

            if exit_data is None:
                st.error(f"❌ {h_ticker} 데이터 없음")
            else:
                st.divider()
                st.markdown(f"#### {h_ticker} 보유 현황")

                hm1, hm2, hm3, hm4 = st.columns(4)
                with hm1:
                    color = "normal" if exit_data["pnl"] >= 0 else "inverse"
                    st.metric("현재가", f"${exit_data['curr']:.2f}", f"{exit_data['pnl']:+.1f}%", delta_color=color)
                with hm2: st.metric("보유 일수", f"{exit_data['hold_days']}일")
                with hm3: st.metric("RSI(2)", f"{exit_data['rsi2']}")
                with hm4: st.metric("RSI(14)", f"{exit_data['rsi14']}")

                st.divider()
                st.markdown("#### 🚦 청산 신호 판정")

                is_mr = strategy == "MR"
                if is_mr:
                    s1, s2, s3 = st.columns(3)
                    with s1:
                        if exit_data["tp_hit"]:
                            st.error(f"🔴 **①익절**\nRSI(2) = {exit_data['rsi2']} > 70")
                        else:
                            st.success(f"🟢 ①대기\nRSI(2) = {exit_data['rsi2']}")
                    with s2:
                        if exit_data["time_hit"]:
                            st.error(f"🔴 **②타임스탑**\n{exit_data['hold_days']}일 ≥ 10일")
                        else:
                            st.success(f"🟢 ②대기\n{exit_data['hold_days']}일 ({10 - exit_data['hold_days']}일 남음)")
                    with s3:
                        if exit_data["stop_hit"]:
                            st.error(f"🔴 **③재난손절**\n${exit_data['curr']} ≤ ${exit_data['stop_3atr']}")
                        else:
                            st.success(f"🟢 ③안전\n손절선 ${exit_data['stop_3atr']}")
                else:
                    s1, s2 = st.columns(2)
                    with s1:
                        if exit_data["tp_hit"]:
                            st.error(f"🔴 **①익절**\n수익률 {exit_data['pnl']:+.1f}% ≥ +8%")
                        else:
                            st.success(f"🟢 ①대기\n수익률 {exit_data['pnl']:+.1f}% (목표 +8%)")
                    with s2:
                        if exit_data["time_hit"]:
                            st.error(f"🔴 **②타임스탑**\n{exit_data['hold_days']}일 ≥ 15일")
                        else:
                            st.success(f"🟢 ②대기\n{exit_data['hold_days']}일 ({15 - exit_data['hold_days']}일 남음)")

                st.divider()
                if exit_data["sell_signals"]:
                    st.markdown(f"""
<div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
    <div style="font-size:3rem">🔴</div>
    <div style="font-size:1.6rem;font-weight:bold;color:#FF5252">매도 — {' + '.join(exit_data['sell_signals'])}</div>
    <div style="color:#aaa;margin-top:8px">{h_ticker} ${exit_data['curr']} | {exit_data['pnl']:+.1f}% | {exit_data['hold_days']}일</div>
</div>""", unsafe_allow_html=True)
                else:
                    st.markdown(f"""
<div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
    <div style="font-size:3rem">🟢</div>
    <div style="font-size:1.6rem;font-weight:bold;color:#00C853">홀드 — 청산 조건 없음</div>
    <div style="color:#aaa;margin-top:8px">{h_ticker} ${exit_data['curr']} | {exit_data['pnl']:+.1f}% | {exit_data['hold_days']}일</div>
</div>""", unsafe_allow_html=True)

