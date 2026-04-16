"""
APEX MR Strategy — 과매도 구간 포착 및 반등 매수 전략
======================================================
조건:
  1) RSI(14) ≤ 30 진입 후 30 상향 돌파 (RSI Cross-Up)
  2) 주가가 볼린저 밴드 하단선 이하 또는 근접 (허용 오차: BB 폭의 2%)
  3) 상승 다이버전스 (Bullish Divergence): 가격 저점 하락 + RSI 저점 상승

Author  : APEX System / Charles Jung
Date    : 2026-04-17
Requires: yfinance, pandas_ta, pandas, numpy
"""

import warnings
warnings.filterwarnings("ignore")

import sys
import numpy as np
import pandas as pd
import pandas_ta as ta

# ─────────────────────────────────────────────
# 0. 설정값 (상단에서 한 번에 관리)
# ─────────────────────────────────────────────
CONFIG = {
    "tickers"           : ["AAPL", "MSFT", "NVDA", "TSLA", "META"],
    "period"            : "1y",          # yfinance 다운로드 기간
    "rsi_period"        : 14,
    "bb_period"         : 20,
    "bb_std"            : 2.0,
    "rsi_oversold"      : 30,            # RSI 과매도 기준선
    "bb_proximity_pct"  : 0.02,          # BB 하단 근접 허용 오차 (2%)
    "div_lookback"      : 14,            # 다이버전스 감지 lookback 기간(봉)
    "div_rsi_min_rise"  : 2.0,           # 다이버전스 RSI 최소 상승폭
}

# ─────────────────────────────────────────────
# 1. 데이터 다운로드
# ─────────────────────────────────────────────
def download_data(ticker: str, period: str) -> pd.DataFrame:
    """
    yfinance로 OHLCV 데이터 다운로드.
    멀티-레벨 컬럼을 단일 레벨로 정규화하고, 결측치 처리 후 반환.
    """
    try:
        import yfinance as yf
        raw = yf.download(ticker, period=period, progress=False, auto_adjust=True)
    except ImportError:
        raise SystemExit("[ERROR] yfinance가 설치되지 않았습니다. pip install yfinance")
    except Exception as e:
        raise RuntimeError(f"[ERROR] {ticker} 다운로드 실패: {e}")

    if raw.empty:
        raise ValueError(f"[WARN] {ticker}: 수신된 데이터가 없습니다.")

    # ── 멀티-레벨 컬럼 평탄화 (yfinance ≥0.2.x 대응)
    if isinstance(raw.columns, pd.MultiIndex):
        raw.columns = raw.columns.get_level_values(0)

    # ── 필수 컬럼 확인
    required = {"Open", "High", "Low", "Close", "Volume"}
    missing = required - set(raw.columns)
    if missing:
        raise ValueError(f"[ERROR] {ticker}: 누락 컬럼 {missing}")

    df = raw[list(required)].copy()

    # ── 인덱스 정렬 & 결측치 처리
    df = df.sort_index()
    df = df.dropna(subset=["Close", "High", "Low"])   # 가격 결측 행 제거
    df["Volume"] = df["Volume"].fillna(0)

    if len(df) < 60:
        raise ValueError(f"[WARN] {ticker}: 데이터가 부족합니다 ({len(df)}봉 < 60봉).")

    return df


# ─────────────────────────────────────────────
# 2. 기술 지표 계산
# ─────────────────────────────────────────────
def compute_indicators(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    RSI, 볼린저 밴드 계산 (pandas_ta 사용).
    충분한 데이터가 없을 경우 ValueError를 발생시킨다.
    """
    min_required = max(cfg["rsi_period"], cfg["bb_period"]) * 3
    if len(df) < min_required:
        raise ValueError(f"지표 계산에 필요한 최소 데이터({min_required}봉)가 부족합니다.")

    # RSI
    df["RSI"] = ta.rsi(df["Close"], length=cfg["rsi_period"])

    # 볼린저 밴드
    bb = ta.bbands(
        df["Close"],
        length=cfg["bb_period"],
        std=cfg["bb_std"]
    )
    # pandas_ta bbands 컬럼명 예시: BBL_20_2.0, BBM_20_2.0, BBU_20_2.0, BBB_20_2.0
    bb_cols = bb.columns.tolist()
    lower_col = [c for c in bb_cols if c.startswith("BBL")][0]
    upper_col = [c for c in bb_cols if c.startswith("BBU")][0]
    mid_col   = [c for c in bb_cols if c.startswith("BBM")][0]

    df["BB_Lower"] = bb[lower_col]
    df["BB_Upper"] = bb[upper_col]
    df["BB_Mid"]   = bb[mid_col]
    df["BB_Width"] = df["BB_Upper"] - df["BB_Lower"]   # 변동성 척도

    # 지표 계산 구간 NaN 제거
    df = df.dropna(subset=["RSI", "BB_Lower", "BB_Upper"])

    return df


# ─────────────────────────────────────────────
# 3. 필터 1 — RSI 30 상향 돌파
# ─────────────────────────────────────────────
def filter_rsi_crossup(df: pd.DataFrame, oversold: int = 30) -> pd.Series:
    """
    RSI가 전봉에 ≤ oversold 이고 현봉에 > oversold 인 날 True.
    즉, 과매도 구간에서 벗어나는 첫 번째 봉만 포착.
    """
    prev_rsi = df["RSI"].shift(1)
    signal   = (prev_rsi <= oversold) & (df["RSI"] > oversold)
    return signal.rename("RSI_CrossUp")


# ─────────────────────────────────────────────
# 4. 필터 2 — 볼린저 밴드 하단 근접
# ─────────────────────────────────────────────
def filter_bb_proximity(df: pd.DataFrame, proximity_pct: float = 0.02) -> pd.Series:
    """
    Close ≤ BB_Lower * (1 + proximity_pct) 이면 True.
    proximity_pct = 0.02 → BB 하단 대비 2% 이내까지 허용.
    """
    threshold = df["BB_Lower"] * (1 + proximity_pct)
    signal    = df["Close"] <= threshold
    return signal.rename("Near_BB_Lower")


# ─────────────────────────────────────────────
# 5. 필터 3 — 상승 다이버전스 (Bullish Divergence)
# ─────────────────────────────────────────────
def filter_bullish_divergence(
    df: pd.DataFrame,
    lookback: int = 14,
    rsi_min_rise: float = 2.0
) -> pd.Series:
    """
    현재 봉 기준 lookback 기간 내에서:
      - Close 저점이 이전 저점보다 낮고 (가격 하락)
      - RSI  저점이 이전 저점보다 높으면 (RSI 상승)
    → 상승 다이버전스 조건 충족 → True 반환

    알고리즘:
      현봉의 RSI, Close와 과거 lookback 기간 내 최저 RSI/Close를 비교.
      단순 슬라이딩 윈도우 방식 (신호 감도와 계산 효율의 균형).
    """
    result = pd.Series(False, index=df.index, name="Bullish_Div")

    close = df["Close"].values
    rsi   = df["RSI"].values
    idx   = df.index

    for i in range(lookback, len(df)):
        window_close = close[i - lookback : i]
        window_rsi   = rsi[i - lookback : i]

        prev_close_low = np.min(window_close)
        prev_rsi_low   = np.min(window_rsi)

        cur_close = close[i]
        cur_rsi   = rsi[i]

        price_lower = cur_close < prev_close_low          # 가격: 신저점
        rsi_higher  = cur_rsi   > prev_rsi_low + rsi_min_rise  # RSI: 저점 상승

        if price_lower and rsi_higher:
            result.iloc[i] = True

    return result


# ─────────────────────────────────────────────
# 6. 신호 통합 & 출력 데이터프레임 생성
# ─────────────────────────────────────────────
def generate_signals(df: pd.DataFrame, cfg: dict) -> pd.DataFrame:
    """
    세 가지 필터를 AND 조건으로 결합하여 최종 매수 신호를 생성.
    """
    df = df.copy()

    # 필터 적용
    df["RSI_CrossUp"]   = filter_rsi_crossup(df, cfg["rsi_oversold"])
    df["Near_BB_Lower"] = filter_bb_proximity(df, cfg["bb_proximity_pct"])
    df["Bullish_Div"]   = filter_bullish_divergence(
                              df, cfg["div_lookback"], cfg["div_rsi_min_rise"]
                          )

    # 최종 신호: 세 조건 모두 충족
    df["BUY_SIGNAL"] = df["RSI_CrossUp"] & df["Near_BB_Lower"] & df["Bullish_Div"]

    return df


# ─────────────────────────────────────────────
# 7. 결과 포맷팅
# ─────────────────────────────────────────────
def extract_signal_rows(ticker: str, df: pd.DataFrame) -> pd.DataFrame:
    """
    BUY_SIGNAL == True 인 행만 추출하여 가독성 좋은 DataFrame 반환.
    """
    cols = ["Close", "RSI", "BB_Lower", "BB_Width",
            "RSI_CrossUp", "Near_BB_Lower", "Bullish_Div", "BUY_SIGNAL"]
    signals = df.loc[df["BUY_SIGNAL"], cols].copy()

    if signals.empty:
        return signals

    signals.insert(0, "Ticker", ticker)
    signals.index.name = "Date"

    # 수치 반올림
    for col in ["Close", "RSI", "BB_Lower", "BB_Width"]:
        signals[col] = signals[col].round(2)

    return signals


# ─────────────────────────────────────────────
# 8. 메인 실행 루프
# ─────────────────────────────────────────────
def run_strategy(cfg: dict) -> pd.DataFrame:
    all_results = []

    for ticker in cfg["tickers"]:
        print(f"\n{'─'*50}")
        print(f"  Processing: {ticker}")
        print(f"{'─'*50}")
        try:
            # 데이터 수집
            df = download_data(ticker, cfg["period"])
            print(f"  [OK] 데이터 수신: {len(df)}봉 ({df.index[0].date()} ~ {df.index[-1].date()})")

            # 지표 계산
            df = compute_indicators(df, cfg)
            print(f"  [OK] 지표 계산 완료 (RSI, BB)")

            # 신호 생성
            df = generate_signals(df, cfg)

            signal_count = df["BUY_SIGNAL"].sum()
            print(f"  [OK] 매수 신호 발생: {signal_count}건")

            # 결과 추출
            result = extract_signal_rows(ticker, df)
            if not result.empty:
                all_results.append(result)

        except ValueError as e:
            print(f"  [SKIP] {ticker}: {e}")
        except RuntimeError as e:
            print(f"  [ERROR] {ticker}: {e}")
        except Exception as e:
            print(f"  [UNEXPECTED] {ticker}: {type(e).__name__}: {e}")

    if not all_results:
        print("\n[결과] 매수 신호가 발생한 종목이 없습니다.")
        return pd.DataFrame()

    final_df = pd.concat(all_results).sort_index()
    return final_df


# ─────────────────────────────────────────────
# 9. 진입점
# ─────────────────────────────────────────────
if __name__ == "__main__":

    print("=" * 50)
    print("  APEX MR Strategy — 과매도 반등 매수 신호 스캐너")
    print("=" * 50)

    results = run_strategy(CONFIG)

    if not results.empty:
        print("\n\n★ 최종 매수 신호 요약 ★")
        print("=" * 80)
        pd.set_option("display.max_columns", None)
        pd.set_option("display.width", 120)
        pd.set_option("display.float_format", "{:.2f}".format)
        print(results.to_string())

        # CSV 저장
        out_path = "apex_mr_signals.csv"
        results.to_csv(out_path)
        print(f"\n[저장] {out_path}")

    else:
        print("\n해당 기간 내 조건을 충족하는 신호가 없습니다.")
        print("CONFIG의 bb_proximity_pct 또는 div_rsi_min_rise 값을 완화해 보세요.")
