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
            }
        else:
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "RSI (14)": "Oversold (40)",
                "Average Volume": "Over 500K",
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
        sentiment = get_social_sentiment(ticker)

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
                "SMA200 위 (종목)": price > s200,
                "RSI(2) ≤ 15": rsi2_v <= 15,
                "어닝 3일내 없음": not earn["within_3d"],
                "SPY RSI(2) > 10": spy_rsi2_val > 10,
            }
            preferred = {
                "BB 하단 터치": price <= bb_low_v * 1.005,
                "RVOL < 1.2": rvol < 1.2,
                "연속 하락 3일+": consec >= 3,
                "감성 45%+": sentiment is not None and sentiment >= 45,
                "VIX ≤ 25": vix_ok_val,
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
            "sentiment": sentiment,
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

# ══════════════════════════════════════════════════════════════
# 탭 분리: Daily Report vs 수동 분석
# ══════════════════════════════════════════════════════════════

# SPY RSI(2) 계산 (Daily Report용)
_spy_hist_dr = yf.Ticker("SPY").history(period="30d", interval="1d")
_spy_d2 = _spy_hist_dr["Close"].diff()
_spy_g2 = _spy_d2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
_spy_l2 = (-_spy_d2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
_spy_rsi2_dr = float((100 - 100/(1 + _spy_g2/_spy_l2.replace(0, 1e-10))).iloc[-1])

# 레짐 판단
_spy_above_dr = spy_price is not None and spy_sma200 is not None and spy_price > spy_sma200
_qqq_above_dr = qqq_price is not None and qqq_sma200 is not None and qqq_price > qqq_sma200
if _spy_above_dr and _qqq_above_dr:
    _regime_dr = "STRONG_BULL"
elif _spy_above_dr or _qqq_above_dr:
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

tab_report, tab_manual = st.tabs(["📊 Daily Report (자동)", "🚦 신호등 + 수동 분석"])


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
    with rc1: st.metric("레짐", f"{_regime_emoji.get(_regime_dr, '⚪')} {_regime_dr}")
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
                        so = {"A":0,"B+":1,"B-":2,"FAIL":3}
                        results.sort(key=lambda x: (so.get(x["score"],9), x["rsi2"]))
                        st.session_state["dr_mr"] = results

            if "dr_mr" in st.session_state and st.session_state["dr_mr"]:
                results = st.session_state["dr_mr"]
                enterable = [r for r in results if r["score"] in ["A","B+"]]
                st.success(f"✅ 후보 {len(results)}개 | 진입 가능 **{len(enterable)}개**")

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
                        with m4: st.metric("감성", f"{r['sentiment'] or 'N/A'}%")

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
                            with g1: st.info(f"⏰ **매수**\n\n장 마감 30분전\nKST 05:30\n지정가 ${r['price']*0.998:.2f}")
                            with g2: st.error(f"🛑 **손절**\n\nSMA20 ${r['sma20']}\n({(r['sma20']/r['price']-1)*100:.1f}%)")
                            with g3: st.success(f"🎯 **익절**\n\nRSI(2)>70 시 매도\n2~5일 홀딩")
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
                        so = {"A":0,"B+":1,"B-":2,"FAIL":3}
                        results.sort(key=lambda x: (so.get(x["score"],9), -x.get("perf_3m",0)))
                        st.session_state["dr_mom"] = results

            if "dr_mom" in st.session_state and st.session_state["dr_mom"]:
                results = st.session_state["dr_mom"]
                enterable = [r for r in results if r["score"] in ["A","B+"]]
                st.success(f"✅ 후보 {len(results)}개 | 진입 가능 **{len(enterable)}개**")

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
                            with g1: st.info(f"⏰ **매수**\n\n장 개장 30분~1시간 후\nKST 23:00~23:30\n브레이크아웃 확인")
                            with g2: st.error(f"🛑 **손절**\n\nSMA20 ${r['sma20']}")
                            with g3: st.success(f"🎯 **익절**\n\n+8~12% 또는\nRSI(14)>75\n5~15일 홀딩")
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
                            4: ("🟢 추세 구조 최상", "4/4 — MOM 진입 최적 환경"),
                            3: ("🟡 추세 구조 양호", "3/4 — MOM 진입 가능, 세부 확인"),
                            2: ("🟠 추세 구조 혼조", "2/4 — MR 전략 또는 관망 검토"),
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

                        # ── 손절/목표가 + ATR 포지션 사이징 ──
                        st.divider()
                        st.markdown("#### 🛑 손절 / 목표가")
                        s20 = float(df60["SMA20"].iloc[-1]) if not pd.isna(df60["SMA20"].iloc[-1]) else None
                        tgt1 = curr * 1.03
                        tgt2 = curr * 1.07
                        sc1, sc2, sc3 = st.columns(3)
                        with sc1:
                            if s20:
                                stop_pct = (s20 - curr) / curr * 100
                                st.error(f"🛑 손절 (SMA20)\n${s20:.2f}\n({stop_pct:.1f}%)\n종가 이탈 시 청산")
                            else:
                                st.error("🛑 손절\nSMA20 계산 불가")
                        with sc2:
                            st.success(f"🎯 목표1\n${tgt1:.2f}\n(+3%)")
                        with sc3:
                            st.success(f"🎯 목표2\n${tgt2:.2f}\n(+7%)")
                        st.caption("⚠️ 손절 기준: SMA20 아래 종가 마감 시 청산 — 장중 노이즈에 흔들리지 말 것")

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
                                st.metric("1ATR 손절가", f"${curr - atr_val:.2f}", f"−{atr_pct:.1f}%")
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
                            stop_1atr    = curr - atr_val                        # 1 ATR 손절가
                            stop_2atr    = curr - atr_val * 0.5                  # 0.5 ATR 타이트 손절
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
                                    "0.5 ATR 손절 (타이트)",
                                    "1.0 ATR 손절 (기본)",
                                    "SMA20 손절 (추세기반)",
                                    "─────",
                                    "R:R 2배 목표 (1ATR 기준)",
                                    "R:R 3배 목표 (1ATR 기준)",
                                ],
                                "가격": [
                                    f"${stop_2atr:.2f}",
                                    f"${stop_1atr:.2f}",
                                    f"${s20:.2f}" if s20 else "계산불가",
                                    "─",
                                    f"${tgt_2r:.2f}",
                                    f"${tgt_3r:.2f}",
                                ],
                                "현가 대비": [
                                    f"−{(curr - stop_2atr)/curr*100:.1f}%",
                                    f"−{atr_pct:.1f}%",
                                    f"{(s20 - curr)/curr*100:.1f}%" if s20 else "─",
                                    "─",
                                    f"+{atr_pct*2:.1f}%",
                                    f"+{atr_pct*3:.1f}%",
                                ],
                                "예상 손익 (해당 주수)": [
                                    f"−${(curr - stop_2atr)*shares_atr:,.0f}",
                                    f"−${risk_dollar:,.0f}",
                                    f"−${(curr - s20)*shares_atr:,.0f}" if s20 else "─",
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
    # ⑦ 인트라데이 진입 타이밍 가이드
    # ORB / VWAP Reclaim / Episodic Pivot
    # ══════════════════════════════════════════════════════════
    st.markdown("### ⏱️ 인트라데이 진입 타이밍 가이드")
    st.caption(
        "일봉 스캔 완료 후 → 장 중 실시간 진입 타이밍 확인용 | "
        "TradingView 1분/5분봉 병행 사용 권장"
    )
    st.info(
        "**사용 순서**: 위 종목 스캐너로 후보 선정 → "
        "아래 3개 패턴 중 해당 패턴 탭 선택 → "
        "체크리스트 수동 확인 → 진입 여부 최종 판단"
    )

    tab_orb, tab_vwap, tab_ep = st.tabs([
        "📐 ORB (Opening Range Breakout)",
        "〰️ VWAP Reclaim",
        "🚀 Episodic Pivot (갭+뉴스)",
    ])

    # ──────────────────────────────────────────
    # TAB 1: ORB
    # ──────────────────────────────────────────
    with tab_orb:
        st.markdown("#### 📐 ORB — Opening Range Breakout")
        st.caption("갭+뉴스 종목의 장 초반 첫 5분/15분 고점 돌파 전략")

        st.markdown("**📌 진입 조건 체크리스트**")
        orb_checks = [
            ("프리마켓 거래량 전일 대비 3배 이상?",           "거래량 없는 갭은 가짜 신호"),
            ("뉴스/촉매 확인? (실적·FDA·계약·업그레이드)",    "촉매 없는 갭은 신뢰도 낮음"),
            ("갭 크기 3~15% 사이?",                           "갭 >15%는 Episodic Pivot 패턴으로 처리"),
            ("SPY/QQQ 장 초반 방향 확인 (하락 중 아님)?",     "시장 역풍 시 ORB 성공률 급감"),
            ("오프닝 레인지 확정 (첫 5분 또는 15분)?",        "고점·저점 가격 메모 필수"),
            ("오프닝 레인지 상단 돌파 + 거래량 급증?",        "거래량 동반 없는 돌파는 함정"),
            ("돌파 캔들이 양봉 + 꼬리 짧음?",                 "윗꼬리 긴 캔들은 매도 압력 신호"),
            ("VWAP 위에서 돌파 발생?",                        "VWAP 아래 돌파는 신뢰도 낮음"),
        ]
        for item, tip in orb_checks:
            col_c, col_t = st.columns([3, 2])
            with col_c:
                st.checkbox(item, key=f"orb_{item[:20]}")
            with col_t:
                st.caption(f"💡 {tip}")

        st.divider()
        st.markdown("**🎯 진입 / 손절 / 목표가**")
        oc1, oc2, oc3 = st.columns(3)
        with oc1:
            st.error("🛑 **손절**\n\nORB 저점 (오프닝 레인지 최저점)\n\n또는 VWAP 아래 종가 1분봉")
        with oc2:
            st.success("🎯 **목표1**\n\nR:R = 1:2\n\n(손절폭 × 2 위)")
        with oc3:
            st.success("🎯 **목표2**\n\n전일 고점 또는\nプレマーケット 고점")

        st.markdown("**⚡ 진입 타이밍 3단계**")
        st.markdown("""
    1. **장 시작 후 첫 5분 대기** — 오프닝 레인지(OR) 고점·저점 확정
    2. **OR 상단 돌파 순간** — 즉시 시장가 또는 돌파가 +0.1% 지정가
    3. **1분봉 저점 이탈 시** → 즉시 손절, 재진입 금지 (당일 해당 종목 종료)
    """)

        with st.expander("📖 ORB 성공률을 높이는 비공개 필터 (공개 자료 종합)"):
            st.markdown("""
    | 필터 | 기준 | 이유 |
    |---|---|---|
    | Float | 2천만 주 이하 선호 | 유동주식 적을수록 변동폭 크고 추세 지속 |
    | 섹터 강도 | 섹터 ETF 당일 상승 중 | 섹터 역풍 시 ORB 실패율 높음 |
    | VIX | 20 이하 | 고변동성 장세에서 ORB는 노이즈 많음 |
    | 갭 방향 | 갭상 종목만 | 갭하 ORB는 반발 매도 강해 위험 |
    | 시간대 | 장 시작 후 30분 이내 | 이후 ORB는 레인지 왜곡 가능성 |
            """)

    # ──────────────────────────────────────────
    # TAB 2: VWAP Reclaim
    # ──────────────────────────────────────────
    with tab_vwap:
        st.markdown("#### 〰️ VWAP Reclaim — VWAP 회복·지지 패턴")
        st.caption("기관·단타 모두가 보는 핵심 기준선 기반 추세 진입")

        st.markdown("**📌 두 가지 진입 방식**")
        vt1, vt2 = st.columns(2)
        with vt1:
            st.info("**방식 A: VWAP 상향 돌파형**\n\nVWAP 아래에 있던 종목이\nVWAP을 강하게 뚫고 올라올 때")
        with vt2:
            st.info("**방식 B: VWAP 지지 확인형**\n\n이미 VWAP 위에 있는 종목이\nVWAP까지 눌렸다가 재상승할 때")

        st.markdown("**📌 진입 조건 체크리스트**")
        vwap_checks = [
            ("VWAP 위치 확인 완료? (TradingView 1분봉)",      "VWAP은 장 중 실시간 계산 — 전일값 사용 금지"),
            ("VWAP 돌파 캔들 거래량 직전 평균 2배 이상?",     "거래량 없는 VWAP 돌파는 가짜 신호 확률 높음"),
            ("돌파 후 1~3분 VWAP 위 유지 확인?",              "즉시 되돌림 시 미결 진입 — 방식 A 핵심 확인"),
            ("VWAP 위 유지 중 직전 1분봉 고점 돌파?",         "3단계 확인: 돌파 → 유지 → 재돌파"),
            ("SPY 같은 시간대 하락 중 아님?",                 "SPY 역풍 시 VWAP reclaim 실패율 급증"),
            ("전일 종가 위에서 VWAP 돌파 발생?",              "전일 종가 아래 VWAP은 하락 추세 신호"),
        ]
        for item, tip in vwap_checks:
            col_c, col_t = st.columns([3, 2])
            with col_c:
                st.checkbox(item, key=f"vwap_{item[:20]}")
            with col_t:
                st.caption(f"💡 {tip}")

        st.divider()
        st.markdown("**🎯 진입 / 손절 / 목표가**")
        vc1, vc2, vc3 = st.columns(3)
        with vc1:
            st.error("🛑 **손절**\n\nVWAP 아래 1분봉 종가\n\n또는 진입 캔들 저점")
        with vc2:
            st.success("🎯 **목표1**\n\n당일 전고점\n\n또는 프리마켓 고점")
        with vc3:
            st.success("🎯 **목표2**\n\nR:R 1:2 이상\n\n(손절폭 × 2 위)")

        st.markdown("**⚡ Warrior Trading 방식 3단계 진입**")
        st.markdown("""
    1. **VWAP 상향 돌파** — 공격적 진입 (리스크 큼)
    2. **돌파 후 1분봉 미세 눌림** → 눌림 저점 지지 확인 후 진입 (기본)
    3. **5분봉 불플래그 상단 돌파** → 가장 안전한 진입 (모멘텀 확인 후)
    """)

        with st.expander("📖 VWAP 패턴 심화 — Anchored VWAP (AVWAP)"):
            st.markdown("""
    **Brian Shannon의 AVWAP**: 특정 이벤트 날짜에 VWAP 앵커를 걸어 계산

    | 앵커 기준 | 의미 |
    |---|---|
    | 실적 발표일 | 실적 이후 평균 매수가 |
    | 52주 저점일 | 바닥 이후 매집 평균가 |
    | 갭 발생일 | 갭 이후 시장 참여자 평균가 |
    | 연초(1월 1일) | 연중 매수자 평균가 |

    **AVWAP 진입 시나리오**:  
    뉴스 갭 → 하루이틀 눌림 → 이벤트 앵커 AVWAP 근처에서 매수세 재유입 → 진입  
    (일반 VWAP과 달리 다음날에도 유효한 기준선)
            """)

    # ──────────────────────────────────────────
    # TAB 3: Episodic Pivot
    # ──────────────────────────────────────────
    with tab_ep:
        st.markdown("#### 🚀 Episodic Pivot — 갭+뉴스 펀더멘털 재평가")
        st.caption("실적 서프라이즈·가이던스 상향·강한 뉴스로 갭이 크게 뜬 날의 진입 전략")
        st.warning("⚠️ ORB보다 갭이 크고 (15%+) 펀더멘털 재평가가 동반되는 경우 사용")

        st.markdown("**📌 진입 조건 체크리스트**")
        ep_checks = [
            ("갭 크기 10% 이상?",                              "갭 <10%는 ORB 패턴으로 처리"),
            ("촉매 종류 확인? (실적·FDA·인수합병·계약)",       "PR·언론 추측성 뉴스는 신뢰도 낮음"),
            ("프리마켓 거래량 평소 5배 이상?",                 "기관 참여 증거 — 필수 조건"),
            ("오프닝 레인지(첫 5분) 고점 돌파?",              "갭 뜬 날 첫 5분 고점 = 핵심 저항선"),
            ("장 시작 후 첫 5분 약해지지 않음?",              "'뜬 뒤 바로 무너짐' = 실패 패턴"),
            ("섹터 전체 강세 동반?",                           "섹터 약세 시 개별주 Pivot도 흘러내림"),
            ("갭 발생 전 압축(눌림) 패턴 있었음?",            "Qullamaggie: 기존 추세 + Pivot이 최강"),
            ("시초가 캔들 저점이 손절로 허용 가능한 수준?",   "초기 캔들 저점 = 손절선 — 너무 넓으면 패스"),
        ]
        for item, tip in ep_checks:
            col_c, col_t = st.columns([3, 2])
            with col_c:
                st.checkbox(item, key=f"ep_{item[:20]}")
            with col_t:
                st.caption(f"💡 {tip}")

        st.divider()
        st.markdown("**🎯 진입 / 손절 / 목표가**")
        ec1, ec2, ec3 = st.columns(3)
        with ec1:
            st.error("🛑 **손절**\n\n시초 캔들 저점\n\n또는 당일 저점\n\n(갭 메우기 시작 = 즉시 청산)")
        with ec2:
            st.success("🎯 **목표1**\n\n오프닝 레인지 상단\n\n돌파 후 R:R 1:2")
        with ec3:
            st.success("🎯 **목표2**\n\n10일선·20일선 종가\n\n이탈까지 보유\n\n(Qullamaggie 방식)")

        st.markdown("**⚡ Episodic Pivot 진입 3단계**")
        st.markdown("""
    1. **장 시작 전**: 뉴스·갭 크기·프리마켓 거래량 확인 → 후보 선정
    2. **장 시작 후 첫 5분 관망**: 시초가 캔들 방향 확인 (위로 치는가 vs 흘러내리는가)
    3. **첫 5분 고점 돌파 + 거래량 급증 시** → 시장가 진입 / 손절: 시초 캔들 저점
    """)

        st.markdown("**🔴 Episodic Pivot 실패 패턴 — 즉시 청산**")
        st.error("""
    • 갭 뜬 후 첫 5분 캔들이 음봉 (매도 압력이 더 강함)  
    • VWAP 아래로 재진입 (기관 평단 아래 = 세력 이탈)  
    • 오프닝 레인지 저점 이탈 (구조 붕괴)  
    • 갭 50% 이상 메워짐 (펀더멘털 재평가 실패 신호)
    """)

        with st.expander("📖 Episodic Pivot vs ORB 비교"):
            st.markdown("""
    | 구분 | ORB | Episodic Pivot |
    |---|---|---|
    | 갭 크기 | 3~15% | 10%+ (대형 갭) |
    | 촉매 강도 | 보통 | 강함 (실적·FDA·M&A) |
    | 프리마켓 거래량 | 3배 이상 | 5배 이상 |
    | 보유 기간 | 당일 | 당일~수일 (스윙 가능) |
    | 손절 기준 | ORB 저점 | 시초 캔들 저점 |
    | 목표가 | R:R 1:2 | 10일/20일선 트레일링 |
    | 핵심 원리 | 기술적 돌파 | 펀더멘털 재평가 |
            """)

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
    □ 소셜 감성지수 45% 이상?  
    □ **ATR 포지션 사이징 완료?** (계좌 × 리스크% ÷ ATR → 주수 확정)  
    □ 손절가 설정 완료? (SMA20 아래 종가 마감 시 청산)  
    □ **인트라데이 진입 패턴 확인?** (위 ⑦ 가이드: ORB / VWAP / EP 중 해당 패턴 체크)  
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

    st.error("**손절 원칙: SMA20 아래 종가 마감 = 즉시 청산 / 장중 노이즈에 흔들리지 말 것**")
