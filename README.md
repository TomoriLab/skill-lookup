# skill-lookup

설치한 Codex 스킬을 터미널에서 한 번에 읽고 검색하는 도구다. 코드에서 찾은 파일과 호출 위치도 로컬 SQLite에 저장해 다음 대화에서 다시 꺼낼 수 있다.

## 설치

```sh
uv tool install git+ssh://git@github.com/TomoriLab/skill-lookup.git
```

이미 복제한 저장소에서는 `uv tool install .`로 설치할 수 있다.

## 스킬 읽기

스킬 이름과 Markdown 경로를 함께 넘기면 지정한 순서대로 읽고 같은 파일은 한 번만 출력한다. 스킬은 `~/.codex/skills`에서 먼저 찾고 `~/.agents/skills`에서 다시 찾는다. `CODEX_HOME`을 지정한 환경에서는 첫 경로가 `$CODEX_HOME/skills`다.

```sh
skill-lookup ko-writing clang dynamic-linking
skill-lookup clang clang/references/flags.md
```

`ko-writing`은 설치된 `effective-writing`과 그 기본 글쓰기 가이드, `ai-slop-thresher`를 묶어 읽는 별칭이다.

스킬 파일이 바뀌면 다음 조회에서 캐시가 갱신된다. `skill-lookup --status clang`으로 캐시 사용 여부를 확인할 수 있다.

절 제목을 알면 `--section`으로 그 절과 하위 절을 읽는다. 제목을 모르면 `--search`로 해당 스킬 안에서 검색한다. FTS5 검색은 일치하는 문서 경로와 제목, 발췌문을 최대 세 개 보여준다.

```sh
skill-lookup --section 'Workflow' clang
skill-lookup --search 'RUNPATH' dynamic-linking
```

## 코드 위치 저장하기

다음은 Swift Wayland 저장소에서 `ImportedProtocolProbe`를 어디서 실행하는지 확인하고 그 위치를 기억해 두는 예다. 저장과 조회는 같은 저장소 루트에서 실행한다.

```sh
rg -n 'check_output.*ImportedProtocolProbe' Scripts/verify-imported-protocols.py
skill-lookup remember probe-launch \
  --file Scripts/verify-imported-protocols.py --skill dynamic-linking \
  --result 'verify-imported-protocols.py에서 debug와 release 실행 파일을 각각 호출한다.' \
  --evidence 'check_output에 ImportedProtocolProbe 경로를 넘기는 두 곳'
```

다음 대화에서는 키로 결과와 근거를 다시 꺼낸다. 키가 기억나지 않으면 검색어로 후보 키를 찾을 수 있다.

```sh
skill-lookup recall probe-launch
skill-lookup recall --search 'ImportedProtocolProbe'
```

여러 파일이나 스킬을 참조했다면 `--file`과 `--skill`을 반복해 등록한다. 등록한 입력이 바뀌면 `recall`은 아무것도 출력하지 않고 종료 코드 1을 반환한다.

## 글로벌 AGENTS.md 예시

`~/.codex/AGENTS.md`에 다음 지침을 추가한다. `CODEX_HOME`을 지정했다면 `$CODEX_HOME/AGENTS.md`를 사용한다.

```markdown
한국어 작업에 필요한 글쓰기 스킬과 기술 스킬은 `skill-lookup ko-writing clang dynamic-linking`처럼 한 번에 읽는다.
내용이 더 필요하면 제목을 아는 절은 `--section`으로 읽고, 제목을 모를 때만 `--search`로 찾는다.
`recall`은 파일과 호출 위치를 찾는 데만 쓴다. 오류는 원본의 기존 진입점에서 재현하고 수정본에서 같은 테스트를 실행한다. 컴파일 오류는 실제 컴파일러로, 로딩 오류는 실제 바이너리를 실행해 확인한다.
```

[BSD 3-Clause 라이선스](LICENSE)
