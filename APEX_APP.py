"""
APEX Daily TOP2 — 매일 04:40 KST 자동 전송
────────────────────────────────────────
당일 상승률 상위 10개 중 내일 상승 확률 높은 2종목 선별
실행: python apex_daily_top2.py
자동화: 작업 스케줄러에서 매일 04:40 KST 실행
"""

import datetime
import time
import requests
import pandas as pd
import yfinance as yf

# ══════════════════════════════════════════════════
# 설정
# ══════════════════════════════════════════════════
TELEGRAM_TOKEN   = "8547833658:AAHEWRtZ8X0pjGD1p5JwPopQFBOrO6XBJo8"
TELEGRAM_CHAT_ID = "8531086237"

ACCOUNT_SIZE = 5000   # 계좌 크기 (USD) — 본인에 맞게 수정
RISK_PCT     = 1.0    # 1회 리스크 %

# S&P500 종목 리스트 (안정적인 대형주 위주 200개)
SP500_TICKERS = [
    "AAPL","MSFT","NVDA","AMZN","META","GOOGL","TSLA","BRK-B","JPM","LLY",
    "AVGO","V","MA","UNH","XOM","COST","HD","PG","JNJ","ABBV",
    "BAC","MRK","CRM","CVX","NFLX","AMD","ACN","TMO","LIN","ORCL",
    "ABT","DHR","MCD","TXN","NEE","PM","QCOM","AMGN","INTU","ISRG",
    "IBM","GS","SPGI","CAT","HON","AMAT","NOW","AXP","BKNG","RTX",
    "BLK","VRTX","PLD","SYK","PANW","MMC","GILD","MDT","SCHW","ADI",
    "CI","DE","REGN","SBUX","ZTS","PGR","LRCX","TJX","CME","ETN",
    "BSX","EOG","MO","ELV","ADP","NOC","SO","DUK","KLAC","APH",
    "MCO","ITW","SHW","ICE","WM","FI","HCA","MSI","CEG","GEV",
    "CDNS","SNPS","MCHP","FICO","IDXX","ROP","CTAS","MNST","BIIB","DXCM",
    "AXON","CRWD","FTNT","ANSS","VRSK","CPRT","EW","ENPH","PODD","ALGN",
    "MSCI","EPAM","PAYC","POOL","TDG","TRMB","BR","CBOE","DT","HOOD",
    "HLT","MAR","UBER","LYFT","ABNB","DASH","ZM","DOCU","TWLO","OKTA",
    "SNOW","MDB","NET","DDOG","ZS","GTLB","U","RBLX","COIN","MARA",
    "WMT","TGT","LOW","F","GM","RIVN","LCID","NKE","LULU","TPR",
    "MU","WDC","STX","NTAP","HPE","DELL","SMCI","PLTR","BBAI","AI",
    "GE","BA","LMT","GD","HII","L3H","TDY","HWM","SPR","KTOS",
    "XOM","CVX","COP","SLB","HAL","BKR","MPC","VLO","PSX","DVN",
    "PFE","MRNA","BNTX","BMY","AZN","GSK","NVO","LLY","RGEN","EXAS",
    "GS","MS","WFC","C","USB","PNC","TFC","COF","AIG","MET",
]


# ══════════════════════════════════════════════════
# 텔레그램 전송
# ══════════════════════════════════════════════════
def send_telegram(text: str) -> bool:
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


# ══════════════════════════════════════════════════
# 당일 상승률 상위 10개 추출
# ══════════════════════════════════════════════════
def get_top10_gainers(tickers: list) -> list:
    """당일 상승률 기준 상위 10개 종목 반환"""
    print(f"  {len(tickers)}개 종목 당일 등락률 수집 중...")
    results = []

    # yfinance 배치 다운로드 (빠름)
    try:
        raw = yf.download(
            tickers,
            period="2d",
            interval="1d",
            progress=False,
            group_by="ticker"
        )
    except Exception as e:
        print(f"  배치 다운로드 실패: {e}")
        return []

    for ticker in tickers:
        try:
            if len(tickers) == 1:
                close = raw["Close"]
            else:
                close = raw[ticker]["Close"]

            if close is None or len(close) < 2:
                continue
            close = close.dropna()
            if len(close) < 2:
                continue

            chg = float((close.iloc[-1] - close.iloc[-2]) / close.iloc[-2] * 100)
            price = float(close.iloc[-1])

            if chg > 0:   # 상승 종목만
                results.append({
                    "ticker": ticker,
                    "price":  round(price, 2),
                    "chg":    round(chg, 2),
                })
        except Exception:
            continue

    # 상승률 내림차순 정렬 → 상위 10개
    results.sort(key=lambda x: x["chg"], reverse=True)
    top10 = results[:10]
    print(f"  상위 10개: {[r['ticker'] for r in top10]}")
    return top10


# ══════════════════════════════════════════════════
# 종목 상세 분석
# ══════════════════════════════════════════════════
def analyze_for_tomorrow(ticker: str, price: float, chg: float) -> dict | None:
    """내일 상승 확률 평가"""
    try:
        df = yf.download(ticker, period="1y", progress=False)
        if df.empty or len(df) < 60:
            return None
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        close  = df["Close"]
        high   = df["High"]
        low    = df["Low"]
        volume = df["Volume"]

        # 지표 계산
        sma200 = float(close.rolling(200).mean().iloc[-1])
        sma50  = float(close.rolling(50).mean().iloc[-1])
        sma20  = float(close.rolling(20).mean().iloc[-1])

        # RSI(14)
        d14 = close.diff()
        g14 = d14.clip(lower=0).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        l14 = (-d14.clip(upper=0)).ewm(alpha=1/14, min_periods=14, adjust=False).mean()
        rsi14 = float((100 - 100/(1 + g14/l14.replace(0, 1e-10))).iloc[-1])

        # RSI(2)
        d2 = close.diff()
        g2 = d2.clip(lower=0).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
        l2 = (-d2.clip(upper=0)).ewm(alpha=1/2, min_periods=2, adjust=False).mean()
        rsi2 = float((100 - 100/(1 + g2/l2.replace(0, 1e-10))).iloc[-1])

        # RVOL
        avg_vol = float(volume.rolling(20).mean().iloc[-1])
        rvol    = float(volume.iloc[-1] / avg_vol) if avg_vol > 0 else 0

        # ATR(14)
        tr  = pd.concat([
            high - low,
            (high - close.shift(1)).abs(),
            (low  - close.shift(1)).abs()
        ], axis=1).max(axis=1)
        atr = float(tr.ewm(alpha=1/14, min_periods=14, adjust=False).mean().iloc[-1])

        # 52주 위치
        h252      = df.tail(252)
        w52_high  = float(h252["High"].max())
        w52_low   = float(h252["Low"].min())
        from_high = (price - w52_high) / w52_high * 100
        from_low  = (price - w52_low)  / w52_low  * 100

        # 3개월 수익률
        perf_3m = ((price / float(close.iloc[-63])) - 1) * 100 if len(close) >= 63 else 0

        # SEPA 정렬
        sma150   = float(close.rolling(150).mean().iloc[-1])
        sepa     = sma50 > sma150 > sma200
        above200 = price > sma200

        # 어닝 체크
        earn_blocked = False
        try:
            tk  = yf.Ticker(ticker)
            cal = tk.calendar
            today = datetime.date.today()
            earn_date = None
            if isinstance(cal, dict):
                raw_e = cal.get("Earnings Date")
                if raw_e:
                    earn_date = pd.Timestamp(
                        raw_e[0] if isinstance(raw_e, (list, tuple)) else raw_e
                    ).date()
            if earn_date:
                days = (earn_date - today).days
                earn_blocked = -1 <= days <= 3
        except Exception:
            pass

        # ── 내일 상승 가능성 점수 계산 ──
        score = 0.0

        # 1) 오늘 상승폭 (최대 20점) — 너무 많이 오르면 오히려 감점
        if 2 <= chg <= 8:
            score += 20        # 적당한 상승 → 모멘텀 지속 가능
        elif 8 < chg <= 15:
            score += 10        # 많이 올랐지만 OK
        elif chg > 15:
            score += 0         # 너무 많이 올랐음 → 내일 되돌림 위험

        # 2) SMA200 위 (15점)
        if above200:
            score += 15

        # 3) RSI(14) 50~75 구간 (20점) — 모멘텀 있으나 과매수 아님
        if 50 <= rsi14 <= 75:
            score += 20
        elif 75 < rsi14 <= 85:
            score += 5         # 약간 과매수

        # 4) RVOL (최대 20점)
        score += min((rvol - 1.0) / 2.0, 1.0) * 20

        # 5) SEPA 정렬 (10점)
        if sepa:
            score += 10

        # 6) 52주 위치 (최대 10점) — 신고가 근접할수록 유리
        if from_high >= -10:
            score += 10
        elif from_high >= -20:
            score += 7
        elif from_high >= -30:
            score += 3

        # 7) 3개월 수익률 (최대 10점)
        score += min(perf_3m / 30, 1.0) * 10

        # 감점
        if earn_blocked:
            score -= 30        # 어닝 3일내 → 위험
        if rsi14 > 85:
            score -= 10        # 극단 과매수
        if from_high < -40:
            score -= 20        # 망가진 종목

        # 포지션 사이징
        risk_dollar = ACCOUNT_SIZE * (RISK_PCT / 100)
        shares      = int(risk_dollar / atr) if atr > 0 else 0
        pos_value   = shares * price
        stop_price  = round(price - 2 * atr, 2)   # 2ATR 손절
        target_price = round(price * 1.05, 2)       # +5% 목표

        return {
            "ticker":       ticker,
            "price":        round(price, 2),
            "chg":          round(chg, 2),
            "score":        round(score, 1),
            "rsi14":        round(rsi14, 1),
            "rsi2":         round(rsi2, 1),
            "rvol":         round(rvol, 2),
            "atr":          round(atr, 2),
            "above200":     above200,
            "sepa":         sepa,
            "from_high":    round(from_high, 1),
            "perf_3m":      round(perf_3m, 1),
            "earn_blocked": earn_blocked,
            "shares":       shares,
            "pos_value":    round(pos_value),
            "stop_price":   stop_price,
            "target_price": target_price,
        }

    except Exception as e:
        print(f"  {ticker} 분석 실패: {e}")
        return None


# ══════════════════════════════════════════════════
# 텔레그램 메시지 조립
# ══════════════════════════════════════════════════
def build_message(top10: list, top2: list) -> str:
    now = datetime.datetime.now().strftime("%Y-%m-%d %H:%M KST")

    lines = [
        f"<b>📈 APEX Daily TOP2 — {now}</b>",
        f"장마감 20분전 · 내일 상승 유력 종목",
        "─────────────────────",
    ]

    if not top2:
        lines += [
            "⚠ 오늘은 조건 충족 종목 없음",
            "내일 다시 확인하세요",
        ]
    else:
        lines.append("<b>🎯 내일 추천 TOP2</b>")
        lines.append("")

        for idx, r in enumerate(top2):
            rank = ["1️⃣", "2️⃣"][idx]
            earn_warn = " 🚨어닝주의" if r["earn_blocked"] else ""
            lines += [
                f"{rank} <b>{r['ticker']}</b>  ${r['price']}  오늘 +{r['chg']}%{earn_warn}",
                f"   RSI(14): {r['rsi14']}  RVOL: {r['rvol']}x  52주고점: {r['from_high']}%",
                f"   SMA200: {'✓위' if r['above200'] else '✗아래'}  SEPA: {'✓' if r['sepa'] else '✗'}",
                f"   🎯 목표 ${r['target_price']} (+5%)  🛑 손절 ${r['stop_price']}",
                f"   📐 {r['shares']}주 = ${r['pos_value']:,}",
                "",
            ]

    # 오늘 상위 10개 요약
    lines.append("─────────────────────")
    lines.append("<b>📊 오늘 상승 TOP10</b>")
    for i, r in enumerate(top10[:10]):
        lines.append(f"  {i+1}. {r['ticker']}  +{r['chg']}%  ${r['price']}")

    lines += [
        "─────────────────────",
        "⚠ 참고용. 손절 필수. 최종 판단은 본인이.",
    ]

    return "\n".join(lines)


# ══════════════════════════════════════════════════
# 메인 실행
# ══════════════════════════════════════════════════
def run():
    print(f"\n[{datetime.datetime.now().strftime('%H:%M:%S')}] APEX Daily TOP2 시작...")

    # 1) 당일 상승 상위 10개 추출
    top10 = get_top10_gainers(SP500_TICKERS)
    if not top10:
        send_telegram("⚠ APEX: 오늘 상승 종목 데이터 수집 실패")
        return

    # 2) 상위 10개 상세 분석
    print(f"  상위 10개 상세 분석 중...")
    analyzed = []
    for r in top10:
        result = analyze_for_tomorrow(r["ticker"], r["price"], r["chg"])
        if result:
            analyzed.append(result)
        time.sleep(0.5)

    # 3) 점수 기준 정렬 → TOP2 선별
    analyzed.sort(key=lambda x: x["score"], reverse=True)

    # 어닝 없는 것 우선, 점수 순
    safe     = [r for r in analyzed if not r["earn_blocked"]]
    top2     = safe[:2] if safe else analyzed[:2]

    print(f"  TOP2: {[r['ticker'] for r in top2]}")
    for r in top2:
        print(f"    {r['ticker']} 점수={r['score']} RSI14={r['rsi14']} RVOL={r['rvol']}")

    # 4) 텔레그램 전송
    msg = build_message(top10, top2)
    ok  = send_telegram(msg)
    print(f"  전송: {'성공' if ok else '실패'}")


if __name__ == "__main__":
    run()
