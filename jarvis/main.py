"""Jarvis 진입점.

실행: python -m jarvis.main
필요 환경 변수:
  - ANTHROPIC_API_KEY
  - GOOGLE_APPLICATION_CREDENTIALS  (Google Cloud STT/TTS 서비스 계정 JSON 경로)

옵션:
  --text    음성 대신 키보드 텍스트로 입력
  --no-orb  시각화 비활성화
"""

from __future__ import annotations

import argparse
import sys
import traceback

from jarvis.config import CONFIG
from jarvis.llm import ClaudeAgent
from jarvis.orb import JarvisOrb
from jarvis.tools.calendar import CalendarTool
from jarvis.tools.tasks import TasksTool
from jarvis.tools.web import WebTool


def build_agent() -> ClaudeAgent:
    tools = []
    try:
        tools.extend(CalendarTool(CONFIG).as_tools())
    except Exception as exc:
        print(f"[jarvis] 캘린더 도구 비활성화: {exc}")
    tools.extend(TasksTool(CONFIG).as_tools())
    tools.extend(WebTool().as_tools())
    return ClaudeAgent(CONFIG, tools)


def run_text_mode() -> None:
    agent = build_agent()
    print("자비스 텍스트 모드. 'exit' 입력 시 종료.")
    while True:
        try:
            user = input("나> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if not user:
            continue
        if user.lower() in {"exit", "quit", "종료"}:
            return
        try:
            reply = agent.chat(user, on_tool_call=lambda n, a: print(f"  · 도구: {n} {a}"))
        except Exception as exc:
            print(f"[오류] {exc}")
            traceback.print_exc()
            continue
        print(f"자비스> {reply}")


def run_voice_mode(enable_orb: bool) -> None:
    from jarvis.voice import VoiceIO  # 오디오 의존성을 텍스트 모드에서는 로딩 안 함

    orb = JarvisOrb() if enable_orb else None
    if orb is not None:
        orb.start()
        orb.set_mode("idle")

    def on_level(level):
        if orb is not None:
            orb.set_level(level.rms)

    voice = VoiceIO(CONFIG, level_callback=on_level)
    agent = build_agent()

    greeting = "안녕하세요. 자비스입니다. 무엇을 도와드릴까요?"
    print(f"자비스> {greeting}")
    if orb is not None:
        orb.set_mode("speaking")
    voice.speak(greeting)
    if orb is not None:
        orb.set_mode("idle")

    print("[음성 모드] 마이크에 말씀하세요. Ctrl+C 로 종료.")
    while True:
        try:
            if orb is not None:
                orb.set_mode("listening")
            user_text = voice.listen()
            if not user_text:
                if orb is not None:
                    orb.set_mode("idle")
                continue
            print(f"나> {user_text}")

            if CONFIG.wake_word and CONFIG.wake_word not in user_text and len(user_text) < 6:
                if orb is not None:
                    orb.set_mode("idle")
                continue

            if any(kw in user_text for kw in ["종료", "잘 자", "꺼져"]):
                voice.speak("네, 종료할게요. 좋은 하루 되세요.")
                break

            if orb is not None:
                orb.set_mode("thinking")
            reply = agent.chat(user_text, on_tool_call=lambda n, a: print(f"  · 도구: {n} {a}"))
            print(f"자비스> {reply}")
            if orb is not None:
                orb.set_mode("speaking")
            voice.speak(reply)
            if orb is not None:
                orb.set_mode("idle")
        except KeyboardInterrupt:
            print("\n[종료]")
            break
        except Exception as exc:
            print(f"[오류] {exc}")
            traceback.print_exc()
            if orb is not None:
                orb.set_mode("idle")

    if orb is not None:
        orb.stop()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="jarvis")
    parser.add_argument("--text", action="store_true", help="음성 대신 텍스트 입력")
    parser.add_argument("--no-orb", action="store_true", help="시각화 비활성화")
    args = parser.parse_args(argv)

    if not CONFIG.anthropic_api_key:
        print("ANTHROPIC_API_KEY 환경 변수를 설정해야 합니다.", file=sys.stderr)
        return 1

    if args.text:
        run_text_mode()
    else:
        run_voice_mode(enable_orb=(not args.no_orb) and CONFIG.enable_orb)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
