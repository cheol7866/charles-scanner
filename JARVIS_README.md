# Jarvis - 한국어 대화형 AI 비서

영화 아이언맨의 자비스(Jarvis)처럼 **음성으로 대화하며 캘린더와 할 일을
관리하는 AI 비서**입니다. Claude API + Google Cloud STT/TTS + Google
Calendar 를 사용합니다.

## 구조

```
jarvis/
├── main.py            # 진입점: 음성/텍스트 모드 선택
├── voice.py           # 마이크 입력, VAD, Google STT/TTS
├── llm.py             # Claude API + tool use 루프
├── orb.py             # 시리/자비스풍 음성 반응 오브 (Pygame)
├── config.py          # 환경 변수 설정
└── tools/
    ├── calendar.py    # Google Calendar 일정 조회/생성
    ├── tasks.py       # 로컬 To-Do 관리
    └── web.py         # 웹 검색 (Brave/SerpAPI)
```

## 설치

```bash
pip install -r requirements-jarvis.txt
```

macOS 에서 PortAudio 가 필요할 수 있습니다:

```bash
brew install portaudio
```

## 환경 변수

| 변수 | 설명 |
| --- | --- |
| `ANTHROPIC_API_KEY` | Claude API 키 (필수) |
| `GOOGLE_APPLICATION_CREDENTIALS` | Google Cloud 서비스 계정 JSON 경로 (STT/TTS 용) |
| `BRAVE_API_KEY` 또는 `SERPAPI_KEY` | 웹 검색용 (선택) |
| `CLAUDE_MODEL` | 기본 `claude-sonnet-4-6` |
| `JARVIS_TTS_VOICE` | 기본 `ko-KR-Neural2-C` (한국어 여성 음성) |
| `JARVIS_WAKE_WORD` | 기본 `자비스`. 짧은 발화는 이 단어가 있어야 응답 |

### Google Calendar 연동

1. Google Cloud Console → API 사용자 인증 정보에서 **OAuth 클라이언트 ID(Desktop)** 생성
2. JSON 다운로드 → `~/.jarvis/credentials.json` 으로 저장
3. 처음 실행하면 브라우저로 동의 화면이 뜨고, 토큰이 `~/.jarvis/calendar_token.json` 에 저장됩니다.

## 실행

```bash
# 음성 모드 (기본, 오브 시각화 켜짐)
python -m jarvis.main

# 텍스트 모드 (음성 없이 키보드로)
python -m jarvis.main --text

# 오브 없이
python -m jarvis.main --no-orb
```

## 대화 예시

> 나: "내일 일정 알려줘"
> 자비스: "내일은 오전 10시 디자인 리뷰와 오후 3시 영업팀 미팅이 있어요."

> 나: "내일 오후 2시에 치과 예약 추가해줘"
> 자비스: "내일 오후 2시 치과 예약 잡았습니다."

> 나: "물 마시기 잊지 말라고 해줘"
> 자비스: "할 일에 추가했어요."

## 동작 원리

1. **마이크** → `sounddevice` 로 16kHz PCM 캡처
2. **VAD** → RMS 기반으로 침묵 1.2초가 지나면 자동 종료
3. **STT** → Google Cloud Speech `latest_short` 모델 (한국어)
4. **Claude** → 도구 정의를 함께 보내고, `tool_use` 응답이 오면 핸들러 실행 후 재요청
5. **TTS** → 응답을 문장 단위로 잘라 Google Cloud TTS (`ko-KR-Neural2-C`) 로 합성
6. **오브** → 별도 스레드에서 입력/출력 음량을 시각화

## 새 도구 추가

`jarvis/tools/` 에 새 파일을 만들고 `as_tools()` 가 `Tool` 리스트를 반환하게
한 뒤 `main.py` 의 `build_agent()` 에 등록하면 됩니다. Claude 가 자동으로
필요할 때 호출합니다.
