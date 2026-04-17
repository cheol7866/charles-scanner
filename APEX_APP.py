"""
============================================================
  진입 신호 스캐너 (Signal Scanner)
  ----------------------------------------------------------
  여러 기술적 지표를 조합해 매수/매도 시그널을 자동 탐지합니다.

  사용 라이브러리: bukosabino/ta (MIT License)
  데이터 소스: yfinance (Yahoo Finance)

  실행 방법:
    python signal_scanner.py

  필수 패키지 설치:
    pip install yfinance ta pandas numpy
============================================================
"""

import sys
import warnings
warnings.filterwarnings('ignore')

import pandas as pd
import numpy as np
import yfinance as yf

from ta.momentum import RSIIndicator, StochasticOscillator
from ta.trend import SMAIndicator, EMAIndicator, MACD, ADXIndicator
from ta.volatility import BollingerBands, AverageTrueRange
from ta.volume import OnBalanceVolumeIndicator


# ============================================================
#  1. 데이터 수집
# ============================================================
def fetch_data(ticker: str, period: str = "1y") -> pd.DataFrame:
    """yfinance로 OHLCV 데이터를 가져옵니다."""
    print(f"\n[{ticker}] 데이터 수집 중...")
    df = yf.download(ticker, period=period, progress=False, auto_adjust=True)

    if df.empty:
        print(f"  ERROR: {ticker} 데이터를 가져올 수 없습니다.")
        return None

    # yfinance 최신 버전은 MultiIndex 컬럼을 반환 → 단일 레벨로 평탄화
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)

    df = df.dropna()
    print(f"  [OK] {len(df)}개 봉 수집 완료 (기간: {df.index[0].date()} ~ {df.index[-1].date()})")
    return df


# ============================================================
#  2. 지표 계산 (ta 라이브러리 활용)
# ============================================================
def compute_indicators(df: pd.DataFrame) -> pd.DataFrame:
    """주요 기술적 지표를 계산해 컬럼으로 추가합니다."""
    close, high, low, volume = df['Close'], df['High'], df['Low'], df['Volume']

    # 추세 (Trend)
    df['SMA20']  = SMAIndicator(close=close, window=20).sma_indicator()
    df['SMA50']  = SMAIndicator(close=close, window=50).sma_indicator()
    df['SMA200'] = SMAIndicator(close=close, window=200).sma_indicator()
    df['EMA12']  = EMAIndicator(close=close, window=12).ema_indicator()
    df['EMA26']  = EMAIndicator(close=close, window=26).ema_indicator()

    # MACD
    macd = MACD(close=close, window_slow=26, window_fast=12, window_sign=9)
    df['MACD']        = macd.macd()
    df['MACD_signal'] = macd.macd_signal()
    df['MACD_diff']   = macd.macd_diff()

    # 모멘텀 (Momentum)
    df['RSI14'] = RSIIndicator(close=close, window=14).rsi()
    df['RSI2']  = RSIIndicator(close=close, window=2).rsi()
    stoch = StochasticOscillator(high=high, low=low, close=close, window=14, smooth_window=3)
    df['Stoch_K'] = stoch.stoch()
    df['Stoch_D'] = stoch.stoch_signal()

    # 변동성 (Volatility)
    bb = BollingerBands(close=close, window=20, window_dev=2)
    df['BB_upper']  = bb.bollinger_hband()
    df['BB_middle'] = bb.bollinger_mavg()
    df['BB_lower']  = bb.bollinger_lband()
    df['BB_pband']  = bb.bollinger_pband()  # %B (0~1 정규화)
    df['ATR14']     = AverageTrueRange(high=high, low=low, close=close, window=14).average_true_range()

    # 추세 강도 (ADX)
    adx = ADXIndicator(high=high, low=low, close=close, window=14)
    df['ADX']     = adx.adx()
    df['ADX_pos'] = adx.adx_pos()
    df['ADX_neg'] = adx.adx_neg()

    # 거래량
    df['OBV']     = OnBalanceVolumeIndicator(close=close, volume=volume).on_balance_volume()
    df['Vol_MA20'] = volume.rolling(20).mean()
    df['RVOL']    = volume / df['Vol_MA20']  # 상대 거래량

    return df


# ============================================================
#  3. 시그널 탐지 로직
# ============================================================
def detect_signals(df: pd.DataFrame) -> pd.DataFrame:
    """각 봉마다 매수/매도 시그널 조건을 평가합니다."""

    # ---------- 매수 시그널 (BUY) ----------
    # [BUY-1] 골든크로스 (SMA50이 SMA200을 상향 돌파)
    df['BUY_golden_cross'] = (
        (df['SMA50'] > df['SMA200']) &
        (df['SMA50'].shift(1) <= df['SMA200'].shift(1))
    )

    # [BUY-2] MACD 상향 돌파 (MACD선이 Signal선 위로)
    df['BUY_macd_cross'] = (
        (df['MACD'] > df['MACD_signal']) &
        (df['MACD'].shift(1) <= df['MACD_signal'].shift(1))
    )

    # [BUY-3] RSI 과매도 반등 (RSI14가 30 밑에서 위로 돌파)
    df['BUY_rsi_oversold'] = (
        (df['RSI14'] > 30) &
        (df['RSI14'].shift(1) <= 30)
    )

    # [BUY-4] 볼린저 밴드 하단 터치 후 복귀 + 거래량 증가
    df['BUY_bb_bounce'] = (
        (df['Close'].shift(1) < df['BB_lower'].shift(1)) &
        (df['Close'] > df['BB_lower']) &
        (df['RVOL'] > 1.2)
    )

    # [BUY-5] 강한 상승 추세 초입 (ADX > 25, +DI > -DI, 추세 가속)
    df['BUY_adx_trend'] = (
        (df['ADX'] > 25) &
        (df['ADX_pos'] > df['ADX_neg']) &
        (df['ADX'] > df['ADX'].shift(1)) &
        (df['Close'] > df['SMA50'])
    )

    # ---------- 매도 시그널 (SELL) ----------
    # [SELL-1] 데드크로스
    df['SELL_dead_cross'] = (
        (df['SMA50'] < df['SMA200']) &
        (df['SMA50'].shift(1) >= df['SMA200'].shift(1))
    )

    # [SELL-2] MACD 하향 돌파
    df['SELL_macd_cross'] = (
        (df['MACD'] < df['MACD_signal']) &
        (df['MACD'].shift(1) >= df['MACD_signal'].shift(1))
    )

    # [SELL-3] RSI 과매수 이탈
    df['SELL_rsi_overbought'] = (
        (df['RSI14'] < 70) &
        (df['RSI14'].shift(1) >= 70)
    )

    # [SELL-4] 볼린저 상단 이탈 후 반락
    df['SELL_bb_rejection'] = (
        (df['Close'].shift(1) > df['BB_upper'].shift(1)) &
        (df['Close'] < df['BB_upper'])
    )

    # ---------- 종합 점수 (Composite Score) ----------
    buy_cols  = [c for c in df.columns if c.startswith('BUY_')]
    sell_cols = [c for c in df.columns if c.startswith('SELL_')]
    df['BUY_score']  = df[buy_cols].sum(axis=1)
    df['SELL_score'] = df[sell_cols].sum(axis=1)
    df['NET_score']  = df['BUY_score'] - df['SELL_score']

    return df


# ============================================================
#  4. 결과 출력
# ============================================================
def print_latest_status(df: pd.DataFrame, ticker: str):
    """가장 최근 봉의 상태를 요약 출력합니다."""
    latest = df.iloc[-1]

    print("\n" + "=" * 60)
    print(f"  [{ticker}] 최신 스냅샷 ({df.index[-1].date()})")
    print("=" * 60)
    print(f"  종가:       ${latest['Close']:,.2f}")
    print(f"  RSI(14):    {latest['RSI14']:.1f}")
    print(f"  RSI(2):     {latest['RSI2']:.1f}")
    print(f"  ADX:        {latest['ADX']:.1f}  (+DI {latest['ADX_pos']:.1f} / -DI {latest['ADX_neg']:.1f})")
    print(f"  BB %B:      {latest['BB_pband']:.2f}  (0=하단, 1=상단)")
    print(f"  ATR(14):    ${latest['ATR14']:.2f}  ({latest['ATR14']/latest['Close']*100:.1f}% of price)")
    print(f"  RVOL:       {latest['RVOL']:.2f}x")

    # 추세 판정
    trend = "UPTREND" if latest['Close'] > latest['SMA200'] else "DOWNTREND"
    above_50 = "YES" if latest['Close'] > latest['SMA50'] else "NO"
    print(f"  추세:       {trend} (SMA200 기준) / SMA50 위: {above_50}")


def print_recent_signals(df: pd.DataFrame, ticker: str, lookback: int = 30):
    """최근 N일 내 발생한 시그널을 리스팅합니다."""
    recent = df.iloc[-lookback:].copy()

    buy_cols  = [c for c in df.columns if c.startswith('BUY_')]
    sell_cols = [c for c in df.columns if c.startswith('SELL_')]

    print("\n" + "=" * 60)
    print(f"  [{ticker}] 최근 {lookback}일 시그널 발생 기록")
    print("=" * 60)

    events = []
    for date, row in recent.iterrows():
        for col in buy_cols:
            if row[col]:
                events.append((date.date(), 'BUY', col.replace('BUY_', ''), row['Close']))
        for col in sell_cols:
            if row[col]:
                events.append((date.date(), 'SELL', col.replace('SELL_', ''), row['Close']))

    if not events:
        print("  (발생한 시그널 없음)")
        return

    for date, side, name, price in events:
        marker = "[BUY ]" if side == 'BUY' else "[SELL]"
        print(f"  {date} {marker} {name:25s}  @ ${price:,.2f}")


def print_current_signal_strength(df: pd.DataFrame, ticker: str):
    """가장 최근 봉의 시그널 강도를 표시합니다."""
    latest = df.iloc[-1]

    print("\n" + "=" * 60)
    print(f"  [{ticker}] 오늘의 시그널 점수")
    print("=" * 60)
    print(f"  매수 점수 (BUY):   {int(latest['BUY_score'])} / 5")
    print(f"  매도 점수 (SELL):  {int(latest['SELL_score'])} / 4")
    print(f"  순 점수 (NET):     {int(latest['NET_score']):+d}")

    # 활성화된 시그널 나열
    active_buys  = [c.replace('BUY_','')  for c in df.columns if c.startswith('BUY_')  and latest[c]]
    active_sells = [c.replace('SELL_','') for c in df.columns if c.startswith('SELL_') and latest[c]]

    if active_buys:
        print(f"\n  [활성 매수 시그널]")
        for s in active_buys:
            print(f"    - {s}")
    if active_sells:
        print(f"\n  [활성 매도 시그널]")
        for s in active_sells:
            print(f"    - {s}")
    if not active_buys and not active_sells:
        print("\n  (오늘 활성화된 시그널 없음 - 관망)")


# ============================================================
#  5. 메인 실행 루프
# ============================================================
def scan_ticker(ticker: str, period: str = "1y"):
    """단일 티커 전체 스캔 파이프라인."""
    df = fetch_data(ticker, period=period)
    if df is None or len(df) < 200:
        print(f"  [SKIP] 데이터 부족 (최소 200봉 필요)")
        return

    df = compute_indicators(df)
    df = detect_signals(df)

    print_latest_status(df, ticker)
    print_current_signal_strength(df, ticker)
    print_recent_signals(df, ticker, lookback=30)


def main():
    print("=" * 60)
    print("         진입 신호 스캐너 (Signal Scanner)")
    print("         Powered by ta library + yfinance")
    print("=" * 60)

    user_input = input("\n티커 입력 (여러 개는 쉼표로 구분, 예: AAPL,MSFT,NVDA): ").strip()
    if not user_input:
        print("티커가 입력되지 않았습니다. 종료합니다.")
        return

    tickers = [t.strip().upper() for t in user_input.split(',') if t.strip()]
    period = input("조회 기간 (기본 1y, 예: 6mo/1y/2y/5y): ").strip() or "1y"

    for ticker in tickers:
        try:
            scan_ticker(ticker, period=period)
        except Exception as e:
            print(f"\n  [ERROR] {ticker} 처리 중 오류: {e}")

    print("\n" + "=" * 60)
    print("  스캔 완료")
    print("=" * 60)


if __name__ == "__main__":
    main()
