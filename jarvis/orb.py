"""시리/자비스 풍 음성 반응 오브 - Pygame.

다른 스레드에서 set_level(0~1) 을 호출하면 오브가 그에 맞춰 부드럽게
부풀고 색이 변한다. 음성 입력 중에는 파랑, 자비스가 말할 때는 시안.
"""

from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass

try:
    import pygame
except ImportError:  # pygame이 없어도 시스템이 죽지 않도록
    pygame = None  # type: ignore


@dataclass
class OrbState:
    level: float = 0.0
    mode: str = "idle"  # idle | listening | thinking | speaking


class JarvisOrb:
    def __init__(self, size: int = 640):
        self.size = size
        self.state = OrbState()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if pygame is None:
            print("[orb] pygame이 설치되어 있지 않습니다. 시각화 없이 진행.")
            return
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1.0)

    def set_level(self, level: float) -> None:
        with self._lock:
            self.state.level = max(0.0, min(1.0, level))

    def set_mode(self, mode: str) -> None:
        with self._lock:
            self.state.mode = mode

    def _run(self) -> None:
        pygame.init()
        screen = pygame.display.set_mode((self.size, self.size), pygame.NOFRAME)
        pygame.display.set_caption("Jarvis")
        clock = pygame.time.Clock()
        center = (self.size // 2, self.size // 2)
        base_radius = self.size * 0.18
        smoothed_level = 0.0
        t0 = time.time()

        while not self._stop.is_set():
            for event in pygame.event.get():
                if event.type == pygame.QUIT:
                    self._stop.set()
                if event.type == pygame.KEYDOWN and event.key == pygame.K_ESCAPE:
                    self._stop.set()

            with self._lock:
                target_level = self.state.level
                mode = self.state.mode

            smoothed_level += (target_level - smoothed_level) * 0.25
            t = time.time() - t0
            breathe = 0.07 * math.sin(t * 1.6)
            radius = base_radius * (1.0 + breathe + smoothed_level * 1.1)

            screen.fill((4, 6, 14))

            colors = _palette(mode)
            for i, (color, scale, alpha) in enumerate(colors):
                surf = pygame.Surface((self.size, self.size), pygame.SRCALPHA)
                wobble = 1.0 + 0.05 * math.sin(t * (2.0 + i * 0.4) + i)
                r = int(radius * scale * wobble)
                pygame.draw.circle(surf, (*color, alpha), center, r)
                screen.blit(surf, (0, 0))

            core_r = int(base_radius * (0.55 + smoothed_level * 0.4))
            pygame.draw.circle(screen, (210, 240, 255), center, core_r)
            pygame.draw.circle(screen, (255, 255, 255), center, max(2, core_r // 4))

            pygame.display.flip()
            clock.tick(60)

        pygame.quit()


def _palette(mode: str) -> list[tuple[tuple[int, int, int], float, int]]:
    if mode == "listening":
        base = (60, 140, 255)
    elif mode == "thinking":
        base = (180, 120, 255)
    elif mode == "speaking":
        base = (90, 220, 240)
    else:
        base = (90, 160, 220)
    layers = []
    for i, (scale, alpha) in enumerate([(2.6, 22), (2.0, 38), (1.5, 60), (1.1, 110)]):
        tint = tuple(min(255, int(c * (0.7 + i * 0.1))) for c in base)
        layers.append((tint, scale, alpha))
    return layers
