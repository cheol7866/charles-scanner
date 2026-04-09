"""
APEX Telegram Daily Report
──────────────────────────
매일 자동 스캔 후 텔레그램으로 결과 전송.
실행: python apex_telegram.py
설치: pip install yfinance pandas finvizfinance requests
"""

import datetime
import time
import requests
import pandas as pd
import yfinance as yf

# ══════════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════════
TELEGRAM_TOKEN   = "8547833658:AAHEWRtZ8X0pjGD1p5JwPopQFBOrO6XBJo8"
TELEGRAM_CHAT_ID = "8531086237"

ACCOUNT_SIZE = 5000   # 계좌 크기 (USD)
RISK_PCT     = 1.0    # 1회 리스크 %


# ══════════════════════════════════════════════════════
# 텔레그램 전송
# ══════════════════════════════════════════════════════
def send_telegram(text):
    url = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
    try:
        r = requests.post(url, json={
            "chat_id": TELEGRAM_CHAT_ID,
            "text": text,
            "parse_mode": "HTML"
        }, timeout=10)
        return r.status_code == 200
    except Exception as e:
        print(f"텔레그램 전송 실패: {e}")
        return False


# ══════════════════════════════════════════════════════
# 지표 계산
# ══════════════════════════════════════════════════════
def _calc_rsi(series, period):
    delta    = series.diff()
    gain     = delta.where(delta > 0, 0.0)
    loss     = -delta.where(delta < 0, 0.0)
    avg_gain = gain.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    avg_loss = loss.ewm(alpha=1/period, min_periods=period, adjust=False).mean()
    rs       = avg_gain / avg_loss.replace(0, 1e-10)
    return 100 - (100 / (1 + rs))

def _calc_sma(series, period):
    return series.rolling(window=period).mean()

def _calc_bollinger(series, period=20, std_mult=2):
    sma = _calc_sma(series, period)
    std = series.rolling(window=period).std()
    return sma, sma + std_mult * std, sma - std_mult * std

def _calc_atr(high, low, close, period=14):
    tr = pd.concat([
        high - low,
        (high - close.shift(1)).abs(),
        (low  - close.shift(1)).abs()
    ], axis=1).max(axis=1)
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

def _check_eps_growth(ticker, min_growth_pct=25.0):
    """[참고용] 직전 분기 EPS 전년 동기 대비 성장률 확인"""
    try:
        qe = yf.Ticker(ticker).quarterly_earnings
        if qe is None or qe.empty or len(qe) < 5:
            return False
        qe           = qe.sort_index(ascending=False)
        latest_eps   = float(qe["Earnings"].iloc[0])
        year_ago_eps = float(qe["Earnings"].iloc[4])
        if year_ago_eps <= 0:
            return False
        growth = (latest_eps - year_ago_eps) / abs(year_ago_eps) * 100
        return growth >= min_growth_pct
    except Exception:
        return False

def _mr_rank_score(r):
    score = 0.0
    score += max(0, (15 - r.get("rsi2", 15)) / 15 * 40)
    score += 20 if r.get("bb_touch", False) else 0
    score += min(r.get("consec", 0) / 5, 1.0) * 20
    rvol   = r.get("rvol", 1.2)
    score += max(0, (1.2 - rvol) / 1.2 * 10)
    score += {"A": 10, "B+": 5, "B-": 0, "FAIL": -99}.get(r.get("score", "FAIL"), 0)
    return score

def _mom_rank_score(r):
    score = 0.0
    score += min(r.get("perf_3m", 0) / 30, 1.0) * 30
    score += min((r.get("rvol", 1.0) - 1.0) / 1.0, 1.0) * 20
    score += 20 if r.get("sepa", False) else 0
    score += min(r.get("from_low", 0) / 100, 1.0) * 15
    score += {"A": 15, "B+": 7, "B-": 0, "FAIL": -99}.get(r.get("score", "FAIL"), 0)
    return score


# ══════════════════════════════════════════════════════
# 시장 신호 수집
# ══════════════════════════════════════════════════════
def get_index_data(ticker):
    try:
        hist   = yf.Ticker(ticker).history(period="300d", interval="1d")
        if hist.empty or len(hist) < 200:
            return None, None, None
        price  = float(hist["Close"].iloc[-1])
        sma200 = float(hist["Close"].rolling(200).mean().iloc[-1])
        chg    = float(hist["Close"].pct_change().iloc[-1] * 100)
        return price, sma200, chg
    except Exception:
        return None, None, None

def get_vix():
    try:
        hist = yf.Ticker("^VIX").history(period="5d", interval="1d")
        return float(hist["Close"].iloc[-1]) if not hist.empty else None
    except Exception:
        return None

def get_spy_rsi2():
    try:
        hist = yf.Ticker("SPY").history(period="30d", interval="1d")
        rsi  = _calc_rsi(hist["Close"], 2)
        return float(rsi.iloc[-1])
    except Exception:
        return None

def get_earnings_within_3d(ticker):
    today = datetime.date.today()
    try:
        tk  = yf.Ticker(ticker)
        cal = tk.calendar
        earn_date = None
        if isinstance(cal, dict):
            raw = cal.get("Earnings Date")
            if raw:
                earn_date = pd.Timestamp(
                    raw[0] if isinstance(raw, (list, tuple)) else raw
                ).date()
        elif isinstance(cal, pd.DataFrame) and not cal.empty:
            if "Earnings Date" in cal.index:
                earn_date = pd.Timestamp(cal.loc["Earnings Date"].iloc[0]).date()
        if earn_date:
            days = (earn_date - today).days
            return -1 <= days <= 3
    except Exception:
        pass
    return False


# ══════════════════════════════════════════════════════
# 레짐 판단
# ══════════════════════════════════════════════════════
def get_regime(spy_price, spy_sma200, qqq_price, qqq_sma200):
    if None in (spy_price, spy_sma200, qqq_price, qqq_sma200):
        return "UNKNOWN"
    spy_margin = (spy_price - spy_sma200) / spy_sma200 * 100
    qqq_margin = (qqq_price - qqq_sma200) / qqq_sma200 * 100
    if spy_margin >= 5 and qqq_margin >= 5:
        return "STRONG_BULL"
    elif spy_margin >= 3 and qqq_margin >= 3:
        return "WEAK_BULL"
    else:
        return "BEAR"


# ══════════════════════════════════════════════════════
# Finviz 스크리닝
# ══════════════════════════════════════════════════════
def run_finviz(mode):
    try:
        from finvizfinance.screener.overview import Overview
        fov = Overview()
        if mode == "MOM":
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "50-Day Simple Moving Average":  "Price above SMA50",
                "RSI (14)":                      "Not Overbought (<60)",
                "Performance":                   "Quarter +10%",
                "Average Volume":                "Over 500K",
                "Industry":                      "Stocks only (ex-Funds)",
                "Relative Volume":               "Over 1.5",
                "Price":                         "Over $10",
            }
        else:  # MR
            filters = {
                "200-Day Simple Moving Average": "Price above SMA200",
                "RSI (14)":                      "Oversold (40)",
                "Average Volume":                "Over 500K",
                "Market Cap.":                   "+Mid (over $2bln)",
                "EPS growthqtr over qtr":        "Positive (>0%)",
                "Industry":                      "Stocks only (ex-Funds)",
                "Price":                         "Over $10",
            }
        fov.set_filter(filters_dict=filters)
        df = fov.screener_view()
        if df is None or df.empty:
            return []
        return df["Ticker"].tolist()
    except Exception as e:
        print(f"Finviz 오류: {e}")
        return []


# ══════════════════════════════════════════════════════
# 종목 분석
# ══════════════════════════════════════════════════════
def analyze_stock(ticker, mode, spy_rsi2, mom_ok, vix_ok):
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 200:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close, high, lo, volume = df["Close"], df["High"], df["Low"], df["Volume"]
        price = float(close.iloc[-1])

        sma200  = _calc_sma(close, 200)
        sma150  = _calc_sma(close, 150)
        sma50   = _calc_sma(close, 50)
        rsi2    = _calc_rsi(close, 2)
        rsi14   = _calc_rsi(close, 14)
        _, _, bb_lower = _calc_bollinger(close)
        atr     = _calc_atr(high, lo, close)
        rvol    = _calc_rvol(volume)
        consec  = _consec_down(close)

        s200     = float(sma200.iloc[-1])
        s150     = float(sma150.iloc[-1]) if not pd.isna(sma150.iloc[-1]) else None
        s50      = float(sma50.iloc[-1])
        rsi2_v   = float(rsi2.iloc[-1])
        rsi14_v  = float(rsi14.iloc[-1])
        bb_low_v = float(bb_lower.iloc[-1])
        atr_v    = float(atr.iloc[-1])
        bb_touch = price <= bb_low_v * 1.005   # bb_touch 키 추가

        sepa          = s150 is not None and s50 > s150 > s200
        sma200_rising = len(sma200) >= 21 and float(sma200.iloc[-1]) > float(sma200.iloc[-21])

        h252      = df.tail(252)
        w52_high  = float(h252["High"].max())
        w52_low   = float(h252["Low"].min())
        from_high = (price - w52_high) / w52_high * 100
        from_low  = (price - w52_low)  / w52_low  * 100
        perf_3m   = ((price / float(close.iloc[-63])) - 1) * 100 if len(close) >= 63 else 0

        earn_blocked = get_earnings_within_3d(ticker)

        if mode == "MR":
            required = {
                "SMA200 위":           price > s200,
                "RSI(2) ≤ 15":        rsi2_v <= 15,
                "어닝 3일내 없음":     not earn_blocked,
                "SPY RSI(2) > 10":    spy_rsi2 > 10,
                "52주고점 -40%이내":  from_high >= -40,
            }
            preferred = {
                "BB 하단 터치":    bb_touch,
                "RVOL < 1.2":      rvol < 1.2,
                "연속 하락 3일+":  consec >= 3,
                "VIX ≤ 25":        vix_ok,
                "SMA200 상승 중":  sma200_rising,
            }
        else:  # MOM
            eps_ok = _check_eps_growth(ticker)
            required = {
                "시장 레짐 Bull":  mom_ok,
                "RSI(14) 50~70":  50 <= rsi14_v <= 70,
                "어닝 3일내 없음": not earn_blocked,
                "SMA200 상승 중": sma200_rising,
            }
            preferred = {
                "SEPA 정렬":           sepa,
                "RVOL ≥ 1.2":          rvol >= 1.2,
                "3개월 +10%":          perf_3m >= 10,
                "52주고점 -25%이내":   from_high >= -25,
                "52주저점 +30%이상":   from_low >= 30,
                "RSI(2) < 80":         rsi2_v < 80,
                "EPS YoY +25% [참고]": eps_ok,
            }

        req_pass  = sum(required.values())
        pref_pass = sum(preferred.values())
        pref_pct  = pref_pass / len(preferred) if preferred else 0

        if req_pass < len(required):
            score, win_rate = "FAIL", "—"
        elif pref_pct >= 1.0:
            score, win_rate = ("A", "75~82%") if mode == "MR" else ("A", "70~78%")
        elif pref_pct >= 0.7:
            score, win_rate = ("B+", "68~75%") if mode == "MR" else ("B+", "63~70%")
        else:
            score, win_rate = ("B-", "60~65%") if mode == "MR" else ("B-", "55~63%")

        risk_dollar = ACCOUNT_SIZE * (RISK_PCT / 100)
        shares      = int(risk_dollar / atr_v) if atr_v > 0 else 0
        pos_value   = shares * price
        stop_3atr   = price - 3 * atr_v

        return {
            "ticker":       ticker,
            "price":        round(price, 2),
            "rsi2":         round(rsi2_v, 1),
            "rsi14":        round(rsi14_v, 1),
            "rvol":         round(rvol, 2),
            "consec":       consec,
            "bb_touch":     bb_touch,           # 추가
            "atr":          round(atr_v, 2),
            "perf_3m":      round(perf_3m, 1),
            "from_high":    round(from_high, 1),
            "from_low":     round(from_low, 1),
            "sepa":         sepa,
            "earn_blocked": earn_blocked,
            "score":        score,
            "win_rate":     win_rate,
            "shares":       shares,
            "pos_value":    round(pos_value),
            "stop_3atr":    round(stop_3atr, 2),
            "target_8pct":  round(price * 1.08, 2),
        }
    except Exception:
        return None


# ══════════════════════════════════════════════════════
# 텔레그램 메시지 조립
# ══════════════════════════════════════════════════════
def build_message(regime, spy_p, spy_s200, qqq_p, qqq_s200,
                  vix, spy_rsi2, mr_top2, mom_top2):

    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")
    spy_margin = (spy_p - spy_s200) / spy_s200 * 100 if spy_p and spy_s200 else 0
    qqq_margin = (qqq_p - qqq_s200) / qqq_s200 * 100 if qqq_p and qqq_s200 else 0
    regime_emoji = {"STRONG_BULL": "🟢", "WEAK_BULL": "🟡", "BEAR": "🔴"}.get(regime, "⚪")
    vix_str = f"{vix:.1f}" if vix is not None else "N/A"
    rsi2_str = f"{spy_rsi2:.1f}" if spy_rsi2 is not None else "N/A"

    lines = [
        f"<b>🚦 APEX Daily — {now}</b>",
        f"레짐: {regime_emoji} {regime}",
        f"SPY {spy_margin:+.1f}%  QQQ {qqq_margin:+.1f}%  VIX {vix_str}  RSI2 {rsi2_str}",
        "─────────────────────",
    ]

    # MR TOP2
    lines.append("<b>🔄 MR 오늘의 추천</b>")
    if mr_top2:
        for idx, r in enumerate(mr_top2):
            rank = ["1️⃣", "2️⃣"][idx]
            lines += [
                f"{rank} <b>{r['ticker']}</b>  ${r['price']}  [{r['score']}]",
                f"   RSI(2): {r['rsi2']}  RVOL: {r['rvol']}x  ↓{r['consec']}일  BB: {'✓' if r['bb_touch'] else '✗'}",
                f"   ⏰ 04:30 KST 매수  |  손절 ${r['stop_3atr']}",
                f"   📐 {r['shares']}주 = ${r['pos_value']:,}",
                "",
            ]
    else:
        lines.append("   조건 충족 종목 없음 — 오늘은 패스\n")

    lines.append("─────────────────────")

    # MOM TOP2
    lines.append("<b>🚀 MOM 오늘의 추천</b>")
    if mom_top2:
        for idx, r in enumerate(mom_top2):
            rank = ["1️⃣", "2️⃣"][idx]
            lines += [
                f"{rank} <b>{r['ticker']}</b>  ${r['price']}  [{r['score']}]",
                f"   RSI(14): {r['rsi14']}  RVOL: {r['rvol']}x  3M: +{r['perf_3m']}%",
                f"   ⏰ 23:00 KST 매수  |  목표 +8% ${r['target_8pct']}",
                f"   📐 {r['shares']}주 = ${r['pos_value']:,}",
                "",
            ]
    else:
        lines.append("   Bear 레짐 — MOM 패스\n")

    lines += [
        "─────────────────────",
        "⚠ 참고용. 손절 필수. 최종 판단은 본인이.",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════════
def run():
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] APEX 스캔 시작...")

    # 1) 시장 데이터
    spy_p, spy_s200, _ = get_index_data("SPY")
    qqq_p, qqq_s200, _ = get_index_data("QQQ")
    vix      = get_vix()
    spy_rsi2 = get_spy_rsi2()

    vix_ok = vix is not None and vix <= 25
    regime = get_regime(spy_p, spy_s200, qqq_p, qqq_s200)
    mom_ok = regime in ["STRONG_BULL", "WEAK_BULL"]
    mr_ok  = spy_rsi2 is not None and spy_rsi2 > 10

    rsi2_str = f"{spy_rsi2:.1f}" if spy_rsi2 is not None else "N/A"
    print(f"  레짐: {regime}  VIX: {vix}  SPY RSI(2): {rsi2_str}")

    # 2) MR 스캔
    print("  MR Finviz 스크리닝...")
    mr_tickers = run_finviz("MR") if mr_ok else []
    print(f"  MR 후보: {len(mr_tickers)}개")
    mr_results = []
    for t in mr_tickers:
        r = analyze_stock(t, "MR", spy_rsi2, mom_ok, vix_ok)
        if r and r["score"] != "FAIL":
            mr_results.append(r)
        time.sleep(1)
    mr_results.sort(key=lambda x: _mr_rank_score(x), reverse=True)
    mr_top2 = mr_results[:2]

    # 3) MOM 스캔
    print("  MOM Finviz 스크리닝...")
    mom_tickers = run_finviz("MOM") if mom_ok else []
    print(f"  MOM 후보: {len(mom_tickers)}개")
    mom_results = []
    for t in mom_tickers:
        r = analyze_stock(t, "MOM", spy_rsi2, mom_ok, vix_ok)
        if r and r["score"] != "FAIL":
            mom_results.append(r)
        time.sleep(1)
    mom_results.sort(key=lambda x: _mom_rank_score(x), reverse=True)
    mom_top2 = mom_results[:2]

    # 4) 전송
    msg = build_message(
        regime, spy_p, spy_s200, qqq_p, qqq_s200,
        vix, spy_rsi2, mr_top2, mom_top2
    )
    ok = send_telegram(msg)
    print(f"  전송: {'성공' if ok else '실패'}")
    print(f"  MR TOP2: {[r['ticker'] for r in mr_top2]}")
    print(f"  MOM TOP2: {[r['ticker'] for r in mom_top2]}")


if __name__ == "__main__":
    run()
