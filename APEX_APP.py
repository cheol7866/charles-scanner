import streamlit as st
import yfinance as yf
import pandas as pd

# 1. 화면 설정
st.set_page_config(page_title="APEX v8.2 전략 가이드 대시보드", layout="wide")

st.title("🚀 APEX v8.2 프리마켓 폭등 전략 센터")
st.sidebar.header("🕹️ 분석실")
ticker = st.sidebar.text_input("분석할 티커 입력", value="").upper()

if ticker:
    st.subheader(f"🔍 {ticker} 정밀 팩트체크 리포트")
    
    try:
        stock = yf.Ticker(ticker)
        info = stock.info
        
        # 2. 상단 3대 핵심 지표 (수치 + 가이드)
        col1, col2, col3 = st.columns(3)
        
        with col1:
            avg_vol = info.get('averageVolume10days', 1)
            curr_vol = info.get('regularMarketVolume', 0)
            rvol = curr_vol / avg_vol if avg_vol > 0 else 0
            st.metric("📊 상대 거래량 (RVOL)", f"{rvol:.2f}x")
            st.caption("**[의미]** 평소보다 돈이 얼마나 들어왔나?")
            if rvol > 2.0: 
                st.success("✅ **폭등 신호:** 세력이 종가 매집 중!")
            elif rvol > 1.5:
                st.warning("⚠️ **주의:** 수급이 붙기 시작함.")
            else:
                st.info("⚪ **보통:** 세력 개입 증거 부족.")

        with col2:
            float_shares = info.get('floatShares', 0)
            st.metric("🎈 유동주식수 (Float)", f"{float_shares/1e6:.1f}M")
            st.caption("**[의미]** 몸무게가 가벼운가? (주식 수)")
            if float_shares < 20e6:
                st.success("✅ **폭등 신호:** 가벼워서 150% 튈 수 있음!")
            elif float_shares < 50e6:
                st.info("⚪ **보통:** 적절한 중소형주 체급.")
            else:
                st.error("❌ **무거움:** 폭등시키기엔 너무 무거움.")

        with col3:
            si_ratio = info.get('shortPercentOfFloat', 0) * 100
            st.metric("🧨 공매도 잔고 (SI%)", f"{si_ratio:.1f}%")
            st.caption("**[의미]** 숏 스퀴즈(폭발) 연료가 충분한가?")
            if si_ratio > 15:
                st.success("✅ **폭등 신호:** 숏 스퀴즈 탄약 완비!")
            elif si_ratio > 10:
                st.warning("⚠️ **주의:** 공매도가 쌓여 있음.")
            else:
                st.info("⚪ **낮음:** 폭발적인 반등 확률 낮음.")

        st.divider()

        # 3. 하단 정밀 체크리스트
        c1, c2 = st.columns(2)
        
        with c1:
            st.write("### 📂 1단계: 뉴스 & 공시 (재료 체크)")
            st.info("💡 **체크:** 뉴스 제목에 **'Offering', 'S-3', 'F-3'** 단어가 보이면 무조건 패스하세요!")
            news_list = stock.news
            if news_list:
                for item in news_list[:5]:
                    title = item.get('title', '제목 없음')
                    link = item.get('link', '#')
                    st.write(f"- [{title}]({link})")
            else:
                st.write("최근 뉴스가 없습니다.")

        with c2:
            st.write("### 📊 2단계: 세력 수급 (다크풀 체크)")
            st.info("💡 **체크:** 아래 링크 클릭 후 **'Dark Pool %'**가 **50% 이상**인지 확인하세요.")
            st.markdown(f"**[👉 {ticker} 실시간 다크풀 데이터 확인하기](https://chartexchange.com/symbol/nasdaq-{ticker}/stats/)**")
            
            st.write("")
            st.write("### 📈 3단계: 기술적 위치")
            st.markdown(f"**[👉 Finviz에서 {ticker} 차트/지표 정밀 확인](https://finviz.com/quote.ashx?t={ticker})**")

        # 4. 찰스님 전용 전략 요약 (Summary)
        st.divider()
        st.subheader("💡 APEX v8.2 실전 필살기 가이드 (찰스님 전용)")
        
        col_sum1, col_sum2, col_sum3 = st.columns(3)
        
        with col_sum1:
            st.info("🎯 **폭등 후보 체급**\n\n**Float 10M ~ 20M**\n\n몸무게가 가벼워야 적은 돈으로도 150% 수직 상승이 가능합니다.")
            
        with col_sum2:
            st.error("🤫 **세력 매집 증거**\n\n**다크풀 60% 이상**\n\n세력이 뒤에서 물량을 꽉 쥐고 '품귀 현상'을 세팅 완료했다는 증거입니다.")
            
        with col_sum3:
            st.success("🧨 **폭발 가속도**\n\n**SI% 15% 이상**\n\n주가가 오를 때 공매도 세력이 '손절 매수'를 하며 폭등을 더 부채질합니다.")

        st.warning("⚠️ **최종 판단:** 위 3가지가 모두 일치하고, 오늘 밤 '호재 뉴스'가 있다면 승부수를 던질 타이밍입니다! `[추론]`")

        st.divider()

        # 5. Grok 자동 조립 프롬프트
        st.write("### 🤖 5단계: Grok에게 최종 검증 시키기")
        grok_prompt = f"""너는 프리마켓 폭등 추적 AI APEX v8.2이다. 대상 티커: {ticker}. 이 종목의 8-K 공시와 X(트위터) 반응을 뒤져서 내일 아침 +50% 폭등 가능성을 100점 만점으로 점수 매겨줘. 특히 오늘 밤이나 내일 새벽에 터질 호재가 있는지 집중 분석해."""
        st.code(grok_prompt, language="text")

    except Exception as e:
        st.error(f"데이터를 가져오는 중 오류가 발생했습니다: {e}")

else:
    st.info("왼쪽 사이드바에 티커를 입력하면 팩트체크 가이드가 나타납니다.")
