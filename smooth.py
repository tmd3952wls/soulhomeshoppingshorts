"""사진 여러 장을 끊김 없이 이어지는 세로 영상으로 만든다.

사진마다 카메라가 일정한 속도로 천천히 움직이고, 컷이 바뀔 때는 두 사진이
겹치며 넘어간다. 겹치는 동안에도 두 카메라가 모두 계속 움직여 멈추는 순간이 없다.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / '.tools/studio-python'))

import numpy as np
from PIL import Image
import imageio_ffmpeg

W, H, FPS = 1080, 1920, 30
MOVES = ('right', 'in', 'left', 'out')


def camera(size, move, travel=0.16, zoom=0.07):
    """화면에 담을 원본 영역의 시작·끝 (left, top, width, height)."""
    w, h = size
    full_h = min(h, w * H / W)
    full_w = full_h * W / H
    small_w, small_h = full_w * (1 - zoom), full_h * (1 - zoom)
    room = w - full_w
    shift = min(room / 2, full_w * travel / 2)

    def box(bw, bh, dx=0.0):
        return ((w - bw) / 2 + dx, (h - bh) / 2, bw, bh)

    if move == 'right' and shift > 1:
        return box(full_w, full_h, -shift), box(small_w, small_h, shift)
    if move == 'left' and shift > 1:
        return box(full_w, full_h, shift), box(small_w, small_h, -shift)
    if move == 'out':
        return box(small_w, small_h), box(full_w, full_h)
    return box(full_w, full_h), box(small_w, small_h)


def frame(image, start, end, t):
    left, top, bw, bh = (a + (b - a) * t for a, b in zip(start, end))
    return np.asarray(image.transform((W, H), Image.Transform.EXTENT,
                                      (left, top, left + bw, top + bh), Image.Resampling.BICUBIC), np.float32)


def render(photos, output, seconds=2.6, overlap=0.7):
    """seconds: 사진 한 장이 보이는 시간, overlap: 다음 사진과 겹치는 시간."""
    shot, fade = round(seconds * FPS), round(overlap * FPS)
    step = shot - fade
    images = [Image.open(p).convert('RGB') for p in photos]
    for i, image in enumerate(images):
        # 필요한 것보다 훨씬 큰 원본은 미리 줄여 속도와 화질을 함께 챙긴다.
        scale = max(W * 1.6 / image.width, H * 1.6 / image.height)
        if scale < 1:
            images[i] = image.resize((round(image.width * scale), round(image.height * scale)), Image.Resampling.LANCZOS)
    cameras = [camera(image.size, MOVES[i % len(MOVES)]) for i, image in enumerate(images)]
    total = step * (len(images) - 1) + shot
    process = subprocess.Popen(
        [imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', '-f', 'rawvideo', '-pix_fmt', 'rgb24',
         '-s', f'{W}x{H}', '-r', str(FPS), '-i', '-', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '17',
         '-preset', 'medium', '-movflags', '+faststart', str(output)], stdin=subprocess.PIPE)
    for n in range(total):
        i = min(n // step, len(images) - 1)
        local = n - i * step
        picture = frame(images[i], *cameras[i], local / (shot - 1))
        if i and local < fade:
            a = (local + 1) / (fade + 1)
            a = a * a * (3 - 2 * a)
            before = frame(images[i - 1], *cameras[i - 1], (local + step) / (shot - 1))
            picture = before * (1 - a) + picture * a
        process.stdin.write(picture.astype(np.uint8).tobytes())
    process.stdin.close()
    if process.wait():
        raise RuntimeError('영상 인코딩에 실패했습니다.')
    return total / FPS


if __name__ == '__main__':
    out = Path(sys.argv[1])
    print(f'{render(sys.argv[2:], out):.1f}초 영상 저장: {out}')
