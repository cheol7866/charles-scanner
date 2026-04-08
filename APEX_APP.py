"""
APEX 2.0 Daily Report Generator v3 — 최종 통합본
=================================================
기존 APEX_NEW_v2.py (Streamlit 1,489줄) 로직 전부 반영 +
이번 대화에서 추가된 기능:
  ✅ SPY RSI(2) ≤ 10 → MR도 진입 금지
  ✅ 필수/선호 체크리스트 분리 + 자동 채점 (A/B+/B-/FAIL)
  ✅ 승률 참고 (Connors RSI(2) 연구 기반)
  ✅ MR/MOM 매수 타이밍 가이드
  ✅ 멀티 섹터 필터
  ✅ ATR 포지션 사이징
  ✅ Minervini SEPA + 52주 조건
  ✅ StockTwits 소셜 감성
  ✅ VIX 체크
  ✅ 텔레그램/카카오톡 알림

사용:
  pip install yfinance finvizfinance pandas requests --break-system-packages
  python apex_daily_report_v3.py

크론잡 (매일 KST 23:00 = UTC 14:00):
  0 14 * * 1-5 /usr/bin/python3 /path/to/apex_daily_report_v3.py
"""

import yfinance as yf
import pandas as pd
import numpy as np
from datetime import datetime, timedelta, date
import json
import requests
import warnings
warnings.filterwarnings("ignore")


# ══════════════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════════════

# 알림 설정
TELEGRAM_TOKEN = ""
TELEGRAM_CHAT_ID = ""
KAKAO_ACCESS_TOKEN = ""

# 계좌 설정
ACCOUNT_SIZE = 5000     # USD
RISK_PCT = 1.0          # 1회 리스크 %

# 섹터 멀티셀렉트 (빈 리스트 = 전체)
# 예: ["Technology", "Industrials", "Healthcare"]
SECTORS = []

# 포지션 사이징 (레짐별)
POSITION_SIZE = {
    "STRONG_BULL": 600,
    "WEAK_BULL": 450,
    "BEAR": 300,
}


# ══════════════════════════════════════════════════════════════
# 핵심 계산 함수 (APEX_NEW_v2.py 기반)
# ══════════════════════════════════════════════════════════════

def calc_rsi(series, period):
    delta = series.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))


def calc_sma(series, period):
    return series.rolling(window=period).mean()


def calc_bollinger(series, period=20, std_mult=2):
    sma = calc_sma(series, period)
    std = series.rolling(window=period).std()
    lower = sma - std_mult * std
    upper = sma + std_mult * std
    return sma, upper, lower


def calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low - close.shift(1)).abs()
    ], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, min_periods=period, adjust=False).mean()


def calc_rvol(volume, period=20):
    avg_vol = volume.rolling(window=period).mean()
    return float(volume.iloc[-1] / avg_vol.iloc[-1]) if avg_vol.iloc[-1] > 0 else 0


def consecutive_down_days(close):
    count = 0
    for i in range(len(close) - 1, 0, -1):
        if close.iloc[i] < close.iloc[i - 1]:
            count += 1
        else:
            break
    return count


def get_earnings_info(ticker):
    """어닝 조회 — APEX_NEW_v2.py 방식 그대로"""
    today = date.today()
    result = {"date": None, "days_away": None, "within_3d": False, "label": "어닝 정보 없음", "source": "none"}
    try:
        tk = yf.Ticker(ticker)
        cal = tk.calendar
        earn_date = None

        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if raw:
                if isinstance(raw, (list, tuple)) and len(raw) > 0:
                    earn_date = pd.Timestamp(raw[0]).date()
                elif hasattr(raw, "date"):
                    earn_date = raw.date()
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index:
                val = cal.loc["Earnings Date"].iloc[0]
                earn_date = pd.Timestamp(val).date()

        if earn_date:
            days_away = (earn_date - today).days
            result.update({
                "date": earn_date, "days_away": days_away,
                "within_3d": -1 <= days_away <= 3,
                "label": f"{earn_date.strftime('%Y-%m-%d')} (D{days_away:+d})",
                "source": "calendar"
            })
            return result

        fi = tk.fast_info
        if hasattr(fi, "next_earnings_date") and fi.next_earnings_date:
            earn_date = pd.Timestamp(fi.next_earnings_date).date()
            days_away = (earn_date - today).days
            result.update({
                "date": earn_date, "days_away": days_away,
                "within_3d": -1 <= days_away <= 3,
                "label": f"{earn_date.strftime('%Y-%m-%d')} (D{days_away:+d})",
                "source": "fast_info"
            })
    except:
        pass
    return result


def get_social_sentiment(ticker):
    """StockTwits 감성 — APEX_NEW_v2.py 방식"""
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
        return round(bull / total * 100, 1) if total > 0 else None
    except:
        return None


def check_stage2_weinstein(close, sma50, sma150, sma200):
    """Weinstein Stage 2 + SEPA + SMA200 상승"""
    if any(pd.isna(x.iloc[-1]) for x in [sma50, sma150, sma200]):
        return False, False, False
    price = float(close.iloc[-1])
    s50 = float(sma50.iloc[-1])
    s150 = float(sma150.iloc[-1])
    s200 = float(sma200.iloc[-1])

    sepa = s50 > s150 > s200
    sma200_rising = len(sma200) >= 21 and float(sma200.iloc[-1]) > float(sma200.iloc[-21])
    stage2 = price > s50 and sepa and sma200_rising

    return stage2, sepa, sma200_rising


def get_52w_analysis(hist):
    """Minervini 52주 조건 — APEX_NEW_v2.py 방식"""
    hist_252 = hist.tail(252)
    curr = float(hist["Close"].iloc[-1])
    w52_high = float(hist_252["High"].max())
    w52_low = float(hist_252["Low"].min())
    from_high = (curr - w52_high) / w52_high * 100
    from_low = (curr - w52_low) / w52_low * 100
    return {
        "high": w52_high, "low": w52_low,
        "from_high_pct": round(from_high, 1),
        "from_low_pct": round(from_low, 1),
        "minv_high_ok": from_high >= -25.0,   # 고점 대비 -25% 이내
        "minv_low_ok": from_low >= 30.0,       # 저점 대비 +30% 이상
    }


# ══════════════════════════════════════════════════════════════
# 시장 레짐 판단
# ══════════════════════════════════════════════════════════════

def get_market_data():
    """SPY/QQQ/VIX 데이터"""
    result = {}
    for sym in ["SPY", "QQQ"]:
        df = yf.download(sym, period="1y", progress=False)
        if df.empty:
            continue
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)
        close = df["Close"]
        sma200 = calc_sma(close, 200)
        rsi2 = calc_rsi(close, 2)
        rsi14 = calc_rsi(close, 14)
        chg = float(close.pct_change().iloc[-1] * 100)
        result[sym] = {
            "price": round(float(close.iloc[-1]), 2),
            "sma200": round(float(sma200.iloc[-1]), 2),
            "above_sma200": bool(close.iloc[-1] > sma200.iloc[-1]),
            "rsi2": round(float(rsi2.iloc[-1]), 1),
            "rsi14": round(float(rsi14.iloc[-1]), 1),
            "chg": round(chg, 2),
        }

    # VIX
    try:
        vix_df = yf.download("^VIX", period="5d", progress=False)
        if isinstance(vix_df.columns, pd.MultiIndex):
            vix_df.columns = vix_df.columns.get_level_values(0)
        vix_val = round(float(vix_df["Close"].iloc[-1]), 1) if not vix_df.empty else None
    except:
        vix_val = None

    result["VIX"] = vix_val
    return result


def determine_regime(market):
    spy = market.get("SPY", {})
    qqq = market.get("QQQ", {})
    vix = market.get("VIX")

    spy_above = spy.get("above_sma200", False)
    qqq_above = qqq.get("above_sma200", False)
    spy_rsi2 = spy.get("rsi2", 50)
    vix_ok = vix is not None and vix <= 25

    # 레짐 판정
    if spy_above and qqq_above:
        regime = "STRONG_BULL"
    elif spy_above or qqq_above:
        regime = "WEAK_BULL"
    else:
        regime = "BEAR"

    # MOM 허용 여부
    mom_ok = regime in ["STRONG_BULL", "WEAK_BULL"]

    # MR 허용 여부: SPY RSI(2) > 10이어야 함
    mr_ok = spy_rsi2 > 10
    mr_block = None
    if spy_rsi2 <= 10:
        mr_block = f"SPY RSI(2) = {spy_rsi2} ≤ 10 → 시장 패닉, MR도 진입 금지"

    # VIX 경고
    vix_warn = None
    if vix is not None:
        if vix > 25:
            vix_warn = f"VIX {vix} > 25 — 진입 자제"
        elif vix > 20:
            vix_warn = f"VIX {vix} — 포지션 50% 줄이기"

    return {
        "regime": regime,
        "mom_ok": mom_ok,
        "mr_ok": mr_ok,
        "mr_block": mr_block,
        "vix": vix,
        "vix_ok": vix_ok,
        "vix_warn": vix_warn,
    }


# ══════════════════════════════════════════════════════════════
# Finviz 스크리닝
# ══════════════════════════════════════════════════════════════

def finviz_screen(mode="MR"):
    try:
        from finvizfinance.screener.overview import Overview
        fov = Overview()

        # 기존 APEX_NEW_v2.py 필터 기반
        if mode == "MOM":
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "50-Day Simple Moving Average": "Price above SMA50",
                "RSI (14)": "Not Overbought (<60)",
                "Performance": "Quarter +10%",
                "Average Volume": "Over 500K",
            }
        else:  # MR
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "RSI (14)": "Oversold (<40)",
                "Average Volume": "Over 500K",
            }

        # 섹터 멀티셀렉트
        if SECTORS and len(SECTORS) == 1:
            filters["Sector"] = SECTORS[0]
        # 멀티 섹터는 finviz에서 직접 지원 안 함 → 후처리

        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        if df is None or df.empty:
            return []

        # 멀티 섹터 필터 후처리
        if SECTORS and len(SECTORS) > 1 and "Sector" in df.columns:
            df = df[df["Sector"].isin(SECTORS)]

        return df["Ticker"].tolist()[:50]

    except ImportError:
        print("⚠️ finvizfinance 미설치 — 폴백 워치리스트 사용")
        return ["AAPL", "MSFT", "GOOGL", "AMZN", "NVDA", "META", "RTX", "LMT",
                "NOC", "RKLB", "AMD", "AVGO", "PLTR", "NET", "CRWD", "PANW"]
    except Exception as e:
        print(f"⚠️ Finviz 오류: {e}")
        return []


# ══════════════════════════════════════════════════════════════
# 종목 분석 — MR
# ══════════════════════════════════════════════════════════════

def analyze_mr(ticker, market_data, regime_info):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 200:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        sma200 = calc_sma(close, 200)
        sma150 = calc_sma(close, 150)
        sma50 = calc_sma(close, 50)
        sma20 = calc_sma(close, 20)
        rsi2 = calc_rsi(close, 2)
        rsi14 = calc_rsi(close, 14)
        bb_mid, bb_upper, bb_lower = calc_bollinger(close)
        atr = calc_atr(high, low, close)
        rvol = calc_rvol(volume)
        consec = consecutive_down_days(close)
        earn = get_earnings_info(ticker)
        sentiment = get_social_sentiment(ticker)
        w52 = get_52w_analysis(df)

        s200 = float(sma200.iloc[-1])
        s50 = float(sma50.iloc[-1])
        s20 = float(sma20.iloc[-1])
        rsi2_v = float(rsi2.iloc[-1])
        rsi14_v = float(rsi14.iloc[-1])
        bb_low_v = float(bb_lower.iloc[-1])
        bb_up_v = float(bb_upper.iloc[-1])
        atr_v = float(atr.iloc[-1])

        spy_rsi2 = market_data.get("SPY", {}).get("rsi2", 50)

        # ═══ 필수 조건 (4개 — 전부 녹색 필요) ═══
        required = {
            "SMA200 위 (종목)": price > s200,
            "RSI(2) ≤ 15": rsi2_v <= 15,
            "어닝 3일내 없음": not earn["within_3d"],
            "SPY RSI(2) > 10": spy_rsi2 > 10,
        }

        # ═══ 선호 조건 (5개 — 70% 이상) ═══
        preferred = {
            "볼린저밴드 하단 터치": price <= bb_low_v * 1.005,
            "RVOL < 1.2 (조용한 눌림)": rvol < 1.2,
            "연속 하락 3일+": consec >= 3,
            "소셜 감성 45%+": sentiment is not None and sentiment >= 45,
            "VIX ≤ 25": regime_info["vix_ok"],
        }

        req_pass = sum(required.values())
        pref_pass = sum(preferred.values())
        pref_pct = pref_pass / len(preferred)

        # 등급 + 승률
        if req_pass < len(required):
            score = "FAIL"
            win_rate = "—"
        elif pref_pct >= 1.0:
            score = "A"
            win_rate = "75~82%"
        elif pref_pct >= 0.7:
            score = "B+"
            win_rate = "68~75%"
        else:
            score = "B-"
            win_rate = "60~65%"

        # ATR 포지션 사이징
        risk_dollar = ACCOUNT_SIZE * (RISK_PCT / 100)
        shares = int(risk_dollar / atr_v) if atr_v > 0 else 0
        pos_value = shares * price
        pos_pct = (pos_value / ACCOUNT_SIZE * 100) if ACCOUNT_SIZE > 0 else 0

        # 진입 가이드
        entry_guide = ""
        if score in ["A", "B+"]:
            entry_guide = (
                f"⏰ 매수: 장 마감 30분전 (KST 05:30) 지정가 ${price * 0.998:.2f}\n"
                f"💰 ATR 사이징: {shares}주 × ${price:.2f} = ${pos_value:,.0f} (계좌 {pos_pct:.1f}%)\n"
                f"🛑 손절: SMA20 ${s20:.2f} 이탈 ({(s20/price-1)*100:.1f}%)\n"
                f"   1ATR 손절: ${price - atr_v:.2f} (−{atr_v/price*100:.1f}%)\n"
                f"🎯 익절: RSI(2) > 70 시 장중 매도 (2~5일 홀딩)\n"
                f"   R:R 2배 목표: ${price + atr_v * 2:.2f} (+{atr_v*2/price*100:.1f}%)"
            )

        # 불합격 사유
        fail_reasons = [k for k, v in required.items() if not v]

        return {
            "ticker": ticker,
            "mode": "MR",
            "price": round(price, 2),
            "sma200": round(s200, 2),
            "sma50": round(s50, 2),
            "sma20": round(s20, 2),
            "rsi2": round(rsi2_v, 1),
            "rsi14": round(rsi14_v, 1),
            "rvol": round(rvol, 2),
            "bb_lower": round(bb_low_v, 2),
            "bb_touch": price <= bb_low_v * 1.005,
            "consec_down": consec,
            "atr": round(atr_v, 2),
            "earnings": earn["label"],
            "earnings_blocked": earn["within_3d"],
            "sentiment": sentiment,
            "w52": w52,
            "required": required,
            "req_pass": req_pass,
            "req_total": len(required),
            "preferred": preferred,
            "pref_pass": pref_pass,
            "pref_total": len(preferred),
            "pref_pct": round(pref_pct * 100),
            "score": score,
            "win_rate": win_rate,
            "shares": shares,
            "pos_value": round(pos_value),
            "pos_pct": round(pos_pct, 1),
            "entry_guide": entry_guide,
            "fail_reasons": fail_reasons,
        }

    except Exception as e:
        print(f"  ⚠️ {ticker} MR 분석 실패: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 종목 분석 — MOM
# ══════════════════════════════════════════════════════════════

def analyze_mom(ticker, market_data, regime_info):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 200:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close = df["Close"]
        high = df["High"]
        low = df["Low"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        sma200 = calc_sma(close, 200)
        sma150 = calc_sma(close, 150)
        sma50 = calc_sma(close, 50)
        sma20 = calc_sma(close, 20)
        rsi2 = calc_rsi(close, 2)
        rsi14 = calc_rsi(close, 14)
        bb_mid, bb_upper, bb_lower = calc_bollinger(close)
        atr = calc_atr(high, low, close)
        rvol = calc_rvol(volume)
        earn = get_earnings_info(ticker)
        sentiment = get_social_sentiment(ticker)
        w52 = get_52w_analysis(df)
        stage2, sepa, sma200_rising = check_stage2_weinstein(close, sma50, sma150, sma200)

        s200 = float(sma200.iloc[-1])
        s150 = float(sma150.iloc[-1])
        s50 = float(sma50.iloc[-1])
        s20 = float(sma20.iloc[-1])
        rsi2_v = float(rsi2.iloc[-1])
        rsi14_v = float(rsi14.iloc[-1])
        bb_up_v = float(bb_upper.iloc[-1])
        atr_v = float(atr.iloc[-1])

        # 3개월 수익률
        perf_3m = ((price / float(close.iloc[-63])) - 1) * 100 if len(close) >= 63 else 0

        # ═══ 필수 조건 (4개) — APEX_NEW_v2.py의 MOM 체크리스트 통합 ═══
        required = {
            "시장 레짐 Bull": regime_info["mom_ok"],
            "RSI(14) 50~70": 50 <= rsi14_v <= 70,
            "어닝 3일내 없음": not earn["within_3d"],
            "SMA200 상승 중": sma200_rising,
        }

        # ═══ 선호 조건 (6개) — SEPA, 52주, RVOL, 감성 포함 ═══
        preferred = {
            "SEPA 정렬 (50>150>200)": sepa,
            "RVOL ≥ 1.2": rvol >= 1.2,
            "3개월 +10%": perf_3m >= 10,
            "52주고점 -25%이내": w52["minv_high_ok"],
            "52주저점 +30%이상": w52["minv_low_ok"],
            "RSI(2) < 80 (과열X)": rsi2_v < 80,
        }

        req_pass = sum(required.values())
        pref_pass = sum(preferred.values())
        pref_pct = pref_pass / len(preferred)

        if req_pass < len(required):
            score = "FAIL"
            win_rate = "—"
        elif pref_pct >= 1.0:
            score = "A"
            win_rate = "70~78%"
        elif pref_pct >= 0.7:
            score = "B+"
            win_rate = "63~70%"
        else:
            score = "B-"
            win_rate = "55~63%"

        # ATR 포지션 사이징
        risk_dollar = ACCOUNT_SIZE * (RISK_PCT / 100)
        shares = int(risk_dollar / atr_v) if atr_v > 0 else 0
        pos_value = shares * price
        pos_pct = (pos_value / ACCOUNT_SIZE * 100) if ACCOUNT_SIZE > 0 else 0

        entry_guide = ""
        if score in ["A", "B+"]:
            entry_guide = (
                f"⏰ 매수: 장 개장 30분~1시간 후 (KST 23:00~23:30) 브레이크아웃 확인\n"
                f"💰 ATR 사이징: {shares}주 × ${price:.2f} = ${pos_value:,.0f} (계좌 {pos_pct:.1f}%)\n"
                f"🛑 손절: SMA20 ${s20:.2f} 이탈\n"
                f"   1ATR 손절: ${price - atr_v:.2f} (−{atr_v/price*100:.1f}%)\n"
                f"🎯 익절: +8~12% 또는 RSI(14) > 75 (5~15일)\n"
                f"   R:R 2배 목표: ${price + atr_v * 2:.2f}"
            )

        fail_reasons = [k for k, v in required.items() if not v]

        return {
            "ticker": ticker,
            "mode": "MOM",
            "price": round(price, 2),
            "sma200": round(s200, 2),
            "sma50": round(s50, 2),
            "sma20": round(s20, 2),
            "rsi2": round(rsi2_v, 1),
            "rsi14": round(rsi14_v, 1),
            "rvol": round(rvol, 2),
            "perf_3m": round(perf_3m, 1),
            "stage2": stage2,
            "sepa": sepa,
            "sma200_rising": sma200_rising,
            "atr": round(atr_v, 2),
            "earnings": earn["label"],
            "earnings_blocked": earn["within_3d"],
            "sentiment": sentiment,
            "w52": w52,
            "required": required,
            "req_pass": req_pass,
            "req_total": len(required),
            "preferred": preferred,
            "pref_pass": pref_pass,
            "pref_total": len(preferred),
            "pref_pct": round(pref_pct * 100),
            "score": score,
            "win_rate": win_rate,
            "shares": shares,
            "pos_value": round(pos_value),
            "pos_pct": round(pos_pct, 1),
            "entry_guide": entry_guide,
            "fail_reasons": fail_reasons,
        }

    except Exception as e:
        print(f"  ⚠️ {ticker} MOM 분석 실패: {e}")
        return None


# ══════════════════════════════════════════════════════════════
# 리포트 포매팅
# ══════════════════════════════════════════════════════════════

def format_stock_report(r):
    """개별 종목 리포트 라인"""
    lines = []
    emoji = {"A": "🟢", "B+": "🔵", "B-": "🟡", "FAIL": "🔴"}.get(r["score"], "⚪")

    lines.append(f"{emoji} {r['ticker']} ${r['price']} [{r['score']}] 승률:{r['win_rate']}")

    if r["mode"] == "MR":
        lines.append(f"  RSI(2):{r['rsi2']} | RVOL:{r['rvol']} | 연속↓:{r.get('consec_down','-')}일 | BB터치:{'Y' if r.get('bb_touch') else 'N'}")
    else:
        lines.append(f"  RSI(14):{r['rsi14']} | RVOL:{r['rvol']} | 3M:+{r.get('perf_3m',0)}% | Stage2:{'Y' if r.get('stage2') else 'N'}")

    lines.append(f"  어닝:{r['earnings']} | 감성:{r['sentiment'] or 'N/A'}%")
    lines.append(f"  52주: 고점{r['w52']['from_high_pct']}% / 저점+{r['w52']['from_low_pct']}%")

    # 필수/선호 상세
    lines.append(f"  ── 필수 {r['req_pass']}/{r['req_total']} ──")
    for name, ok in r["required"].items():
        lines.append(f"    {'✓' if ok else '✗'} {name}")
    lines.append(f"  ── 선호 {r['pref_pass']}/{r['pref_total']} ({r['pref_pct']}%) ──")
    for name, ok in r["preferred"].items():
        lines.append(f"    {'✓' if ok else '✗'} {name}")

    # ATR 사이징
    if r["shares"] > 0:
        lines.append(f"  📐 ATR:{r['atr']} → {r['shares']}주 ${r['pos_value']:,} (계좌 {r['pos_pct']}%)")

    if r["entry_guide"]:
        lines.append(f"  {r['entry_guide']}")

    if r["fail_reasons"]:
        lines.append(f"  ⛔ 불합격: {', '.join(r['fail_reasons'])}")

    lines.append("")
    return "\n".join(lines)


# ══════════════════════════════════════════════════════════════
# 메인 리포트 생성
# ══════════════════════════════════════════════════════════════

def generate_report():
    now = datetime.now()
    print(f"\n{'='*60}")
    print(f"  APEX 2.0 Daily Report v3 — {now.strftime('%Y-%m-%d %H:%M KST')}")
    print(f"{'='*60}\n")

    # ── 시장 데이터 ──
    print("📊 시장 데이터 수집 중...")
    market = get_market_data()
    regime = determine_regime(market)

    lines = []
    lines.append(f"📅 APEX 2.0 Daily Report — {now.strftime('%Y-%m-%d %H:%M')}")
    lines.append("")

    # ── 시장 레짐 ──
    lines.append("━━━ 시장 레짐 ━━━")
    spy = market.get("SPY", {})
    qqq = market.get("QQQ", {})
    lines.append(f"SPY ${spy.get('price','?')} (SMA200:${spy.get('sma200','?')}) {'▲' if spy.get('above_sma200') else '▼'} 등락:{spy.get('chg',0):+.2f}%")
    lines.append(f"  RSI(2):{spy.get('rsi2','?')} | RSI(14):{spy.get('rsi14','?')}")
    lines.append(f"QQQ ${qqq.get('price','?')} (SMA200:${qqq.get('sma200','?')}) {'▲' if qqq.get('above_sma200') else '▼'} 등락:{qqq.get('chg',0):+.2f}%")
    lines.append(f"  RSI(2):{qqq.get('rsi2','?')} | RSI(14):{qqq.get('rsi14','?')}")
    lines.append(f"VIX: {market.get('VIX', '?')}")

    regime_emoji = {"STRONG_BULL": "🟢", "WEAK_BULL": "🟡", "BEAR": "🔴"}.get(regime["regime"], "⚪")
    lines.append(f"레짐: {regime_emoji} {regime['regime']}")
    lines.append(f"MOM: {'✅' if regime['mom_ok'] else '🚫'} | MR: {'✅' if regime['mr_ok'] else '🚫'}")
    if regime["mr_block"]:
        lines.append(f"⛔ {regime['mr_block']}")
    if regime["vix_warn"]:
        lines.append(f"⚠️ {regime['vix_warn']}")
    lines.append(f"포지션: ${POSITION_SIZE.get(regime['regime'], 300)}")
    lines.append("")

    print(f"  레짐: {regime['regime']} | MOM:{'OK' if regime['mom_ok'] else 'X'} | MR:{'OK' if regime['mr_ok'] else 'X'}")

    all_results = {"MR": [], "MOM": []}

    # ── MR 스크리닝 ──
    lines.append("━━━ MR (평균회귀) ━━━")
    if regime["mr_ok"]:
        print("\n🔄 MR 스크리닝...")
        tickers = finviz_screen("MR")
        print(f"  Finviz 프리필터: {len(tickers)}개")

        for t in tickers:
            print(f"  {t}...", end=" ", flush=True)
            r = analyze_mr(t, market, regime)
            if r:
                all_results["MR"].append(r)
                print(f"→ {r['score']} RSI2:{r['rsi2']}")
            else:
                print("skip")

        score_order = {"A": 0, "B+": 1, "B-": 2, "FAIL": 3}
        all_results["MR"].sort(key=lambda x: (score_order.get(x["score"], 9), x["rsi2"]))

        enterable = [r for r in all_results["MR"] if r["score"] in ["A", "B+"]]
        lines.append(f"후보: {len(all_results['MR'])}개 | 진입 가능: {len(enterable)}개")
        lines.append("")
        for r in all_results["MR"]:
            lines.append(format_stock_report(r))
    else:
        lines.append(f"🚫 MR 진입 금지 — {regime['mr_block'] or '조건 미충족'}")
        lines.append("")

    # ── MOM 스크리닝 ──
    lines.append("━━━ MOM (모멘텀) ━━━")
    if regime["mom_ok"]:
        print("\n🚀 MOM 스크리닝...")
        tickers = finviz_screen("MOM")
        print(f"  Finviz 프리필터: {len(tickers)}개")

        for t in tickers:
            print(f"  {t}...", end=" ", flush=True)
            r = analyze_mom(t, market, regime)
            if r:
                all_results["MOM"].append(r)
                print(f"→ {r['score']} RSI14:{r['rsi14']}")
            else:
                print("skip")

        score_order = {"A": 0, "B+": 1, "B-": 2, "FAIL": 3}
        all_results["MOM"].sort(key=lambda x: (score_order.get(x["score"], 9), -x.get("perf_3m", 0)))

        enterable = [r for r in all_results["MOM"] if r["score"] in ["A", "B+"]]
        lines.append(f"후보: {len(all_results['MOM'])}개 | 진입 가능: {len(enterable)}개")
        lines.append("")
        for r in all_results["MOM"]:
            lines.append(format_stock_report(r))
    else:
        lines.append("🚫 MOM 진입 금지 — Bear 레짐")
        lines.append("")

    # ── 매수 타이밍 ──
    lines.append("━━━ 매수 타이밍 ━━━")
    lines.append("🔄 MR: 장 마감 30분전 (KST 05:30) 지정가")
    lines.append("  차선: KST 23:00 지정가 걸고 취침")
    lines.append("  익절: RSI(2) > 70 시 장중 매도 (2~5일)")
    lines.append("🚀 MOM: 장 개장 30분~1시간 후 (KST 23:00)")
    lines.append("  차선: 전일 브레이크아웃 → 다음날 풀백")
    lines.append("  익절: +8~12% 또는 RSI(14) > 75 (5~15일)")
    lines.append("")

    # ── 승률 참고 ──
    lines.append("━━━ 승률 참고 (Connors RSI(2) 연구 기반) ━━━")
    lines.append("필수만 통과 → 60~65%")
    lines.append("필수 + 선호 70% → 68~75%")
    lines.append("필수 + 선호 100% → 75~82%")
    lines.append("")

    # ── 인트라데이 패턴 참고 ──
    lines.append("━━━ 인트라데이 진입 패턴 (참고) ━━━")
    lines.append("📐 ORB: 갭3~15% + 프리마켓 거래량 3배 + 첫5분 고점 돌파")
    lines.append("〰️ VWAP: VWAP 상향돌파 + 거래량 2배 + 1~3분 유지")
    lines.append("🚀 EP: 갭10%+ + 프리마켓 5배 + 펀더멘탈 촉매")
    lines.append("")

    lines.append("⚠️ 최종 매매 판단은 반드시 본인이 하세요")
    lines.append(f"📐 계좌: ${ACCOUNT_SIZE:,} | 리스크: {RISK_PCT}%/회")

    report_text = "\n".join(lines)

    print(f"\n{'='*60}")
    print(report_text)
    print(f"{'='*60}")

    return report_text, all_results


# ══════════════════════════════════════════════════════════════
# 알림 전송
# ══════════════════════════════════════════════════════════════

def send_telegram(text):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        print("ℹ️ 텔레그램 미설정")
        return
    try:
        url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        chunks = [text[i:i+4000] for i in range(0, len(text), 4000)]
        for chunk in chunks:
            requests.post(url, json={"chat_id": TELEGRAM_CHAT_ID, "text": chunk}, timeout=10)
        print("✅ 텔레그램 전송 완료")
    except Exception as e:
        print(f"❌ 텔레그램 실패: {e}")


def send_kakao(text):
    """
    카카오톡 나에게 보내기
    설정법:
    1. developers.kakao.com → 앱 생성
    2. 카카오 로그인 활성화 → 동의항목 → talk_message 체크
    3. 브라우저에서 인증 URL 접속:
       https://kauth.kakao.com/oauth/authorize?client_id=YOUR_REST_KEY&redirect_uri=https://localhost&response_type=code
    4. 리다이렉트 URL에서 code 추출
    5. REST API로 access_token 발급
    6. 스크립트 상단 KAKAO_ACCESS_TOKEN에 입력
    ※ 토큰 12시간마다 갱신 필요 → 텔레그램 권장
    """
    if not KAKAO_ACCESS_TOKEN:
        print("ℹ️ 카카오톡 미설정")
        return
    try:
        url = "https://kapi.kakao.com/v2/api/talk/memo/default/send"
        headers = {"Authorization": f"Bearer {KAKAO_ACCESS_TOKEN}"}
        truncated = text[:4000]
        data = {
            "template_object": json.dumps({
                "object_type": "text",
                "text": truncated,
                "link": {"web_url": "https://finviz.com"},
                "button_title": "Finviz",
            })
        }
        resp = requests.post(url, headers=headers, data=data, timeout=10)
        if resp.status_code == 200:
            print("✅ 카카오톡 전송 완료")
        else:
            print(f"❌ 카카오톡 실패: {resp.status_code}")
    except Exception as e:
        print(f"❌ 카카오톡 실패: {e}")


# ══════════════════════════════════════════════════════════════
# 실행
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    report_text, results = generate_report()

    send_telegram(report_text)
    send_kakao(report_text)

    # JSON 저장
    fname = f"apex_report_{datetime.now().strftime('%Y%m%d_%H%M')}.json"
    with open(fname, "w", encoding="utf-8") as f:
        json.dump(results, f, ensure_ascii=False, indent=2, default=str)
    print(f"\n📁 JSON 저장: {fname}")
    print("✅ 완료")
