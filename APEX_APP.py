"""
APEX v9.0 
─────────────────────────────────────────────────────────────
수정 내역 vs v8.2:
  [BUG FIX] st.write() → st.markdown() 전환 (HTML 엔티티 / ** 렌더링 오류 제거)
  [BUG FIX] Float 165M 종목이 개별 분석에서 경고 없이 표시되던 문제 → 일관성 경고 추가
  [NEW] RSI(2) 계산 및 APEX MR 조건 체크 추가
  [NEW] RSI(14) 계산 추가
  [NEW] Bollinger Band (BB Width / %B) 계산 및 Squeeze 감지 추가
  [NEW] APEX 가중 점수 시스템 (100점 만점, 조건별 차등 배점)
  [NEW] Float 경고 등급 세분화 (20M / 50M / 100M / 초과)
  [NEW] Squeeze 스크리너 탭 (v8.2에서 이어받아 개선)
  [IMPROVED] 진입 타이밍 가이드 상세화
  [IMPROVED] ATR 손절 탭 — 계좌 보호 경고 강화

의존 패키지: pip install streamlit yfinance pandas finvizfinance
실행: streamlit run apex_v90.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd

# ══════════════════════════════════════════════════════════════
# 공통 유틸 함수
# ══════════════════════════════════════════════════════════════
def calc_rsi(series: pd.Series, period: int) -> float:
    """Wilder 방식 RSI 계산. 데이터 부족 시 None 반환."""
    if len(series) < period + 1:
        return None
    delta    = series.diff()
    gain     = delta.clip(lower=0)
    loss     = -delta.clip(upper=0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, 1e-10)
    rsi      = 100 - (100 / (1 + rs))
    val      = rsi.iloc[-1]
    return float(val) if pd.notna(val) else None

def calc_bb(series: pd.Series, window: int = 20):
    """Bollinger Band 계산. (upper, mid, lower, width_pct, pct_b) 반환."""
    if len(series) < window:
        return None, None, None, None, None
    mid   = series.rolling(window).mean().iloc[-1]
    std   = series.rolling(window).std().iloc[-1]
    upper = mid + 2 * std
    lower = mid - 2 * std
    width = (upper - lower) / mid * 100 if mid else None
    span  = upper - lower
    pct_b = (series.iloc[-1] - lower) / span * 100 if span else None
    return float(upper), float(mid), float(lower), float(width), float(pct_b)

def calc_atr(hist: pd.DataFrame, period: int = 14):
    """ATR 계산. None 반환 가능."""
    if len(hist) < period + 1:
        return None
    h  = hist["High"]
    l  = hist["Low"]
    pc = hist["Close"].shift(1)
    tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
    val = tr.rolling(period).mean().iloc[-1]
    return float(val) if pd.notna(val) else None

def handle_screener_error(e: Exception):
    err = str(e)
    if any(k in err for k in ["ProxyError", "ConnectionError", "Max retries", "403"]):
        st.error(
            "🌐 **Finviz 접속 실패** — 1~2분 후 재시도하거나 VPN 없이 다시 시도하세요.\n\n"
            "직접 확인: https://finviz.com/screener.ashx"
        )
    else:
        st.error(f"❌ 스크리너 오류: {e}")

# ══════════════════════════════════════════════════════════════
# 화면 설정
# ══════════════════════════════════════════════════════════════
st.set_page_config(page_title="APEX v9.0 전략 센터", layout="wide")
st.title("🚀 APEX v9.0 — Overnight Gap Play 전략 센터")
st.caption(
    "전략 A (Overnight): After-market 촉매 진입 → 다음날 Pre-market 청산  |  "
    "전략 B (Squeeze): 에너지 응축 종목 선제 발굴 → 정규장 돌파 진입"
)

tab_screen, tab_squeeze, tab_analyze, tab_risk = st.tabs([
    "🔭 APEX 스크리너",
    "🗜️ Squeeze 스크리너",
    "🔍 개별 종목 분석",
    "💰 ATR 손절 & 포지션 사이징",
])


# ══════════════════════════════════════════════════════════════
# TAB 1 — APEX 스크리너 (Overnight Gap Play 후보 발굴)
# ══════════════════════════════════════════════════════════════
with tab_screen:
    st.header("🔭 APEX 조건 자동 스크리닝 (Overnight Gap Play)")
    st.caption("Finviz에서 APEX 핵심 조건을 충족하는 후보 종목을 자동 추출합니다.")

    with st.expander("⚙️ 스크리너 조건 설정", expanded=True):
        c1, c2, c3 = st.columns(3)
        with c1:
            float_f  = st.selectbox("🎈 Float", ["Under 20M","Under 50M","Under 100M"], 0,
                                    help="폭등 최적: Under 20M")
            si_f     = st.selectbox("🧨 Float Short", ["Over 15%","Over 10%","Over 5%"], 0,
                                    help="숏 스퀴즈 연료: Over 15%")
        with c2:
            sma200_f = st.selectbox("🦴 200일 SMA", ["Price above SMA200","Any"], 0,
                                    help="악성 매물대 위 필수")
            rvol_f   = st.selectbox("📊 상대 거래량", ["Over 2","Over 1.5","Over 3","Any"], 0,
                                    help="세력 개입: Over 2")
        with c3:
            avgvol_f = st.selectbox("💧 평균 거래량", ["Over 500K","Over 200K","Over 1M"], 0)
            price_f  = st.selectbox("💲 주가", ["Over $1","Over $2","Over $5","Over $10"], 0)

    if st.button("🚀 APEX 스크리너 실행", type="primary", use_container_width=True):
        fd = {}
        if float_f  != "Any": fd["Float"]                         = float_f
        if si_f     != "Any": fd["Float Short"]                   = si_f
        if sma200_f != "Any": fd["200-Day Simple Moving Average"] = sma200_f
        if rvol_f   != "Any": fd["Relative Volume"]               = rvol_f
        if avgvol_f != "Any": fd["Average Volume"]                = avgvol_f
        if price_f  != "Any": fd["Price"]                         = price_f

        st.info(f"📡 스크리닝 중... `{fd}`")
        try:
            from finvizfinance.screener.overview import Overview
            fov = Overview()
            fov.set_filter(filters_dict=fd)
            df = fov.screener_view()
            if df is None or df.empty:
                st.warning("⚠️ 조건 충족 종목 없음. 조건을 완화하세요.")
            else:
                st.success(f"✅ {len(df)}개 후보 발굴!")
                preferred = ["Ticker","Company","Sector","Price","Change",
                             "Volume","Relative Volume","Float","Short Float","Market Cap"]
                cols = [c for c in preferred if c in df.columns] or df.columns.tolist()
                st.dataframe(df[cols], use_container_width=True, hide_index=True)
                if "Ticker" in df.columns:
                    st.markdown("#### 🎯 발굴된 티커 — **[🔍 개별 종목 분석]** 탭에 입력하세요")
                    st.code(", ".join(df["Ticker"].tolist()[:20]))
        except ImportError:
            st.error("❌ `pip install finvizfinance` 후 재실행하세요.")
        except Exception as e:
            handle_screener_error(e)
    else:
        st.info("⬆️ 조건 확인 후 실행 버튼을 누르세요.")

    st.divider()
    st.subheader("📋 APEX 5대 조건 가중 점수 해설")
    ec1, ec2, ec3, ec4, ec5 = st.columns(5)
    with ec1: st.info("🎈 **Float < 20M** ⭐30점\n\n가벼운 체급 = 150% 폭등 가능")
    with ec2: st.success("🧨 **SI > 15%** ⭐20점\n\n숏 커버 매수 = 갭업 증폭")
    with ec3: st.success("🦴 **SMA200 위** ⭐20점\n\n악성 매물대 없음 = 저항 없는 상승")
    with ec4: st.warning("🎯 **VWAP 위** ⭐15점\n\n세력 수익권 = 홀딩 신호")
    with ec5: st.error("📊 **RVOL > 2x** ⭐15점\n\n세력 개입 증거")


# ══════════════════════════════════════════════════════════════
# TAB 2 — Squeeze 스크리너 (에너지 응축 돌파 대기)
# ══════════════════════════════════════════════════════════════
with tab_squeeze:
    st.header("🗜️ Squeeze 스크리너 — 에너지 응축 돌파 대기")
    st.caption("RVOL이 낮고 변동폭이 수렴한 종목 = 폭발 직전 응축 상태")

    dc1, dc2 = st.columns(2)
    with dc1:
        st.info("**🔭 APEX Overnight**\n\nRVOL 높음(>2x) + 당일 촉매\n보유 12~18시간")
    with dc2:
        st.success("**🗜️ Squeeze Breakout**\n\nRVOL 낮음(<0.75) + 패턴 수렴\n보유 수일~수주")

    st.divider()
    with st.expander("⚙️ Squeeze 조건 설정", expanded=True):
        sc1, sc2, sc3 = st.columns(3)
        with sc1:
            sq_20hl  = st.selectbox("📐 20일 고저범위 (응축)", ["0-10% below High","0-5% below High","Any"], 0,
                                    help="고점 대비 10% 이내 횡보 = 에너지 응축")
            sq_rvol  = st.selectbox("📉 상대 거래량 (소멸)", ["Under 0.75","Under 0.5","Any"], 0,
                                    help="거래량이 죽어야 응축 상태. APEX와 반대")
            sq_beta  = st.selectbox("📊 베타", ["0.5 to 1.5","Under 1.5","Any"], 0)
        with sc2:
            sq_sma20 = st.selectbox("📈 20일 SMA", ["Price above SMA20","Price crossed SMA20","Any"], 0)
            sq_sma50 = st.selectbox("📈 50일 SMA", ["Price above SMA50","Any"], 0)
            sq_sma200= st.selectbox("🦴 200일 SMA", ["Price above SMA200","Any"], 0)
        with sc3:
            sq_avg   = st.selectbox("💧 평균 거래량", ["Over 300K","Over 500K","Any"], 0)
            sq_inst  = st.selectbox("🏛️ 기관 보유", ["Over 10%","Over 20%","Any"], 0,
                                    help="InstitutionalOwnership (붙여쓰기 필수)")
            sq_pat   = st.selectbox("📐 차트 패턴", ["Triangle Ascending","Wedge","Any"], 0)

    if st.button("🗜️ Squeeze 스크리너 실행", type="primary", use_container_width=True):
        sq = {}
        if sq_20hl  != "Any": sq["20-Day High/Low"]                   = sq_20hl
        if sq_rvol  != "Any": sq["Relative Volume"]                   = sq_rvol
        if sq_beta  != "Any": sq["Beta"]                              = sq_beta
        if sq_sma20 != "Any": sq["20-Day Simple Moving Average"]      = sq_sma20
        if sq_sma50 != "Any": sq["50-Day Simple Moving Average"]      = sq_sma50
        if sq_sma200!= "Any": sq["200-Day Simple Moving Average"]     = sq_sma200
        if sq_avg   != "Any": sq["Average Volume"]                    = sq_avg
        if sq_inst  != "Any": sq["InstitutionalOwnership"]            = sq_inst
        if sq_pat   != "Any": sq["Pattern"]                           = sq_pat

        st.info(f"📡 Squeeze 스크리닝 중... `{sq}`")
        try:
            from finvizfinance.screener.overview import Overview
            fov2 = Overview()
            fov2.set_filter(filters_dict=sq)
            df2 = fov2.screener_view()
            if df2 is None or df2.empty:
                st.warning("⚠️ 조건 충족 종목 없음. 패턴 조건을 Any로 완화해보세요.")
            else:
                st.success(f"✅ {len(df2)}개 응축 대기 종목 발굴!")
                preferred2 = ["Ticker","Company","Sector","Price","Change",
                              "Volume","Relative Volume","Beta","Market Cap","Pattern"]
                cols2 = [c for c in preferred2 if c in df2.columns] or df2.columns.tolist()
                st.dataframe(df2[cols2], use_container_width=True, hide_index=True)
                if "Ticker" in df2.columns:
                    st.markdown("#### 🎯 발굴된 Squeeze 후보 티커")
                    st.code(", ".join(df2["Ticker"].tolist()[:20]))
                    st.caption("⚠️ 돌파 캔들 + 거래량 급증 확인 후 정규장 진입. After-hours 아님.")
        except ImportError:
            st.error("❌ `pip install finvizfinance` 후 재실행하세요.")
        except Exception as e:
            handle_screener_error(e)
    else:
        st.info("⬆️ 조건 확인 후 실행 버튼을 누르세요.")

    st.divider()
    st.warning(
        "⚠️ **Squeeze 전략 주의사항**\n\n"
        "① 응축 → 하락 해소 가능성도 항상 존재. 돌파 전 진입 금지.\n"
        "② 어닝 발표 예정 종목은 결과에서 수동 제거.\n"
        "③ APEX Overnight 전략과 혼용 금지 — 목적이 완전히 다름."
    )


# ══════════════════════════════════════════════════════════════
# TAB 3 — 개별 종목 정밀 분석
# ══════════════════════════════════════════════════════════════
with tab_analyze:
    st.header("🔍 개별 종목 정밀 팩트체크")

    ticker = st.text_input(
        "분석할 티커 입력", value="", placeholder="예: ASTS, MSTR, TSLA"
    ).upper().strip()

    if ticker:
        st.subheader(f"🔍 {ticker} 정밀 팩트체크 리포트")

        try:
            stock = yf.Ticker(ticker)
            info  = stock.info

            # ── 데이터 수집 ────────────────────────────
            current_price = info.get("regularMarketPrice") or info.get("currentPrice")

            hist_daily    = stock.history(period="300d", interval="1d")
            hist_intraday = stock.history(period="1d",   interval="1m")

            # SMA200
            sma200 = None
            if len(hist_daily) >= 200:
                sma200 = float(hist_daily["Close"].rolling(200).mean().iloc[-1])

            # ATR14
            atr14 = calc_atr(hist_daily, 14)

            # RSI(2), RSI(14)
            rsi2  = calc_rsi(hist_daily["Close"], 2)
            rsi14 = calc_rsi(hist_daily["Close"], 14)

            # Bollinger Band
            bb_upper, bb_mid, bb_lower, bb_width, bb_pctb = calc_bb(hist_daily["Close"], 20)

            # VWAP
            vwap = None
            if not hist_intraday.empty and hist_intraday["Volume"].sum() > 0:
                tp       = (hist_intraday["High"] + hist_intraday["Low"] + hist_intraday["Close"]) / 3
                tot_vol  = hist_intraday["Volume"].cumsum().iloc[-1]
                if tot_vol > 0:
                    vwap = float((tp * hist_intraday["Volume"]).cumsum().iloc[-1] / tot_vol)

            # 수급 지표
            avg_vol      = info.get("averageVolume10days") or info.get("averageVolume") or 1
            curr_vol     = info.get("regularMarketVolume") or 0
            rvol         = curr_vol / avg_vol if avg_vol > 0 else 0
            float_shares = info.get("floatShares") or 0
            si_raw       = info.get("shortPercentOfFloat") or 0
            si_ratio     = si_raw * 100 if si_raw < 1 else si_raw

            # session_state 저장 (TAB 4 공유)
            st.session_state.update({
                "apex_ticker":        ticker,
                "apex_current_price": current_price,
                "apex_atr14":         atr14,
                "apex_sma200":        sma200,
            })

            # ══════════════════════════════════════════
            # APEX 가중 점수 계산
            # ══════════════════════════════════════════
            # ── APEX 가중 점수 계산 (nonlocal 대신 mutable 리스트 사용) ──
            score_box    = [0]   # [0] = 현재 점수 (int 불변 객체 우회)
            score_detail = {}

            def add_score(label, condition, points, reason=""):
                if condition is True:
                    score_box[0] += points
                    score_detail[label] = (True,  points, reason)
                elif condition is False:
                    score_detail[label] = (False, 0,      reason)
                else:
                    score_detail[label] = (None,  0,      "데이터 없음")

            add_score("🎈 Float < 20M",    (float_shares < 20e6)        if float_shares  else None, 30, "폭등 체급")
            add_score("🧨 SI > 15%",       (si_ratio > 15)              if si_ratio      else None, 20, "숏 스퀴즈 연료")
            add_score("🦴 SMA200 위",      (current_price > sma200)     if (sma200 and current_price) else None, 20, "악성 매물대 없음")
            add_score("🎯 VWAP 위",        (current_price > vwap)       if (vwap and current_price) else None, 15, "세력 수익권")
            add_score("📊 RVOL > 2x",      (rvol > 2.0)                 if rvol          else None, 15, "세력 개입 증거")
            score = score_box[0]   # 이후 코드에서 score 변수명 유지

            pass_count = sum(1 for v in score_detail.values() if v[0] is True)

            # ── APEX 종합 점수 헤더 ──────────────────────
            st.divider()
            score_col1, score_col2 = st.columns([1, 2])
            with score_col1:
                if score >= 80:
                    st.metric("🏆 APEX 종합 점수", f"{score}/100")
                    st.success("🔥 **최우선 후보** — 촉매 확인 시 승부 타이밍")
                elif score >= 55:
                    st.metric("⚠️ APEX 종합 점수", f"{score}/100")
                    st.warning("🟡 **조건 부분 충족** — 신중 접근 필요")
                elif score >= 35:
                    st.metric("❌ APEX 종합 점수", f"{score}/100")
                    st.error("🔴 **조건 미달** — 이 종목은 APEX 기준 부적합")
                else:
                    st.metric("🚫 APEX 종합 점수", f"{score}/100")
                    st.error("🚫 **즉시 패스** — APEX 기준 전혀 충족 못함")

            with score_col2:
                st.markdown("**📊 조건별 점수 내역**")
                for label, (result, pts, reason) in score_detail.items():
                    if result is True:
                        st.markdown(f"✅ {label} **+{pts}점** — {reason}")
                    elif result is False:
                        st.markdown(f"❌ {label} **+0점** — {reason}")
                    else:
                        st.markdown(f"⚪ {label} **데이터 없음**")

            # ── Float 경고 세분화 ─────────────────────
            if float_shares:
                fm = float_shares / 1e6
                if fm > 100:
                    st.error(
                        f"🚨 **Float 경고: {fm:.0f}M** — APEX Overnight 전략에 매우 부적합. "
                        f"단, SI {si_ratio:.1f}%가 높다면 대형 숏 스퀴즈 가능성은 별도 검토."
                    )
                elif fm > 50:
                    st.warning(f"⚠️ **Float {fm:.0f}M** — 중형주. 150% 폭등 어렵고 20~40% 상승 기대.")
                elif fm > 20:
                    st.info(f"ℹ️ **Float {fm:.0f}M** — 소형주 범위. 조건 완화 가능하나 최적은 아님.")

            st.divider()

            # ── 핵심 수급 지표 ────────────────────────────
            st.markdown("### 📊 핵심 수급 지표")
            col1, col2, col3 = st.columns(3)

            with col1:
                st.metric("📊 RVOL", f"{rvol:.2f}x")
                st.caption("평소 대비 자금 유입량")
                if rvol > 2.0:   st.success("✅ 세력 매집 신호")
                elif rvol > 1.5: st.warning("⚠️ 수급 유입 시작")
                else:            st.info("⚪ 세력 개입 증거 부족")

            with col2:
                st.metric("🎈 Float", f"{float_shares/1e6:.1f}M" if float_shares else "N/A")
                st.caption("유동주식수 — 가벼울수록 폭등 용이")
                if float_shares:
                    fm = float_shares / 1e6
                    if fm < 20:        st.success("✅ 폭등 최적 체급 (<20M)")
                    elif fm < 50:      st.info("⚪ 소형주 (~50M)")
                    elif fm < 100:     st.warning("⚠️ 중형주 (~100M)")
                    else:              st.error("❌ 대형주 — 폭등 불적합")
                else:
                    st.info("⚪ 데이터 없음")

            with col3:
                st.metric("🧨 SI%", f"{si_ratio:.1f}%")
                st.caption("숏 스퀴즈 연료")
                if si_ratio > 20:    st.success("✅ 초강력 숏 스퀴즈 탄약 (>20%)")
                elif si_ratio > 15:  st.success("✅ 숏 스퀴즈 탄약 완비")
                elif si_ratio > 10:  st.warning("⚠️ 공매도 축적 중")
                else:                st.info("⚪ 연료 부족")

            st.divider()

            # ── 기술적 지표 (SMA200, VWAP, RSI, BB) ─────
            st.markdown("### 📐 기술적 분석 지표")
            t1, t2 = st.columns(2)

            with t1:
                # SMA200
                st.markdown("#### 🦴 현재가 vs SMA200")
                st.caption("현재가 > SMA200 = 매물대 위 / 이하 = 진입 금지")
                if sma200 and current_price:
                    gap = ((current_price - sma200) / sma200) * 100
                    st.metric("현재가 vs SMA200", f"${current_price:.2f}",
                              delta=f"SMA200 ${sma200:.2f} 대비 {gap:+.1f}%")
                    if current_price > sma200:
                        st.success(f"🟢 초록불 — **${current_price:.2f}** > SMA200 **${sma200:.2f}**")
                    else:
                        st.error(f"🔴 빨간불 — **${current_price:.2f}** < SMA200 **${sma200:.2f}** → 진입 금지")
                elif not sma200:
                    st.warning("⚠️ 상장 200일 미만 또는 데이터 오류")
                else:
                    st.warning("⚠️ 현재가 데이터 없음")

                st.write("")
                # VWAP
                st.markdown("#### 🎯 현재가 vs VWAP")
                st.caption("현재가 > VWAP = 세력 수익권 / 이탈 = 세력 털기 신호")
                if vwap and current_price:
                    gv = ((current_price - vwap) / vwap) * 100
                    st.metric("현재가 vs VWAP", f"${current_price:.2f}",
                              delta=f"VWAP ${vwap:.2f} 대비 {gv:+.1f}%")
                    if current_price > vwap:
                        st.success(f"🟢 초록불 — **${current_price:.2f}** > VWAP **${vwap:.2f}**")
                    else:
                        st.error(f"🔴 빨간불 — **${current_price:.2f}** < VWAP **${vwap:.2f}** → 보유 재고")
                else:
                    st.warning("⚠️ VWAP 산출 불가 — 장 마감 후이거나 거래량 없음")

            with t2:
                # RSI(2) + RSI(14)
                st.markdown("#### 📉 RSI 지표")
                st.caption("RSI(2) ≤ 10 = APEX MR 전략 과매도 조건 충족")

                rsi_c1, rsi_c2 = st.columns(2)
                with rsi_c1:
                    if rsi2 is not None:
                        st.metric("RSI(2)", f"{rsi2:.1f}")
                        if rsi2 <= 10:
                            st.success("✅ APEX MR 조건 충족\n(극도 과매도)")
                        elif rsi2 <= 30:
                            st.info("⚪ 과매도 구간")
                        elif rsi2 >= 70:
                            st.error("❌ 과매수 — 추격 금지")
                        else:
                            st.info(f"⚪ 중립 구간")
                    else:
                        st.info("RSI(2) 계산 불가")

                with rsi_c2:
                    if rsi14 is not None:
                        st.metric("RSI(14)", f"{rsi14:.1f}")
                        if rsi14 >= 70:
                            st.error("❌ 과매수")
                        elif rsi14 <= 30:
                            st.success("✅ 과매도 반등 기대")
                        else:
                            st.info("⚪ 중립")
                    else:
                        st.info("RSI(14) 계산 불가")

                st.write("")
                # Bollinger Band
                st.markdown("#### 📊 볼린저 밴드 (Squeeze 감지)")
                st.caption("BB Width 낮음 = 응축 상태. %B 낮음 = 하단 근처 (반등 준비)")
                if bb_upper and bb_lower and current_price:
                    st.metric("현재가", f"${current_price:.2f}")
                    bb_c1, bb_c2 = st.columns(2)
                    with bb_c1:
                        st.metric("BB Width", f"{bb_width:.1f}%",
                                  help="좁을수록 에너지 응축. 5% 이하 = 폭발 직전")
                        if bb_width < 5:
                            st.success("✅ 극도 응축 — 폭발 임박")
                        elif bb_width < 10:
                            st.info("⚪ 응축 구간")
                        else:
                            st.warning("⚠️ 확장 구간 — 응축 아님")
                    with bb_c2:
                        st.metric("BB %B", f"{bb_pctb:.1f}%",
                                  help="0%=하단, 50%=중간, 100%=상단")
                        if bb_pctb < 20:
                            st.success("✅ 하단 근처 — 반등 준비")
                        elif bb_pctb > 80:
                            st.error("❌ 상단 근처 — 진입 위험")
                        else:
                            st.info(f"⚪ 중간 구간")

                    # BB 시각화
                    st.markdown(
                        f"**상단** ${bb_upper:.2f} &nbsp;|&nbsp; "
                        f"**중간(20일MA)** ${bb_mid:.2f} &nbsp;|&nbsp; "
                        f"**하단** ${bb_lower:.2f}"
                    )
                else:
                    st.info("⚪ 볼린저 밴드 계산 불가 (데이터 부족)")

            st.divider()

            # ── 뉴스 & 외부 링크 ──────────────────────────
            n1, n2 = st.columns(2)

            with n1:
                st.markdown("### 📂 뉴스 & 공시 (재료 체크)")
                st.info("⚠️ 제목에 **Offering / S-3 / F-3 / Dilut / Warrant** → 무조건 패스")
                DANGER = ["offering","s-3","f-3","dilut","warrant","shelf","secondary"]
                try:
                    news_list = stock.news or []
                    if news_list:
                        for item in news_list[:5]:
                            content = item.get("content", {})
                            if isinstance(content, dict):
                                title = content.get("title", "제목 없음")
                                link  = (content.get("canonicalUrl") or {}).get("url", "#")
                            else:
                                title = item.get("title", "제목 없음")
                                link  = item.get("link", "#")
                            if any(k in title.lower() for k in DANGER):
                                st.error(f"🚨 위험 키워드 감지 — [{title}]({link})")
                            else:
                                st.markdown(f"- [{title}]({link})")
                    else:
                        st.write("최근 뉴스 없음")
                except Exception:
                    st.write("뉴스 로드 실패")

            with n2:
                st.markdown("### 📊 세력 수급 & 차트")
                st.info("Dark Pool % **50%+** = 세력 물량 매집 증거")
                st.markdown(
                    f"**[👉 {ticker} 다크풀 데이터]"
                    f"(https://chartexchange.com/symbol/nasdaq-{ticker}/stats/)**"
                )
                st.write("")
                st.markdown(
                    f"**[👉 Finviz {ticker} 차트]"
                    f"(https://finviz.com/quote.ashx?t={ticker})**"
                )
                st.write("")
                st.markdown(
                    f"**[👉 {ticker} SEC 공시 확인 (EDGAR)]"
                    f"(https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany&company={ticker}&type=8-K)**"
                )

            st.divider()

            # ── Overnight Gap Play 진입 타이밍 ──────────
            st.markdown("### ⏰ Overnight Gap Play 진입 타이밍 가이드")
            t_c1, t_c2, t_c3 = st.columns(3)
            with t_c1:
                st.info(
                    "**📅 1단계 — 장 마감 전 (3:30~4:00 ET)**\n\n"
                    "- 스크리너로 후보 발굴 완료\n"
                    "- 오늘 밤 8-K / 임상 / 어닝 공시 확인\n"
                    "- Grok X 반응 사전 스캔\n"
                    "- Offering 공시 종목 진입 금지 리스트 작성"
                )
            with t_c2:
                st.warning(
                    "**🌙 2단계 — After-market 진입 (4:00~8:00 ET)**\n\n"
                    "- 촉매 확인 후 **30분 이내** 진입\n"
                    "- 진입가 = AH 현재 호가 (지정가 주문)\n"
                    "- 진입 직후 ATR 손절가 즉시 설정\n"
                    "- 계좌 **최대 2% 리스크** 포지션 사이징\n"
                    "- 뉴스 30분 후 수급 식으면 **진입 포기**"
                )
            with t_c3:
                st.success(
                    "**🌅 3단계 — Pre-market 청산 (7:00~9:30 ET)**\n\n"
                    "- 갭업 확인 시 9:30 전 **50~70% 물량 청산**\n"
                    "- 잔량은 9:30 오픈 후 VWAP 반응 보고 청산\n"
                    "- 갭다운 또는 VWAP 이탈 시 **전량 즉시 손절**"
                )
            st.error(
                "🚨 **절대 금지 조건** — ① Offering/Dilution 공시 → 즉시 전량 손절 "
                "② Pre-market 고점 대비 -15% 이탈 → 손절 실행 "
                "③ 정규장 VWAP 이탈 → 잔량 청산 "
                "④ 촉매 없는 After-hours 급등 → 진입 금지 (펌프&덤프 주의)"
            )

            st.divider()

            # ── 최종 조건 체크 + Grok 프롬프트 ──────────
            st.markdown("### ✅ APEX 최종 조건 체크")
            ch_cols = st.columns(len(score_detail))
            for i, (label, (result, pts, reason)) in enumerate(score_detail.items()):
                with ch_cols[i]:
                    if result is True:   st.success(f"✅ {label}\n+{pts}점")
                    elif result is False: st.error(f"❌ {label}\n0점")
                    else:                st.info(f"⚪ {label}\n데이터 없음")

            st.write("")
            if score >= 80:
                st.success(f"🔥 **{score}/100점** — 촉매 + 다크풀 60%+ 확인 시 승부 타이밍! [추론]")
                st.info("👉 **[💰 ATR 손절 & 포지션 사이징]** 탭에서 리스크 계산하세요.")
            elif score >= 55:
                st.warning(f"⚠️ **{score}/100점** — 조건 부분 충족. 신중 접근. [추론]")
            else:
                st.error(f"🚫 **{score}/100점** — APEX 기준 미달. 패스 권장. [추론]")

            # Grok 프롬프트
            st.divider()
            st.markdown("### 🤖 Grok 최종 검증 프롬프트")
            p = current_price
            grok = (
                f"너는 Overnight Gap Play 전략 AI APEX v9.0이다. 대상: {ticker}\n"
                f"현재가: ${p:.2f} | SMA200: ${sma200:.2f} | VWAP: ${vwap:.2f} | ATR14: ${atr14:.2f}\n"
                f"RSI(2): {rsi2:.1f} | RSI(14): {rsi14:.1f} | BB Width: {bb_width:.1f}%\n"
                f"Float: {float_shares/1e6:.1f}M | SI: {si_ratio:.1f}% | RVOL: {rvol:.2f}x\n"
                f"APEX 점수: {score}/100 ({pass_count}/5 조건 충족)\n\n"
                f"1. 오늘 밤~내일 새벽 터질 8-K 공시/호재가 있는가?\n"
                f"2. X(트위터) 모멘텀과 반응이 살아있는가?\n"
                f"3. Offering/Dilution 위험이 있는가?\n"
                f"4. 내일 Pre-market 갭업 가능성을 100점 만점으로 점수 매겨줘."
            ) if (p and sma200 and vwap and atr14 and rsi2 and rsi14 and bb_width) else (
                f"너는 Overnight Gap Play 전략 AI APEX v9.0이다. 대상: {ticker}\n"
                f"APEX 점수: {score}/100\n일부 데이터 없음. 위 종목의 오늘 밤 폭등 가능성을 분석해줘."
            )
            st.code(grok, language="text")

        except Exception as e:
            st.error(f"오류 발생: {e}")
            st.info("티커 확인 후 잠시 후 재시도하세요.")

    else:
        st.info("티커를 입력하면 분석이 시작됩니다.")
        st.markdown("""
**APEX v9.0 분석 흐름:**
1. **[🔭 APEX 스크리너]** → 후보 자동 발굴
2. **[🔍 개별 분석]** → 100점 가중 점수 + RSI + BB + 진입 타이밍
3. **[💰 ATR 손절]** → 손절가·목표가·수량 계산
4. Grok 최종 검증 → 승부수 결정
        """)


# ══════════════════════════════════════════════════════════════
# TAB 4 — ATR 손절 & 포지션 사이징
# ══════════════════════════════════════════════════════════════
with tab_risk:
    st.header("💰 ATR 기반 손절선 & 포지션 사이징 계산기")
    st.caption(
        "ATR14 = 최근 14거래일 평균 변동폭. 손절을 ATR 기준으로 설정 = 노이즈에 의한 허위 손절 방지."
    )

    default_ticker = st.session_state.get("apex_ticker", "")
    default_price  = st.session_state.get("apex_current_price", None)
    default_atr    = st.session_state.get("apex_atr14", None)

    risk_ticker = st.text_input(
        "티커 입력 (개별 분석 탭 실행 시 자동 입력)",
        value=default_ticker, placeholder="예: ASTS"
    ).upper().strip()

    if risk_ticker:
        # 데이터 로드
        if risk_ticker == default_ticker and default_price and default_atr:
            current_price = default_price
            atr14         = default_atr
            st.success(f"✅ [{risk_ticker}] 개별 분석 탭 데이터 자동 로드")
        else:
            with st.spinner(f"{risk_ticker} 데이터 로딩 중..."):
                try:
                    stk   = yf.Ticker(risk_ticker)
                    info2 = stk.info
                    current_price = info2.get("regularMarketPrice") or info2.get("currentPrice")
                    hist2 = stk.history(period="30d", interval="1d")
                    atr14 = calc_atr(hist2, 14)
                except Exception as e:
                    st.error(f"데이터 오류: {e}")
                    current_price = None
                    atr14 = None

        if current_price and atr14:
            st.markdown(f"**현재가:** ${current_price:.2f} &nbsp;|&nbsp; **ATR14:** ${atr14:.2f}")

            st.divider()
            st.markdown("### ⚙️ 리스크 파라미터")
            p1, p2, p3 = st.columns(3)
            with p1:
                account = st.number_input("💼 계좌 총 자본 ($)",
                                          min_value=100.0, max_value=1_000_000.0,
                                          value=4000.0, step=100.0)
            with p2:
                risk_pct = st.slider("🎯 트레이드당 최대 손실 허용 (%)",
                                     min_value=0.5, max_value=5.0,
                                     value=2.0, step=0.5,
                                     help="권장: 1~2%. 3% 초과 시 고위험.")
            with p3:
                atr_mult = st.selectbox("📏 ATR 배수 (손절 여유폭)",
                                        [1.0, 1.5, 2.0, 2.5, 3.0], index=1,
                                        help="Overnight Gap Play 기본: 1.5x")

            # 계산
            risk_dollar   = account * (risk_pct / 100)
            stop_dist     = atr14 * atr_mult
            stop_price    = current_price - stop_dist
            shares        = max(1, int(risk_dollar / stop_dist))
            pos_value     = shares * current_price
            pos_pct       = (pos_value / account) * 100
            t1r = current_price + stop_dist
            t2r = current_price + stop_dist * 2
            t3r = current_price + stop_dist * 3
            g1  = (stop_dist / current_price) * 100
            g2, g3 = g1 * 2, g1 * 3

            st.divider()
            st.markdown("### 📊 계산 결과")
            r1, r2, r3, r4 = st.columns(4)
            with r1:
                st.metric("🔴 손절가", f"${stop_price:.2f}",
                          delta=f"-{stop_dist:.2f} (-{(stop_dist/current_price*100):.1f}%)",
                          delta_color="inverse")
                st.caption(f"ATR14 ${atr14:.2f} × {atr_mult}배")
            with r2:
                st.metric("📦 매수 수량", f"{shares:,} 주",
                          delta=f"포지션 ${pos_value:,.0f} ({pos_pct:.1f}%)")
                st.caption(f"리스크 ${risk_dollar:.0f} ÷ 손절폭 ${stop_dist:.2f}")
            with r3:
                st.metric("💵 최대 예상 손실", f"-${risk_dollar:,.0f}",
                          delta=f"-{risk_pct:.1f}%", delta_color="inverse")
                st.caption("이 금액 이상 잃지 않도록 손절 필수")
            with r4:
                if pos_pct > 50:
                    st.metric("⚠️ 포지션 비중", f"{pos_pct:.1f}%")
                    st.error("50% 초과 — 분할 진입 고려")
                else:
                    st.metric("✅ 포지션 비중", f"{pos_pct:.1f}%")

            st.divider()
            st.markdown("### 🎯 Risk/Reward 목표가")
            g_c1, g_c2, g_c3 = st.columns(3)
            with g_c1:
                st.info(
                    f"**1:1 RR (보수적)**\n\n"
                    f"목표가: **${t1r:.2f}** (+{g1:.1f}%)\n\n"
                    f"예상 수익: **+${shares*stop_dist:,.0f}**\n\n"
                    f"Pre-market 갭업 초기 50% 청산"
                )
            with g_c2:
                st.success(
                    f"**1:2 RR (기본 목표)**\n\n"
                    f"목표가: **${t2r:.2f}** (+{g2:.1f}%)\n\n"
                    f"예상 수익: **+${shares*stop_dist*2:,.0f}**\n\n"
                    f"Overnight Gap Play 메인 타겟"
                )
            with g_c3:
                st.warning(
                    f"**1:3 RR (공격적)**\n\n"
                    f"목표가: **${t3r:.2f}** (+{g3:.1f}%)\n\n"
                    f"예상 수익: **+${shares*stop_dist*3:,.0f}**\n\n"
                    f"SI 20%+ 강한 촉매 종목만"
                )

            st.divider()
            st.markdown("### 📋 실전 트레이드 플랜 요약")
            st.markdown(f"""
| 항목 | 수치 |
|------|------|
| 📌 **진입가 (After-market 기준)** | ${current_price:.2f} |
| 🔴 **손절가** | ${stop_price:.2f} (현재가 대비 -{(stop_dist/current_price*100):.1f}%) |
| 🎯 **1차 목표 (1:2 RR)** | ${t2r:.2f} (+{g2:.1f}%) |
| 🎯 **2차 목표 (1:3 RR)** | ${t3r:.2f} (+{g3:.1f}%) |
| 📦 **매수 수량** | {shares:,} 주 |
| 💼 **포지션 금액** | ${pos_value:,.0f} (계좌 {pos_pct:.1f}%) |
| 🛡️ **최대 손실** | -${risk_dollar:,.0f} (계좌 -{risk_pct:.1f}%) |
| ⏰ **1차 청산** | 다음날 Pre-market 갭업 시 50~70% |
            """)

            st.warning(
                "⚠️ **Overnight 리스크 주의사항** — "
                "① After-hours 지정가 주문 필수 (시장가 금지) "
                "② Pre-market Offering 공시 시 즉시 전량 손절 "
                "③ 갭다운 오픈 시 기다리지 말고 즉시 청산 "
                "④ 수익 중에도 VWAP 이탈 시 잔량 정리"
            )
        else:
            if risk_ticker:
                st.warning("⚠️ 데이터 로드 실패. [🔍 개별 분석] 탭 먼저 실행하거나 잠시 후 재시도.")
    else:
        st.info("티커를 입력하거나 **[🔍 개별 종목 분석]** 탭 실행 후 이 탭으로 이동하면 자동 입력됩니다.")
        st.markdown("""
**ATR 손절 계산 원리:**
- ATR14 = 최근 14거래일 평균 실제 변동폭 (노이즈 기준)
- 손절가 = 진입가 − (ATR × 배수)
- 매수 수량 = (계좌 × 리스크%) ÷ 손절폭
- 이 공식은 시장 노이즈를 고려한 과학적 손절 기준입니다.
        """)
