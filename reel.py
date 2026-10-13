"""짧은 영상 컷들을 빠른 리듬으로 이어 붙이고 컷마다 자막 한 줄을 얹는다.

참고한 릴스처럼 겹침 효과 없이 바로 넘어가되, 모든 컷이 처음부터 끝까지
움직이고 멈추는 프레임이 없다. 24fps 원본은 0.8배속으로 늘려 30fps에 정확히 맞춘다.
"""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT.parent / '.tools/studio-python'))

from PIL import Image, ImageDraw, ImageFont
import imageio_ffmpeg

W, H, FPS = 1080, 1920, 30
FONT = ROOT.parent / 'assets/fonts/Paperlogy-7Bold.ttf'


def caption(text, target, size=62, y=0.61):
    """흰 글씨에 검은 테두리, 화면 가운데보다 조금 아래."""
    image = Image.new('RGBA', (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(image).text((W / 2, H * y), text, font=ImageFont.truetype(str(FONT), size), anchor='mm',
                               fill='white', stroke_width=6, stroke_fill='black')
    image.save(target)


def render(shots, output, work, longest=1.4, slow=1.25):
    """shots: (영상 파일, 시작 초, 끝 초, 자막) 목록."""
    work.mkdir(parents=True, exist_ok=True)
    inputs, filters, names = [], [], []
    for i, (video, start, end, text) in enumerate(shots):
        picture = work / f'caption-{i:02}.png'
        caption(text, picture)
        inputs += ['-i', str(video), '-i', str(picture)]
        # 컷 경계의 섞인 프레임을 피하려고 앞뒤를 조금씩 덜어 낸다.
        filters.append(
            f'[{2*i}:v]trim=start={start+0.05:.3f}:end={end-0.05:.3f},setpts={slow}*(PTS-STARTPTS),fps={FPS},'
            f'trim=duration={longest},scale={W}:{H}:force_original_aspect_ratio=increase:flags=lanczos,'
            f'crop={W}:{H},setsar=1[v{i}];[v{i}][{2*i+1}:v]overlay=0:0[s{i}]')
        names.append(f'[s{i}]')
    filters.append(f"{''.join(names)}concat=n={len(shots)}:v=1:a=0[out]")
    subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), '-y', '-loglevel', 'error', *inputs,
                    '-filter_complex', ';'.join(filters), '-map', '[out]', '-r', str(FPS), '-c:v', 'libx264',
                    '-pix_fmt', 'yuv420p', '-crf', '17', '-preset', 'medium', '-movflags', '+faststart',
                    str(output)], check=True)
