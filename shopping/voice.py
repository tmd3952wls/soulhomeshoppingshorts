"""대본 줄마다 Fish Audio 목소리(Drama3)를 만들어 내려받는다.

API 키 없이, 친구 프로그램(studio/fish.py)에 저장된 Fish 로그인을 그대로 쓴다.
크레딧이 드는 단계는 go=True일 때만 실행하고, 그 전에는 견적만 알려 준다.
"""
from pathlib import Path
import asyncio
import json
import sys

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parent.parent
sys.path.insert(0, str(REPO / '.tools/studio-python'))
sys.path.insert(0, str(REPO))

from studio.fish import Fish

VOICE_ID = '4a81bbbb5cd44f22922bf934cb93b369'  # 일반여성2
MODEL = 'drama-3'


async def speak(name, lines, folder, go=False):
    """lines의 각 줄을 음성 파일로 만든다. 돌려주는 값: (견적 크레딧, 파일 목록 또는 None)."""
    folder.mkdir(parents=True, exist_ok=True)
    state_path = folder / 'project.json'
    state = json.loads(state_path.read_text(encoding='utf-8')) if state_path.exists() else {}
    ready = [folder / f'line-{i:02}.mp3' for i in range(len(lines))]
    if state.get('done') == lines and all(path.exists() for path in ready):
        return 0, ready  # 이미 받아 둔 음성이면 Fish에 접속하지 않는다
    fish = Fish()
    async with fish.session() as session:
        async def call(tool, **args):
            return Fish.parse(await session.call_tool(tool, args))

        await call('studio_help', topic='quickstart')
        if state and len(state['lines']) == len(lines) and state['lines'] != lines:
            # 몇 줄만 고친 경우: 바뀐 줄만 고쳐 쓰면 그 줄만 다시 녹음되고 나머지 목소리는 그대로 남는다.
            value = await call('studio_read_blocks', project_id=state['project'], chapter=state['chapter'])
            found = [b for b in value['blocks'] if b.get('text')]
            ops = [{'block': b['anchor'], 'rev': b['rev'], 'text': line}
                   for b, line in zip(found, lines) if b['text'] != line]
            await call('studio_write_blocks', project_id=state['project'], ops=ops)
            state['lines'] = lines
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
        if state.get('lines') != lines:
            # 대본이 바뀌면 새 프로젝트를 만든다. 만들기와 글 쓰기는 무료다.
            created = await call('studio_create_project', name=name[:30], default_voice_id=VOICE_ID,
                                 roster=[{'name': '일반여성2', 'voice_id': VOICE_ID}])
            project = created['project_id']
            # 모델 설정은 새로 쓰는 줄에만 적용되므로 줄을 넣기 전에 먼저 바꾼다.
            await call('studio_update_project', project_id=project, default_backend=MODEL,
                       default_voice_id=VOICE_ID, scene_preset='off')
            overview = await call('studio_project', project_id=project)
            if overview.get('default_backend') != MODEL:
                raise RuntimeError('Drama3 모델로 설정되지 않았습니다.')
            chapter = overview['chapters'][0]['anchor']
            await call('studio_write_blocks', project_id=project,
                       ops=[{'append_to': chapter, 'text': line, 'voice': VOICE_ID} for line in lines])
            state = {'project': project, 'chapter': chapter, 'lines': lines}
            state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
        project, chapter = state['project'], state['chapter']

        async def blocks():
            value = await call('studio_read_blocks', project_id=project, chapter=chapter, include_audio=True)
            found = [b for b in value['blocks'] if b.get('text')]
            if [b['text'] for b in found] != lines:
                raise RuntimeError('Fish에 올라간 대본이 내 대본과 다릅니다.')
            return found

        await blocks()
        quote = (await call('studio_generate', project_id=project, chapter=chapter, dry_run=True)).get('estimated_credits')
        if not go:
            return quote, None
        if quote:
            await call('studio_generate', project_id=project, chapter=chapter)
        for _ in range(60):
            found = await blocks()
            if all(b.get('audio_url') and not b.get('dirty', True) for b in found):
                break
            await asyncio.sleep(3)
        else:
            raise RuntimeError('음성 생성이 끝나지 않았습니다. 다시 실행하면 이어서 확인합니다(추가 요금 없음).')
        files = []
        for i, block in enumerate(found):
            path = folder / f'line-{i:02}.mp3'
            await fish.download(block['audio_url'], path)
            files.append(path)
        state['done'] = lines
        state_path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding='utf-8')
        return quote, files
