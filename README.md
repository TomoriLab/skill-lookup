# skill-lookup

설치된 Codex 스킬과 Markdown 참조를 한 명령으로 읽는 CLI다. 스킬 이름과 문서 경로를 섞어서 넘길 수 있다. 특정 규칙만 필요하면 제목으로 해당 절을 읽거나 SQLite FTS5로 관련 구절을 찾는다.

## 설치

비공개 저장소를 읽을 수 있는 GitHub 계정과 SSH 키, Python 3의 `sqlite3` 모듈이 필요하다. `--search`는 SQLite의 FTS5와 `trigram` 토크나이저를 사용한다.

```sh
git clone git@github.com:TomoriLab/skill-lookup.git
cd skill-lookup
bin_dir="${CODEX_HOME:-$HOME/.codex}/bin"
mkdir -p "$bin_dir"
install -m 0755 skill-lookup "$bin_dir/skill-lookup"
export PATH="$bin_dir:$PATH"
skill-lookup --help
```

현재 디렉터리의 README로 절 조회와 검색을 확인할 수 있다.

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
- `ko-writing`은 `effective-writing/SKILL.md`, `effective-writing/references/base-writing.md`, `ai-slop-thresher/SKILL.md`를 묶는 별칭이다. 세 파일이 필요하다.
- `--section`은 문서 한 개에서 정확히 일치하는 ATX 제목과 하위 절을 출력한다. `--search`에 디렉터리를 주면 하위 `.md` 파일에서 모든 검색어가 일치하는 구절을 최대 3개 반환한다. 결과에는 문서 경로, 제목, 발췌문이 표시된다.

## 캐시

본문과 검색 색인은 `${XDG_CACHE_HOME:-$HOME/.cache}/codex-skill-lookup/v1.sqlite3`에 저장된다. 파일이 바뀌면 다음 조회에서 해당 본문이나 색인을 갱신한다. 일반 조회에 `--status`를 붙이면 본문은 표준 출력에, 캐시 상태는 표준 오류에 기록된다.

```sh
skill-lookup --status "$PWD/README.md"
```

첫 조회나 파일 변경 후에는 `refreshed`, 같은 파일을 다시 읽으면 `hit`가 표시된다. 디스크 캐시를 쓸 수 없으면 일반 조회는 원문을 반환하고 `source`를 표시한다. 캐시에 적중해도 일반 조회는 본문 전체를 출력하므로 모델에 전달할 분량을 줄이려면 `--section`이나 `--search`를 사용한다.
