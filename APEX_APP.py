import streamlit as st
import yfinance as yf
import pandas as pd

# 1. 앱 기본 설정
st.set_page_config(page_title="APEX 스캐너 v8.5", layout="wide")

st.title("🚀 APEX v8.5 프리마켓 폭등 전략 센터")

# 2. 데이터 가져오기 함수 (안전 모드)
def get_safe_data(symbol):
    ticker = yf.Ticker(symbol)
    try:
        # 에러 방지를 위해 info 데이터만 따로 추출
        info = ticker.info
        if not info: info = {}
    except:
        info = {}
    return ticker, info

# 사이드바 입력창
st.sidebar.markdown("### 🕹️ 분석실")
ticker_input = st.sidebar.text_input("분석할 티커 입력", "NVDA").strip().upper()

if ticker_input:
    st.markdown(f"## 🔍 {ticker_input} 정밀 팩트체크 리포트")
    
    with st.spinner('데이터를 가져오는 중입니다...'):
        ticker, info = get_safe_data(ticker_input)

        # 데이터가 아예 없는 경우 (서버 차단 등)
        if not info and ticker_input != "":
            st.error("⚠️ 야후 서버에서 접속을 제한했습니다. 3~5분 뒤에 다시 시도하거나 다른 티커를 입력해 보세요.")
        else:
            try:
                # 3. 데이터 추출
                current_price = info.get('currentPrice', info.get('regularMarketPrice', 0))
                if current_price == 0:
                    hist_1d = ticker.history(period="1d")
                    current_price = hist_1d['Close'].iloc[-1] if not hist_1d.empty else 0

                volume = info.get('regularMarketVolume', 0)
                avg_volume_10d = info.get('averageVolume10days', 1)
                rvol = volume / avg_volume_10d if avg_volume_10d > 0 else 0

                float_shares = info.get('floatShares', 0)
                float_m = float_shares / 1000000 if float_shares else 0

                short_percent = info.get('shortPercentOfFloat', 0)
                si_percent = short_percent * 100 if short_percent else 0

                # 4. 기술적 지표 (SMA200, VWAP)
                hist_1y = ticker.history(period="1y")
                sma200 = hist_1y['Close'].rolling(window=200).mean().iloc[-1] if len(hist_1y) >= 200 else None

                hist_today = ticker.history(period="1d", interval="1m")
                if not hist_today.empty:
                    hist_today['Typical_Price'] = (hist_today['High'] + hist_today['Low'] + hist_today['Close']) / 3
                    vwap_series = (hist_today['Typical_Price'] * hist_today['Volume']).cumsum() / hist_today['Volume'].cumsum()
                    current_vwap = vwap_series.iloc[-1]
                else:
                    current_vwap = None

                # 5. 화면 출력 (필수 3요소)
                col1, col2, col3 = st.columns(3)
                with col1:
                    st.metric("📊 상대 거래량 (RVOL)", f"{rvol:.2f}x")
                    if rvol >= 2.0: st.success("✅ 베스트: 수급 폭발!")
                    else: st.info("⭕ 수급 관찰")

                with col2:
                    st.metric("🎈 유동주식수 (Float)", f"{float_m:.1f}M")
                    if 0 < float_m <= 20: st.success("✅ 합격: 가벼움!")
                    else: st.error("❌ 무거움: 주의")

                with col3:
                    st.metric("🧨 공매도 잔고 (SI%)", f"{si_percent:.1f}%")
                    if si_percent >= 15: st.success("✅ 신호: 숏 스퀴즈 가능!")
                    else: st.info("⭕ 낮음: 반등 확률 낮음")

                st.markdown("---")
                
                # 6. 기술적 안전장치
                st.markdown("### 🛡️ 기술적 안전장치")
                t_col1, t_col2 = st.columns(2)
                with t_col1:
                    if sma200:
                        if current_price > sma200: st.success(f"✅ SMA200 위 ({current_price:.2f} > {sma200:.2f})")
                        else: st.error(f"❌ SMA200 아래 ({current_price:.2f} < {sma200:.2f})")
                    else: st.warning("⚠️ SMA200 계산 불가")
                with t_col2:
                    if current_vwap:
                        if current_price > current_vwap: st.success(f"✅ VWAP 지지 ({current_price:.2f} > {current_vwap:.2f})")
                        else: st.error(f"❌ VWAP 이탈 ({current_price:.2f} < {current_vwap:.2f})")
                    else: st.warning("⚠️ VWAP 데이터 없음")

                st.markdown("---")

                # 7. 외부 링크 (다크풀 주소 수정 완료)
                row1_col1, row1_col2 = st.columns(2)
                with row1_col1:
                    st.markdown("### 📂 1단계: 뉴스 & 공시")
                    st.markdown(f"- [야후 뉴스](https://finance.yahoo.com/quote/{ticker_input}/news)")
                    st.markdown(f"- [SEC 8-K 공시](https://www.sec.gov/cgi-bin/browse-edgar?CIK={ticker_input}&action=getcompany)")
                with row1_col2:
                    st.markdown("### 📊 2단계: 다크풀")
                    st.markdown(f"👉 [{ticker_input} 다크풀 확인](https://stocksera.pythonanywhere.com/ticker/short_volume/{ticker_input}/)")

                st.markdown("---")
                st.markdown("### 🎯 5단계: Grok에게 최종 검증 시키기")
                grok_prompt = f"너는 폭등 추적 AI APEX v8.5이다. 티커: {ticker_input}. 분석해줘."
                st.code(grok_prompt, language="text")

            except Exception as e:
                st.warning("일부 데이터를 가져오지 못했습니다. (서버 응답 지연)")
