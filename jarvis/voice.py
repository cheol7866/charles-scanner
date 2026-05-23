"""음성 입력/출력 - Google Cloud Speech-to-Text와 Text-to-Speech.

마이크에서 한국어를 실시간으로 받아 텍스트로 변환하고, Claude의 응답을
다시 자연스러운 한국어 음성으로 출력한다. VAD(음성 활동 감지)로
사용자가 말을 멈추면 자동으로 인식이 종료된다.
"""

from __future__ import annotations

import io
import queue
import threading
import time
from collections.abc import Iterator
from dataclasses import dataclass

import numpy as np
import sounddevice as sd
import soundfile as sf
from google.cloud import speech, texttospeech

from jarvis.config import JarvisConfig


@dataclass
class VoiceLevel:
    """오브 시각화에 쓸 실시간 음량 수준 (0.0 ~ 1.0)."""

    rms: float
    is_speech: bool


class VoiceIO:
    def __init__(self, config: JarvisConfig, level_callback=None):
        self.config = config
        self.level_callback = level_callback
        self._stt_client = speech.SpeechClient()
        self._tts_client = texttospeech.TextToSpeechClient()
        self._playback_lock = threading.Lock()
        self._tts_voice = texttospeech.VoiceSelectionParams(
            language_code=config.tts_language,
            name=config.tts_voice,
        )
        self._tts_audio_config = texttospeech.AudioConfig(
            audio_encoding=texttospeech.AudioEncoding.LINEAR16,
            speaking_rate=config.tts_speaking_rate,
            sample_rate_hertz=24000,
        )

    def listen(self) -> str:
        """한 번 발화를 듣고 텍스트를 반환한다. 침묵이 길어지면 종료."""

        audio_q: queue.Queue[bytes] = queue.Queue()
        stop_event = threading.Event()
        sample_rate = self.config.sample_rate
        block_size = int(sample_rate * 0.05)  # 50ms 단위
        silence_blocks_needed = int(self.config.silence_duration / 0.05)
        max_blocks = int(self.config.max_record_seconds / 0.05)

        state = {"voiced_blocks": 0, "silent_blocks": 0, "total_blocks": 0, "started": False}

        def callback(indata, frames, time_info, status):
            if status:
                return
            mono = indata[:, 0] if indata.ndim > 1 else indata
            rms = float(np.sqrt(np.mean(mono.astype(np.float32) ** 2)))
            is_speech = rms > self.config.silence_threshold
            if self.level_callback is not None:
                try:
                    self.level_callback(VoiceLevel(rms=min(rms * 8, 1.0), is_speech=is_speech))
                except Exception:
                    pass

            if is_speech:
                state["started"] = True
                state["silent_blocks"] = 0
                state["voiced_blocks"] += 1
            elif state["started"]:
                state["silent_blocks"] += 1

            state["total_blocks"] += 1
            audio_q.put((indata.copy() * 32767).astype(np.int16).tobytes())

            if state["started"] and state["silent_blocks"] >= silence_blocks_needed:
                stop_event.set()
                raise sd.CallbackStop
            if state["total_blocks"] >= max_blocks:
                stop_event.set()
                raise sd.CallbackStop

        with sd.InputStream(
            samplerate=sample_rate,
            channels=1,
            dtype="float32",
            blocksize=block_size,
            callback=callback,
        ):
            stop_event.wait(timeout=self.config.max_record_seconds + 2)

        chunks = []
        while not audio_q.empty():
            chunks.append(audio_q.get())
        if not chunks:
            return ""
        audio_bytes = b"".join(chunks)

        if not state["started"] or state["voiced_blocks"] < 3:
            return ""

        recognition_audio = speech.RecognitionAudio(content=audio_bytes)
        recognition_config = speech.RecognitionConfig(
            encoding=speech.RecognitionConfig.AudioEncoding.LINEAR16,
            sample_rate_hertz=sample_rate,
            language_code=self.config.stt_language,
            enable_automatic_punctuation=True,
            model="latest_short",
        )
        response = self._stt_client.recognize(config=recognition_config, audio=recognition_audio)
        for result in response.results:
            if result.alternatives:
                return result.alternatives[0].transcript.strip()
        return ""

    def stream_tts(self, text: str) -> Iterator[np.ndarray]:
        """긴 응답을 문장 단위로 잘라 차례로 합성 후 재생용 청크를 생성한다."""

        sentences = _split_sentences(text)
        for sentence in sentences:
            if not sentence.strip():
                continue
            synthesis_input = texttospeech.SynthesisInput(text=sentence)
            response = self._tts_client.synthesize_speech(
                input=synthesis_input,
                voice=self._tts_voice,
                audio_config=self._tts_audio_config,
            )
            audio, sr = sf.read(io.BytesIO(response.audio_content), dtype="float32")
            yield audio, sr

    def speak(self, text: str) -> None:
        """텍스트를 음성으로 합성해 즉시 재생한다."""

        if not text.strip():
            return
        with self._playback_lock:
            for audio, sr in self.stream_tts(text):
                if self.level_callback is not None:
                    self._play_with_levels(audio, sr)
                else:
                    sd.play(audio, sr)
                    sd.wait()

    def _play_with_levels(self, audio: np.ndarray, sr: int) -> None:
        """재생하며 오브에 음량 변화를 실시간 전달한다."""

        block = int(sr * 0.05)
        sd.play(audio, sr)
        for i in range(0, len(audio), block):
            chunk = audio[i : i + block]
            rms = float(np.sqrt(np.mean(chunk.astype(np.float32) ** 2)))
            try:
                self.level_callback(VoiceLevel(rms=min(rms * 6, 1.0), is_speech=True))
            except Exception:
                pass
            time.sleep(0.05)
        sd.wait()
        try:
            self.level_callback(VoiceLevel(rms=0.0, is_speech=False))
        except Exception:
            pass


def _split_sentences(text: str) -> list[str]:
    """한국어 문장 단위로 분리. 점·물음표·느낌표·마침표 기준."""

    out = []
    buf = []
    for ch in text:
        buf.append(ch)
        if ch in "다.!?\n" and len("".join(buf).strip()) > 8:
            out.append("".join(buf).strip())
            buf = []
    tail = "".join(buf).strip()
    if tail:
        out.append(tail)
    return out
