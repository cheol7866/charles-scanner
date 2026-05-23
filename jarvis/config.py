"""Jarvis 설정 - 환경 변수에서 키와 옵션을 로드한다."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str | None = None) -> str | None:
    value = os.environ.get(name, default)
    if value is None or value == "":
        return None
    return value


@dataclass
class JarvisConfig:
    anthropic_api_key: str | None = field(default_factory=lambda: _env("ANTHROPIC_API_KEY"))
    claude_model: str = field(default_factory=lambda: _env("CLAUDE_MODEL", "claude-sonnet-4-6") or "claude-sonnet-4-6")

    google_credentials_path: str | None = field(default_factory=lambda: _env("GOOGLE_APPLICATION_CREDENTIALS"))
    google_calendar_token_path: str = field(
        default_factory=lambda: _env("GOOGLE_CALENDAR_TOKEN", str(Path.home() / ".jarvis" / "calendar_token.json"))
        or str(Path.home() / ".jarvis" / "calendar_token.json")
    )
    google_calendar_credentials_path: str = field(
        default_factory=lambda: _env("GOOGLE_CALENDAR_CREDENTIALS", str(Path.home() / ".jarvis" / "credentials.json"))
        or str(Path.home() / ".jarvis" / "credentials.json")
    )

    stt_language: str = field(default_factory=lambda: _env("JARVIS_STT_LANG", "ko-KR") or "ko-KR")
    tts_language: str = field(default_factory=lambda: _env("JARVIS_TTS_LANG", "ko-KR") or "ko-KR")
    tts_voice: str = field(default_factory=lambda: _env("JARVIS_TTS_VOICE", "ko-KR-Neural2-C") or "ko-KR-Neural2-C")
    tts_speaking_rate: float = field(default_factory=lambda: float(_env("JARVIS_TTS_RATE", "1.05") or 1.05))

    sample_rate: int = field(default_factory=lambda: int(_env("JARVIS_SAMPLE_RATE", "16000") or 16000))
    silence_threshold: float = field(default_factory=lambda: float(_env("JARVIS_SILENCE_THRESHOLD", "0.015") or 0.015))
    silence_duration: float = field(default_factory=lambda: float(_env("JARVIS_SILENCE_DURATION", "1.2") or 1.2))
    max_record_seconds: float = field(default_factory=lambda: float(_env("JARVIS_MAX_RECORD", "30") or 30))

    wake_word: str | None = field(default_factory=lambda: _env("JARVIS_WAKE_WORD", "자비스"))
    enable_orb: bool = field(default_factory=lambda: (_env("JARVIS_ENABLE_ORB", "1") or "1") == "1")

    tasks_db_path: str = field(
        default_factory=lambda: _env("JARVIS_TASKS_DB", str(Path.home() / ".jarvis" / "tasks.json"))
        or str(Path.home() / ".jarvis" / "tasks.json")
    )

    system_prompt: str = (
        "당신은 사용자의 개인 비서 '자비스(Jarvis)'입니다. "
        "한국어로 간결하고 정중하게 답변하세요. 핵심만 1-3 문장으로 말합니다. "
        "사용자가 일정·할 일·정보 검색을 요청하면 제공된 도구를 적극적으로 사용하세요. "
        "확실하지 않으면 추측하지 말고 짧게 되묻습니다. "
        "코드나 URL을 음성으로 읽지 말고 요약만 말합니다."
    )

    def ensure_dirs(self) -> None:
        Path(self.google_calendar_token_path).parent.mkdir(parents=True, exist_ok=True)
        Path(self.tasks_db_path).parent.mkdir(parents=True, exist_ok=True)


CONFIG = JarvisConfig()
CONFIG.ensure_dirs()
