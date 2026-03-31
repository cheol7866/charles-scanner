import streamlit as st
import yfinance as yf
import pandas as pd

# ──────────────────────────────────────────────
# 1. 화면 설정
# ──────────────────────────────────────────────
st.set_page_config(page_title="APEX v8.2 전략 가이드 대시보드", layout="wide")

st.title("🚀 APEX v8.2 프리마켓 폭등 전략 센터")
st.sidebar.header("🕹️ 분석실")
ticker = st.sidebar.text_input("분석할 티커 입력", value="").upper()

if ticker:
    st.subheader(f"🔍 {ticker} 정밀 팩트체크 리포트")

    try:
        stock  = yf.Ticker(ticker)
        info   = stock.info

        # ── 데이터 사전 수집 ──────────────────────────────
        # 현재가 (regularMarketPrice → currentPrice 순으로 fallback)
        current_price = info.get("regularMarketPrice") or info.get("currentPrice")

        # SMA200 계산: 최소 200 거래일 필요 → 300일치 요청
        hist_daily   = stock.history(period="300d", interval="1d")
        sma200       = None
        if len(hist_daily) >= 200:
            sma200 = float(hist_daily["Close"].rolling(200).mean().iloc[-1])

        # VWAP 계산: 당일 1분봉 기준
        hist_intraday = stock.history(period="1d", interval="1m")
        vwap          = None
        if not hist_intraday.empty and hist_intraday["Volume"].sum() > 0:
            typical_price = (
                hist_intraday["High"] +
                hist_intraday["Low"]  +
                hist_intraday["Close"]
            ) / 3
            vwap = float(
                (typical_price * hist_intraday["Volume"]).cumsum().iloc[-1]
                / hist_intraday["Volume"].cumsum().iloc[-1]
            )

        # ──────────────────────────────────────────────────
        # 2. 상단 3대 핵심 지표
        # ──────────────────────────────────────────────────
        col1, col2, col3 = st.columns(3)

        # ① RVOL
        with col1:
            avg_vol  = info.get("averageVolume10days") or info.get("averageVolume") or 1
            curr_vol = info.get("regularMarketVolume", 0) or 0
            rvol     = curr_vol / avg_vol if avg_vol > 0 else 0

            st.metric("📊 상대 거래량 (RVOL)", f"{rvol:.2f}x")
            st.caption("**[의미]** 평소보다 돈이 얼마나 들어왔나?")
            if rvol > 2.0:
                st.success("✅ **폭등 신호:** 세력이 종가 매집 중!")
            elif rvol > 1.5:
                st.warning("⚠️ **주의:** 수급이 붙기 시작함.")
            else:
                st.info("⚪ **보통:** 세력 개입 증거 부족.")

        # ② Float
        with col2:
            float_shares = info.get("floatShares") or 0

            st.metric("🎈 유동주식수 (Float)",
                      f"{float_shares / 1e6:.1f}M" if float_shares else "N/A")
            st.caption("**[의미]** 몸무게가 가벼운가? (주식 수)")
            if float_shares and float_shares < 20e6:
                st.success("✅ **폭등 신호:** 가벼워서 150% 튈 수 있음!")
            elif float_shares and float_shares < 50e6:
                st.info("⚪ **보통:** 적절한 중소형주 체급.")
            elif float_shares:
                st.error("❌ **무거움:** 폭등시키기엔 너무 무거움.")
            else:
                st.info("⚪ Float 데이터 없음.")

        # ③ Short Interest
        with col3:
            # yfinance는 소수(0.15 = 15%)로 반환 → *100 필요
            # 간혹 이미 퍼센트로 오는 엣지 케이스 방어
            si_raw   = info.get("shortPercentOfFloat") or 0
            si_ratio = si_raw * 100 if si_raw < 1 else si_raw

            st.metric("🧨 공매도 잔고 (SI%)", f"{si_ratio:.1f}%")
            st.caption("**[의미]** 숏 스퀴즈(폭발) 연료가 충분한가?")
            if si_ratio > 15:
                st.success("✅ **폭등 신호:** 숏 스퀴즈 탄약 완비!")
            elif si_ratio > 10:
                st.warning("⚠️ **주의:** 공매도가 쌓여 있음.")
            else:
                st.info("⚪ **낮음:** 폭발적인 반등 확률 낮음.")

        st.divider()

        # ──────────────────────────────────────────────────
        # 3. [NEW] SMA200 / VWAP 기준선 섹션
        # ──────────────────────────────────────────────────
        st.subheader("📐 기술적 핵심 기준선 (APEX 필수 조건)")
        col4, col5 = st.columns(2)

        # ④ SMA 200
        with col4:
            st.write("### 🦴 SMA 200 (200일 이동평균선)")
            st.caption(
                "**[의미]** 주가의 뼈대. 현재가 > SMA200 이어야 "
                "악성 매물대를 피해 150% 폭등이 가능합니다."
            )
            if sma200 is not None and current_price:
                gap_pct = ((current_price - sma200) / sma200) * 100
                st.metric(
                    label   = "SMA 200",
                    value   = f"${sma200:.2f}",
                    delta   = f"현재가 ${current_price:.2f} ({gap_pct:+.1f}%)"
                )
                if current_price > sma200:
                    st.success(
                        f"🟢 **초록불 — 폭등 가능 구간**\n\n"
                        f"현재가 **${current_price:.2f}** > SMA200 **${sma200:.2f}**\n\n"
                        f"상승 궤도 유지 중. 매물대 위에 있어 진입 고려 가능."
                    )
                else:
                    st.error(
                        f"🔴 **빨간불 — 진입 금지 구간**\n\n"
                        f"현재가 **${current_price:.2f}** < SMA200 **${sma200:.2f}**\n\n"
                        f"악성 매물대 아래. 아무리 뉴스가 좋아도 세력 없이 150% 불가."
                    )
            elif sma200 is None:
                st.warning("⚠️ 데이터 부족 — 상장 200일 미만 종목이거나 데이터 오류.")
            else:
                st.warning("⚠️ 현재가 데이터 없음.")

        # ⑤ VWAP
        with col5:
            st.write("### 🎯 VWAP (거래량 가중 평균가)")
            st.caption(
                "**[의미]** 데이트레이더·세력의 당일 평균 단가. "
                "현재가 > VWAP = 세력 수익권 → 홀딩. "
                "VWAP 이탈 = 세력 털기 신호 → 즉시 손절."
            )
            if vwap is not None and current_price:
                gap_pct = ((current_price - vwap) / vwap) * 100
                st.metric(
                    label = "당일 VWAP",
                    value = f"${vwap:.2f}",
                    delta = f"현재가 ${current_price:.2f} ({gap_pct:+.1f}%)"
                )
                if current_price > vwap:
                    st.success(
                        f"🟢 **초록불 — 세력 수익권**\n\n"
                        f"현재가 **${current_price:.2f}** > VWAP **${vwap:.2f}**\n\n"
                        f"세력이 아직 홀딩 중. 추가 상승 여력 있음."
                    )
                else:
                    st.error(
                        f"🔴 **빨간불 — 세력 이탈 주의**\n\n"
                        f"현재가 **${current_price:.2f}** < VWAP **${vwap:.2f}**\n\n"
                        f"세력이 물량 털고 나갈 수 있는 구간. 진입/보유 재고."
                    )
            else:
                st.warning(
                    "⚠️ VWAP 산출 불가 — 장 마감 후이거나 거래량 데이터 없음.\n\n"
                    "장 중(프리마켓 포함)에 다시 확인하세요."
                )

        st.divider()

        # ──────────────────────────────────────────────────
        # 4. 뉴스 & 외부 링크
        # ──────────────────────────────────────────────────
        c1, c2 = st.columns(2)

        with c1:
            st.write("### 📂 1단계: 뉴스 & 공시 (재료 체크)")
            st.info(
                "💡 **체크:** 뉴스 제목에 **'Offering', 'S-3', 'F-3', 'Dilut'** "
                "단어가 보이면 무조건 패스하세요!"
            )
            DANGER_KEYWORDS = ["offering", "s-3", "f-3", "dilut", "warrant"]
            try:
                news_list = stock.news or []
                if news_list:
                    for item in news_list[:5]:
                        # yfinance 신버전: content 중첩 dict 방어
                        content = item.get("content", {})
                        if isinstance(content, dict):
                            title = content.get("title", "제목 없음")
                            link  = (content.get("canonicalUrl") or {}).get("url", "#")
                        else:
                            title = item.get("title", "제목 없음")
                            link  = item.get("link", "#")

                        is_danger = any(kw in title.lower() for kw in DANGER_KEYWORDS)
                        if is_danger:
                            st.error(f"🚨 위험 키워드 감지 — [{title}]({link})")
                        else:
                            st.write(f"- [{title}]({link})")
                else:
                    st.write("최근 뉴스가 없습니다.")
            except Exception:
                st.write("뉴스 데이터를 불러올 수 없습니다.")

        with c2:
            st.write("### 📊 2단계: 세력 수급 (다크풀 체크)")
            st.info(
                "💡 **체크:** 아래 링크 클릭 후 **'Dark Pool %'**가 "
                "**50% 이상**인지 확인하세요."
            )
            st.markdown(
                f"**[👉 {ticker} 실시간 다크풀 데이터 확인]"
                f"(https://chartexchange.com/symbol/nasdaq-{ticker}/stats/)**"
            )
            st.write("")
            st.write("### 📈 3단계: 기술적 위치")
            st.markdown(
                f"**[👉 Finviz에서 {ticker} 차트/지표 정밀 확인]"
                f"(https://finviz.com/quote.ashx?t={ticker})**"
            )

        # ──────────────────────────────────────────────────
        # 5. 찰스님 전용 전략 요약
        # ──────────────────────────────────────────────────
        st.divider()
        st.subheader("💡 APEX v8.2 실전 필살기 가이드 (찰스님 전용)")

        col_s1, col_s2, col_s3, col_s4, col_s5 = st.columns(5)

        with col_s1:
            st.info(
                "🎯 **폭등 체급**\n\n"
                "Float **10M~20M**\n\n"
                "가벼워야 적은 돈으로도 150% 수직 상승."
            )
        with col_s2:
            st.error(
                "🤫 **세력 매집 증거**\n\n"
                "Dark Pool **60%+**\n\n"
                "세력이 물량을 꽉 쥐고 품귀 세팅 완료."
            )
        with col_s3:
            st.success(
                "🧨 **폭발 가속도**\n\n"
                "SI% **15%+**\n\n"
                "숏이 손절 매수하며 폭등을 부채질."
            )
        with col_s4:
            st.success(
                "🦴 **뼈대 확인**\n\n"
                "현재가 > **SMA200**\n\n"
                "악성 매물대 위에 있어야 폭등 가능."
            )
        with col_s5:
            st.success(
                "🎯 **세력 수익권**\n\n"
                "현재가 > **VWAP**\n\n"
                "세력이 홀딩 중이어야 추가 상승 기대."
            )

        st.warning(
            "⚠️ **최종 승부 조건 (5개 모두 충족 시):** "
            "Float 소형 ✅ + Dark Pool 60%+ ✅ + SI 15%+ ✅ + "
            "현재가 > SMA200 ✅ + 현재가 > VWAP ✅ + 오늘 밤 호재 뉴스 ✅ "
            "→ 전부 일치 시 승부수 타이밍! `[추론]`"
        )

        st.divider()

        # ──────────────────────────────────────────────────
        # 6. Grok 자동 조립 프롬프트 (SMA200 / VWAP 포함)
        # ──────────────────────────────────────────────────
        st.write("### 🤖 5단계: Grok에게 최종 검증 시키기")

        price_str = f"${current_price:.2f}" if current_price else "N/A"
        sma200_str = f"${sma200:.2f}" if sma200 else "N/A"
        vwap_str   = f"${vwap:.2f}"   if vwap   else "N/A"

        grok_prompt = (
            f"너는 프리마켓 폭등 추적 AI APEX v8.2이다. 대상 티커: {ticker}.\n"
            f"현재가: {price_str} | SMA200: {sma200_str} | VWAP: {vwap_str}\n\n"
            f"이 종목의 8-K 공시와 X(트위터) 반응을 분석해서 "
            f"내일 아침 +50% 폭등 가능성을 100점 만점으로 점수 매겨줘.\n"
            f"특히 오늘 밤/새벽에 터질 호재가 있는지, "
            f"현재가가 SMA200 및 VWAP 대비 어느 위치인지 집중 분석해."
        )
        st.code(grok_prompt, language="text")

    except Exception as e:
        st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")
        st.info("티커가 올바른지 확인하거나, 잠시 후 다시 시도해주세요.")

else:
    st.info("왼쪽 사이드바에 티커를 입력하면 팩트체크 가이드가 나타납니다.")
