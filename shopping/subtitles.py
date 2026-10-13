"""원본 영상에 박힌 글자(중국 자막·워터마크)를 찾아, 그 글자가 화면 밖으로 나가는 확대 위치를 정한다.

화면에 덧씌운 글자와 물건에 원래 적힌 글자(상표 등)를 구분한다.
 - 자막: 같은 높이에서 글 내용이 계속 바뀐다.
 - 워터마크: 같은 자리에 같은 글자가 영상 내내 떠 있다.
 - 그 밖의 글자는 장면 속 물건의 글자로 보고 가리지 않는다.
"""
from pathlib import Path
import json
import sys

import cv2

ROOT = Path(__file__).resolve().parent
STEP = 0.5        # 몇 초마다 한 장씩 살펴볼지
MARGIN = 0.012    # 글자 둘레에 두는 여유(화면 크기 대비)
ICON = 0.06       # 워터마크 옆 그림을 위해 더 넓히는 폭
MAX_ZOOM = 1.6    # 이보다 더 확대해야 하면 화질이 너무 나빠지므로 Vmake로 보낸다
ASPECT = 9 / 16


def chinese(text):
    return sum('一' <= ch <= '鿿' for ch in text)


def distinct(texts):
    """서로 다른 문장의 수. 같은 글자를 잘못 읽어 생긴 비슷한 글들은 하나로 센다."""
    kept = []
    for text in sorted(texts, key=len, reverse=True):
        if all(len(set(text) & set(other)) < 0.5 * min(len(set(text)), len(set(other))) for other in kept):
            kept.append(text)
    return len(kept)


def scan(video):
    """영상을 STEP초마다 읽어 글자 상자를 모은다. 상자는 화면 크기 대비 비율 (x0, y0, x1, y1)."""
    from rapidocr_onnxruntime import RapidOCR
    engine = scan.engine = getattr(scan, 'engine', None) or RapidOCR()
    capture = cv2.VideoCapture(str(video))
    width, height = capture.get(cv2.CAP_PROP_FRAME_WIDTH), capture.get(cv2.CAP_PROP_FRAME_HEIGHT)
    length = capture.get(cv2.CAP_PROP_FRAME_COUNT) / (capture.get(cv2.CAP_PROP_FPS) or 30)
    frames, moment = [], STEP / 2
    while moment < length:
        capture.set(cv2.CAP_PROP_POS_MSEC, moment * 1000)
        ok, frame = capture.read()
        if not ok:
            break
        found, _ = engine(frame)
        frames.append([{'text': text, 'box': [min(p[0] for p in box) / width, min(p[1] for p in box) / height,
                                              max(p[0] for p in box) / width, max(p[1] for p in box) / height]}
                       for box, text, score in (found or []) if score > 0.5])
        moment += STEP
    return {'aspect': width / height, 'frames': frames}


def overlays(frames):
    """덧씌운 글자(자막·워터마크)가 차지하는 상자들을 돌려준다."""
    groups = []  # 높이가 비슷한 글자끼리 묶는다
    for index, frame in enumerate(frames):
        for item in frame:
            middle = (item['box'][1] + item['box'][3]) / 2
            for group in groups:
                if abs(group['middle'] - middle) < 0.025:
                    break
            else:
                group = {'middle': middle, 'items': []}
                groups.append(group)
            group['items'].append((index, item))
    hidden = []
    for group in groups:
        seen = {index for index, _ in group['items']}
        texts = {item['text'] for _, item in group['items']}
        boxes = [item['box'] for _, item in group['items']]
        centered = sum(abs((b[0] + b[2]) / 2 - 0.5) < 0.08 for b in boxes) / len(boxes)
        subtitle = len(seen) >= 4 and distinct(texts) >= 3 and centered > 0.7 and any(chinese(t) for t in texts)
        steady = max(b[2] for b in boxes) - min(b[0] for b in boxes) < 0.5 and len(texts) <= 3
        watermark = len(seen) >= 0.7 * len(frames) and steady
        if subtitle or watermark:
            # 워터마크 옆에는 글자 읽기에 안 잡히는 그림(녹화 표시의 빨간 점 등)이 붙어 있곤 해서 좌우로 넉넉히 넓힌다.
            extra = 0 if subtitle else ICON
            hidden.append({'kind': '자막' if subtitle else '워터마크', 'sample': sorted(texts)[0],
                           'box': [min(b[0] for b in boxes) - extra, min(b[1] for b in boxes) - extra / 3,
                                   max(b[2] for b in boxes) + extra, max(b[3] for b in boxes) + extra / 3]})
    return hidden


def window(hidden, aspect):
    """가릴 상자를 모두 피하는 가장 덜 확대한 9:16 창. 돌려주는 값: (배율, 왼쪽, 위, 너비, 높이) 또는 None(확대로는 안 됨)."""
    wide = min(1, ASPECT / aspect)   # 확대하지 않았을 때 9:16 창의 크기(원본 대비 비율)
    tall = min(1, aspect / ASPECT)
    if not hidden:
        return None
    steps = [i / 100 for i in range(101)]
    zoom = 1.0
    while zoom <= MAX_ZOOM + 1e-9:
        w, h = wide / zoom, tall / zoom
        best = None
        for x in steps:
            for y in steps:
                left, top = x * (1 - w), y * (1 - h)
                if all(b['box'][2] + MARGIN <= left or b['box'][0] - MARGIN >= left + w or
                       b['box'][3] + MARGIN <= top or b['box'][1] - MARGIN >= top + h for b in hidden):
                    miss = abs(left + w / 2 - 0.5) + abs(top + h / 2 - 0.5)  # 가운데에서 덜 벗어난 창이 좋다
                    if best is None or miss < best[0]:
                        best = (miss, left, top)
        if best:
            return round(zoom, 2), round(best[1], 4), round(best[2], 4), round(w, 4), round(h, 4)
        zoom += 0.02
    return None


def analyze(video, cache=ROOT / 'work/subtitles.json'):
    """영상 하나의 판정. {'hidden': 가릴 글자들, 'crop': (배율, 왼쪽, 위, 너비, 높이) 또는 None, 'vmake': 확대로는 못 가림}."""
    saved = json.loads(cache.read_text(encoding='utf-8')) if cache.exists() else {}
    key = f'{video.name}:{video.stat().st_size}'
    if key not in saved:
        saved[key] = scan(video)
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(saved, ensure_ascii=False), encoding='utf-8')
    hidden = overlays(saved[key]['frames'])
    crop = window(hidden, saved[key]['aspect'])
    return {'hidden': hidden, 'crop': crop, 'vmake': bool(hidden) and crop is None}


if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8')
    for clip in sorted((ROOT / 'clips').glob('*.mp4')):
        result = analyze(clip)
        print(clip.name)
        for item in result['hidden']:
            print(f"   {item['kind']} \"{item['sample']}\" 위치 {[round(v, 3) for v in item['box']]}")
        if result['vmake']:
            print('   → 확대로는 가릴 수 없음: Vmake로 지워야 함')
        elif result['crop']:
            print(f"   → {result['crop'][0]}배 확대, 왼쪽 {result['crop'][1]}, 위 {result['crop'][2]}")
        else:
            print('   → 가릴 글자 없음')
