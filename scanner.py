"""
찰스 트레이딩 스캐너 v1.0
매일 자동 실행 → S&P500 전 종목 스크린 → Claude 분석 → Gmail 알림
"""

import yfinance as yf
import pandas as pd
import numpy as np
import anthropic
import smtplib
import json
import time
import logging
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

# ════════════════════════════════════════════════
#  ★ 설정 (여기만 수정하세요)
# ════════════════════════════════════════════════
import os

# ★ 로컬 실행 시: 아래 직접 입력
# ★ GitHub Actions 실행 시: Secrets에서 자동으로 읽음
_API_KEY   = os.environ.get("ANTHROPIC_API_KEY", "sk-ant-여기에입력")
_GMAIL_PW  = os.environ.get("GMAIL_APP_PW",      "앱비밀번호16자리")
_GMAIL_SNS = os.environ.get("GMAIL_SENDER",      "보내는계정@gmail.com")

CONFIG = {
    "ANTHROPIC_API_KEY": _API_KEY,
    "GMAIL_SENDER":      _GMAIL_SNS,
    "GMAIL_APP_PW":      _GMAIL_PW,
    "GMAIL_RECEIVER":    _GMAIL_SNS,   # 본인에게 발송

    # 스캔 설정
    "TOP_N": 5,               # 최종 추천 종목 수
    "MAX_CLAUDE_CALLS": 15,   # Claude API 호출 최대 종목 수 (비용 제한)
    "PRICE_MIN": 5,           # 종목 최소 가격
    "PRICE_MAX": 500,         # 종목 최대 가격
}
# ════════════════════════════════════════════════

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("scanner.log", encoding="utf-8"),
        logging.StreamHandler()
    ]
)
log = logging.getLogger(__name__)


# ── S&P500 + NASDAQ 종목 리스트 ─────────────────
def get_all_tickers():
    import urllib.request, io
    tickers = set()

    # ── S&P500: GitHub CSV ──
    try:
        url = "https://raw.githubusercontent.com/datasets/s-and-p-500-companies/main/data/constituents.csv"
        with urllib.request.urlopen(url, timeout=10) as r:
            df = pd.read_csv(io.StringIO(r.read().decode()))
        sp5 = [t.replace(".", "-") for t in df["Symbol"].tolist()]
        tickers.update(sp5)
        log.info(f"S&P500 {len(sp5)}종목 로드 (GitHub)")
    except Exception as e:
        log.warning(f"S&P500 GitHub 오류: {e}")

    # ── NASDAQ-100: Wikipedia ──
    try:
        req = urllib.request.Request(
            "https://en.wikipedia.org/wiki/Nasdaq-100",
            headers={"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        )
        with urllib.request.urlopen(req, timeout=10) as r:
            tables = pd.read_html(io.StringIO(r.read().decode()))
        # 티커 컬럼 찾기
        nq100 = []
        for t in tables:
            if "Ticker" in t.columns:
                nq100 = [str(x).replace(".", "-").strip() for x in t["Ticker"].tolist()]
                break
            elif "Symbol" in t.columns:
                nq100 = [str(x).replace(".", "-").strip() for x in t["Symbol"].tolist()]
                break
        if nq100:
            tickers.update(nq100)
            log.info(f"NASDAQ100 {len(nq100)}종목 로드 (Wikipedia)")
        else:
            raise ValueError("NASDAQ100 테이블 파싱 실패")
    except Exception as e:
        log.warning(f"NASDAQ100 Wikipedia 오류: {e} → 하드코딩 사용")
        # 하드코딩 NASDAQ100 (2024 기준)
        nq100_fallback = [
            "AAPL","MSFT","NVDA","AMZN","META","TSLA","GOOGL","GOOG","AVGO","COST",
            "NFLX","TMUS","ASML","CSCO","AMD","ADBE","QCOM","INTU","AMAT","TXN",
            "ISRG","AMGN","PDD","BKNG","MU","VRTX","PANW","ADP","LRCX","SBUX",
            "KLAC","MELI","INTC","MDLZ","REGN","CTAS","SNPS","CDNS","MAR","PYPL",
            "CRWD","ORLY","ABNB","NXPI","FTNT","MNST","MRVL","ADSK","PAYX","CHTR",
            "PCAR","CPRT","WDAY","MRNA","DXCM","KDP","MCHP","ROST","IDXX","AEP",
            "ODFL","LULU","BIIB","EA","CTSH","DDOG","TEAM","FAST","VRSK","XEL",
            "GEHC","FANG","CSGP","ON","CDW","CCEP","DLTR","BKR","ANSS","EXC",
            "ILMN","GFS","TTWO","WBA","SIRI","ZS","ALGN","ENPH","JD","LCID",
            "RIVN","DASH","RBLX","COIN","HOOD","PLTR","SOFI","IONQ","SOUN","MSTR"
        ]
        tickers.update(nq100_fallback)
        log.info(f"NASDAQ100 {len(nq100_fallback)}종목 로드 (하드코딩)")

    # ── 두 소스 다 실패 → 폴백 300종목 ──
    if len(tickers) < 100:
        log.warning("폴백 종목 리스트 사용")
        fallback = [
            # S&P500 대표
            "AAPL","MSFT","NVDA","AMZN","GOOGL","META","TSLA","BRK-B","JPM","V",
            "UNH","XOM","LLY","JNJ","MA","PG","AVGO","HD","MRK","CVX",
            "ABBV","COST","PEP","KO","WMT","BAC","CRM","NFLX","TMO","CSCO",
            "ACN","MCD","NKE","DHR","TXN","NEE","PM","RTX","ORCL","AMGN",
            "QCOM","HON","UPS","IBM","GS","CAT","SBUX","INTU","SPGI","AXP",
            "LOW","ISRG","BLK","ELV","MDLZ","DE","REGN","ZTS","ADI","VRTX",
            "PLD","CI","MMC","GILD","SYK","BSX","EOG","CB","SO","DUK",
            "MO","ITW","HCA","KLAC","PNC","ADP","WM","CL","AON","CME",
            # NASDAQ 중소형 (전략 적합)
            "PLTR","SOFI","HOOD","COIN","RIVN","DKNG","IONQ","SOUN","MSTR","SMCI",
            "UPST","AFRM","RBLX","U","SNAP","PINS","LYFT","UBER","DASH","ABNB",
            "ROKU","ZM","BILL","DOCN","DDOG","NET","CRWD","S","ASAN","GTLB",
            "MARA","RIOT","CORZ","WULF","IREN","APLD","HUT","BTBT","CIFR","BTDR",
            "NVAX","SRPT","IONS","ALNY","BMRN","EXEL","INCY","NBIX","ACAD","SAGE",
            "AMD","INTC","MU","MRVL","SWKS","MPWR","ENPH","SEDG","FSLR","PLUG",
            "LCID","NKLA","FSR","WKHS","FFIE","GOEV","ARVL","RIDE","HYLN","BLNK",
            "DUOL","LMND","OPEN","RKT","TREE","COUR","BARK","UWMC","GHLD","DLO",
            "WOLF","FIGS","ACMR","JAMF","NCNO","TOST","RELY","VERA","HUBS","ZOOM",
            "SMAR","PCVX","DNLI","RCKT","ACLS","FORM","AMBA","POWI","DIOD","COHU",
            # 추가 인기 종목
            "TSLA","PYPL","SQ","TWLO","OKTA","ZS","PANW","SPLK","MDB","SNOW",
            "DKNG","LYFT","ABNB","RDFN","OPEN","PRPL","BYND","OZON","SE","GRAB",
        ]
        tickers.update(fallback)

    result = sorted(tickers)
    log.info(f"총 스캔 대상: {len(result)}종목 (S&P500 + NASDAQ 중복제거)")
    return result

# 하위 호환용 별칭
def get_sp500_tickers():
    return get_all_tickers()


# ── 지표 계산 ────────────────────────────────────
def calc_indicators(tk: str) -> dict | None:
    try:
        df = yf.download(tk, period="1y", interval="1d", progress=False, auto_adjust=True)
        if df is None or len(df) < 50:
            return None

        c = df["Close"].values.flatten()
        h = df["High"].values.flatten()
        l = df["Low"].values.flatten()
        v = df["Volume"].values.flatten()

        # 가격 필터
        price = float(c[-1])
        if not (CONFIG["PRICE_MIN"] <= price <= CONFIG["PRICE_MAX"]):
            return None

        def sma(n):
            return float(np.mean(c[-n:])) if len(c) >= n else None

        def ema_arr(arr, n):
            if len(arr) < n:
                return np.array([])
            k = 2 / (n + 1)
            emas = [np.mean(arr[:n])]
            for val in arr[n:]:
                emas.append(val * k + emas[-1] * (1 - k))
            return np.array(emas)

        def calc_rsi(n):
            need = n * 3 + 1
            if len(c) < need:
                return None
            sl = c[-need:]
            gains, losses = [], []
            for i in range(1, n + 1):
                d = sl[i] - sl[i - 1]
                gains.append(max(d, 0))
                losses.append(max(-d, 0))
            ag, al = np.mean(gains), np.mean(losses)
            for i in range(n + 1, len(sl)):
                d = sl[i] - sl[i - 1]
                ag = (ag * (n - 1) + max(d, 0)) / n
                al = (al * (n - 1) + max(-d, 0)) / n
            return 100.0 if al == 0 else 100 - (100 / (1 + ag / al))

        def calc_bb(n=20, mult=2):
            if len(c) < n:
                return None
            sl = c[-n:]
            m = np.mean(sl)
            std = np.std(sl)
            return {"upper": m + mult * std, "middle": m, "lower": m - mult * std}

        def calc_atr(n=14):
            if len(c) < n + 1:
                return None
            trs = [max(h[i] - l[i], abs(h[i] - c[i-1]), abs(l[i] - c[i-1]))
                   for i in range(len(c) - n, len(c))]
            return float(np.mean(trs))

        def calc_macd_hist():
            if len(c) < 35:
                return None
            e12 = ema_arr(c, 12)
            e26 = ema_arr(c, 26)
            ml = e12[-len(e26):] - e26
            sig = ema_arr(ml, 9)
            if len(sig) == 0:
                return None
            return float(ml[-1] - sig[-1])

        def calc_rvol(n=20):
            if len(v) < n + 1:
                return None
            avg = np.mean(v[-n-1:-1])
            return float(v[-1] / avg) if avg > 0 else None

        # 연속 하락일
        down_days = 0
        for i in range(len(c) - 1, 0, -1):
            if c[i] < c[i - 1]:
                down_days += 1
            else:
                break

        drop_5d = (price - float(c[-6])) / float(c[-6]) * 100 if len(c) > 5 else 0
        gap_pct  = (float(c[-1]) - float(c[-2])) / float(c[-2]) * 100 if len(c) > 1 else 0
        wk52_high = float(np.max(c[-252:])) if len(c) >= 252 else float(np.max(c))

        bb = calc_bb()
        return {
            "ticker": tk,
            "price": price,
            "sma200": sma(200),
            "sma50": sma(50),
            "ma20": sma(20),
            "ma9": sma(9),
            "ma5": sma(5),
            "rsi2": calc_rsi(2),
            "rsi14": calc_rsi(14),
            "bb_upper": bb["upper"] if bb else None,
            "bb_lower": bb["lower"] if bb else None,
            "atr14": calc_atr(),
            "macd_hist": calc_macd_hist(),
            "rvol": calc_rvol(),
            "wk52_high": wk52_high,
            "down_days": down_days,
            "drop_5d": drop_5d,
            "gap_pct": gap_pct,
        }
    except Exception as e:
        log.debug(f"{tk} 지표 계산 오류: {e}")
        return None


# ── 전략 1차 필터 ────────────────────────────────
def strategy_filter(ind: dict, spy_rsi2: float | None) -> tuple[bool, str, int]:
    """
    Returns (passed, strategy_hint, priority_score)
    priority_score: 높을수록 먼저 Claude 분석
    """
    p = ind.get
    price     = p("price", 0)
    sma200    = p("sma200")
    ma20      = p("ma20")
    rsi2      = p("rsi2")
    rsi14     = p("rsi14")
    rvol      = p("rvol", 0) or 0
    bb_lower  = p("bb_lower")
    macd      = p("macd_hist")
    wk52      = p("wk52_high", price)
    down_days = p("down_days", 0)
    drop_5d   = p("drop_5d", 0)

    score = 0
    hint  = "auto"

    # ── 전략③ 평균회귀 RSI(2) ──
    strat3 = (
        sma200 and price > sma200 and
        rsi2 is not None and rsi2 <= 10 and
        bb_lower and price <= bb_lower * 1.01 and
        rvol < 0.9 and
        (down_days >= 3 or drop_5d <= -5) and
        (spy_rsi2 is None or spy_rsi2 > 8)
    )
    if strat3:
        score += 100 + (10 - (rsi2 or 10))  # rsi2 낮을수록 가산
        hint = "③"
        return True, hint, int(score)

    # ── 전략① 모멘텀/돌파 ──
    strat1 = (
        wk52 and price >= wk52 * 0.95 and
        rvol >= 2.0 and
        ma20 and price > ma20 and
        rsi14 is not None and rsi14 >= 50 and
        macd is not None and macd > 0
    )
    if strat1:
        score += 80 + min(rvol * 5, 20)
        hint = "①"
        return True, hint, int(score)

    # ── 전략② 눌림목 ──
    ma9 = p("ma9")
    strat2 = (
        ma20 and price > ma20 * 0.98 and
        ma9 and price < ma9 and  # 단기 눌림
        rsi14 is not None and 35 <= rsi14 <= 62 and
        sma200 and price > sma200
    )
    if strat2:
        score += 60
        hint = "②"
        return True, hint, int(score)

    return False, "없음", 0


# ── SPY 시장 환경 ─────────────────────────────────
def get_spy_rsi2() -> float | None:
    try:
        spy = yf.download("SPY", period="60d", interval="1d", progress=False, auto_adjust=True)
        c = spy["Close"].values.flatten()
        if len(c) < 10:
            return None
        need = 7
        sl = c[-need:]
        ag = al = 0.0
        for i in range(1, 3):
            d = sl[i] - sl[i - 1]
            ag += max(d, 0); al += max(-d, 0)
        ag /= 2; al /= 2
        for i in range(3, len(sl)):
            d = sl[i] - sl[i - 1]
            ag = (ag + max(d, 0)) / 2
            al = (al + max(-d, 0)) / 2
        rsi2 = 100.0 if al == 0 else 100 - (100 / (1 + ag / al))
        log.info(f"SPY RSI(2): {rsi2:.1f}")
        return rsi2
    except Exception as e:
        log.error(f"SPY 데이터 오류: {e}")
        return None


# ── Claude API 정밀 분석 ──────────────────────────
SYSTEM_PROMPT = """당신은 미국 단기주식 매매 전문 AI 어드바이저입니다. 사용자: 찰스(Charles)
원칙: Hallucination 절대 금지. 출력: 순수 JSON만. 마크다운/코드블록/설명문 일절 금지.
확실성: confirmed=검증된사실 / interpreted=해석추론 / uncertain=데이터부족 / inferred=경험칙예측
전략:
① 모멘텀/돌파: 52주고가-5%이내+RVOL>2+주가>MA20+MACD양전환+RSI14≥50. 손절=기준봉저점 R/R≥1:2
② 눌림목: MA9/MA20눌림후반등+MA20기울기양+MACD OSC바닥반전+RSI14 40-60. 손절=MA20이탈
③ 평균회귀RSI2: 주가>SMA200+RSI2≤10+BB하단터치+RVOL<0.8+3일연속하락or-5%+SPY RSI2>20. 손절=-4%orSMA200이탈
JSON만출력:
{"ticker":"","strategy":{"matched":"①②③없음","name":""},"checklist":{"items":[{"label":"","passed":true}],"score":"X/Y"},"signal":{"action":"진입|관망|제외","confidence":"confirmed|interpreted|uncertain|inferred","reason":""},"levels":{"entry":0,"stop":0,"target":0,"rr_ratio":0,"basis":""},"risk":{"flags":[],"earnings_warning":false},"meta":{"requires_manual_check":false,"note":null}}"""

def claude_analyze(ind: dict, spy_rsi2: float | None, hint: str) -> dict | None:
    try:
        client = anthropic.Anthropic(api_key=CONFIG["ANTHROPIC_API_KEY"])
        f  = lambda v: f"{v:.2f}" if v is not None else "미입력"
        fi = lambda v: f"{v:.1f}" if v is not None else "미입력"

        prompt = f"""종목:{ind['ticker']} 전략힌트:{hint}
현재가:{f(ind.get('price'))} SMA200:{f(ind.get('sma200'))} MA20:{f(ind.get('ma20'))} MA9:{f(ind.get('ma9'))}
52주고가:{f(ind.get('wk52_high'))} ATR14:{f(ind.get('atr14'))}
RSI2:{fi(ind.get('rsi2'))} RSI14:{fi(ind.get('rsi14'))} MACD히스토그램:{f(ind.get('macd_hist'))} RVOL:{fi(ind.get('rvol'))}
BB상단:{f(ind.get('bb_upper'))} BB하단:{f(ind.get('bb_lower'))}
SPY RSI2:{fi(spy_rsi2)} 연속하락일:{ind.get('down_days',0)} 5일낙폭:{fi(ind.get('drop_5d'))}% 갭:{fi(ind.get('gap_pct'))}%
실적발표여부:알수없음
JSON으로만응답하세요."""

        msg = client.messages.create(
            model="claude-sonnet-4-6",
            max_tokens=800,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": prompt}]
        )
        raw = msg.content[0].text.strip().replace("```json", "").replace("```", "").strip()
        # JSON 블록만 추출 (앞뒤 텍스트 제거)
        start = raw.find("{")
        end   = raw.rfind("}") + 1
        if start == -1 or end == 0:
            raise ValueError("JSON 블록 없음")
        raw = raw[start:end]
        return json.loads(raw)
    except Exception as e:
        log.error(f"Claude 분석 오류 ({ind.get('ticker')}): {e}")
        return None


# ── Gmail 발송 ────────────────────────────────────
def send_gmail(results: list[dict], spy_rsi2: float | None, scan_date: str):
    subject = f"📈 찰스 트레이딩 스캐너 — {scan_date} 추천 {len(results)}종목"

    # HTML 이메일 본문
    gate_color = "#00cc7a" if (spy_rsi2 and spy_rsi2 > 20) else "#e8980a"
    gate_label = "✓ 진입 환경 양호" if (spy_rsi2 and spy_rsi2 > 20) else "⚠ 시장 주의"

    ACTION_COLOR = {"진입": "#00cc7a", "관망": "#e8980a", "제외": "#666"}
    CONF_KO = {
        "confirmed": "[확인됨]", "interpreted": "[해석]",
        "uncertain": "[불확실]", "inferred": "[추론]"
    }
    STRAT_COLOR = {"①": "#2a7aee", "②": "#8840e8", "③": "#00cc7a", "④": "#e8980a"}

    # 종목별 카드 HTML 생성
    cards = ""
    for i, r in enumerate(results, 1):
        a   = r.get("signal", {})
        lv  = r.get("levels", {})
        st  = r.get("strategy", {})
        cl  = r.get("checklist", {})
        mt  = r.get("meta", {})
        ac  = a.get("action", "-")
        sc  = STRAT_COLOR.get(st.get("matched", ""), "#aaa")
        conf_ko = CONF_KO.get(a.get("confidence", ""), a.get("confidence", ""))
        flags = r.get("risk", {}).get("flags", [])
        flag_html = "".join(f'<span style="background:#3a0a0a;color:#e03030;padding:2px 6px;border-radius:2px;font-size:11px;margin-right:4px;display:inline-block;margin-bottom:3px">⚠ {f}</span>' for f in flags)

        entry  = lv.get("entry")
        stop   = lv.get("stop")
        target = lv.get("target")
        rr     = lv.get("rr_ratio")
        basis  = lv.get("basis", "")
        price  = r.get("_ind", {}).get("price")
        score  = cl.get("score", "?/?")
        checklist_items = cl.get("items", [])
        manual = mt.get("requires_manual_check", False)
        manual_reason = mt.get("manual_check_reason", "")
        note = mt.get("note", "")

        # 체크리스트 HTML
        cl_html = ""
        for ci in checklist_items:
            icon = "✓" if ci.get("passed") else "✗"
            col  = "#00cc7a" if ci.get("passed") else "#e03030"
            cl_html += f'<div style="font-size:11px;margin-bottom:3px"><span style="color:{col};font-weight:bold;margin-right:6px">{icon}</span><span style="color:#8a9aaa">{ci.get("label","")}</span>' + (f'<span style="color:#5a7a9a;margin-left:6px">{ci.get("note","")}</span>' if ci.get("note") else "") + "</div>"

        # 진입 방법 텍스트
        entry_guide = ""
        if entry and stop and target:
            entry_guide = f'진입 ${entry:.2f} / 손절 ${stop:.2f} / 목표 ${target:.2f}'
            if basis:
                entry_guide += f' ({basis})'

        cards += f"""
<div style="background:#0f1520;border:1px solid #1a2535;border-left:3px solid #00cc7a;border-radius:6px;margin-bottom:20px;overflow:hidden">

  <!-- 카드 헤더 -->
  <div style="padding:16px 20px;border-bottom:1px solid #1a2535;display:flex;align-items:center;gap:12px">
    <div>
      <span style="font-family:monospace;font-size:11px;color:#5a7a9a">#{i}</span>
      <span style="font-family:monospace;font-size:22px;font-weight:bold;color:#b8cce0;letter-spacing:2px;margin-left:6px">{r.get("ticker","-")}</span>
      <span style="font-family:monospace;font-size:18px;font-weight:bold;color:{sc};margin-left:10px">{st.get("matched","?")}</span>
      <span style="font-size:12px;color:#5a7a9a;margin-left:6px">{st.get("name","")}</span>
    </div>
    <div style="margin-left:auto;text-align:right">
      <div style="font-family:monospace;font-size:13px;font-weight:bold;color:#b8cce0">${f'{price:.2f}' if price else '-'}</div>
      <div style="font-size:11px;color:#5a7a9a">{conf_ko}</div>
    </div>
  </div>

  <!-- 레벨 3칸 -->
  <div style="display:grid;grid-template-columns:1fr 1fr 1fr;border-bottom:1px solid #1a2535">
    <div style="padding:12px 16px;text-align:center;border-right:1px solid #1a2535">
      <div style="font-family:monospace;font-size:10px;color:#5a7a9a;letter-spacing:1px;margin-bottom:4px">ENTRY</div>
      <div style="font-family:monospace;font-size:18px;font-weight:bold;color:#2a7aee">${f'{entry:.2f}' if entry else '-'}</div>
    </div>
    <div style="padding:12px 16px;text-align:center;border-right:1px solid #1a2535">
      <div style="font-family:monospace;font-size:10px;color:#5a7a9a;letter-spacing:1px;margin-bottom:4px">STOP</div>
      <div style="font-family:monospace;font-size:18px;font-weight:bold;color:#e03030">${f'{stop:.2f}' if stop else '-'}</div>
    </div>
    <div style="padding:12px 16px;text-align:center">
      <div style="font-family:monospace;font-size:10px;color:#5a7a9a;letter-spacing:1px;margin-bottom:4px">TARGET / R:R</div>
      <div style="font-family:monospace;font-size:18px;font-weight:bold;color:#00cc7a">${f'{target:.2f}' if target else '-'}</div>
      <div style="font-family:monospace;font-size:11px;color:#e8980a">{f'1:{rr:.1f}' if rr else ''}</div>
    </div>
  </div>

  <!-- 체크리스트 + 최종의견 -->
  <div style="display:grid;grid-template-columns:1fr 1fr;border-bottom:1px solid #1a2535">
    <div style="padding:14px 16px;border-right:1px solid #1a2535">
      <div style="font-family:monospace;font-size:10px;color:#5a7a9a;letter-spacing:1px;margin-bottom:8px">CHECKLIST {score}</div>
      {cl_html}
    </div>
    <div style="padding:14px 16px">
      <div style="font-family:monospace;font-size:10px;color:#5a7a9a;letter-spacing:1px;margin-bottom:8px">⑥ 최종 의견</div>
      <div style="background:#002a18;border:1px solid #00cc7a;border-radius:4px;padding:10px 12px;margin-bottom:10px">
        <div style="font-size:15px;font-weight:bold;color:#00cc7a;margin-bottom:4px">✅ 진입 가능</div>
        <div style="font-size:12px;color:#b8cce0;line-height:1.5">{a.get("reason","-")}</div>
      </div>
      {f'<div style="background:#301e00;border:1px solid #e8980a;border-radius:4px;padding:8px 12px;font-size:11px;color:#e8980a">⚠ 수동확인: {manual_reason}</div>' if manual and manual_reason else ""}
      {f'<div style="margin-top:6px;font-size:11px;color:#5a7a9a">{note}</div>' if note else ""}
    </div>
  </div>

  <!-- 리스크 + 진입방법 -->
  <div style="padding:12px 16px">
    {f'<div style="margin-bottom:8px">{flag_html}</div>' if flags else ''}
    {f'<div style="font-family:monospace;font-size:11px;color:#5a7a9a">진입: {entry_guide}</div>' if entry_guide else ''}
  </div>

</div>"""

    spy_txt = f"{spy_rsi2:.1f}" if spy_rsi2 else "-"
    html_body = f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="background:#090c10;color:#b8cce0;font-family:-apple-system,sans-serif;margin:0;padding:16px">
<div style="max-width:640px;margin:0 auto">

  <!-- 헤더 -->
  <div style="background:#0f1520;border:1px solid #1a2535;border-radius:6px;padding:14px 18px;margin-bottom:16px">
    <div style="font-family:monospace;font-size:12px;letter-spacing:2px;color:#5a7a9a">CHARLES TRADING SCANNER</div>
    <div style="font-size:18px;font-weight:bold;color:#b8cce0;margin-top:4px">📈 오늘의 추천 {len(results)}종목</div>
    <div style="font-family:monospace;font-size:11px;color:#2a4060;margin-top:2px">{scan_date} · S&P500+NASDAQ 전종목 스캔</div>
    <div style="margin-top:8px;font-family:monospace;font-size:11px;color:{gate_color};font-weight:bold">{gate_label} · SPY RSI(2) {spy_txt}</div>
  </div>

  <!-- 종목 카드들 -->
  {cards}

  <!-- 푸터 -->
  <div style="padding:12px;font-family:monospace;font-size:10px;color:#2a4060;text-align:center;border-top:1px solid #1a2535;margin-top:4px">
    ⚠ AI 보조 분석 — 최종 매매 결정은 찰스 본인 판단으로<br>
    실적발표 자동 감지 불가 → earningswhispers.com 수동 확인 필수
  </div>
</div>
</body>
</html>"""

    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = CONFIG["GMAIL_SENDER"]
        msg["To"]      = CONFIG["GMAIL_RECEIVER"]
        msg.attach(MIMEText(html_body, "html", "utf-8"))

        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(CONFIG["GMAIL_SENDER"], CONFIG["GMAIL_APP_PW"])
            server.sendmail(CONFIG["GMAIL_SENDER"], CONFIG["GMAIL_RECEIVER"], msg.as_string())

        log.info(f"Gmail 발송 완료 → {CONFIG['GMAIL_RECEIVER']}")
    except Exception as e:
        log.error(f"Gmail 발송 오류: {e}")


# ── 메인 실행 ─────────────────────────────────────
# ── 진입 없을 때 간단 알림 ────────────────────────
def send_no_signal_email(spy_rsi2: float | None, scan_date: str):
    spy_txt = f"{spy_rsi2:.1f}" if spy_rsi2 else "-"
    gate = "극단적 약세 (SPY RSI(2) < 20)" if spy_rsi2 and spy_rsi2 < 20 else "시장 약세"
    subject = f"📊 찰스 스캐너 — {scan_date} 오늘 진입 종목 없음"
    html = f"""<!DOCTYPE html><html><body style="background:#090c10;color:#b8cce0;font-family:sans-serif;padding:30px">
<div style="max-width:500px;margin:0 auto;background:#0f1520;border:1px solid #1a2535;border-radius:8px;padding:24px">
<div style="font-family:monospace;font-size:13px;letter-spacing:2px;color:#5a7a9a;margin-bottom:16px">CHARLES TRADING SCANNER · {scan_date}</div>
<div style="font-size:22px;font-weight:bold;color:#b8cce0;margin-bottom:8px">오늘 진입 종목 없음</div>
<div style="color:#5a7a9a;font-size:13px;margin-bottom:20px">S&P500 전 종목 스캔 완료 — 찰스 전략 진입 조건 충족 종목 없음</div>
<div style="background:#1c2535;border-radius:6px;padding:14px;font-family:monospace;font-size:12px">
<div style="color:#5a7a9a;margin-bottom:6px">MARKET CONDITION</div>
<div style="color:#e8980a;font-size:18px;font-weight:bold">⚠ {gate}</div>
<div style="color:#5a7a9a;margin-top:6px">SPY RSI(2): {spy_txt}</div>
</div>
<div style="margin-top:16px;font-size:11px;color:#2a4060">내일 다시 스캔합니다. 시장 안정 시 진입 후보 자동 알림.</div>
</div></body></html>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"] = CONFIG["GMAIL_SENDER"]
        msg["To"] = CONFIG["GMAIL_RECEIVER"]
        msg.attach(MIMEText(html, "html", "utf-8"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(CONFIG["GMAIL_SENDER"], CONFIG["GMAIL_APP_PW"])
            server.sendmail(CONFIG["GMAIL_SENDER"], CONFIG["GMAIL_RECEIVER"], msg.as_string())
        log.info("진입없음 알림 메일 발송 완료")
    except Exception as e:
        log.error(f"알림 메일 오류: {e}")


def main():
    now = datetime.now()
    scan_date = now.strftime("%Y-%m-%d %H:%M")
    log.info(f"{'='*50}")
    log.info(f"찰스 스캐너 시작 — {scan_date}")
    log.info(f"{'='*50}")

    # 1. SPY 시장 게이트
    spy_rsi2 = get_spy_rsi2()
    if spy_rsi2 is not None and spy_rsi2 < 15:
        log.warning(f"SPY RSI(2)={spy_rsi2:.1f} — 시장 극단적 약세. 스캔 계속하되 관망 위주 예상")

    # 2. S&P500 전 종목 로드
    tickers = get_all_tickers()

    # 3. 지표 계산 + 1차 필터
    log.info(f"지표 계산 시작 ({len(tickers)}종목)...")
    candidates = []
    for i, tk in enumerate(tickers):
        if i % 50 == 0:
            log.info(f"  진행: {i}/{len(tickers)}")
        ind = calc_indicators(tk)
        if ind is None:
            continue
        passed, hint, score = strategy_filter(ind, spy_rsi2)
        if passed:
            candidates.append({"ind": ind, "hint": hint, "score": score})
        time.sleep(0.05)  # yfinance 레이트 리밋 방지

    log.info(f"1차 필터 통과: {len(candidates)}종목")

    # 4. 점수 상위 MAX_CLAUDE_CALLS개만 Claude 분석
    candidates.sort(key=lambda x: x["score"], reverse=True)
    to_analyze = candidates[:CONFIG["MAX_CLAUDE_CALLS"]]

    log.info(f"Claude 분석 시작 ({len(to_analyze)}종목)...")
    analyzed = []
    for item in to_analyze:
        tk = item["ind"]["ticker"]
        log.info(f"  Claude 분석: {tk} ({item['hint']})")
        result = claude_analyze(item["ind"], spy_rsi2, item["hint"])
        if result:
            result["_ind"] = item["ind"]
            result["ticker"] = tk
            analyzed.append(result)
        time.sleep(1.0)  # Claude API 레이트 리밋 방지

    # 5. 진입 신호만 추출, TOP_N개 선발
    entry_results = [r for r in analyzed if r.get("signal", {}).get("action") == "진입"]
    # 확실성 우선순위
    conf_order = {"confirmed": 0, "interpreted": 1, "uncertain": 2, "inferred": 3}
    entry_results.sort(key=lambda r: conf_order.get(r.get("signal", {}).get("confidence", "uncertain"), 9))
    top = entry_results[:CONFIG["TOP_N"]]

    # 진입 종목만 — 없으면 메일 안 보냄

    log.info(f"최종 추천: {len(top)}종목 — {[r.get('ticker') for r in top]}")

    # 6. Gmail 발송
    if top:
        send_gmail(top, spy_rsi2, scan_date)
    else:
        # 진입 종목 없을 때 — 간단 알림만
        spy_txt = f"{spy_rsi2:.1f}" if spy_rsi2 else "-"
        send_no_signal_email(spy_rsi2, scan_date)

    log.info("스캐너 완료")


if __name__ == "__main__":
    main()
