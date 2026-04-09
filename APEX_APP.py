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
        color: #FFFFFF;
    }
    [data-testid="stMetric"] label,
    [data-testid="stMetric"] [data-testid="stMetricValue"],
    [data-testid="stMetric"] [data-testid="stMetricDelta"] {
        color: #FFFFFF !important;
    }
    .signal-box {
        border-radius: 16px;
        padding: 16px;
        margin: 8px 0;
        font-size: 1.1rem;
    }
    .block-container { padding-top: 1rem; }
    .stSelectbox > div > div { font-size: 1rem; }
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

@st.cache_data(ttl=3600, show_spinner=False)
def get_earnings_info(ticker: str):
    """
    어닝 날짜 조회 및 3일 이내 여부 판정.
    반환: {
        "date"      : datetime.date | None,  # 다음 어닝 날짜
        "days_away" : int | None,            # 오늘 기준 남은 일수 (음수=이미 지남)
        "within_3d" : bool,                  # 3일 이내 True → 진입 금지
        "label"     : str,                   # UI 표시용 문자열
        "source"    : str                    # 데이터 출처 ("calendar"|"fast_info"|"none")
    }
    """
    today = datetime.date.today()
    result = {
        "date": None, "days_away": None,
        "within_3d": False, "label": "어닝 정보 없음", "source": "none"
    }
    try:
        tk = yf.Ticker(ticker)

        # 방법 1: .calendar (dict 또는 DataFrame)
        cal = tk.calendar
        earn_date = None

        if isinstance(cal, dict):
            # yfinance ≥ 0.2.x: dict 형태
            raw = cal.get("Earnings Date")
            if raw:
                if isinstance(raw, (list, tuple)) and len(raw) > 0:
                    earn_date = pd.Timestamp(raw[0]).date()
                elif hasattr(raw, "date"):
                    earn_date = raw.date()

        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            # 구버전: DataFrame 형태 — "Earnings Date" 행
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
                earn_date = pd.Timestamp(val).date()

        if earn_date:
            days_away = (earn_date - today).days
            result.update({
                "date": earn_date,
                "days_away": days_away,
                "within_3d": -1 <= days_away <= 3,
                "label": f"{earn_date.strftime('%Y-%m-%d')} (D{days_away:+d})",
                "source": "calendar"
            })
            return result

        # 방법 2: fast_info 폴백
        fi = tk.fast_info
        if hasattr(fi, "next_earnings_date") and fi.next_earnings_date:
            earn_date = pd.Timestamp(fi.next_earnings_date).date()
            days_away = (earn_date - today).days
            result.update({
                "date": earn_date,
                "days_away": days_away,
                "within_3d": -1 <= days_away <= 3,
                "label": f"{earn_date.strftime('%Y-%m-%d')} (D{days_away:+d})",
                "source": "fast_info"
            })
            return result

    except Exception:
        pass

    return result  # 조회 실패 시 기본값 반환


@st.cache_data(ttl=600, show_spinner=False)
def run_screener(sector: str, mode: str = "MOM"):
    try:
        from finvizfinance.screener.overview import Overview
        if mode == "MOM":
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "50-Day Simple Moving Average":  "Price above SMA50",
                "RSI (14)":                      "Not Overbought (<60)",
                "Performance":                   "Quarter +10%",
                "Average Volume":                "Over 500K",
                "Industry":                      "Stocks only (ex-Funds)",
                "Price":                         "Over $10",
            }
        else:
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "RSI (14)":          "Oversold (40)",
                "Average Volume":    "Over 500K",
                "Market Cap":        "Mid ($2bln to $10bln) to Large (over $10bln)",  # 소형·부실주 배제
                "EPS growthqtr over qtr": "Positive (>0%)",                           # 적자 기업 배제
                "Industry":          "Stocks only (ex-Funds)",
                "Price":             "Over $10",
            }
        if sector != "전체":
            filters["Sector"] = sector
        fov = Overview()
        fov.set_filter(filters_dict=filters)
        return fov.screener_view()
    except Exception as e:
        return str(e)



# ══════════════════════════════════════════════════════════════
# Daily Report 전용 함수
# ══════════════════════════════════════════════════════════════

def _calc_rsi(series, period):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def _calc_sma(series, period):
    return series.rolling(window=period).mean()

def _calc_bollinger(series, period=20, std_mult=2):
    sma = _calc_sma(series, period)
    std = series.rolling(window=period).std()
    return sma, sma + std_mult * std, sma - std_mult * std

def _calc_atr(high, low, close, period=14):
    tr = pd.concat([high - low, (high - close.shift(1)).abs(), (low - close.shift(1)).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()

def _calc_rvol(volume, period=20):
    avg = volume.rolling(window=period).mean()
    return float(volume.iloc[-1] / avg.iloc[-1]) if avg.iloc[-1] > 0 else 0

def _consec_down(close):
    count = 0
    for i in range(len(close) - 1, 0, -1):
        if close.iloc[i] < close.iloc[i - 1]:
            count += 1
        else:
            break
    return count

def _mr_rank_score(r: dict) -> float:
    """
    MR 후보 종목 랭킹 점수 계산 — 높을수록 우선순위 높음.
    기준: RSI(2) 낮음 + BB터치 + 연속하락 + RVOL 낮음 + 등급
    """
    score = 0.0
    # RSI(2): 낮을수록 과매도 심화 → 반등 폭 클 가능성 (최대 40점)
    score += max(0, (15 - r.get("rsi2", 15)) / 15 * 40)
    # BB 하단 터치 여부 (20점)
    score += 20 if r.get("bb_touch", False) else 0
    # 연속 하락일수 (최대 20점, 5일 기준)
    score += min(r.get("consec", 0) / 5, 1.0) * 20
    # RVOL 낮을수록 조용한 눌림목 (최대 10점)
    rvol = r.get("rvol", 1.2)
    score += max(0, (1.2 - rvol) / 1.2 * 10)
    # 등급 보너스
    grade_bonus = {"A": 10, "B+": 5, "B-": 0, "FAIL": -99}
    score += grade_bonus.get(r.get("score", "FAIL"), 0)
    return score

def _mom_rank_score(r: dict) -> float:
    """
    MOM 후보 종목 랭킹 점수 계산.
    기준: 3개월 퍼포먼스 + RVOL + SEPA + 52주 위치 + 등급
    """
    score = 0.0
    # 3개월 수익률 (최대 30점)
    score += min(r.get("perf_3m", 0) / 30, 1.0) * 30
    # RVOL (최대 20점)
    score += min((r.get("rvol", 1.0) - 1.0) / 1.0, 1.0) * 20
    # SEPA 정렬 (20점)
    score += 20 if r.get("sepa", False) else 0
    # 52주 저점 대비 위치 (최대 15점)
    score += min(r.get("from_low", 0) / 100, 1.0) * 15
    # 등급 보너스
    grade_bonus = {"A": 15, "B+": 7, "B-": 0, "FAIL": -99}
    score += grade_bonus.get(r.get("score", "FAIL"), 0)
    return score

@st.cache_data(ttl=600, show_spinner=False)
def run_finviz_dr(mode, sectors_list):
    """Daily Report용 Finviz 스크리닝"""
    try:
        from finvizfinance.screener.overview import Overview
        fov = Overview()
        if mode == "MOM":
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "50-Day Simple Moving Average": "Price above SMA50",
                "RSI (14)": "Not Overbought (<60)",
                "Performance": "Quarter +10%",
                "Average Volume": "Over 500K",
                "Industry": "Stocks only (ex-Funds)",
                "Relative Volume": "Over 1.5",
                "Current Volume": "Over 500K",
                "Price": "Over $10",
            }
        else:
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "RSI (14)":          "Oversold (40)",
                "Average Volume":    "Over 500K",
                "Market Cap":        "Mid ($2bln to $10bln) to Large (over $10bln)",  # 소형·부실주 배제
                "EPS growthqtr over qtr": "Positive (>0%)",                           # 적자 기업 배제
                "Industry":          "Stocks only (ex-Funds)",
                "Price":             "Over $10",
            }
        if sectors_list and len(sectors_list) == 1 and sectors_list[0] != "전체":
            filters["Sector"] = sectors_list[0]
        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        if df is None or df.empty: return []
        if sectors_list and "전체" not in sectors_list and len(sectors_list) > 1 and "Sector" in df.columns:
            df = df[df["Sector"].isin(sectors_list)]
        return df["Ticker"].tolist()
    except Exception as e:
        return f"오류: {e}"

@st.cache_data(ttl=600, show_spinner=False)
def analyze_stock_dr(ticker, mode, spy_rsi2_val, mom_ok_val, vix_ok_val, account_sz, risk_p):
    """Daily Report용 종목 분석 + 자동 채점"""
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 200: return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close, high, lo, volume = df["Close"], df["High"], df["Low"], df["Volume"]
        price = float(close.iloc[-1])

        sma200 = _calc_sma(close, 200)
        sma150 = _calc_sma(close, 150)
        sma50 = _calc_sma(close, 50)
        sma20 = _calc_sma(close, 20)
        rsi2 = _calc_rsi(close, 2)
        rsi14 = _calc_rsi(close, 14)
        bb_mid, bb_upper, bb_lower = _calc_bollinger(close)
        tr = pd.concat([high - lo, (high - close.shift(1)).abs(), (lo - close.shift(1)).abs()], axis=1).max(axis=1)
        atr = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rvol = _calc_rvol(volume)
        consec = _consec_down(close)
        earn = get_earnings_info(ticker)

        s200 = float(sma200.iloc[-1])
        s150 = float(sma150.iloc[-1]) if not pd.isna(sma150.iloc[-1]) else None
        s50 = float(sma50.iloc[-1])
        s20 = float(sma20.iloc[-1])
        rsi2_v = float(rsi2.iloc[-1])
        rsi14_v = float(rsi14.iloc[-1])
        bb_low_v = float(bb_lower.iloc[-1])
        atr_v = float(atr.iloc[-1])

        sepa = s150 is not None and s50 > s150 > s200
        sma200_rising = len(sma200) >= 21 and float(sma200.iloc[-1]) > float(sma200.iloc[-21])

        h252 = df.tail(252)
        w52_high = float(h252["High"].max())
        w52_low = float(h252["Low"].min())
        from_high = (price - w52_high) / w52_high * 100
        from_low = (price - w52_low) / w52_low * 100
        perf_3m = ((price / float(close.iloc[-63])) - 1) * 100 if len(close) >= 63 else 0

        if mode == "MR":
            required = {
                "SMA200 위 (종목)":    price > s200,
                "RSI(2) ≤ 15":        rsi2_v <= 15,
                "어닝 3일내 없음":     not earn["within_3d"],
                "SPY RSI(2) > 10":    spy_rsi2_val > 10,
                "52주고점 -40%이내":  from_high >= -40,   # 망가진 종목 배제
                "SMA200 상승 중":     sma200_rising,       # 지지선 역할 확인
            }
            preferred = {
                "BB 하단 터치":   price <= bb_low_v * 1.005,
                "RVOL < 1.2":     rvol < 1.2,
                "연속 하락 3일+": consec >= 3,
                "VIX ≤ 25":       vix_ok_val,
            }
        else:
            required = {
                "시장 레짐 Bull": mom_ok_val,
                "RSI(14) 50~70": 50 <= rsi14_v <= 70,
                "어닝 3일내 없음": not earn["within_3d"],
                "SMA200 상승 중": sma200_rising,
            }
            preferred = {
                "SEPA 정렬": sepa,
                "RVOL ≥ 1.2": rvol >= 1.2,
                "3개월 +10%": perf_3m >= 10,
                "52주고점 -25%이내": from_high >= -25,
                "52주저점 +30%이상": from_low >= 30,
                "RSI(2) < 80": rsi2_v < 80,
            }

        req_pass = sum(required.values())
        pref_pass = sum(preferred.values())
        pref_pct = pref_pass / len(preferred) if preferred else 0

        if req_pass < len(required):
            score, win_rate = "FAIL", "—"
        elif pref_pct >= 1.0:
            score, win_rate = ("A", "75~82%") if mode == "MR" else ("A", "70~78%")
        elif pref_pct >= 0.7:
            score, win_rate = ("B+", "68~75%") if mode == "MR" else ("B+", "63~70%")
        else:
            score, win_rate = ("B-", "60~65%") if mode == "MR" else ("B-", "55~63%")

        risk_dollar = account_sz * (risk_p / 100)
        shares = int(risk_dollar / atr_v) if atr_v > 0 else 0
        pos_value = shares * price

        return {
            "ticker": ticker, "price": round(price, 2),
            "sma200": round(s200, 2), "sma50": round(s50, 2), "sma20": round(s20, 2),
            "rsi2": round(rsi2_v, 1), "rsi14": round(rsi14_v, 1),
            "rvol": round(rvol, 2), "consec": consec,
            "bb_touch": price <= bb_low_v * 1.005,
            "atr": round(atr_v, 2), "perf_3m": round(perf_3m, 1),
            "sepa": sepa, "sma200_rising": sma200_rising,
            "from_high": round(from_high, 1), "from_low": round(from_low, 1),
            "earn_label": earn["label"], "earn_blocked": earn["within_3d"],
            "required": required, "req_pass": req_pass, "req_total": len(required),
            "preferred": preferred, "pref_pass": pref_pass, "pref_total": len(preferred),
            "pref_pct": round(pref_pct * 100),
            "score": score, "win_rate": win_rate,
            "shares": shares, "pos_value": round(pos_value),
            "pos_pct": round(pos_value / account_sz * 100, 1) if account_sz > 0 else 0,
        }
    except:
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
    spy_gap = (spy_price - spy_sma200) / spy_sma200 * 100
    spy_ok  = spy_gap >= 3  # 3% 마진 기준
    chg_note = "📈 상승" if spy_chg > 0 else "📉 하락"
    if spy_gap >= 3:
        st.success(
            f"**① 시장 추세 (SPY) 🟢 GO**\n\n"
            f"SPY ${spy_price:.1f} > SMA200 ${spy_sma200:.1f} (**{spy_gap:+.1f}%** ≥ 3% 안전마진)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** {chg_note}"
        )
    elif spy_gap > 0:
        st.warning(
            f"**① 시장 추세 (SPY) 🟡 경계**\n\n"
            f"SPY ${spy_price:.1f} > SMA200 ${spy_sma200:.1f} (**{spy_gap:+.1f}%** < 3% 안전마진 미달)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** {chg_note} — MOM 진입 금지 구간"
        )
    else:
        st.error(
            f"**① 시장 추세 (SPY) 🔴 주의**\n\n"
            f"SPY ${spy_price:.1f} < SMA200 ${spy_sma200:.1f} ({spy_gap:.1f}%)\n\n"
            f"오늘 등락: **{spy_chg:+.2f}%** {chg_note}"
        )
else:
    st.warning("**① 시장 추세 (SPY) ⚪ 데이터 없음** — 새로고침 해보세요")
    spy_ok = False

# 신호 1-B: QQQ (나스닥 기술주 추세 확인용)
if qqq_price and qqq_sma200:
    qqq_gap = (qqq_price - qqq_sma200) / qqq_sma200 * 100
    qqq_ok  = qqq_gap >= 3  # 3% 마진 기준
    qqq_note = "📈 상승" if qqq_chg > 0 else "📉 하락"
    if qqq_gap >= 3:
        st.success(
            f"**① 시장 추세 (QQQ) 🟢 GO**\n\n"
            f"QQQ ${qqq_price:.1f} > SMA200 ${qqq_sma200:.1f} (**{qqq_gap:+.1f}%** ≥ 3% 안전마진)\n\n"
            f"오늘 등락: **{qqq_chg:+.2f}%** {qqq_note}"
        )
    elif qqq_gap > 0:
        st.warning(
            f"**① 시장 추세 (QQQ) 🟡 경계**\n\n"
            f"QQQ ${qqq_price:.1f} > SMA200 ${qqq_sma200:.1f} (**{qqq_gap:+.1f}%** < 3% 안전마진 미달)\n\n"
            f"오늘 등락: **{qqq_chg:+.2f}%** {qqq_note} — MOM 진입 금지 구간"
        )
    else:
        st.error(
            f"**① 시장 추세 (QQQ) 🔴 주의**\n\n"
            f"QQQ ${qqq_price:.1f} < SMA200 ${qqq_sma200:.1f} ({qqq_gap:.1f}%)\n\n"
            f"오늘 등락: **{qqq_chg:+.2f}%** {qqq_note}"
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
spy_ok_val  = spy_price is not None and spy_sma200 is not None and ((spy_price - spy_sma200) / spy_sma200 * 100) >= 3
qqq_ok_val  = qqq_price is not None and qqq_sma200 is not None and ((qqq_price - qqq_sma200) / qqq_sma200 * 100) >= 3
vix_ok_val  = vix_now is not None and vix_now <= 25
all_green = spy_ok_val and qqq_ok_val and vix_ok_val and not event_risk

# 경계 구간 판별 (SMA200 위이지만 3% 미만)
_spy_border = spy_price is not None and spy_sma200 is not None and spy_price > spy_sma200 and not spy_ok_val
_qqq_border = qqq_price is not None and qqq_sma200 is not None and qqq_price > qqq_sma200 and not qqq_ok_val
_is_border = (_spy_border or _qqq_border) and vix_ok_val and not event_risk

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
elif _is_border:
    st.markdown("""
    <div style="background:#2d2d00;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🟡</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FFD700">경계 구간 — MR만 가능</div>
        <div style="color:#aaa;margin-top:8px">SPY/QQQ SMA200 위이나 3% 안전마진 미달 → MOM 금지</div>
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

# ══════════════════════════════════════════════════════════════
# 탭 분리: Daily Report vs 수동 분석
# ══════════════════════════════════════════════════════════════

# SPY RSI(2) 계산 (Daily Report용)
_spy_hist_dr = yf.Ticker("SPY").history(period="30d", interval="1d")
_spy_d2 = _spy_hist_dr["Close"].diff()
_spy_g2 = _spy_d2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
_spy_l2 = (-_spy_d2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
_spy_rsi2_dr = float((100 - 100/(1 + _spy_g2/_spy_l2.replace(0, 1e-10))).iloc[-1])

# 레짐 판단 (안전마진 적용)
_spy_margin_dr = ((spy_price - spy_sma200) / spy_sma200 * 100) if (spy_price and spy_sma200) else -99
_qqq_margin_dr = ((qqq_price - qqq_sma200) / qqq_sma200 * 100) if (qqq_price and qqq_sma200) else -99

# STRONG_BULL: SPY & QQQ 모두 SMA200 위 5% 이상
# WEAK_BULL:   SPY & QQQ 모두 SMA200 위 3% 이상
# BEAR:        그 외 (경계구간 포함)
if _spy_margin_dr >= 5 and _qqq_margin_dr >= 5:
    _regime_dr = "STRONG_BULL"
elif _spy_margin_dr >= 3 and _qqq_margin_dr >= 3:
    _regime_dr = "WEAK_BULL"
else:
    _regime_dr = "BEAR"
_mom_ok_dr = _regime_dr in ["STRONG_BULL", "WEAK_BULL"]
_mr_ok_dr = _spy_rsi2_dr > 10
_vix_ok_dr = vix_now is not None and vix_now <= 25

# SPY RSI(2) ≤ 10 경고
if _spy_rsi2_dr <= 10:
    st.error(f"⛔ SPY RSI(2) = {_spy_rsi2_dr:.1f} ≤ 10 — 시장 패닉, MR도 진입 금지")

st.divider()

tab_report, tab_manual, tab_hold = st.tabs(["📊 Daily Report (자동)", "🚦 신호등 + 수동 분석", "📌 보유 종목 모니터"])


# ──────────────────────────────────────────
# TAB 1: Daily Report
# ──────────────────────────────────────────
with tab_report:
    st.markdown("### 📊 APEX 2.0 Daily Report — 자동 스크리닝")
    st.caption("버튼 한 번 → Finviz 프리필터 → 체크리스트 자동 채점 → 등급 + 매수 타이밍")

    # 사이드바 대신 expander로 설정
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
                default=["전체"], key="dr_sectors"
            )
            if "전체" in dr_sectors: dr_sectors = ["전체"]

    # 레짐 요약
    _regime_emoji = {"STRONG_BULL": "🟢", "WEAK_BULL": "🟡", "BEAR": "🔴"}
    rc1, rc2, rc3, rc4 = st.columns(4)
    with rc1: st.metric("레짐", f"{_regime_emoji.get(_regime_dr, '⚪')} {_regime_dr}",
                        f"SPY {_spy_margin_dr:+.1f}% / QQQ {_qqq_margin_dr:+.1f}% vs SMA200")
    with rc2: st.metric("SPY RSI(2)", f"{_spy_rsi2_dr:.1f}")
    with rc3: st.metric("MOM", "✅ 허용" if _mom_ok_dr else "🚫 금지")
    with rc4: st.metric("MR", "✅ 허용" if _mr_ok_dr else "🚫 금지")

    # 승률 참고
    with st.expander("📈 승률 참고 (Connors RSI(2) 연구 기반)"):
        st.markdown("""
| 통과 수준 | 추정 승률 (2~5일) | 근거 |
|---|---|---|
| 필수만 통과 | 60~65% | RSI(2) 단독 |
| 필수 + 선호 70% | 68~75% | 복합 필터 |
| 필수 + 선호 100% | 75~82% | 최고 확신 |
        """)

    st.markdown("---")

    # ── MR / MOM 탭 ──
    dr_tab_mr, dr_tab_mom = st.tabs(["🔄 MR (평균회귀)", "🚀 MOM (모멘텀)"])

    with dr_tab_mr:
        if not _mr_ok_dr:
            st.error(f"🚫 MR 진입 금지 — SPY RSI(2) = {_spy_rsi2_dr:.1f} ≤ 10 (시장 패닉)")
        else:
            if st.button("🔄 MR 자동 스캔", key="dr_mr_scan", type="primary", use_container_width=True):
                with st.spinner("Finviz + yfinance 분석 중... (1~5분)"):
                    tickers = run_finviz_dr("MR", dr_sectors)
                    if isinstance(tickers, str):
                        st.error(tickers)
                    elif not tickers:
                        st.warning("조건 충족 종목 없음 — 섹터를 '전체'로 변경해보세요")
                    else:
                        st.info(f"Finviz 프리필터 통과: {len(tickers)}개")
                        prog = st.progress(0)
                        results = []
                        for i, t in enumerate(tickers):
                            r = analyze_stock_dr(t, "MR", _spy_rsi2_dr, _mom_ok_dr, _vix_ok_dr, dr_account, dr_risk)
                            if r: results.append(r)
                            prog.progress((i+1)/len(tickers))
                        prog.empty()
                        # FAIL 제거 후 랭킹 점수 기준 정렬
                        results = [r for r in results if r["score"] != "FAIL"]
                        results.sort(key=lambda x: _mr_rank_score(x), reverse=True)
                        st.session_state["dr_mr"] = results

            if "dr_mr" in st.session_state and st.session_state["dr_mr"]:
                results = st.session_state["dr_mr"]
                enterable = [r for r in results if r["score"] in ["A","B+"]]

                # ── TOP 2 오늘의 추천 ──
                top2 = enterable[:2]
                if top2:
                    st.markdown("### 🎯 오늘의 추천 — TOP 2")
                    for idx, r in enumerate(top2):
                        rank_label = ["1️⃣", "2️⃣"][idx]
                        emj = {"A":"🟢","B+":"🔵"}.get(r["score"],"⚪")
                        st.markdown(f"""
<div style="background:#1a3a2a;border-radius:12px;padding:14px 16px;margin:6px 0;border:1px solid #2d6a4f">
<b>{rank_label} {emj} {r['ticker']}</b> &nbsp; ${r['price']} &nbsp; [{r['score']}] 승률 {r['win_rate']}<br>
RSI(2): <b>{r['rsi2']}</b> &nbsp;|&nbsp; RVOL: {r['rvol']}x &nbsp;|&nbsp; 연속↓: {r['consec']}일 &nbsp;|&nbsp; BB하단: {'✅' if r['bb_touch'] else '❌'}<br>
⏰ 매수 <b>04:30 KST</b> &nbsp;|&nbsp; 🎯 익절 RSI(2)>70 &nbsp;|&nbsp; 🛑 손절 ${r['price'] - r['atr']*3:.2f}<br>
📐 {r['shares']}주 × ${r['price']} = <b>${r['pos_value']:,}</b> (계좌 {r['pos_pct']}%)
</div>""", unsafe_allow_html=True)
                else:
                    st.warning("⚠️ 오늘 A/B+ 등급 후보 없음 — 오늘은 쉬는 날")

                st.divider()
                st.success(f"✅ 전체 후보 {len(results)}개 | 진입 가능 {len(enterable)}개")

                for r in results:
                    emj = {"A":"🟢","B+":"🔵","B-":"🟡","FAIL":"🔴"}.get(r["score"],"⚪")
                    with st.expander(
                        f"{emj} **{r['ticker']}** ${r['price']} — [{r['score']}] 승률 {r['win_rate']}"
                        f"  |  RSI2:{r['rsi2']}  RVOL:{r['rvol']}  연속↓:{r['consec']}일"
                    ):
                        m1,m2,m3,m4 = st.columns(4)
                        with m1: st.metric("RSI(2)", f"{r['rsi2']}", "≤15 ✓" if r['rsi2']<=15 else ">15 ✗")
                        with m2: st.metric("RVOL", f"{r['rvol']}x")
                        with m3: st.metric("ATR", f"${r['atr']}")
                        with m4: st.metric("연속↓", f"{r['consec']}일")

                        ch1, ch2 = st.columns(2)
                        with ch1:
                            st.markdown(f"**필수 ({r['req_pass']}/{r['req_total']})**")
                            for name, ok in r["required"].items():
                                st.markdown(f"{'✅' if ok else '❌'} {name}")
                        with ch2:
                            st.markdown(f"**선호 ({r['pref_pass']}/{r['pref_total']} = {r['pref_pct']}%)**")
                            for name, ok in r["preferred"].items():
                                st.markdown(f"{'✅' if ok else '❌'} {name}")

                        if r["score"] in ["A","B+"]:
                            st.divider()
                            g1,g2,g3,g4 = st.columns(4)
                            with g1: st.info(f"⏰ **매수**\n\n장 마감 30분전\nKST 05:30\n지정가 ${r['price']*0.998:.2f}")
                            with g2: st.success(f"🎯 **①익절**\n\nRSI(2)>70\n시 매도")
                            with g3: st.warning(f"⏱️ **②타임스탑**\n\n최대 10일\n보유 후 청산")
                            with g4: st.error(f"🛑 **③재난손절**\n\n진입가−3ATR\n${r['price'] - r['atr']*3:.2f}\n({-r['atr']*3/r['price']*100:.1f}%)")
                            st.markdown(f"📐 **포지션:** {r['shares']}주 × ${r['price']} = **${r['pos_value']:,}** (계좌 {r['pos_pct']}%)")
                            if r['pos_pct'] > 25: st.error(f"⚠️ 과집중 {r['pos_pct']}%")
                        if r["earn_blocked"]: st.error(f"🚨 어닝 3일 이내 — 진입 금지")

    with dr_tab_mom:
        if not _mom_ok_dr:
            st.error("🚫 MOM 진입 금지 — Bear 레짐")
        else:
            if st.button("🚀 MOM 자동 스캔", key="dr_mom_scan", type="primary", use_container_width=True):
                with st.spinner("Finviz + yfinance 분석 중..."):
                    tickers = run_finviz_dr("MOM", dr_sectors)
                    if isinstance(tickers, str):
                        st.error(tickers)
                    elif not tickers:
                        st.warning("조건 충족 종목 없음")
                    else:
                        st.info(f"Finviz 프리필터 통과: {len(tickers)}개")
                        prog = st.progress(0)
                        results = []
                        for i, t in enumerate(tickers):
                            r = analyze_stock_dr(t, "MOM", _spy_rsi2_dr, _mom_ok_dr, _vix_ok_dr, dr_account, dr_risk)
                            if r: results.append(r)
                            prog.progress((i+1)/len(tickers))
                        prog.empty()
                        # FAIL 제거 후 랭킹 점수 기준 정렬
                        results = [r for r in results if r["score"] != "FAIL"]
                        results.sort(key=lambda x: _mom_rank_score(x), reverse=True)
                        st.session_state["dr_mom"] = results

            if "dr_mom" in st.session_state and st.session_state["dr_mom"]:
                results = st.session_state["dr_mom"]
                enterable = [r for r in results if r["score"] in ["A","B+"]]

                # ── TOP 2 오늘의 추천 ──
                top2 = enterable[:2]
                if top2:
                    st.markdown("### 🎯 오늘의 추천 — TOP 2")
                    for idx, r in enumerate(top2):
                        rank_label = ["1️⃣", "2️⃣"][idx]
                        emj = {"A":"🟢","B+":"🔵"}.get(r["score"],"⚪")
                        st.markdown(f"""
<div style="background:#1a2a3a;border-radius:12px;padding:14px 16px;margin:6px 0;border:1px solid #2d4a6f">
<b>{rank_label} {emj} {r['ticker']}</b> &nbsp; ${r['price']} &nbsp; [{r['score']}] 승률 {r['win_rate']}<br>
RSI(14): <b>{r['rsi14']}</b> &nbsp;|&nbsp; RVOL: {r['rvol']}x &nbsp;|&nbsp; 3M: +{r['perf_3m']}% &nbsp;|&nbsp; SEPA: {'✅' if r['sepa'] else '❌'}<br>
⏰ 매수 <b>23:00 KST</b> &nbsp;|&nbsp; 🎯 익절 +8% ${r['price']*1.08:.2f} &nbsp;|&nbsp; ⏱️ 타임스탑 15일<br>
📐 {r['shares']}주 × ${r['price']} = <b>${r['pos_value']:,}</b> (계좌 {r['pos_pct']}%)
</div>""", unsafe_allow_html=True)
                else:
                    st.warning("⚠️ 오늘 A/B+ 등급 MOM 후보 없음")

                st.divider()
                st.success(f"✅ 전체 후보 {len(results)}개 | 진입 가능 {len(enterable)}개")

                for r in results:
                    emj = {"A":"🟢","B+":"🔵","B-":"🟡","FAIL":"🔴"}.get(r["score"],"⚪")
                    with st.expander(
                        f"{emj} **{r['ticker']}** ${r['price']} — [{r['score']}] 승률 {r['win_rate']}"
                        f"  |  RSI14:{r['rsi14']}  RVOL:{r['rvol']}  3M:+{r['perf_3m']}%"
                    ):
                        m1,m2,m3,m4 = st.columns(4)
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

                        if r["score"] in ["A","B+"]:
                            st.divider()
                            g1,g2,g3 = st.columns(3)
                            with g1: st.info(f"⏰ **매수**\n\n장 개장 30분~1시간 후\nKST 23:00~23:30")
                            with g2: st.success(f"🎯 **①익절**\n\n+8% 도달 시\n즉시 매도")
                            with g3: st.warning(f"⏱️ **②타임스탑**\n\n최대 15일\n보유 후 청산")
                            st.caption("⚠️ MOM 백테스트 결과: +8% 익절 + 15일 타임스탑이 최적 (RSI익절·3ATR손절은 성과 저하)")
                            st.markdown(f"📐 **포지션:** {r['shares']}주 × ${r['price']} = **${r['pos_value']:,}** (계좌 {r['pos_pct']}%)")
                        if r["earn_blocked"]: st.error(f"🚨 어닝 3일 이내 — 진입 금지")

    # 매수 타이밍 가이드
    st.divider()
    st.markdown("### ⏱️ 매수 타이밍 가이드")
    tc1, tc2 = st.columns(2)
    with tc1:
        st.info("""
**🔄 MR (평균회귀)**

⏰ **최적:** 장 마감 30분전 (KST 05:30)
- 당일 RSI(2)/BB 확정 후 진입
- 패닉매도 장 초반 → 마감 안정화
- 오버나이트 갭업 수혜

⏰ **차선:** KST 23:00 지정가 걸고 취침
🎯 **익절:** RSI(2) > 70 시 장중 매도
📅 **홀딩:** 2~5일
        """)
    with tc2:
        st.success("""
**🚀 MOM (모멘텀)**

⏰ **최적:** 장 개장 30분~1시간 후 (KST 23:00)
- 가짜 브레이크아웃 필터: 30분 관망
- 볼륨 1.5배 이상 동반 확인

⏰ **차선:** 전일 브레이크아웃 → 다음날 풀백
🎯 **익절:** +8~12% 또는 RSI(14) > 75
📅 **홀딩:** 5~15일
        """)


# ──────────────────────────────────────────
# TAB 2: 기존 수동 분석 (APEX_NEW_v2.py 원본)
# ──────────────────────────────────────────
with tab_manual:
    # ══════════════════════════════════════════════════════════
    # ⑤ 종목 스캐너
    # ══════════════════════════════════════════════════════════
    st.markdown("## 🔍 종목 스캔")
    st.caption("MOM: SMA200위+SMA50위+RSI<60+분기+10%+거래량500K+ | MR: SMA200위+RSI(14)<40+거래량500K+")

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
            result = run_screener(sector, "MOM" if is_mom else "MR")
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
                        hist["SMA150"] = hist["Close"].rolling(150).mean()
                        hist["SMA200"] = hist["Close"].rolling(200).mean()

                        # ── RSI(14): 과매수 필터용 ──
                        d14 = hist["Close"].diff()
                        g14 = d14.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                        l14 = (-d14.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                        hist["RSI14"] = 100 - 100/(1 + g14/l14.replace(0, 1e-10))

                        # ── RSI(2): APEX 2.0 MR 핵심 신호 ──
                        d2 = hist["Close"].diff()
                        g2 = d2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                        l2 = (-d2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                        hist["RSI2"] = 100 - 100/(1 + g2/l2.replace(0, 1e-10))

                        # ── Bollinger Band(20, 2σ): MR 하단 터치 신호 ──
                        bb_mid   = hist["Close"].rolling(20).mean()
                        bb_std   = hist["Close"].rolling(20).std()
                        hist["BB_upper"] = bb_mid + 2 * bb_std
                        hist["BB_lower"] = bb_mid - 2 * bb_std
                        hist["BB_mid"]   = bb_mid

                        # ── SPY RSI(2): 시장 급락 여부 확인 ──
                        spy_hist = yf.Ticker("SPY").history(period="30d", interval="1d")
                        spy_d2 = spy_hist["Close"].diff()
                        spy_g2 = spy_d2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                        spy_l2 = (-spy_d2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                        spy_rsi2_series = 100 - 100/(1 + spy_g2/spy_l2.replace(0, 1e-10))
                        spy_rsi2_val = float(spy_rsi2_series.iloc[-1]) if not spy_rsi2_series.empty else None

                        df60 = hist.tail(60)
                        curr    = float(df60["Close"].iloc[-1])
                        s200    = float(df60["SMA200"].iloc[-1])   if not pd.isna(df60["SMA200"].iloc[-1])   else None
                        s150    = float(df60["SMA150"].iloc[-1])   if not pd.isna(df60["SMA150"].iloc[-1])   else None
                        s50     = float(df60["SMA50"].iloc[-1])    if not pd.isna(df60["SMA50"].iloc[-1])    else None
                        rsi_v   = float(df60["RSI14"].iloc[-1])    if not pd.isna(df60["RSI14"].iloc[-1])    else None
                        rsi2_v  = float(df60["RSI2"].iloc[-1])     if not pd.isna(df60["RSI2"].iloc[-1])     else None
                        bb_low  = float(df60["BB_lower"].iloc[-1]) if not pd.isna(df60["BB_lower"].iloc[-1]) else None
                        bb_up   = float(df60["BB_upper"].iloc[-1]) if not pd.isna(df60["BB_upper"].iloc[-1]) else None
                        bb_mid_v= float(df60["BB_mid"].iloc[-1])   if not pd.isna(df60["BB_mid"].iloc[-1])   else None

                        # ── SMA200 방향성: 현재 vs 20일 전 비교 ──
                        sma200_now  = hist["SMA200"].iloc[-1]
                        sma200_20d  = hist["SMA200"].iloc[-21] if len(hist) >= 21 else None
                        sma200_rising = (
                            not pd.isna(sma200_now) and
                            sma200_20d is not None and
                            not pd.isna(sma200_20d) and
                            float(sma200_now) > float(sma200_20d)
                        )
                        sma200_slope_pct = (
                            (float(sma200_now) - float(sma200_20d)) / float(sma200_20d) * 100
                            if sma200_20d is not None and not pd.isna(sma200_20d) and float(sma200_20d) != 0
                            else None
                        )

                        # ── Minervini SEPA 정렬: SMA50 > SMA150 > SMA200 ──
                        sepa_aligned = (
                            s50 is not None and s150 is not None and s200 is not None and
                            s50 > s150 > s200
                        )

                        # ── 52주 고저점 위치 계산 ──
                        # hist는 300d 데이터 — 252 거래일(≈52주) 사용
                        hist_252 = hist.tail(252)
                        w52_high  = float(hist_252["High"].max())
                        w52_low   = float(hist_252["Low"].min())
                        # 현재가의 52주 레인지 내 위치 (0%=52주 저점, 100%=52주 고점)
                        w52_range = w52_high - w52_low
                        w52_pos   = (curr - w52_low) / w52_range * 100 if w52_range > 0 else None
                        # 고점 대비 하락폭 (Minervini: 신고가 25% 이내 조건)
                        w52_from_high_pct = (curr - w52_high) / w52_high * 100   # 음수
                        # 저점 대비 상승폭 (Minervini: 52주 저점 30% 이상 위 조건)
                        w52_from_low_pct  = (curr - w52_low)  / w52_low  * 100   # 양수
                        # Minervini 조건 판정
                        minv_high_ok = w52_from_high_pct >= -25.0   # 고점 대비 -25% 이내
                        minv_low_ok  = w52_from_low_pct  >= 30.0    # 저점 대비 +30% 이상

                        chg_3m = None
                        if len(hist) >= 63:
                            chg_3m = (hist["Close"].iloc[-1] / hist["Close"].iloc[-63] - 1) * 100

                        avg_vol  = hist["Volume"].tail(20).mean()
                        rvol_now = hist["Volume"].iloc[-1] / avg_vol if avg_vol > 0 else 0

                        # ── ATR(14) 계산: 포지션 사이징 기반 ──
                        hi  = hist["High"]
                        lo  = hist["Low"]
                        cl  = hist["Close"]
                        tr  = pd.concat([
                            hi - lo,
                            (hi - cl.shift(1)).abs(),
                            (lo - cl.shift(1)).abs()
                        ], axis=1).max(axis=1)
                        hist["ATR14"] = tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                        atr_val = float(hist["ATR14"].iloc[-1]) if not pd.isna(hist["ATR14"].iloc[-1]) else None

                        # ── 어닝 날짜 조회 ──
                        with st.spinner(f"{selected} 어닝 날짜 확인 중..."):
                            earn_info = get_earnings_info(selected)

                        # ── 체크카드 (MOM/MR 분기) ──
                        if is_mom:
                            # MOM: SMA200 위, SMA50 위, RSI<60, 현재가
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
                            # MR: SMA200 위, RSI(2), BB하단, 연속하락
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

                        # ══════════════════════════════════════════
                        # SMA200 방향성 + Minervini SEPA 정렬
                        # ══════════════════════════════════════════
                        st.divider()
                        st.markdown("#### 📈 추세 구조 분석")
                        st.caption("SMA200 방향성 (Minervini SEPA 조건) — 상승 추세의 질을 판단")

                        ta1, ta2 = st.columns(2)

                        # ── SMA200 방향성 카드 ──
                        with ta1:
                            st.markdown("**SMA200 방향성**")
                            if sma200_slope_pct is not None:
                                if sma200_rising:
                                    st.success(
                                        f"✅ SMA200 **상승 중**\n\n"
                                        f"20일 변화: **+{sma200_slope_pct:.2f}%**\n\n"
                                        f"현재 ${float(sma200_now):.2f} > 20일전 ${float(sma200_20d):.2f}"
                                    )
                                else:
                                    st.error(
                                        f"❌ SMA200 **하락/횡보**\n\n"
                                        f"20일 변화: **{sma200_slope_pct:.2f}%**\n\n"
                                        f"현재 ${float(sma200_now):.2f} ≤ 20일전 ${float(sma200_20d):.2f}"
                                    )
                            else:
                                st.warning("⚪ SMA200 방향 계산 불가\n\n데이터 21일 미만")

                        # ── SEPA 정렬 카드 ──
                        with ta2:
                            st.markdown("**Minervini SEPA 정렬**")
                            st.caption("SMA50 > SMA150 > SMA200")
                            if s50 and s150 and s200:
                                if sepa_aligned:
                                    st.success(
                                        f"✅ 정렬 완료\n\n"
                                        f"SMA50 ${s50:.1f}\n"
                                        f"SMA150 ${s150:.1f}\n"
                                        f"SMA200 ${s200:.1f}"
                                    )
                                else:
                                    # 어느 조건이 깨졌는지 명시
                                    broken = []
                                    if not (s50 > s150): broken.append(f"SMA50({s50:.1f}) ≤ SMA150({s150:.1f})")
                                    if not (s150 > s200): broken.append(f"SMA150({s150:.1f}) ≤ SMA200({s200:.1f})")
                                    st.error(
                                        f"❌ 정렬 미완성\n\n" +
                                        "\n".join(broken)
                                    )
                            else:
                                st.warning("⚪ 계산 불가\n\n데이터 부족")

                        # ── 추세 구조 종합 판정 ──
                        trend_score = sum([
                            sma200_rising,
                            sepa_aligned,
                            s200 is not None and curr > s200,
                            s50  is not None and curr > s50,
                        ])
                        trend_labels = {
                            4: ("🟢 추세 구조 최상", "4/4 — MOM 진입 최적 환경" if is_mom else "4/4 — 강한 추세 속 눌림 (MR 양호)"),
                            3: ("🟡 추세 구조 양호", "3/4 — MOM 진입 가능, 세부 확인" if is_mom else "3/4 — MR 눌림목 탐색 적합"),
                            2: ("🟠 추세 구조 혼조", "2/4 — MR 전략 또는 관망 검토" if is_mom else "2/4 — MR 진입 시 신중"),
                            1: ("🔴 추세 구조 취약", "1/4 — 진입 비권장"),
                            0: ("🔴 추세 구조 붕괴", "0/4 — 진입 금지"),
                        }
                        tlabel, tdesc = trend_labels[trend_score]
                        st.info(f"**{tlabel}** ({trend_score}/4)  \n{tdesc}")

                        with st.expander("📖 추세 구조 판단 기준"):
                            st.markdown(f"""
    | 체크 항목 | 상태 | 의미 |
    |---|---|---|
    | SMA200 상승 중 (20일 기준) | {"✅" if sma200_rising else "❌"} | 장기 추세가 살아있는가 |
    | SEPA 정렬 (SMA50>150>200) | {"✅" if sepa_aligned else "❌"} | 단/중/장기 이평 정배열 |
    | 현재가 > SMA200 | {"✅" if s200 and curr > s200 else "❌"} | 장기 지지선 위 |
    | 현재가 > SMA50 | {"✅" if s50 and curr > s50 else "❌"} | 중기 지지선 위 |

    **Minervini SEPA 조건 출처**: Mark Minervini의 공개 저서 *Trade Like a Stock Market Wizard* 기반.  
    SMA200이 방향성 없이 수평이거나 하락 중이면, 현재가가 SMA200 위에 있어도 추세 진입으로 보지 않는다.
                            """)

                        # ══════════════════════════════════════════
                        # 52주 고저점 위치 분석
                        # ══════════════════════════════════════════
                        st.divider()
                        st.markdown("#### 📊 52주 고저점 위치")
                        st.caption(
                            "Minervini 조건: 52주 고점 대비 **−25% 이내** + 52주 저점 대비 **+30% 이상**"
                        )

                        # 상단 메트릭 3개
                        w1, w2, w3 = st.columns(3)
                        with w1:
                            st.metric("52주 고점", f"${w52_high:.2f}",
                                      f"{w52_from_high_pct:+.1f}% (현재가 기준)")
                        with w2:
                            st.metric("52주 저점", f"${w52_low:.2f}",
                                      f"+{w52_from_low_pct:.1f}% (현재가 기준)")
                        with w3:
                            if w52_pos is not None:
                                st.metric("52주 레인지 위치", f"{w52_pos:.0f}%",
                                          "0%=저점 / 100%=고점")

                        # 시각적 레인지 바
                        if w52_pos is not None:
                            # 색상: 위치에 따라
                            if w52_pos >= 75:
                                bar_col = "#00C853"   # 고점 근처 — 강세
                            elif w52_pos >= 40:
                                bar_col = "#FFD700"   # 중간
                            else:
                                bar_col = "#FF5252"   # 저점 근처 — 약세 또는 MR 기회
                            st.markdown(f"""
    <div style="margin:12px 0">
        <div style="display:flex;justify-content:space-between;
                    font-size:0.8rem;color:#aaa;margin-bottom:4px">
            <span>52주 저점 ${w52_low:.2f}</span>
            <span>현재 ${curr:.2f} ({w52_pos:.0f}%)</span>
            <span>52주 고점 ${w52_high:.2f}</span>
        </div>
        <div style="position:relative;background:#333;border-radius:8px;
                    height:22px;overflow:hidden">
            <div style="width:{w52_pos:.1f}%;background:{bar_col};
                        height:100%;border-radius:8px;
                        transition:width 0.4s ease"></div>
        </div>
    </div>
    """, unsafe_allow_html=True)

                        # Minervini 조건 2개 판정 카드
                        mc_a, mc_b = st.columns(2)
                        with mc_a:
                            if minv_high_ok:
                                st.success(
                                    f"✅ 고점 근접\n\n"
                                    f"고점 대비 **{w52_from_high_pct:.1f}%**\n\n"
                                    f"기준: −25% 이내 ✓"
                                )
                            else:
                                st.error(
                                    f"❌ 고점 과리\n\n"
                                    f"고점 대비 **{w52_from_high_pct:.1f}%**\n\n"
                                    f"기준: −25% 이내 미충족"
                                )
                        with mc_b:
                            if minv_low_ok:
                                st.success(
                                    f"✅ 저점 충분히 회복\n\n"
                                    f"저점 대비 **+{w52_from_low_pct:.1f}%**\n\n"
                                    f"기준: +30% 이상 ✓"
                                )
                            else:
                                st.error(
                                    f"❌ 저점 회복 부족\n\n"
                                    f"저점 대비 **+{w52_from_low_pct:.1f}%**\n\n"
                                    f"기준: +30% 이상 미충족"
                                )

                        # Minervini 52주 종합
                        minv_52w_score = sum([minv_high_ok, minv_low_ok])
                        if minv_52w_score == 2:
                            st.success("🟢 **Minervini 52주 조건 충족** — 유니버스 진입 자격")
                        elif minv_52w_score == 1:
                            st.warning("🟡 **Minervini 52주 조건 1/2** — 부분 충족, 신중 접근")
                        else:
                            st.error("🔴 **Minervini 52주 조건 미충족** — 유니버스 제외 검토")

                        with st.expander("📖 52주 조건 해석"):
                            st.markdown(f"""
    **Minervini 52주 조건 (공개 저서 기준)**

    | 조건 | 기준 | 현재값 | 판정 |
    |---|---|---|---|
    | 52주 고점 대비 | −25% 이내 | {w52_from_high_pct:.1f}% | {"✅" if minv_high_ok else "❌"} |
    | 52주 저점 대비 | +30% 이상 | +{w52_from_low_pct:.1f}% | {"✅" if minv_low_ok else "❌"} |
    | 52주 레인지 위치 | — | {w52_pos:.0f}% | — |

    **고점 근접 조건 (−25% 이내)**  
    고점에서 너무 멀리 떨어진 종목은 이미 추세가 꺾였거나 회복 단계.  
    브레이크아웃을 기다리는 종목은 대개 신고가 0~25% 아래에서 눌림목을 형성.

    **저점 충분히 회복 (30% 이상)**  
    저점에서 30% 이상 오른 종목만 매집 세력이 진입했다는 증거로 봄.  
    저점 부근 종목은 아직 바닥 형성 중일 가능성 높음.

    **레인지 위치 해석**  
    - 75~100%: 고점 돌파 또는 근접 — MOM 브레이크아웃 후보  
    - 40~74%: 중간 눌림 — 추세 확인 후 판단  
    - 0~39%: 저점 근처 — MR 반등 후보 또는 추세 붕괴
                            """)

                        # ── 어닝 경고 배너 ──
                        st.divider()
                        st.markdown("#### 📅 어닝 일정")
                        if earn_info["source"] == "none":
                            st.warning(
                                "⚪ 어닝 날짜 조회 실패\n\n"
                                "yfinance 응답 없음 — Finviz/Nasdaq.com에서 수동 확인 필수\n\n"
                                f"[Finviz {selected} 확인](https://finviz.com/quote.ashx?t={selected})"
                            )
                        elif earn_info["within_3d"]:
                            st.error(
                                f"🚨 **어닝 3일 이내 — 진입 금지**\n\n"
                                f"예정일: **{earn_info['label']}**\n\n"
                                f"APEX 2.0 룰: 어닝 ±3일은 갭 리스크로 인해 신규 진입 금지"
                            )
                        else:
                            days = earn_info["days_away"]
                            if days is not None and days <= 14:
                                st.warning(
                                    f"🟡 어닝 **{earn_info['label']}** — 14일 이내\n\n"
                                    f"포지션 보유 중이라면 어닝 전 청산 여부 사전 결정 필요"
                                )
                            else:
                                st.success(
                                    f"✅ 어닝 안전 구간\n\n"
                                    f"예정일: {earn_info['label']}"
                                )

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

                        # ══════════════════════════════════════════
                        # APEX 2.0 MR 전용 신호 블록
                        # RSI(2) + Bollinger Band + SPY RSI(2)
                        # ══════════════════════════════════════════
                        if not is_mom:
                            st.divider()
                            st.markdown("#### 🎯 APEX 2.0 MR 진입 신호")
                            st.caption("RSI(2) ≤ 15 + BB 하단 터치 + SPY RSI(2) > 10 — 3개 동시 충족 시 진입 검토")

                            mr1, mr2, mr3 = st.columns(3)

                            # ── RSI(2) ──
                            with mr1:
                                if rsi2_v is not None:
                                    if rsi2_v <= 15:
                                        st.success(f"✅ RSI(2)\n**{rsi2_v:.1f}**\n≤15 MR 진입 신호")
                                    elif rsi2_v <= 30:
                                        st.warning(f"🟡 RSI(2)\n**{rsi2_v:.1f}**\n눌림 중, 대기")
                                    else:
                                        st.error(f"❌ RSI(2)\n**{rsi2_v:.1f}**\n아직 과열")
                                else:
                                    st.info("RSI(2) 계산 불가")

                            # ── BB 하단 터치 ──
                            with mr2:
                                if bb_low is not None:
                                    bb_pct = (curr - bb_low) / (bb_up - bb_low) * 100 if bb_up != bb_low else 50
                                    if curr <= bb_low * 1.005:   # 하단 0.5% 이내
                                        st.success(f"✅ BB 하단 터치\n현가 ${curr:.2f}\nBB↓ ${bb_low:.2f}")
                                    elif curr <= bb_mid_v:
                                        st.warning(f"🟡 BB 중단 이하\n현가 ${curr:.2f}\nBB↓ ${bb_low:.2f}")
                                    else:
                                        st.error(f"❌ BB 중단 이상\n현가 ${curr:.2f}\nBB↓ ${bb_low:.2f}")
                                    st.caption(f"BB 위치: 하단 기준 {bb_pct:.0f}%")
                                else:
                                    st.info("BB 계산 불가")

                            # ── SPY RSI(2): 시장 급락 아님 확인 ──
                            with mr3:
                                if spy_rsi2_val is not None:
                                    if spy_rsi2_val > 10:
                                        st.success(f"✅ SPY RSI(2)\n**{spy_rsi2_val:.1f}**\n시장 급락 아님 ✓")
                                    elif spy_rsi2_val > 5:
                                        st.warning(f"🟡 SPY RSI(2)\n**{spy_rsi2_val:.1f}**\n시장 약세 주의")
                                    else:
                                        st.error(f"❌ SPY RSI(2)\n**{spy_rsi2_val:.1f}**\n시장 급락 — 진입 금지")
                                else:
                                    st.info("SPY RSI(2) 계산 불가")

                            # ── MR 종합 판정 ──
                            rsi2_ok     = rsi2_v is not None and rsi2_v <= 15
                            bb_ok       = bb_low is not None and curr <= bb_low * 1.005
                            spy_rsi2_ok = spy_rsi2_val is not None and spy_rsi2_val > 10
                            earn_ok     = not earn_info["within_3d"]   # 어닝 3일 이내면 False
                            mr_score    = sum([rsi2_ok, bb_ok, spy_rsi2_ok])

                            if not earn_ok:
                                st.error("🚨 **어닝 3일 이내 — MR 진입 자동 차단** (어닝 통과 후 재검토)")
                            elif mr_score == 3:
                                st.success("🟢 **MR 진입 신호 FULL** — RSI(2) + BB하단 + SPY RSI(2) 3개 충족")
                            elif mr_score == 2:
                                st.warning(f"🟡 **MR 신호 2/3** — {'RSI2✅' if rsi2_ok else 'RSI2❌'} | {'BB✅' if bb_ok else 'BB❌'} | {'SPY✅' if spy_rsi2_ok else 'SPY❌'} — 추가 확인 후 판단")
                            else:
                                st.error(f"🔴 **MR 신호 {mr_score}/3** — 진입 조건 미충족")

                        # ── MOM 전용: RSI(2) 방향 확인 ──
                        else:
                            st.divider()
                            st.markdown("#### 🚀 APEX 2.0 MOM 보조 신호")
                            st.caption("RSI(2) 방향 + BB 위치 — MOM 과열 여부 보조 확인")

                            mom1, mom2 = st.columns(2)
                            with mom1:
                                if rsi2_v is not None:
                                    if rsi2_v >= 80:
                                        st.error(f"⚠️ RSI(2) {rsi2_v:.1f}\n단기 과열 — 추격 주의")
                                    elif rsi2_v >= 50:
                                        st.success(f"✅ RSI(2) {rsi2_v:.1f}\n모멘텀 지속 중")
                                    else:
                                        st.warning(f"🟡 RSI(2) {rsi2_v:.1f}\n단기 약세 — 눌림 중")
                            with mom2:
                                if bb_up is not None:
                                    if curr >= bb_up * 0.995:
                                        st.error(f"⚠️ BB 상단 근접\n현가 ${curr:.2f}\nBB↑ ${bb_up:.2f}\n추격 위험")
                                    elif curr >= bb_mid_v:
                                        st.success(f"✅ BB 중단 위\n현가 ${curr:.2f}\n상승 추세 유효")
                                    else:
                                        st.warning(f"🟡 BB 중단 아래\n현가 ${curr:.2f}\n추세 약화 주의")

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
                                ("SMA150", "#FFA726", "SMA150"),
                                ("SMA200", "#FF7043", "SMA200 ★"),
                                ("BB_upper", "#9C27B0", "BB상단"),
                                ("BB_lower", "#9C27B0", "BB하단"),
                                ("BB_mid",   "#7B1FA2", "BB중단"),
                            ]:
                                dash_style = "dot" if "BB" in col_n else "solid"
                                width_style = 1 if "BB" in col_n else 2
                                fig.add_trace(go.Scatter(
                                    x=df60.index, y=df60[col_n],
                                    name=nm, line=dict(color=color, width=width_style, dash=dash_style)
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
                                title=f"{selected} — SMA50·SMA150·SMA200·BB·거래량",
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

                        # ── 손절/목표가 (MOM/MR 분기) ──
                        st.divider()
                        st.markdown("#### 🛑 손절 / 목표가")
                        if is_mom:
                            sc1, sc2 = st.columns(2)
                            with sc1:
                                st.success(f"🎯 ①익절\n+8% 도달 시 매도\n목표 ${curr * 1.08:.2f}")
                            with sc2:
                                st.warning(f"⏱️ ②타임스탑\n최대 15일 보유 후 청산")
                            st.caption("⚠️ MOM 백테스트 결과: +8% 익절 + 15일 타임스탑이 최적 (재난손절 없음)")
                        else:
                            sc1, sc2, sc3 = st.columns(3)
                            with sc1:
                                st.success(f"🎯 ①익절\nRSI(2)>70 시 매도")
                            with sc2:
                                st.warning(f"⏱️ ②타임스탑\n최대 10일 보유 후 청산")
                            with sc3:
                                if atr_val:
                                    stop_3atr = curr - atr_val * 3
                                    stop_pct = -atr_val * 3 / curr * 100
                                    st.error(f"🛑 ③재난손절\n진입가−3ATR\n${stop_3atr:.2f} ({stop_pct:.1f}%)")
                                else:
                                    st.error("🛑 ③재난손절\nATR 계산 불가")
                            st.caption("⚠️ MR 백테스트 결과: RSI(2)>70 익절 + 10일 타임스탑 + 3ATR 재난손절")

                        # ══════════════════════════════════════════
                        # ATR 기반 포지션 사이징
                        # 공식: 주수 = (계좌 × 리스크%) / ATR
                        # ══════════════════════════════════════════
                        st.divider()
                        st.markdown("#### 📐 ATR 포지션 사이징")
                        st.caption(
                            "공식: **주수 = (계좌금액 × 리스크%) ÷ ATR(14)**  |  "
                            "ATR = 종목의 일평균 변동폭 → 손실이 '1 ATR'을 넘지 않도록 주수 결정"
                        )

                        if atr_val:
                            # ATR 현황 표시
                            atr_pct = atr_val / curr * 100
                            ac1, ac2, ac3 = st.columns(3)
                            with ac1:
                                st.metric("ATR(14)", f"${atr_val:.2f}", f"현가 대비 {atr_pct:.1f}%")
                            with ac2:
                                st.metric("3ATR 재난손절", f"${curr - atr_val * 3:.2f}", f"−{atr_pct*3:.1f}%")
                            with ac3:
                                st.metric("2ATR 목표가", f"${curr + atr_val * 2:.2f}", f"+{atr_pct*2:.1f}%")

                            st.markdown("---")

                            # 사용자 입력: 계좌 크기 + 리스크 %
                            ps1, ps2 = st.columns(2)
                            with ps1:
                                account_size = st.number_input(
                                    "💰 계좌 금액 (USD)",
                                    min_value=500,
                                    max_value=500_000,
                                    value=st.session_state.get("apex_account", 5000),
                                    step=500,
                                    key="apex_account",
                                    help="실제 트레이딩 계좌 전체 금액"
                                )
                            with ps2:
                                risk_pct = st.slider(
                                    "🎯 1회 리스크 % (계좌 대비)",
                                    min_value=0.5,
                                    max_value=3.0,
                                    value=st.session_state.get("apex_risk_pct", 1.0),
                                    step=0.5,
                                    key="apex_risk_pct",
                                    help="계좌의 몇 %를 이번 트레이드에서 최대 잃을 수 있는가"
                                )

                            # 핵심 계산
                            risk_dollar  = account_size * (risk_pct / 100)
                            shares_atr   = int(risk_dollar / atr_val)           # ATR 기준 주수
                            pos_value    = shares_atr * curr                     # 포지션 금액
                            pos_pct      = pos_value / account_size * 100        # 계좌 대비 비중
                            stop_3atr    = curr - atr_val * 3                    # 3 ATR 재난손절
                            tgt_2r       = curr + atr_val * 2                    # R:R 2배 목표
                            tgt_3r       = curr + atr_val * 3                    # R:R 3배 목표

                            # 결과 표시
                            st.markdown("##### 📊 포지션 계산 결과")

                            res1, res2, res3 = st.columns(3)
                            with res1:
                                st.metric("리스크 금액", f"${risk_dollar:,.0f}",
                                          f"계좌의 {risk_pct}%")
                            with res2:
                                color_warn = pos_pct > 30
                                st.metric(
                                    "권장 주수",
                                    f"{shares_atr:,} 주",
                                    f"포지션 ${pos_value:,.0f} ({pos_pct:.1f}%)"
                                )
                            with res3:
                                st.metric("현재가 기준 매수금", f"${pos_value:,.0f}",
                                          f"계좌 비중 {pos_pct:.1f}%")

                            # 과집중 경고
                            if pos_pct > 25:
                                st.error(
                                    f"⚠️ **포지션 비중 {pos_pct:.1f}% — 과집중 주의**\n\n"
                                    f"단일 종목 권장 한도: 계좌의 20~25% 이하\n"
                                    f"리스크 %를 낮추거나 계좌 금액 재확인 필요"
                                )
                            elif pos_pct > 15:
                                st.warning(f"🟡 포지션 비중 {pos_pct:.1f}% — 적정 범위 상단")
                            else:
                                st.success(f"✅ 포지션 비중 {pos_pct:.1f}% — 적정")

                            # 손절 / 목표가 시나리오 테이블
                            st.markdown("##### 🗂️ 시나리오 테이블")
                            scenario_data = {
                                "구분": [
                                    "1.0 ATR 손절 (타이트)",
                                    "2.0 ATR 손절 (보통)",
                                    "★ 3.0 ATR 재난손절 (MR 권장)",
                                    "─────",
                                    "R:R 2배 목표 (1ATR 기준)",
                                    "R:R 3배 목표 (1ATR 기준)",
                                ],
                                "가격": [
                                    f"${curr - atr_val:.2f}",
                                    f"${curr - atr_val * 2:.2f}",
                                    f"${curr - atr_val * 3:.2f}",
                                    "─",
                                    f"${tgt_2r:.2f}",
                                    f"${tgt_3r:.2f}",
                                ],
                                "현가 대비": [
                                    f"−{atr_pct:.1f}%",
                                    f"−{atr_pct*2:.1f}%",
                                    f"−{atr_pct*3:.1f}%",
                                    "─",
                                    f"+{atr_pct*2:.1f}%",
                                    f"+{atr_pct*3:.1f}%",
                                ],
                                "예상 손익 (해당 주수)": [
                                    f"−${atr_val*shares_atr:,.0f}",
                                    f"−${atr_val*2*shares_atr:,.0f}",
                                    f"−${atr_val*3*shares_atr:,.0f}",
                                    "─",
                                    f"+${atr_val*2*shares_atr:,.0f}",
                                    f"+${atr_val*3*shares_atr:,.0f}",
                                ],
                            }
                            st.dataframe(
                                pd.DataFrame(scenario_data),
                                use_container_width=True,
                                hide_index=True
                            )

                            with st.expander("📖 ATR 포지션 사이징 원리"):
                                st.markdown(f"""
    **공식**: 주수 = 리스크 금액 ÷ ATR(14)

    | 항목 | 값 |
    |---|---|
    | ATR(14) | ${atr_val:.2f} (일평균 변동폭) |
    | 리스크 금액 | 계좌 ${account_size:,} × {risk_pct}% = ${risk_dollar:,.0f} |
    | 권장 주수 | ${risk_dollar:,.0f} ÷ ${atr_val:.2f} = **{shares_atr}주** |

    **왜 ATR인가**: 고정 % 손절은 변동성이 큰 종목에서 너무 자주 털린다.  
    ATR은 "이 종목이 보통 하루에 얼마나 움직이는가"를 반영하므로,  
    변동성이 큰 종목은 주수를 줄이고 조용한 종목은 주수를 늘려 **리스크를 균일하게** 유지한다.

    **포지션 비중 가이드**:  
    - 단일 종목 최대: 계좌의 25% 이하 권장  
    - 동시 보유 종목 수: 계좌 규모에 따라 3~6개 분산  
    - 리스크 1%는 20번 연속 손절해도 계좌의 18%만 손실 (복리 기준)
                                """)
                        else:
                            st.warning("⚠️ ATR 계산 불가 — 데이터 부족 (최소 15일 이상 필요)")

    st.divider()



    # ══════════════════════════════════════════════════════════
    # ⑥ 핵심 체크리스트
    # ══════════════════════════════════════════════════════════
    st.markdown("### 📋 진입 체크리스트")

    st.markdown("**🔵 공통 (MOM + MR 모두)**")
    st.markdown("""
    □ SPY + QQQ 신호등 초록?  
    □ VIX 25 이하?  
    □ 이벤트 없음?  
    □ 종목 SMA200 위?  
    □ 종목 SMA50 위?  
    □ RSI(14) 60 미만? (과매수 아님)  
    □ RVOL 전략 기준 충족? (MOM > 1.2 / MR < 1.2)  
    □ **ATR 포지션 사이징 완료?** (계좌 × 리스크% ÷ ATR → 주수 확정)  
    □ 손절가 설정 완료? (1차 RSI(2)>70 익절 / 2차 10일 타임스탑 / 3차 3ATR 재난손절)  
    """)

    st.markdown("**🟠 MR 전용 추가 체크 (APEX 2.0 핵심)**")
    st.markdown("""
    □ RSI(2) ≤ 15?  
    □ BB 하단 터치 (BB하단 ±0.5% 이내)?  
    □ SPY RSI(2) > 10? (시장 급락 아님)  
    □ 어닝 발표 3일 이내 아님? ← 종목 체크리스트에서 자동 판정  
    → 공통 + MR 전용 전부 ✅면 진입
    """)

    st.markdown("**🟢 MOM 전용 추가 체크**")
    st.markdown("""
    □ RSI(2) 80 미만? (단기 과열 아님)  
    □ BB 상단 근접 아님? (추격 진입 위험 확인)  
    □ Bull Regime 확인? (SPY > SMA200)  
    □ **SMA200 상승 중?** (20일 기준 방향성) ← 자동 판정  
    □ **SEPA 정렬?** (SMA50 > SMA150 > SMA200) ← 자동 판정  
    □ **52주 고점 대비 −25% 이내?** ← 자동 판정  
    □ **52주 저점 대비 +30% 이상?** ← 자동 판정  
    → 공통 + MOM 전용 전부 ✅면 진입
    """)

    st.markdown("**📌 청산 규칙 (백테스트 검증)**")
    st.markdown("""
    | | MR (평균회귀) | MOM (모멘텀) |
    |---|---|---|
    | ①익절 | RSI(2)>70 매도 | **+8% 도달 시 매도** |
    | ②타임스탑 | 최대 **10일** | 최대 **15일** |
    | ③재난손절 | 진입가−3ATR | **없음** (성과 저하) |
    """)

# ──────────────────────────────────────────
# TAB 3: 보유 종목 모니터
# ──────────────────────────────────────────
with tab_hold:
    st.markdown("### 📌 보유 종목 모니터")
    st.caption("보유 중인 종목의 청산 조건만 체크 — 스크리너(진입용)와 별개")

    st.info("💡 **스크리너에서 종목이 사라졌다 = 팔아라가 아닙니다.**\n\n"
            "스크리너는 진입용이고, 청산은 아래 규칙으로만 판단하세요.")

    # 사용자 입력
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
            try:
                hdf = yf.download(h_ticker, period="60d", progress=False)
                if hdf.empty or len(hdf) < 5:
                    st.error(f"❌ {h_ticker} 데이터 없음")
                else:
                    if isinstance(hdf.columns, pd.MultiIndex):
                        hdf.columns = hdf.columns.get_level_values(0)

                    h_close = hdf["Close"]
                    h_high = hdf["High"]
                    h_low = hdf["Low"]
                    h_curr = float(h_close.iloc[-1])
                    h_pnl = (h_curr - h_entry_price) / h_entry_price * 100

                    # RSI(2)
                    hd2 = h_close.diff()
                    hg2 = hd2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                    hl2 = (-hd2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
                    h_rsi2 = float((100 - 100/(1 + hg2/hl2.replace(0, 1e-10))).iloc[-1])

                    # RSI(14)
                    hd14 = h_close.diff()
                    hg14 = hd14.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    hl14 = (-hd14.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
                    h_rsi14 = float((100 - 100/(1 + hg14/hl14.replace(0, 1e-10))).iloc[-1])

                    # ATR(14)
                    h_tr = pd.concat([
                        h_high - h_low,
                        (h_high - h_close.shift(1)).abs(),
                        (h_low - h_close.shift(1)).abs()
                    ], axis=1).max(axis=1)
                    h_atr = float(h_tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().iloc[-1])

                    # 보유 일수
                    h_hold_days = (datetime.date.today() - h_entry_date).days

                    # 3ATR 손절가
                    h_stop_3atr = h_entry_price - 3 * h_atr

                    is_mr = h_mode == "MR (평균회귀)"

                    # ── 현황 표시 ──
                    st.divider()
                    st.markdown(f"#### {h_ticker} 보유 현황")

                    hm1, hm2, hm3, hm4 = st.columns(4)
                    with hm1:
                        color = "normal" if h_pnl >= 0 else "inverse"
                        st.metric("현재가", f"${h_curr:.2f}", f"{h_pnl:+.1f}%", delta_color=color)
                    with hm2:
                        st.metric("보유 일수", f"{h_hold_days}일")
                    with hm3:
                        st.metric("RSI(2)", f"{h_rsi2:.1f}")
                    with hm4:
                        st.metric("RSI(14)", f"{h_rsi14:.1f}")

                    # ── 청산 조건 체크 ──
                    st.divider()
                    st.markdown("#### 🚦 청산 신호 판정")

                    sell_signals = []

                    if is_mr:
                        # MR 청산: ①RSI(2)>70 ②10일 타임스탑 ③3ATR 재난손절 ④상대적 약세
                        tp_hit   = h_rsi2 > 70
                        time_hit = h_hold_days >= 10
                        stop_hit = h_curr <= h_stop_3atr

                        # ④ 상대적 약세 판단 — 당일 SPY 등락 vs 종목 등락 비교
                        try:
                            spy_today = yf.Ticker("SPY").history(period="2d", interval="1d")
                            spy_chg = float(spy_today["Close"].pct_change().iloc[-1] * 100) if len(spy_today) >= 2 else 0
                            stk_today = yf.Ticker(h_ticker).history(period="2d", interval="1d")
                            stk_chg = float(stk_today["Close"].pct_change().iloc[-1] * 100) if len(stk_today) >= 2 else 0
                            relative_weak = spy_chg >= 2.0 and stk_chg <= -1.0
                        except Exception:
                            spy_chg, stk_chg, relative_weak = 0, 0, False

                        s1, s2, s3 = st.columns(3)
                        with s1:
                            if tp_hit:
                                st.error(f"🔴 **①익절 신호**\n\nRSI(2) = {h_rsi2:.1f} > 70\n**매도 실행**")
                                sell_signals.append("RSI(2)>70 익절")
                            else:
                                st.success(f"🟢 ①익절 대기\n\nRSI(2) = {h_rsi2:.1f}\n70 미만 → 홀드")
                        with s2:
                            if time_hit:
                                st.error(f"🔴 **②타임스탑**\n\n보유 {h_hold_days}일 ≥ 10일\n**매도 실행**")
                                sell_signals.append("10일 타임스탑")
                            else:
                                st.success(f"🟢 ②타임스탑 대기\n\n보유 {h_hold_days}일\n{10 - h_hold_days}일 남음")
                        with s3:
                            if stop_hit:
                                st.error(f"🔴 **③재난손절**\n\n현가 ${h_curr:.2f} ≤ ${h_stop_3atr:.2f}\n**즉시 매도**")
                                sell_signals.append("3ATR 재난손절")
                            else:
                                st.success(f"🟢 ③재난손절 안전\n\n현가 ${h_curr:.2f}\n손절선 ${h_stop_3atr:.2f}")

                        # ④ 상대적 약세 경고 — 별도 표시
                        if relative_weak:
                            st.warning(
                                f"⚠️ **④ 상대적 약세 경고**\n\n"
                                f"SPY 당일 {spy_chg:+.1f}% 상승인데 {h_ticker} {stk_chg:+.1f}%\n"
                                f"지수 오르는데 종목이 빠짐 → **청산 강력 검토**"
                            )
                            sell_signals.append("상대적 약세")
                    else:
                        # MOM 청산: ①+8% 익절 ②15일 타임스탑
                        tp_hit = h_pnl >= 8.0
                        time_hit = h_hold_days >= 15

                        s1, s2 = st.columns(2)
                        with s1:
                            if tp_hit:
                                st.error(f"🔴 **①익절 신호**\n\n수익률 {h_pnl:+.1f}% ≥ +8%\n**매도 실행**")
                                sell_signals.append("+8% 익절")
                            else:
                                st.success(f"🟢 ①익절 대기\n\n수익률 {h_pnl:+.1f}%\n목표 +8% (${h_entry_price * 1.08:.2f})")
                        with s2:
                            if time_hit:
                                st.error(f"🔴 **②타임스탑**\n\n보유 {h_hold_days}일 ≥ 15일\n**매도 실행**")
                                sell_signals.append("15일 타임스탑")
                            else:
                                st.success(f"🟢 ②타임스탑 대기\n\n보유 {h_hold_days}일\n{15 - h_hold_days}일 남음")

                    # ── 최종 판정 ──
                    st.divider()
                    if sell_signals:
                        st.markdown(f"""
    <div style="background:#3d1a1a;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🔴</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#FF5252">매도 — {' + '.join(sell_signals)}</div>
        <div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | 수익률 {h_pnl:+.1f}% | 보유 {h_hold_days}일</div>
    </div>
    """, unsafe_allow_html=True)
                    else:
                        st.markdown(f"""
    <div style="background:#1a4731;border-radius:16px;padding:20px;text-align:center;margin:8px 0">
        <div style="font-size:3rem">🟢</div>
        <div style="font-size:1.6rem;font-weight:bold;color:#00C853">홀드 — 청산 조건 없음</div>
        <div style="color:#aaa;margin-top:8px">{h_ticker} ${h_curr:.2f} | 수익률 {h_pnl:+.1f}% | 보유 {h_hold_days}일</div>
    </div>
    """, unsafe_allow_html=True)

            except Exception as e:
                st.error(f"❌ 오류: {e}")
