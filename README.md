# my-shorts

짧은 세로 영상(쇼츠)을 자동으로 만드는 도구 모음.

## shopping — 쇼핑 쇼츠

원본 영상 5~10개에서 1~2초짜리 컷을 뽑아 20~28초 영상으로 이어 붙인다.

- `make.py` — 컷 이어 붙이기, 자막, [광고] 표기, 목소리 합치기
- `voice.py` — Fish Audio(Drama3) 목소리 만들기
- `subtitles.py` — 원본에 박힌 중국 자막·워터마크를 찾아 확대로 가리기
- `style/script-examples.txt` — 대본 말투 본보기

원본 영상은 `shopping/clips/`에 넣는다(저장소에는 올리지 않음).

## 실행에 필요한 것

이 폴더는 [Instagram_automation](https://github.com/DataChuLee/Instagram_automation) 저장소 안의
`my-shorts/` 자리에 놓고 쓴다. 그 저장소의 글꼴(`assets/fonts`), 도구 모음(`.tools/studio-python`),
Fish Audio 로그인 연결(`studio/fish.py`)을 빌려 쓰기 때문이다. 글자 읽기에는 `rapidocr-onnxruntime`이 필요하다.

```bash
python shopping/make.py        # 음성 견적만 확인
python shopping/make.py --go   # 음성을 만들고 영상까지 완성
```
