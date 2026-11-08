#!/usr/bin/env python3
"""生成演示曲 examples/player/music/样例.wav。

30 秒 A 小调五声拨弦琶音（Am–F–C–G 和声），22.05kHz 单声道 16-bit PCM。
旧样例只有 0.25 秒，播放器一放就触发自动接歌——本脚本产出可正常试听的长度。
"""
import math
import os
import struct
import wave

RATE = 22050
SECONDS = 30
BPM = 100
BEAT = 60.0 / BPM  # 0.6s

# A 小调五声：A C D E G（含低八度）
FREQ = {
    'A2': 110.00, 'C3': 130.81, 'D3': 146.83, 'E3': 164.81, 'G3': 196.00,
    'A3': 220.00, 'C4': 261.63, 'D4': 293.66, 'E4': 329.63, 'G4': 392.00,
    'A4': 440.00, 'C5': 523.25, 'D5': 587.33, 'E5': 659.25, 'G5': 783.99,
    'A5': 880.00,
}

# Am – F – C – G；每小节 4 拍，每拍一个分解和弦音。
PROG = [
    ['A3', 'C4', 'E4', 'A4', 'E4', 'C4'],
    ['F3' if 'F3' in FREQ else 'A3', 'C4', 'F3' if 'F3' in FREQ else 'A3', 'A4', 'C4', 'A4'],
    ['C3' if 'C3' in FREQ else 'C3', 'E4', 'G4', 'C5', 'G4', 'E4'],
    ['G3', 'D4', 'G4', 'B3' if 'B3' in FREQ else 'D4', 'G4', 'D5'],
]
FREQ.update({'F3': 174.61, 'C3': 130.81, 'B3': 246.94})

BAR_LEN = 4 * BEAT  # 2.4s / 小节
PATTERN_STEP = BEAT / 1.5  # 一小节 6 音 → 0.4s/音


def pluck(freq, t):
    """指数衰减拨弦，带软起音与二次谐波。"""
    attack = min(1.0, t / 0.008)
    env = math.exp(-t * 4.2) * attack
    v = math.sin(2 * math.pi * freq * t) + 0.35 * math.sin(4 * math.pi * freq * t)
    return v * env * 0.45


def main():
    total = RATE * SECONDS
    out = [0.0] * total
    n_bars = int(SECONDS / BAR_LEN)
    for bar in range(n_bars):
        chord = PROG[bar % len(PROG)]
        for i, note in enumerate(chord):
            f = FREQ[note]
            start = int((bar * BAR_LEN + i * PATTERN_STEP) * RATE)
            n = int(BEAT * 2.2 * RATE)  # 音长留点重叠
            for k in range(n):
                idx = start + k
                if idx >= total:
                    break
                out[idx] += pluck(f, k / RATE)
    # 结尾 1.5 秒淡出，防爆音。
    fade = int(1.5 * RATE)
    for i in range(fade):
        out[total - fade + i] *= 1.0 - i / fade
    peak = max(1e-9, max(abs(v) for v in out))
    scale = 0.89 / peak

    path = os.path.join(os.path.dirname(__file__), '..', 'examples', 'player', 'music', '样例.wav')
    path = os.path.abspath(path)
    with wave.open(path, 'wb') as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        frames = b''.join(struct.pack('<h', int(max(-1.0, min(1.0, v * scale)) * 32767)) for v in out)
        w.writeframes(frames)
    print(f'written {path}  {SECONDS}s  {os.path.getsize(path)} bytes')


if __name__ == '__main__':
    main()
