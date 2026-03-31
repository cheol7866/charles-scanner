"""
APEX v8.2 — 프리마켓 폭등 전략 센터 (ATR 손절 + 포지션 사이징 + 진입 타이밍 포함)
의존 패키지: pip install streamlit yfinance pandas finvizfinance
실행: streamlit run apex_v82_full.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd

# ──────────────────────────────────────────────
# 화면 설정
# ──────────────────────────────────────────────
st.set_page_config(page_title="APEX v8.2 전략 센터", layout="wide")
st.title("🚀 APEX v8.2 — Overnight Gap Play 전략 센터")
st.caption(
    "전략: After-market 촉매 확인 후 진입 → 다음날 Pre-market 갭업 시 청산 | "
    "Float 소형 + SI 높음 + SMA200 위 + 강한 촉매 = 핵심 조건"
)

tab_screen, tab_analyze, tab_risk = st.tabs([
    "🔭 스크리너 (후보 자동 발굴)",
    "🔍 개별 종목 분석",
    "💰 ATR 손절 & 포지션 사이징",
])


# ══════════════════════════════════════════════
# TAB 1 — Finviz 스크리너
# ══════════════════════════════════════════════
with tab_screen:
    st.header("🔭 APEX 조건 자동 스크리닝")
    st.caption(
        "Finviz에서 APEX 5대 조건을 충족하는 후보 종목을 자동으로 추출합니다."
    )

    with st.expander("⚙️ 스크리너 조건 설정", expanded=True):
        col_f1, col_f2, col_f3 = st.columns(3)

        with col_f1:
            float_filter = st.selectbox(
                "🎈 Float (유동주식수)",
                ["Under 20M", "Under 50M", "Under 100M"],
                index=0,
                help="폭등 최적: Under 20M"
            )
            si_filter = st.selectbox(
                "🧨 Float Short (공매도 잔고)",
                ["Over 15%", "Over 10%", "Over 5%"],
                index=0,
                help="숏 스퀴즈 탄약: Over 15% 권장"
            )

        with col_f2:
            sma_filter = st.selectbox(
                "🦴 200일 이동평균선",
                ["Price above SMA200", "Price below SMA200", "Any"],
                index=0,
                help="매물대 위: Price above SMA200 필수"
            )
            rvol_filter = st.selectbox(
                "📊 상대 거래량",
                ["Over 2", "Over 1.5", "Over 3", "Any"],
                index=0,
                help="세력 개입: Over 2 권장"
            )

        with col_f3:
            avgvol_filter = st.selectbox(
                "💧 평균 거래량 (유동성)",
                ["Over 500K", "Over 200K", "Over 1M"],
                index=0,
                help="유동성 보장: Over 500K"
            )
            price_filter = st.selectbox(
                "💲 주가 범위",
                ["Over $1", "Over $2", "Over $5", "Over $10"],
                index=0,
            )

    run_screen = st.button("🚀 스크리너 실행", type="primary", use_container_width=True)

    if run_screen:
        filters_dict = {}
        if float_filter   != "Any": filters_dict["Float"]                          = float_filter
        if si_filter      != "Any": filters_dict["Float Short"]                    = si_filter
        if sma_filter     != "Any": filters_dict["200-Day Simple Moving Average"]  = sma_filter
        if rvol_filter    != "Any": filters_dict["Relative Volume"]                = rvol_filter
        if avgvol_filter  != "Any": filters_dict["Average Volume"]                 = avgvol_filter
        if price_filter   != "Any": filters_dict["Price"]                          = price_filter

        st.info(f"📡 Finviz 스크리닝 중... 조건: `{filters_dict}`")

        try:
            from finvizfinance.screener.overview import Overview
            fov = Overview()
            fov.set_filter(filters_dict=filters_dict)
            df = fov.screener_view()

            if df is None or df.empty:
                st.warning("⚠️ 조건에 맞는 종목이 없습니다. 조건을 완화해보세요.")
            else:
                st.success(f"✅ {len(df)}개 후보 종목 발굴 완료!")
                preferred_cols = [
                    "Ticker", "Company", "Sector", "Price", "Change",
                    "Volume", "Relative Volume", "Float", "Short Float", "Market Cap"
                ]
                display_cols = [c for c in preferred_cols if c in df.columns] or df.columns.tolist()
                st.dataframe(df[display_cols], use_container_width=True, hide_index=True)

                tickers_found = df["Ticker"].tolist() if "Ticker" in df.columns else []
                if tickers_found:
                    st.write("#### 🎯 발굴된 후보 티커 (개별 분석 탭에 복사)")
                    st.code(", ".join(tickers_found[:20]), language="text")
                    st.caption(
                        "위 티커를 **[🔍 개별 종목 분석]** 탭에 입력 → "
                        "SMA200 / VWAP / 공시 체크 후 "
                        "**[💰 ATR 손절 & 포지션 사이징]** 탭에서 리스크 계산하세요."
                    )

        except ImportError:
            st.error("❌ `pip install finvizfinance` 후 재실행하세요.")
        except Exception as e:
            err = str(e)
            if any(k in err for k in ["ProxyError", "ConnectionError", "Max retries", "403"]):
                st.error(
                    "🌐 **Finviz 접속 실패** — VPN 없이 재시도하거나 1~2분 후 다시 시도하세요.\n\n"
                    "직접 확인: https://finviz.com/screener.ashx"
                )
            else:
                st.error(f"❌ 스크리너 오류: {e}")
    else:
        st.info("⬆️ 조건 확인 후 **[스크리너 실행]** 버튼을 눌러주세요.")

    st.divider()
    st.subheader("📋 APEX 5대 조건 해설")
    ec1, ec2, ec3, ec4, ec5 = st.columns(5)
    with ec1: st.info("🎈 **Float < 20M**\n\n가벼운 체급 = 적은 돈으로 150% 상승 가능.")
    with ec2: st.success("🧨 **SI > 15%**\n\n숏 세력의 패닉 커버가 갭업을 증폭시킴.")
    with ec3: st.success("🦴 **SMA200 위**\n\n악성 매물대 없음 = 저항 없는 상승 가능.")
    with ec4: st.warning("📊 **RVOL > 2x**\n\n세력 개입 증거 = 의도적 수급 집중.")
    with ec5: st.error("💲 **유동성 확보**\n\n After-hours 진입·청산 가능 최소 조건.")


# ══════════════════════════════════════════════
# TAB 2 — 개별 종목 정밀 분석
# ══════════════════════════════════════════════
with tab_analyze:
    st.header("🔍 개별 종목 정밀 팩트체크")

    ticker = st.text_input(
        "분석할 티커 입력 (예: AAPL, MSTR)",
        value="",
        placeholder="티커 입력 후 Enter..."
    ).upper().strip()

    if ticker:
        st.subheader(f"🔍 {ticker} 정밀 팩트체크 리포트")
        # 분석 결과를 session_state에 저장해 TAB 3에서 재활용
        try:
            stock = yf.Ticker(ticker)
            info  = stock.info

            current_price = info.get("regularMarketPrice") or info.get("currentPrice")

            # SMA200
            hist_daily = stock.history(period="300d", interval="1d")
            sma200 = None
            if len(hist_daily) >= 200:
                sma200 = float(hist_daily["Close"].rolling(200).mean().iloc[-1])

            # ATR14 (손절 계산에도 사용)
            atr14 = None
            if len(hist_daily) >= 15:
                h = hist_daily["High"]
                l = hist_daily["Low"]
                pc = hist_daily["Close"].shift(1)
                tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
                atr14 = float(tr.rolling(14).mean().iloc[-1])

            # VWAP
            hist_intraday = stock.history(period="1d", interval="1m")
            vwap = None
            if not hist_intraday.empty and hist_intraday["Volume"].sum() > 0:
                tp = (hist_intraday["High"] + hist_intraday["Low"] + hist_intraday["Close"]) / 3
                total_vol = hist_intraday["Volume"].cumsum().iloc[-1]
                if total_vol > 0:
                    vwap = float((tp * hist_intraday["Volume"]).cumsum().iloc[-1] / total_vol)

            # session_state 저장 (TAB 3 공유)
            st.session_state["apex_ticker"]        = ticker
            st.session_state["apex_current_price"] = current_price
            st.session_state["apex_atr14"]         = atr14
            st.session_state["apex_sma200"]        = sma200

            # ── 3대 수급 지표 ──────────────────────────
            st.write("### 📊 핵심 수급 지표")
            col1, col2, col3 = st.columns(3)

            with col1:
                avg_vol  = info.get("averageVolume10days") or info.get("averageVolume") or 1
                curr_vol = info.get("regularMarketVolume") or 0
                rvol     = curr_vol / avg_vol if avg_vol > 0 else 0
                st.metric("📊 상대 거래량 (RVOL)", f"{rvol:.2f}x")
                st.caption("평소 대비 자금 유입량")
                if rvol > 2.0:   st.success("✅ 세력 매집 신호")
                elif rvol > 1.5: st.warning("⚠️ 수급 유입 시작")
                else:            st.info("⚪ 세력 개입 증거 부족")

            with col2:
                float_shares = info.get("floatShares") or 0
                st.metric("🎈 Float", f"{float_shares/1e6:.1f}M" if float_shares else "N/A")
                st.caption("유동주식수 — 가벼울수록 폭등 용이")
                if float_shares and float_shares < 20e6:   st.success("✅ 폭등 체급")
                elif float_shares and float_shares < 50e6: st.info("⚪ 중소형주")
                elif float_shares:                          st.error("❌ 너무 무거움")
                else:                                       st.info("⚪ 데이터 없음")

            with col3:
                si_raw   = info.get("shortPercentOfFloat") or 0
                si_ratio = si_raw * 100 if si_raw < 1 else si_raw
                st.metric("🧨 공매도 잔고 (SI%)", f"{si_ratio:.1f}%")
                st.caption("숏 스퀴즈 연료")
                if si_ratio > 15:   st.success("✅ 숏 스퀴즈 탄약 완비")
                elif si_ratio > 10: st.warning("⚠️ 공매도 축적 중")
                else:               st.info("⚪ 연료 부족")

            st.divider()

            # ── SMA200 / VWAP ──────────────────────────
            st.write("### 📐 기술적 기준선")
            col4, col5 = st.columns(2)

            with col4:
                st.write("#### 🦴 현재가 vs SMA200")
                st.caption("현재가 > SMA200 = 매물대 위 = 진입 가능 / 이하 = 진입 금지")
                if sma200 and current_price:
                    gap = ((current_price - sma200) / sma200) * 100
                    st.metric("현재가 vs SMA200", f"${current_price:.2f}",
                              delta=f"SMA200 ${sma200:.2f} 대비 {gap:+.1f}%")
                    if current_price > sma200:
                        st.success(f"🟢 초록불 — 현재가 ${current_price:.2f} > SMA200 ${sma200:.2f}")
                    else:
                        st.error(f"🔴 빨간불 — 현재가 ${current_price:.2f} < SMA200 ${sma200:.2f} → 진입 금지")
                elif not sma200:
                    st.warning("⚠️ 상장 200일 미만 또는 데이터 오류")
                else:
                    st.warning("⚠️ 현재가 데이터 없음")

            with col5:
                st.write("#### 🎯 현재가 vs VWAP")
                st.caption("현재가 > VWAP = 세력 수익권 = 홀딩 / 이탈 = 세력 털기 신호")
                if vwap and current_price:
                    gap_v = ((current_price - vwap) / vwap) * 100
                    st.metric("현재가 vs VWAP", f"${current_price:.2f}",
                              delta=f"VWAP ${vwap:.2f} 대비 {gap_v:+.1f}%")
                    if current_price > vwap:
                        st.success(f"🟢 초록불 — 현재가 ${current_price:.2f} > VWAP ${vwap:.2f}")
                    else:
                        st.error(f"🔴 빨간불 — 현재가 ${current_price:.2f} < VWAP ${vwap:.2f} → 보유 재고")
                else:
                    st.warning("⚠️ VWAP 산출 불가 — 장 마감 후이거나 거래량 없음. 장 중 재확인 필요.")

            st.divider()

            # ── 뉴스 & 외부 링크 ──────────────────────
            c1, c2 = st.columns(2)

            with c1:
                st.write("### 📂 뉴스 & 공시 (재료 체크)")
                st.info("⚠️ 제목에 **Offering / S-3 / F-3 / Dilut / Warrant** → 무조건 패스")
                DANGER_KEYWORDS = ["offering", "s-3", "f-3", "dilut", "warrant"]
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
                            if any(kw in title.lower() for kw in DANGER_KEYWORDS):
                                st.error(f"🚨 위험 키워드 — [{title}]({link})")
                            else:
                                st.write(f"- [{title}]({link})")
                    else:
                        st.write("최근 뉴스 없음")
                except Exception:
                    st.write("뉴스 데이터를 불러올 수 없습니다.")

            with c2:
                st.write("### 📊 세력 수급 (다크풀 체크)")
                st.info("Dark Pool % **50% 이상** = 세력 물량 매집 증거")
                st.markdown(
                    f"**[👉 {ticker} 다크풀 데이터]"
                    f"(https://chartexchange.com/symbol/nasdaq-{ticker}/stats/)**"
                )
                st.write("")
                st.write("### 📈 차트 & 기술적 위치")
                st.markdown(
                    f"**[👉 Finviz {ticker} 차트 확인]"
                    f"(https://finviz.com/quote.ashx?t={ticker})**"
                )

            st.divider()

            # ── Overnight Gap Play 진입 타이밍 가이드 ──
            st.write("### ⏰ Overnight Gap Play 진입 타이밍 가이드")

            timing_col1, timing_col2, timing_col3 = st.columns(3)

            with timing_col1:
                st.info(
                    "**📅 1단계 — After-market 전 (오후 3:30~4:00 ET)**\n\n"
                    "- Finviz 스크리너로 후보 발굴 완료\n"
                    "- 오늘 밤 예정된 8-K / 임상 결과 / 어닝 공시 확인\n"
                    "- Grok으로 X(트위터) 반응 사전 스캔\n"
                    "- **진입 금지 리스트:** Offering 공시 있는 종목"
                )

            with timing_col2:
                st.warning(
                    "**🌙 2단계 — After-market 진입 (오후 4:00~8:00 ET)**\n\n"
                    "- 촉매 뉴스 확인 후 **즉시 진입 (30분 이내)**\n"
                    "- 진입가 = After-market 현재 호가 기준\n"
                    "- 진입 직후 ATR 손절가 즉시 설정\n"
                    "- 포지션 사이징: 계좌의 **최대 2% 리스크** 기준\n"
                    "- 뉴스 30분 후 수급 식으면 **진입 포기**"
                )

            with timing_col3:
                st.success(
                    "**🌅 3단계 — Pre-market 청산 (오전 7:00~9:30 ET)**\n\n"
                    "- 갭업 확인 시 **9:30 정규장 오픈 전** 부분 청산\n"
                    "- 목표: +20~50% 갭업 시 **50~70% 물량 먼저 청산**\n"
                    "- 나머지는 9:30 오픈 후 VWAP 반응 보고 추가 청산\n"
                    "- **갭다운 or VWAP 이탈 시 전량 즉시 손절**"
                )

            st.error(
                "🚨 **Overnight Gap Play 절대 금지 조건**\n\n"
                "① Offering / Dilution 공시 발생 → 즉시 전량 손절\n"
                "② Pre-market에서 고점 대비 -15% 이탈 → 손절 실행\n"
                "③ 정규장 오픈 후 VWAP 이탈 → 잔여 물량 청산\n"
                "④ 촉매 없는 종목 After-hours 급등 → 진입 금지 (펌프 덤프 주의)"
            )

            st.divider()

            # ── 최종 조건 체크리스트 ──────────────────
            st.write("### ✅ APEX 5개 조건 최종 체크")
            conditions = {
                "🎈 Float < 20M":     (float_shares < 20e6)        if float_shares else None,
                "🧨 SI% > 15%":       (si_ratio > 15)              if si_ratio     else None,
                "🦴 현재가 > SMA200": (current_price > sma200)     if (sma200 and current_price) else None,
                "🎯 현재가 > VWAP":   (current_price > vwap)       if (vwap and current_price) else None,
                "📊 RVOL > 2x":       (rvol > 2.0)                 if rvol         else None,
            }
            pass_count = sum(1 for v in conditions.values() if v is True)
            check_cols = st.columns(len(conditions))
            for i, (label, result) in enumerate(conditions.items()):
                with check_cols[i]:
                    if result is True:   st.success(f"✅ {label}")
                    elif result is False: st.error(f"❌ {label}")
                    else:                st.info(f"⚪ {label}\n데이터 없음")

            st.write("")
            if pass_count >= 4:
                st.success(f"🔥 **{pass_count}/5 충족** — 촉매 + 다크풀 60% 확인 시 승부 타이밍!")
                st.info("👉 **[💰 ATR 손절 & 포지션 사이징]** 탭에서 진입 리스크를 계산하세요.")
            elif pass_count >= 3:
                st.warning(f"⚠️ **{pass_count}/5 충족** — 조건 부족. 신중 접근.")
            else:
                st.error(f"🚫 **{pass_count}/5 충족** — APEX 기준 미달. 패스 권장.")

            st.divider()

            # ── Grok 프롬프트 ──────────────────────────
            st.write("### 🤖 Grok 최종 검증 프롬프트")
            price_str  = f"${current_price:.2f}" if current_price else "N/A"
            sma200_str = f"${sma200:.2f}"        if sma200       else "N/A"
            vwap_str   = f"${vwap:.2f}"          if vwap         else "N/A"
            atr_str    = f"${atr14:.2f}"         if atr14        else "N/A"
            grok_prompt = (
                f"너는 Overnight Gap Play 전략 AI APEX v8.2이다. 대상 티커: {ticker}.\n"
                f"현재가: {price_str} | SMA200: {sma200_str} | VWAP: {vwap_str} | ATR14: {atr_str}\n"
                f"APEX 조건 충족: {pass_count}/5\n\n"
                f"오늘 밤 After-market 진입 후 내일 Pre-market 청산 전략 기준으로:\n"
                f"1. 오늘 밤~내일 새벽 터질 호재 공시(8-K)가 있는가?\n"
                f"2. X(트위터) 반응과 모멘텀이 살아있는가?\n"
                f"3. Offering / Dilution 위험이 있는가?\n"
                f"4. 내일 프리마켓 갭업 가능성을 100점 만점으로 점수 매겨줘."
            )
            st.code(grok_prompt, language="text")

        except Exception as e:
            st.error(f"오류 발생: {e}")
            st.info("티커를 확인하거나 잠시 후 다시 시도해주세요.")

    else:
        st.info("티커를 입력하면 분석이 시작됩니다.")
        st.markdown("""
        **활용 순서:**
        1. **[🔭 스크리너]** → APEX 조건으로 후보 자동 발굴
        2. **[🔍 개별 분석]** (이 탭) → SMA200 / VWAP / 공시 / 진입 타이밍 체크
        3. **[💰 ATR 손절]** → 손절가·목표가·포지션 크기 계산
        4. Grok 최종 검증 → 승부수 결정
        """)


# ══════════════════════════════════════════════
# TAB 3 — ATR 손절 & 포지션 사이징
# ══════════════════════════════════════════════
with tab_risk:
    st.header("💰 ATR 기반 손절선 & 포지션 사이징 계산기")
    st.caption(
        "ATR(Average True Range) = 종목의 일평균 변동 폭. "
        "손절선을 ATR 기준으로 설정하면 노이즈에 의한 허위 손절을 방지합니다."
    )

    # ── 티커 자동 불러오기 (TAB 2 분석 시 자동 입력) ──
    default_ticker = st.session_state.get("apex_ticker", "")
    default_price  = st.session_state.get("apex_current_price", None)
    default_atr    = st.session_state.get("apex_atr14", None)

    risk_ticker = st.text_input(
        "티커 입력 (개별 분석 탭 사용 시 자동 입력됨)",
        value=default_ticker,
        placeholder="예: AAPL"
    ).upper().strip()

    if risk_ticker:
        # 데이터 로드 (TAB 2 캐시 우선, 없으면 새로 fetch)
        if risk_ticker == default_ticker and default_price and default_atr:
            current_price = default_price
            atr14         = default_atr
            st.success(f"✅ [{risk_ticker}] 개별 분석 탭 데이터 자동 로드")
        else:
            with st.spinner(f"{risk_ticker} 데이터 로딩 중..."):
                try:
                    stock = yf.Ticker(risk_ticker)
                    info  = stock.info
                    current_price = info.get("regularMarketPrice") or info.get("currentPrice")
                    hist_daily = stock.history(period="30d", interval="1d")
                    atr14 = None
                    if len(hist_daily) >= 15:
                        h  = hist_daily["High"]
                        l  = hist_daily["Low"]
                        pc = hist_daily["Close"].shift(1)
                        tr = pd.concat([(h - l), (h - pc).abs(), (l - pc).abs()], axis=1).max(axis=1)
                        atr14 = float(tr.rolling(14).mean().iloc[-1])
                except Exception as e:
                    st.error(f"데이터 오류: {e}")
                    current_price = None
                    atr14 = None

        if current_price and atr14:
            st.write(f"**현재가:** ${current_price:.2f} &nbsp;|&nbsp; **ATR14:** ${atr14:.2f}")

            st.divider()

            # ── 사용자 입력 파라미터 ──────────────────
            st.write("### ⚙️ 리스크 파라미터 설정")
            param_col1, param_col2, param_col3 = st.columns(3)

            with param_col1:
                account_size = st.number_input(
                    "💼 계좌 총 자본 ($)",
                    min_value=100.0,
                    max_value=1_000_000.0,
                    value=4000.0,
                    step=100.0,
                    help="총 트레이딩 자본 (달러)"
                )

            with param_col2:
                risk_pct = st.slider(
                    "🎯 트레이드당 최대 손실 허용 (%)",
                    min_value=0.5,
                    max_value=5.0,
                    value=2.0,
                    step=0.5,
                    help="권장: 1~2%. 3% 초과 시 고위험."
                )

            with param_col3:
                atr_multiplier = st.selectbox(
                    "📏 ATR 배수 (손절 여유폭)",
                    [1.0, 1.5, 2.0, 2.5, 3.0],
                    index=1,
                    help="1.5x 권장 (Overnight Gap Play). 노이즈 많으면 2x."
                )

            # ── 계산 ──────────────────────────────────
            risk_dollar    = account_size * (risk_pct / 100)
            stop_distance  = atr14 * atr_multiplier
            stop_price     = current_price - stop_distance
            shares         = max(1, int(risk_dollar / stop_distance))
            position_value = shares * current_price
            position_pct   = (position_value / account_size) * 100

            # RR 기반 목표가
            target_1r  = current_price + stop_distance        # 1:1
            target_2r  = current_price + stop_distance * 2    # 1:2
            target_3r  = current_price + stop_distance * 3    # 1:3
            gain_1r_pct = (stop_distance / current_price) * 100
            gain_2r_pct = gain_1r_pct * 2
            gain_3r_pct = gain_1r_pct * 3

            st.divider()
            st.write("### 📊 계산 결과")

            res_col1, res_col2, res_col3, res_col4 = st.columns(4)

            with res_col1:
                st.metric("🔴 손절가 (Stop Loss)", f"${stop_price:.2f}",
                          delta=f"-{stop_distance:.2f} (-{(stop_distance/current_price*100):.1f}%)",
                          delta_color="inverse")
                st.caption(f"ATR14 ${atr14:.2f} × {atr_multiplier}배")

            with res_col2:
                st.metric("📦 매수 수량", f"{shares:,} 주",
                          delta=f"포지션 ${position_value:,.0f} (계좌의 {position_pct:.1f}%)")
                st.caption(f"리스크 ${risk_dollar:.0f} ÷ 손절폭 ${stop_distance:.2f}")

            with res_col3:
                st.metric("💵 최대 예상 손실", f"-${risk_dollar:,.0f}",
                          delta=f"계좌의 -{risk_pct:.1f}%",
                          delta_color="inverse")
                st.caption("이 금액 이상 잃지 않도록 손절 필수")

            with res_col4:
                if position_pct > 50:
                    st.metric("⚠️ 포지션 비중", f"{position_pct:.1f}%")
                    st.error("포지션이 계좌의 50% 초과. 분할 진입 고려.")
                else:
                    st.metric("✅ 포지션 비중", f"{position_pct:.1f}%")
                    st.caption("계좌 대비 적정 비중")

            st.divider()

            # ── RR 목표가 테이블 ──────────────────────
            st.write("### 🎯 Risk/Reward 목표가")
            rr_col1, rr_col2, rr_col3 = st.columns(3)

            with rr_col1:
                st.info(
                    f"**1:1 RR (보수적 목표)**\n\n"
                    f"목표가: **${target_1r:.2f}** (+{gain_1r_pct:.1f}%)\n\n"
                    f"예상 수익: **+${shares * stop_distance:,.0f}**\n\n"
                    f"Pre-market 갭업 초기 50% 청산 권장"
                )

            with rr_col2:
                st.success(
                    f"**1:2 RR (기본 목표)**\n\n"
                    f"목표가: **${target_2r:.2f}** (+{gain_2r_pct:.1f}%)\n\n"
                    f"예상 수익: **+${shares * stop_distance * 2:,.0f}**\n\n"
                    f"Overnight Gap Play 메인 타겟"
                )

            with rr_col3:
                st.warning(
                    f"**1:3 RR (공격적 목표)**\n\n"
                    f"목표가: **${target_3r:.2f}** (+{gain_3r_pct:.1f}%)\n\n"
                    f"예상 수익: **+${shares * stop_distance * 3:,.0f}**\n\n"
                    f"강한 촉매 + SI 20%+ 종목만 기대"
                )

            st.divider()

            # ── 실전 트레이드 플랜 요약 ───────────────
            st.write("### 📋 실전 트레이드 플랜 요약")
            st.markdown(f"""
| 항목 | 수치 |
|------|------|
| 📌 **진입가 (After-market 기준)** | ${current_price:.2f} |
| 🔴 **손절가** | ${stop_price:.2f} (현재가 대비 -{(stop_distance/current_price*100):.1f}%) |
| 🎯 **1차 목표 (1:2 RR)** | ${target_2r:.2f} (+{gain_2r_pct:.1f}%) |
| 🎯 **2차 목표 (1:3 RR)** | ${target_3r:.2f} (+{gain_3r_pct:.1f}%) |
| 📦 **매수 수량** | {shares:,} 주 |
| 💼 **포지션 금액** | ${position_value:,.0f} (계좌 {position_pct:.1f}%) |
| 🛡️ **최대 손실** | -${risk_dollar:,.0f} (계좌 -{risk_pct:.1f}%) |
| ⏰ **청산 시점** | 다음날 Pre-market 갭업 시 1차 청산 |
            """)

            st.warning(
                "⚠️ **Overnight 리스크 주의사항**\n\n"
                "① After-hours 유동성 낮음 → 지정가 주문 필수 (시장가 금지)\n"
                "② Pre-market에서 Offering 공시 발생 시 → 즉시 전량 손절\n"
                "③ 갭다운 오픈 시 손절가 기다리지 말고 즉시 청산\n"
                "④ 수익 중에도 VWAP 이탈 시 잔여 물량 정리"
            )

        else:
            if risk_ticker:
                st.warning("⚠️ 현재가 또는 ATR 데이터를 불러오지 못했습니다. 개별 분석 탭을 먼저 실행하거나 잠시 후 재시도하세요.")

    else:
        st.info("티커를 입력하거나, **[🔍 개별 종목 분석]** 탭에서 분석 후 이 탭으로 이동하면 자동 입력됩니다.")
        st.markdown("""
        **ATR 손절 계산 원리:**
        - ATR14 = 최근 14거래일 평균 실제 변동폭
        - 손절가 = 진입가 - (ATR × 배수)
        - 매수 수량 = (계좌 × 리스크%) ÷ 손절폭
        - 이 공식은 시장 노이즈를 고려한 과학적 손절 기준입니다.
        """)
