# skill-lookup

설치된 Codex 스킬과 Markdown 참조를 한 명령으로 읽는 CLI다. 스킬 이름과 문서 경로를 섞어서 넘길 수 있다. 특정 규칙만 필요하면 제목으로 해당 절을 읽거나 SQLite FTS5로 관련 구절을 찾는다.

## 설치

아래 Git 명령은 비공개 저장소를 읽을 수 있는 GitHub SSH 인증을 사용한다. Python 3.10 이상과 `sqlite3` 모듈이 필요하다. `--search`에는 FTS5와 `trigram` 토크나이저도 필요하다.

uv로 GitHub에서 바로 설치할 수 있다. 실행 파일은 `uv tool dir --bin`이 가리키는 디렉터리에 생긴다.

```sh
uv tool install git+ssh://git@github.com/TomoriLab/skill-lookup.git
export PATH="$(uv tool dir --bin):$PATH"
skill-lookup --help
```

새 셸에서도 명령을 찾게 하려면 `uv tool update-shell`을 실행한 뒤 셸을 다시 연다. wheel 파일을 전달받은 환경에서는 `uv tool install ./skill_lookup-0.1.0-py3-none-any.whl`로 설치할 수 있다.

소스에서 설치하려면 저장소를 복제한 뒤 로컬 경로를 지정한다.

```sh
git clone git@github.com:TomoriLab/skill-lookup.git
cd skill-lookup
uv tool install .
export PATH="$(uv tool dir --bin):$PATH"
```

기존 `${CODEX_HOME:-$HOME/.codex}/bin/skill-lookup` 경로가 필요한 환경에서는 복제한 저장소 루트에서 단일 실행 파일을 설치할 수 있다.

```sh
bin_dir="${CODEX_HOME:-$HOME/.codex}/bin"
mkdir -p "$bin_dir"
install -m 0755 skill-lookup "$bin_dir/skill-lookup"
export PATH="$bin_dir:$PATH"
skill-lookup --help
```

복제한 저장소 루트에서는 README로 절 조회와 검색을 확인할 수 있다.

```sh
skill-lookup --section '설치' "$PWD/README.md"
skill-lookup --search '토크나이저' "$PWD/README.md"
```

## 스킬과 참조 일괄 조회

아래 예시는 해당 스킬이 설치된 환경을 기준으로 한다.

```sh
skill-lookup ko-writing clang dynamic-linking
skill-lookup --section 'Grade' repo-eval/references/specs.md
skill-lookup --search 'oracle' repo-eval
```

- 상대 경로와 스킬 이름은 `${CODEX_HOME:-$HOME/.codex}/skills`에서 먼저 찾고 `~/.agents/skills`에서 다시 찾는다. 다른 위치의 문서는 절대 경로로 지정할 수 있다.
- 일반 조회에서 스킬 디렉터리는 그 안의 `SKILL.md`를 가리킨다. 여러 인자는 입력 순서로 읽고 같은 파일은 한 번만 출력한다.
- `ko-writing`은 `effective-writing/SKILL.md`, `effective-writing/references/base-writing.md`, `ai-slop-thresher/SKILL.md`를 묶는 별칭이다. 이 문서들은 각 스킬에서 제공한다. 하나라도 없으면 일괄 조회가 실패하므로 설치된 문서 경로를 직접 지정한다.
- `--section`은 문서 한 개에서 정확히 일치하는 ATX 제목과 하위 절을 출력한다. `--search`에 디렉터리를 주면 하위 `.md` 파일에서 모든 검색어가 일치하는 구절을 최대 3개 반환한다. 결과에는 문서 경로, 제목, 발췌문이 표시된다.

## 글로벌 AGENTS.md 예시

Codex를 실행하는 환경의 `PATH`에 `skill-lookup`이 있으면 다음 지침을 `${CODEX_HOME:-$HOME/.codex}/AGENTS.md`에 추가할 수 있다.

```markdown
현재 대화에서 읽은 스킬 규칙은 재사용한다. 새로 필요한 스킬과 필수 참조는 한 번에 조회한다.
한국어 글쓰기와 기술 작업이 겹치면 `skill-lookup ko-writing clang dynamic-linking`처럼 관련 스킬 이름이나 Markdown 경로를 함께 넘긴다.
정보가 부족하고 절 제목을 알면 `skill-lookup --section '제목' 문서`로 바로 읽는다.
절 제목도 모를 때만 `skill-lookup --search '검색어' 스킬`을 사용한다. 발췌문이 부족할 때만 결과의 문서와 제목으로 해당 절을 읽는다.
FTS5 검색을 사용할 수 없으면 원문에서 제목을 찾는다. CLI가 설치되어 있지 않으면 필요한 스킬과 참조를 원문에서 직접 읽는다.
```

## 캐시

본문과 검색 색인은 `${XDG_CACHE_HOME:-$HOME/.cache}/codex-skill-lookup/v1.sqlite3`에 저장된다. 파일이 바뀌면 다음 조회에서 해당 본문이나 색인을 갱신한다. 일반 조회에 `--status`를 붙이면 본문은 표준 출력에, 캐시 상태는 표준 오류에 기록된다.

```sh
skill-lookup --status "$PWD/README.md"
```

첫 조회나 파일 변경 후에는 `refreshed`, 같은 파일을 다시 읽으면 `hit`가 표시된다. 디스크 캐시를 쓸 수 없으면 일반 조회는 원문을 반환하고 `source`를 표시한다. 캐시에 적중해도 일반 조회는 본문 전체를 출력하므로 모델에 전달할 분량을 줄이려면 `--section`이나 `--search`를 사용한다.

## 개발

복제한 저장소 루트에서 잠금 파일에 맞춰 환경을 만들고 CLI 테스트를 실행한다. 빌드 결과인 소스 배포본과 wheel은 `dist/`에 생성된다.

```sh
uv sync --locked
uv run --locked python -m unittest discover -s tests
uv build
```

## 라이선스

[BSD 3-Clause](LICENSE)
