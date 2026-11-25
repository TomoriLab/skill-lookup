# skill-lookup

설치한 Codex 스킬을 터미널에서 한 번에 읽고 검색하는 도구다. 코드에서 찾은 파일과 호출 위치도 로컬 SQLite에 저장해 다음 대화에서 다시 꺼낼 수 있다.

## 설치

Python 3.10 이상과 저장소를 읽을 수 있는 GitHub SSH 키가 필요하다.

```sh
uv tool install git+ssh://git@github.com/TomoriLab/skill-lookup.git
```

## 스킬 읽기

```sh
skill-lookup ko-writing clang dynamic-linking
skill-lookup --section 'Workflow' clang
skill-lookup --search 'RUNPATH' dynamic-linking
```

`ko-writing`은 설치된 `effective-writing`과 `ai-slop-thresher`를 함께 읽는 별칭이다. `--section`은 제목으로 절을 읽고, `--search`는 SQLite FTS5로 관련 구절을 찾는다.

## 코드 위치 저장하기

Swift Wayland 저장소 루트에서 `ImportedProtocolProbe`의 호출 위치를 저장하는 예다.

```sh
skill-lookup remember probe-launch --file Scripts/verify-imported-protocols.py \
  --skill dynamic-linking --result 'ImportedProtocolProbe는 debug와 release에서 각각 실행된다.' \
  --evidence 'verify-imported-protocols.py의 check_output 호출 두 곳'
skill-lookup recall probe-launch
```

등록한 파일이나 스킬이 바뀌면 같은 키로 조회해도 이전 결과는 나오지 않는다.

## 글로벌 AGENTS.md 예시

```markdown
한국어 작업에 필요한 글쓰기 스킬과 기술 스킬은 `skill-lookup ko-writing clang dynamic-linking`처럼 한 번에 읽는다.
내용이 더 필요하면 제목을 아는 절은 `--section`으로 읽고, 제목을 모를 때만 `--search`로 찾는다.
`recall`은 파일과 호출 위치를 찾는 데만 쓴다. 오류는 원본의 기존 진입점에서 재현하고 수정본에서 같은 테스트를 실행한다. 컴파일 오류는 실제 컴파일러로, 로딩 오류는 실제 바이너리를 실행해 확인한다.
```

[BSD 3-Clause 라이선스](LICENSE)
