#!/usr/bin/env python3
"""
╔══════════════════════════════════════════════════════════════════╗
║     APEX MR 단기 스크리너  |  IBS + RSI(2) + SMA200 + RVOL     ║
║     반드시 미국 장 마감 후 실행 (KST 기준 ~11:00 PM 이후)        ║
║     매수 진입: 당일 마감 직전 5분 OR 익일 시가 (수익률 차이 있음) ║
╚══════════════════════════════════════════════════════════════════╝

[신호 조건]
  매수: IBS < 0.20  AND  RSI(2) < 15  AND  SMA200 위  AND  RVOL < 1.2
  매도: IBS > 0.80  OR  RSI(2) > 65  → 당일 마감 전 청산
        Time Stop: 5거래일 경과 시 청산

[APEX 포지셔닝]
  이 스크리너는 APEX 2.0 MR 레이어와 별개로 운용 가능한 단독 모듈
  bear regime (SPY or QQQ below SMA200) 에서도 SMA200 조건으로 필터링
"""

import sys
import time
import warnings
import pandas as pd
import numpy as np
import yfinance as yf
from finvizfinance.screener.overview import Overview
from datetime import datetime

warnings.filterwarnings("ignore")

# ══════════════════════════════════════════════════
#  설정값 (조정 가능)
# ══════════════════════════════════════════════════
CONFIG = {
    # ── 매수 조건 ──────────────────────────────────
    "IBS_BUY_THRESHOLD":  0.20,   # IBS < 0.20 → 저점 근처 마감
    "RSI2_BUY_THRESHOLD": 15.0,   # RSI(2) < 15 → 과매도
    "RVOL_MAX":           1.2,    # RVOL < 1.2 → 추세 피로 없음
    # SMA200 위 = 상승추세 내 MR (bool 조건)

    # ── 매도 조건 ──────────────────────────────────
    "IBS_SELL_THRESHOLD":  0.80,  # IBS > 0.80 → 당일 청산
    "RSI2_SELL_THRESHOLD": 65.0,  # RSI(2) > 65 → 당일 청산
    "TIME_STOP_DAYS":       5,    # 5거래일 보유 후 강제 청산

    # ── 최소 충족 신호 수 ──────────────────────────
    # 4 = 전부 충족 (보수적), 3 = 하나 완화 (기회 확대)
    "MIN_SIGNALS": 4,

    # ── Finviz 기본 필터 ───────────────────────────
    "MIN_AVG_VOLUME": "Over 200K",  # 유동성
    "MIN_PRICE":      "Over $5",    # 저가주 제외
    "COUNTRY":        "USA",

    # ── 처리 속도 ──────────────────────────────────
    "DELAY_BETWEEN_TICKERS": 0.3,   # 초 (rate limit 방지)
    "PRICE_HISTORY_PERIOD":  "250d", # SMA200 계산용
}

# ══════════════════════════════════════════════════
#  섹터 목록 (finvizfinance 정확한 표기)
# ══════════════════════════════════════════════════
SECTORS = [
    "Basic Materials",
    "Communication Services",
    "Consumer Cyclical",
    "Consumer Defensive",
    "Energy",
    "Financial",
    "Healthcare",
    "Industrials",
    "Real Estate",
    "Technology",
    "Utilities",
]

# ══════════════════════════════════════════════════
#  RSI 계산 (Wilder's smoothing, EWM alpha=1/n)
# ══════════════════════════════════════════════════
def calc_rsi(close_series: pd.Series, period: int = 2) -> pd.Series:
    delta = close_series.diff()
    gain  = delta.clip(lower=0).ewm(alpha=1/period, min_periods=period).mean()
    loss  = (-delta.clip(upper=0)).ewm(alpha=1/period, min_periods=period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return (100 - 100 / (1 + rs)).fillna(50)


# ══════════════════════════════════════════════════
#  Finviz 스크리닝 (섹터별)
# ══════════════════════════════════════════════════
def fetch_finviz_tickers(sector: str) -> list[str]:
    """
    Finviz로 1차 필터링:
      - SMA200 위 (상승추세)
      - 평균거래량 > 200K
      - 주가 > $5
      - 미국 종목
    RSI(2), IBS, RVOL은 yfinance에서 직접 계산
    """
    try:
        screener = Overview()
        screener.set_filter(filters_dict={
            "Sector":                        sector,
            "Country":                       CONFIG["COUNTRY"],
            "200-Day Simple Moving Average": "Price above SMA200",
            "Average Volume":                CONFIG["MIN_AVG_VOLUME"],
            "Price":                         CONFIG["MIN_PRICE"],
        })
        df = screener.screener_view(verbose=0)
        if df is None or df.empty:
            return []
        return df["Ticker"].dropna().tolist()
    except Exception as e:
        print(f"    [Finviz ERROR] {sector}: {e}")
        return []


# ══════════════════════════════════════════════════
#  개별 종목 분석
# ══════════════════════════════════════════════════
def analyze_ticker(ticker: str, sector: str) -> dict | None:
    """
    yfinance로 가격 데이터 다운로드 후
    IBS / RSI(2) / RVOL / SMA200 계산
    """
    try:
        raw = yf.download(
            ticker,
            period=CONFIG["PRICE_HISTORY_PERIOD"],
            interval="1d",
            progress=False,
            auto_adjust=True,
        )
        if raw is None or len(raw) < 30:
            return None

        # MultiIndex 컬럼 정리
        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        close  = raw["Close"].astype(float)
        high   = raw["High"].astype(float)
        low    = raw["Low"].astype(float)
        volume = raw["Volume"].astype(float)

        # ── 최신 확정 데이터 ───────────────────────
        c = close.iloc[-1]
        h = high.iloc[-1]
        l = low.iloc[-1]
        v = volume.iloc[-1]

        # ── IBS ────────────────────────────────────
        # IBS = (Close - Low) / (High - Low)
        # 0에 가까울수록 저점 근처 마감 → 반등 기대
        rng = h - l
        ibs = (c - l) / rng if rng > 0 else 0.5

        # ── RSI(2) ─────────────────────────────────
        rsi2 = calc_rsi(close, 2).iloc[-1]

        # ── RVOL (20일 평균 대비 당일 거래량) ─────
        avg_vol_20 = volume.iloc[-21:-1].mean()  # 당일 제외 20일
        rvol = v / avg_vol_20 if avg_vol_20 > 0 else 999.0

        # ── SMA200 ─────────────────────────────────
        sma200 = close.rolling(200).mean().iloc[-1]
        above_sma200 = bool(c > sma200)

        # ── 신호 체크 ──────────────────────────────
        ibs_ok    = ibs  < CONFIG["IBS_BUY_THRESHOLD"]
        rsi2_ok   = rsi2 < CONFIG["RSI2_BUY_THRESHOLD"]
        rvol_ok   = rvol < CONFIG["RVOL_MAX"]
        sma200_ok = above_sma200

        signals = []
        if ibs_ok:    signals.append("IBS✓")
        if rsi2_ok:   signals.append("RSI(2)✓")
        if sma200_ok: signals.append("SMA200✓")
        if rvol_ok:   signals.append("RVOL✓")

        if len(signals) < CONFIG["MIN_SIGNALS"]:
            return None

        # ── 신호 강도 점수 (랭킹용) ───────────────
        score = (
            (CONFIG["IBS_BUY_THRESHOLD"] - ibs) / CONFIG["IBS_BUY_THRESHOLD"] * 40 +
            (CONFIG["RSI2_BUY_THRESHOLD"] - rsi2) / CONFIG["RSI2_BUY_THRESHOLD"] * 40 +
            (CONFIG["RVOL_MAX"] - rvol) / CONFIG["RVOL_MAX"] * 20
        )

        return {
            "Ticker":       ticker,
            "Sector":       sector,
            "Close":        round(c, 2),
            "IBS":          round(ibs, 3),
            "RSI(2)":       round(rsi2, 1),
            "RVOL":         round(rvol, 2),
            "SMA200":       round(sma200, 2),
            "SMA200 OK":    "✓" if sma200_ok else "✗",
            "Signal Count": len(signals),
            "Signals":      " | ".join(signals),
            "Score":        round(score, 1),
        }

    except Exception:
        return None


# ══════════════════════════════════════════════════
#  매도 기준 체크 (보유 중 종목에 활용)
# ══════════════════════════════════════════════════
def check_exit_signal(ticker: str) -> dict:
    """
    보유 중인 종목의 매도 신호 체크
    usage: python apex_mr_screener.py exit AAPL MSFT TSLA
    """
    try:
        raw = yf.download(ticker, period="30d", interval="1d",
                          progress=False, auto_adjust=True)
        if raw is None or len(raw) < 5:
            return {"Ticker": ticker, "Exit": "데이터 없음"}

        if isinstance(raw.columns, pd.MultiIndex):
            raw.columns = raw.columns.get_level_values(0)

        close  = raw["Close"].astype(float)
        high   = raw["High"].astype(float)
        low    = raw["Low"].astype(float)

        c   = close.iloc[-1]
        h   = high.iloc[-1]
        l   = low.iloc[-1]
        rng = h - l
        ibs  = (c - l) / rng if rng > 0 else 0.5
        rsi2 = calc_rsi(close, 2).iloc[-1]

        exit_ibs  = ibs  > CONFIG["IBS_SELL_THRESHOLD"]
        exit_rsi2 = rsi2 > CONFIG["RSI2_SELL_THRESHOLD"]

        reasons = []
        if exit_ibs:  reasons.append(f"IBS={ibs:.3f}>0.80")
        if exit_rsi2: reasons.append(f"RSI(2)={rsi2:.1f}>65")

        return {
            "Ticker":  ticker,
            "Close":   round(c, 2),
            "IBS":     round(ibs, 3),
            "RSI(2)":  round(rsi2, 1),
            "Exit":    "★ 청산" if reasons else "보유",
            "Reason":  " | ".join(reasons) if reasons else "-",
        }
    except Exception as e:
        return {"Ticker": ticker, "Exit": f"오류: {e}"}


# ══════════════════════════════════════════════════
#  메인 스크리닝 루틴
# ══════════════════════════════════════════════════
def run_screener():
    print("\n" + "═" * 68)
    print("  APEX MR 단기 스크리너  |  IBS + RSI(2) Mean Reversion")
    print(f"  실행: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 68)
    print(f"  조건  : IBS < {CONFIG['IBS_BUY_THRESHOLD']}  │  RSI(2) < {CONFIG['RSI2_BUY_THRESHOLD']}  "
          f"│  SMA200 위  │  RVOL < {CONFIG['RVOL_MAX']}")
    print(f"  최소  : {CONFIG['MIN_SIGNALS']}개 충족 필요  │  "
          f"유동성: 평균거래량 {CONFIG['MIN_AVG_VOLUME']}")
    print(f"  매도  : IBS > 0.80 OR RSI(2) > 65  │  Time Stop: {CONFIG['TIME_STOP_DAYS']}거래일")
    print("═" * 68 + "\n")

    # ── 1단계: Finviz 섹터별 1차 스크리닝 ──────────
    print("▶ Step 1 │ Finviz 스크리닝 (SMA200 위 + 유동성 필터)")
    all_tickers: list[tuple[str, str]] = []

    for sector in SECTORS:
        tickers = fetch_finviz_tickers(sector)
        print(f"  {sector:<30} {len(tickers):>4}개")
        for t in tickers:
            all_tickers.append((t, sector))
        time.sleep(CONFIG["DELAY_BETWEEN_TICKERS"])

    # 중복 제거 (동일 종목이 여러 섹터에서 나올 경우 대비)
    seen: set[str] = set()
    unique: list[tuple[str, str]] = []
    for t, s in all_tickers:
        if t not in seen:
            seen.add(t)
            unique.append((t, s))

    total = len(unique)
    print(f"\n  → 1차 후보: {total}개 종목\n")

    if total == 0:
        print("✗ Finviz 결과 없음. 네트워크/Elite 구독 확인 필요.")
        return

    # ── 2단계: yfinance 정밀 분석 ──────────────────
    print(f"▶ Step 2 │ 정밀 분석 (IBS / RSI(2) / RVOL 계산)")
    results: list[dict] = []

    for i, (ticker, sector) in enumerate(unique):
        pct = (i + 1) / total * 100
        print(f"  [{i+1:4d}/{total}] {ticker:<8} {pct:5.1f}%", end="\r")
        result = analyze_ticker(ticker, sector)
        if result:
            results.append(result)
        time.sleep(CONFIG["DELAY_BETWEEN_TICKERS"])

    print()

    # ── 3단계: 결과 출력 ───────────────────────────
    if not results:
        print("\n  ✗ 조건 충족 종목 없음 (MIN_SIGNALS 낮추거나 내일 재시도)")
        return

    df = pd.DataFrame(results).sort_values(
        by=["Signal Count", "Score", "RSI(2)", "IBS"],
        ascending=[False, False, True, True],
    ).reset_index(drop=True)

    print("\n" + "═" * 68)
    print(f"  ✓ 매수 후보 종목: {len(df)}개")
    print("═" * 68)

    # 출력 컬럼 정리
    display_cols = ["Ticker", "Sector", "Close", "IBS", "RSI(2)",
                    "RVOL", "SMA200", "Signal Count", "Score"]
    print(df[display_cols].to_string(index=True))

    # ── 섹터별 요약 ─────────────────────────────────
    print("\n▶ 섹터별 분포:")
    sec_summary = df.groupby("Sector")["Ticker"].count().sort_values(ascending=False)
    for sec, cnt in sec_summary.items():
        bar = "█" * cnt
        print(f"  {sec:<30} {cnt:>3}개  {bar}")

    # ── 탑 픽 ─────────────────────────────────────
    print("\n▶ Top 5 후보 (신호 강도 기준):")
    top5 = df.head(5)
    for _, row in top5.iterrows():
        print(f"  {row['Ticker']:<8} │ IBS={row['IBS']:.3f} │ RSI(2)={row['RSI(2)']:.1f} │ "
              f"RVOL={row['RVOL']:.2f} │ Score={row['Score']:.1f} │ {row['Sector']}")

    # ── CSV 저장 ───────────────────────────────────
    ts   = datetime.now().strftime("%Y%m%d_%H%M")
    fname = f"mr_signals_{ts}.csv"
    df.to_csv(fname, index=False, encoding="utf-8-sig")
    print(f"\n  → CSV 저장: {fname}")

    # ── 매도 기준 리마인더 ──────────────────────────
    print("\n" + "─" * 68)
    print("  [매도 기준]")
    print(f"  • 익중  : IBS > 0.80  OR  RSI(2) > 65 → 당일 마감 전 청산")
    print(f"  • 타임스탑: {CONFIG['TIME_STOP_DAYS']}거래일 경과 시 무조건 청산")
    print(f"  • APEX 2.0 MR 룰 병행 시: SMA20 종가 이탈 = 즉시 청산")
    print("─" * 68 + "\n")


# ══════════════════════════════════════════════════
#  보유 중 종목 매도 신호 체크 모드
# ══════════════════════════════════════════════════
def run_exit_check(tickers: list[str]):
    print("\n" + "═" * 50)
    print("  매도 신호 체크  |  보유 종목")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("═" * 50)

    results = []
    for t in tickers:
        r = check_exit_signal(t.upper())
        results.append(r)
        time.sleep(CONFIG["DELAY_BETWEEN_TICKERS"])

    df = pd.DataFrame(results)
    print(df.to_string(index=False))

    exits = df[df["Exit"] == "★ 청산"]
    if not exits.empty:
        print(f"\n  ★ 청산 대상: {', '.join(exits['Ticker'].tolist())}")
    else:
        print("\n  → 전 종목 보유 유지")


# ══════════════════════════════════════════════════
#  단일 종목 상세 분석 모드
# ══════════════════════════════════════════════════
def run_single(ticker: str):
    print(f"\n  [{ticker}] 상세 분석")
    print("─" * 40)
    result = analyze_ticker(ticker.upper(), "N/A")
    exit_r = check_exit_signal(ticker.upper())

    if result:
        for k, v in result.items():
            print(f"  {k:<15}: {v}")
        print(f"  {'매도 신호':<15}: {exit_r.get('Exit','N/A')}  {exit_r.get('Reason','')}")
    else:
        print(f"  조건 미충족 종목 (신호: {CONFIG['MIN_SIGNALS']}개 미달)")
        # 원시값 출력
        r = check_exit_signal(ticker.upper())
        for k, v in r.items():
            print(f"  {k:<15}: {v}")


# ══════════════════════════════════════════════════
#  엔트리 포인트
# ══════════════════════════════════════════════════
if __name__ == "__main__":
    """
    실행 방법:
      1. 전체 스크리닝    : python apex_mr_screener.py
      2. 매도 신호 체크   : python apex_mr_screener.py exit AAPL MSFT TSLA
      3. 단일 종목 분석   : python apex_mr_screener.py check AAPL
    """
    args = sys.argv[1:]

    if not args:
        run_screener()

    elif args[0].lower() == "exit" and len(args) > 1:
        run_exit_check(args[1:])

    elif args[0].lower() == "check" and len(args) > 1:
        run_single(args[1])

    else:
        print("사용법:")
        print("  python apex_mr_screener.py              # 전체 스크리닝")
        print("  python apex_mr_screener.py exit AAPL   # 매도 체크")
        print("  python apex_mr_screener.py check AAPL  # 단일 분석")
