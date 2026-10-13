"""쇼핑 쇼츠: 여러 원본 영상에서 짧은 컷을 뽑아 이어 붙이고 컷마다 대본 한 구절을 자막으로 얹는다.

컷 길이는 Fish Audio 목소리의 실제 길이에 맞추되 1~2초를 벗어나지 않는다.
중국 자막이나 워터마크가 있는 원본은 subtitles.py가 찾아낸 위치만큼 확대해 화면 밖으로 내보낸다.
"""
from pathlib import Path
import asyncio
import subprocess
import sys
import wave

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent.parent / '.tools/studio-python'))

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg
import numpy as np

import subtitles

W, H, FPS, RATE = 1080, 1920, 30, 44100
CLIPS = ROOT / 'clips'
FONT = ROOT.parent.parent / 'assets/fonts/Paperlogy-7Bold.ttf'

# ── 나중에 화면에서 조정할 값들 ──
CAPTION_SIZE = 76        # 자막 글자 크기
CAPTION_Y = 0.61         # 자막 높이 (0 = 맨 위, 1 = 맨 아래)
CAPTION_WIDTH = 0.86     # 이 폭을 넘으면 두 줄로 나눈다
LINE_GAP = 0.0           # 줄과 줄 사이에 남기는 숨 쉴 틈(초). 0이면 앞 문장이 끝나자마자 다음 문장
SHORTEST, LONGEST = 1.0, 2.0  # 컷 길이 한계(초)
AD_TEXT, AD_X, AD_Y, AD_SIZE = '[광고]', 39, 44, 40  # 영상 내내 떠 있는 광고 표기: 글, 오른쪽·위에서의 거리(픽셀), 크기
CAPTION_SHORTEST = 0.4   # 자막 한 조각이 화면에 머무는 가장 짧은 시간(초)


def source(video):
    """Vmake로 자막을 지운 파일이 clips/cleaned에 같은 이름으로 있으면 그것을 쓴다."""
    cleaned = CLIPS / 'cleaned' / video
    return cleaned if cleaned.exists() else CLIPS / video


def caption(text, target):
    """흰 글씨에 검은 테두리. 너무 길면 가운데에 가장 가까운 띄어쓰기에서 두 줄로 나눈다."""
    font = ImageFont.truetype(str(FONT), CAPTION_SIZE)
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    text = text.rstrip('.')  # 마침표는 목소리 억양용이라 화면에는 쓰지 않는다
    if draw.textlength(text, font=font) > W * CAPTION_WIDTH and ' ' in text:
        spaces = [i for i, ch in enumerate(text) if ch == ' ']
        cut = min(spaces, key=lambda i: abs(i - len(text) / 2))
        text = text[:cut] + '\n' + text[cut + 1:]
    draw.multiline_text((W / 2, H * CAPTION_Y), text, font=font, anchor='mm', align='center', spacing=18,
                        fill='white', stroke_width=7, stroke_fill='black')
    image.save(target)


def voice_lines(files):
    """줄별 음성의 앞뒤 무음을 잘라 내고 화면 프레임 길이에 맞춘다. 돌려주는 값: 줄마다 (소리, 프레임 수)."""
    result = []
    for file in files:
        raw = subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-loglevel', 'error', '-i', str(file), '-f', 's16le',
                              '-ac', '1', '-ar', str(RATE), '-'], capture_output=True, check=True).stdout
        sound = np.frombuffer(raw, np.int16)
        loud = np.flatnonzero(np.abs(sound) > 500)
        sound = sound[max(0, loud[0] - RATE // 50):loud[-1] + int(RATE * LINE_GAP)]
        frames = -(-len(sound) * FPS // RATE)
        result.append((np.pad(sound, (0, frames * RATE // FPS - len(sound))), frames))
    return result


def split(frames, texts, least):
    """길이를 글자 수 비율로 나눈다. 어느 조각도 least 프레임 밑으로 내려가지 않는다."""
    weights = [sum(1 for ch in text if ch.isalnum()) for text in texts]
    parts = [max(least, round(frames * w / sum(weights))) for w in weights]
    parts[parts.index(max(parts))] += frames - sum(parts)
    return parts


def render(lines, voices, output, work):
    """lines: 줄마다 컷 목록. 컷은 (자막, 영상 파일, 시작 초).

    자막 안의 ' / '는 같은 컷 안에서 자막만 바뀌는 자리다.
    """
    work.mkdir(parents=True, exist_ok=True)
    output.parent.mkdir(parents=True, exist_ok=True)
    spoken = voice_lines(voices)
    track = work / 'voice.wav'
    with wave.open(str(track), 'wb') as file:
        file.setnchannels(1); file.setsampwidth(2); file.setframerate(RATE)
        file.writeframes(np.concatenate([sound for sound, _ in spoken]).tobytes())
    inputs, filters, names, total, i = [], [], [], 0, 0

    def add(path):
        inputs.extend(['-i', str(path)])
        return len(inputs) // 2 - 1

    for cuts, (_, frames) in zip(lines, spoken):
        for (text, video, start), length in zip(cuts, split(frames, [cut[0] for cut in cuts], round(SHORTEST * FPS))):
            seconds = length / FPS
            total += seconds
            found = subtitles.analyze(source(video))
            if found['vmake']:
                raise RuntimeError(f'{video}: 글자를 확대로 가릴 수 없습니다. Vmake로 지운 파일을 clips/cleaned에 같은 이름으로 넣어 주세요.')
            crop = ''
            if found['crop']:
                _, left, top, wide, tall = found['crop']
                crop = f'crop=iw*{wide}:ih*{tall}:iw*{left}:ih*{top},'
            chain = (f'[{add(source(video))}:v]trim=start={start:.3f},setpts=PTS-STARTPTS,fps={FPS},'
                     f'trim=duration={seconds:.4f},{crop}scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,'
                     f'crop={W}:{H},setsar=1[c{i}_0]')
            pieces, begin = text.split(' / '), 0
            for k, (piece, part) in enumerate(zip(pieces, split(length, pieces, round(CAPTION_SHORTEST * FPS)))):
                picture = work / f'caption-{i:02}-{k}.png'
                caption(piece, picture)
                chain += (f";[c{i}_{k}][{add(picture)}:v]overlay=0:0:"
                          f"enable='between(n,{begin},{begin + part - 1})'[c{i}_{k + 1}]")
                begin += part
            filters.append(chain)
            names.append(f'[c{i}_{len(pieces)}]')
            i += 1
            print(f'{i:2} {seconds:.2f}초 {"" if SHORTEST <= seconds <= LONGEST else "(범위 밖!)"} {text}')
    print(f'합계 {total:.1f}초, {i}컷')
    badge = work / 'ad.png'
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((W - AD_X, AD_Y), AD_TEXT, font=ImageFont.truetype(str(FONT), AD_SIZE), anchor='rt',
                               fill='white', stroke_width=4, stroke_fill='black')
    image.save(badge)
    filters.append(f"{''.join(names)}concat=n={i}:v=1:a=0[joined];[joined][{add(badge)}:v]overlay=0:0[out]")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', *inputs, '-i', str(track),
                    '-filter_complex', ';'.join(filters), '-map', '[out]', '-map', f'{len(inputs) // 2}:a', '-r', str(FPS),
                    '-c:v', 'libx264', '-pix_fmt', 'yuv420p', '-crf', '17', '-preset', 'medium',
                    '-c:a', 'aac', '-b:a', '192k', '-movflags', '+faststart', str(output)], check=True)


V1 = 'TikVideo.App_6849868301720472845-hd.mp4'
V2 = 'TikVideo.App_6936393895118900488-hd.mp4'
V3 = 'TikVideo.App_7042175240432012583-hd.mp4'
V6 = 'TikVideo.App_7597278039495684774-hd.mp4'
# 한 줄 = 목소리 한 호흡. 줄 안의 컷들은 그 호흡을 나눠 가진다.
RUST_POWDER = [
    [('저 이거 몰라서', V1, 3.50), ('집주인한테 / 보증금 떼일 뻔했어요.', V1, 0.10)],
    [('이사 나가는 날 / 집을 보러 오셨는데', V2, 5.15)],
    [('세면대랑 상판에 / 녹이 슬었다고', V6, 6.40), ('수리비를 / 내라는 거예요.', V3, 10.35)],
    [('수세미로 / 아무리 밀어도', V1, 2.00), ('꿈쩍도 안 해서 / 울고 싶더라고요.', V6, 0.10)],
    [('그때 옆집 언니가', V1, 5.30), ('이 가루 한 통을 / 주더라고요.', V1, 12.90)],
    [('솔솔 뿌려서', V3, 0.10), ('슥 문지르기만 했는데', V3, 1.30)],
    [('누렇던 상판이', V1, 7.20), ('하얗게 바뀌더라고요.', V1, 8.80)],
    [('수전 주변 / 녹물 자국도', V6, 8.60), ('새것처럼 / 싹 닦이고요.', V3, 5.30)],
    [('알고 보니 / 녹만 녹여내는 / 가루라', V2, 2.85), ('스크래치도 / 안 나더라고요.', V1, 10.00)],
    [('저만 알기 아까워서', V3, 4.00), ('나도 남겨주시면 / 알려드릴게요!', V1, 14.30)],
]

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    from voice import speak
    spoken = [' '.join(cut[0] for cut in cuts).replace(' / ', ' ') for cuts in RUST_POWDER]
    go = '--go' in sys.argv  # 이 표시가 있어야 크레딧을 써서 음성을 만든다
    credits, voices = asyncio.run(speak('쇼핑-녹제거가루', spoken, ROOT / 'work/voice-rust', go))
    print(f'음성 견적 {credits} 크레딧')
    if voices:
        render(RUST_POWDER, voices, ROOT / 'out/rust-powder-v6.mp4', ROOT / 'work')
