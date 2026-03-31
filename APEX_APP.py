import streamlit as st
import yfinance as yf
import pandas as pd

# 앱 기본 설정
st.set_page_config(page_title="APEX 스캐너 v8.3", layout="wide")

st.title("🚀 APEX v8.3 프리마켓 폭등 전략 센터")

# 사이드바 입력창
st.sidebar.markdown("### 🕹️ 분석실")
ticker_input = st.sidebar.text_input("분석할 티커 입력", "PLAY").upper()

if ticker_input:
    st.markdown(f"## 🔍 {ticker_input} 정밀 팩트체크 리포트")
    try:
        # 야후 파이낸스 데이터 불러오기
        ticker = yf.Ticker(ticker_input)
        info = ticker.info

        # 1. 기본 데이터 추출
        current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
        if current_price == 0:
            hist_1d = ticker.history(period="1d")
            if not hist_1d.empty:
                current_price = hist_1d['Close'].iloc[-1]

        volume = info.get('regularMarketVolume', 0)
        avg_volume_10d = info.get('averageVolume10days', 1)
        rvol = volume / avg_volume_10d if avg_volume_10d > 0 else 0

        float_shares = info.get('floatShares', 0)
        float_m = float_shares / 1000000 if float_shares else 0

        short_percent = info.get('shortPercentOfFloat', 0)
        si_percent = short_percent * 100 if short_percent else 0

        # 2. 기술적 지표 계산 (SMA200, VWAP)
        hist_1y = ticker.history(period="1y")
        sma200 = hist_1y['Close'].rolling(window=200).mean().iloc[-1] if len(hist_1y) >= 200 else None

        hist_today = ticker.history(period="1d", interval="1m")
        if not hist_today.empty:
            hist_today['Typical_Price'] = (hist_today['High'] + hist_today['Low'] + hist_today['Close']) / 3
            vwap_series = (hist_today['Typical_Price'] * hist_today['Volume']).cumsum() / hist_today['Volume'].cumsum()
            current_vwap = vwap_series.iloc[-1]
        else:
            current_vwap = None

        # 3. 화면 출력 1: 필수 3요소
        col1, col2, col3 = st.columns(3)
        with col1:
            st.metric("📊 상대 거래량 (RVOL)", f"{rvol:.2f}x")
            st.caption("[의미] 평소보다 돈이 얼마나 들어왔나?")
            if rvol >= 2.0: st.success("✅ 베스트: 수급 폭발 중!")
            elif rvol >= 1.5: st.warning("⚠️ 주의: 수급이 붙기 시작함.")
            else: st.info("⭕ 보통: 세력 개입 증거 부족.")

        with col2:
            st.metric("🎈 유동주식수 (Float)", f"{float_m:.1f}M")
            st.caption("[의미] 몸무게가 가벼운가?")
            if 0 < float_m <= 20: st.success("✅ 합격: 폭등하기 아주 가벼움!")
            elif float_m > 20: st.error("❌ 무거움: 폭등시키기엔 너무 무거움.")
            else: st.info("데이터 없음")

        with col3:
            st.metric("🧨 공매도 잔고 (SI%)", f"{si_percent:.1f}%")
            st.caption("[의미] 숏 스퀴즈(폭발) 연료가 충분한가?")
            if si_percent >= 15: st.success("✅ 폭등 신호: 숏 스퀴즈 탄약 완비!")
            else: st.info("⭕ 낮음: 폭발적인 반등 확률 낮음.")

        # 4. 화면 출력 2: 기술적 안전장치
        st.markdown("### 🛡️ 기술적 안전장치 (클로드 제안)")
        t_col1, t_col2 = st.columns(2)
        with t_col1:
            if sma200:
                if current_price > sma200: st.success(f"✅ SMA200 돌파 (현재가 {current_price:.2f} > SMA {sma200:.2f})\n\n[의미] 장기 매물대 없음!")
                else: st.error(f"❌ SMA200 하회 (현재가 {current_price:.2f} < SMA {sma200:.2f})\n\n[의미] 머리 위 매물 많음.")
            else: st.warning("⚠️ SMA200 계산 불가")

        with t_col2:
            if current_vwap:
                if current_price > current_vwap: st.success(f"✅ VWAP 지지 (현재가 {current_price:.2f} > VWAP {current_vwap:.2f})\n\n[의미] 세력 평단 위!")
                else: st.error(f"❌ VWAP 이탈 (현재가 {current_price:.2f} < VWAP {current_vwap:.2f})\n\n[의미] 세력 이탈 중!")
            else: st.warning("⚠️ VWAP 데이터 불가")

        st.markdown("---")

        # 5. 기존 필살기 단계들 (뉴스, 다크풀, 그록 검증)
        row1_col1, row1_col2 = st.columns(2)
        with row1_col1:
            st.markdown("### 📂 1단계: 뉴스 & 공시 (재료 체크)")
            st.info("💡 체크: 뉴스 제목에 'Offering', 'S-3', 'F-3' 단어가 보이면 무조건 패스하세요!")
            st.markdown(f"- [야후 뉴스 바로가기](https://finance.yahoo.com/quote/{ticker_input}/news)")
            st.markdown(f"- [8-K 공시 확인](https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker_input}&action=getcompany)")

        with row1_col2:
            st.markdown("### 📊 2단계: 세력 수급 (다크풀 체크)")
            st.info("💡 체크: 아래 링크 클릭 후 **Dark Pool %**가 50% 이상인지 확인하세요.")
            st.markdown(f"👉 [{ticker_input} 실시간 다크풀 확인](https://stocksera.pythonanywhere.com/ticker/short_volume/?quote={ticker_input})")

        st.markdown("### 📉 3단계: 기술적 위치")
        st.markdown(f"👉 [Finviz에서 {ticker_input} 차트 정밀 확인](https://finviz.com/quote.ashx?t={ticker_input})")

        st.markdown("---")
        st.markdown("### 💡 APEX v8.3 실전 필살기 가이드 (찰스님 전용)")
        g_col1, g_col2, g_col3 = st.columns(3)
        g_col1.help("Float 10M~20M: 몸무게가 가벼워야 적은 돈으로도 150% 수직 상승 가능")
        g_col2.help("다크풀 60% 이상: 세력이 뒤에서 물량을 꽉 쥐고 있다는 증거")
        g_col3.help("SI% 15% 이상: 주가 오를 때 공매도 세력의 손절 매수가 폭등 부채질")

        st.markdown("---")
        st.markdown("### 🎯 5단계: Grok에게 최종 검증 시키기")
        grok_prompt = f"너는 프리마켓 폭등 추적 AI APEX v8.3이다. 대상 티커: {ticker_input}. 이 종목의 8-K 공시와 X(트위터) 반응을 뒤져서 내일 아침 +50% 폭등 가능성을 100점 만점으로 점수 매겨줘. 특히 오늘 밤이나 내일 새벽에 터질 Catalyst가 있는지 팩트체크해."
        st.code(grok_prompt, language="text")
        st.caption("위 박스의 내용을 복사해서 Grok에게 붙여넣으세요!")

    except Exception as e:
        st.error(f"데이터 로딩 중 오류 발생: {e}")
