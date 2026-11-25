#!/usr/bin/env python3
# BSD 3-Clause License
#
# Copyright (c) 2026 Euiseo Cha
#
# Redistribution and use in source and binary forms, with or without
# modification, are permitted provided that the following conditions are met:
#
# 1. Redistributions of source code must retain the above copyright notice, this
#    list of conditions and the following disclaimer.
#
# 2. Redistributions in binary form must reproduce the above copyright notice,
#    this list of conditions and the following disclaimer in the documentation
#    and/or other materials provided with the distribution.
#
# 3. Neither the name of the copyright holder nor the names of its contributors
#    may be used to endorse or promote products derived from this software
#    without specific prior written permission.
#
# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
# AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
# IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
# FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
# DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
# SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
# CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
# OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
# OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.

"""Retrieve installed Markdown skills and references in one call."""

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from pathlib import Path


def signature(stat):
    return ":".join(
        str(value)
        for value in (
            stat.st_dev,
            stat.st_ino,
            stat.st_size,
            stat.st_mtime_ns,
            stat.st_ctime_ns,
        )
    )


def lookup(path, database):
    with path.open("rb") as source:
        key = signature(os.fstat(source.fileno()))
        if database.exists():
            try:
                with sqlite3.connect(
                    database.as_uri() + "?mode=ro", uri=True
                ) as connection:
                    row = connection.execute(
                        "SELECT body FROM documents WHERE path=? AND signature=?",
                        (str(path), key),
                    ).fetchone()
                if row:
                    return row[0], "hit"
            except sqlite3.Error:
                pass
        body = source.read().decode("utf-8")
        if signature(os.fstat(source.fileno())) != key:
            raise OSError(f"Source changed during lookup: {path}. Retry.")
    try:
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            connection.execute(
                "CREATE TABLE IF NOT EXISTS documents (path TEXT PRIMARY KEY, signature TEXT NOT NULL, body TEXT NOT NULL)"
            )
            connection.execute(
                "INSERT OR REPLACE INTO documents VALUES (?,?,?)",
                (str(path), key, body),
            )
        return body, "refreshed"
    except (OSError, sqlite3.Error):
        return body, "source"


def headings(lines):
    fence = None
    for index, line in enumerate(lines):
        marker = re.match(r"^ {0,3}(`{3,}|~{3,})", line)
        if marker:
            token = marker[1]
            if not fence:
                fence = token
            elif token.startswith(fence) and not line.strip()[len(token) :]:
                fence = None
            continue
        match = re.match(r"^(#{1,6})\s+(.+?)\s*$", line)
        if match and not fence:
            yield index, len(match[1]), match[2]


def section(body, heading):
    lines = body.splitlines(keepends=True)
    matches = headings(lines)
    for start, depth, title in matches:
        if title == heading:
            end = next((i for i, level, _ in matches if level <= depth), len(lines))
            return "".join(lines[start:end])
    raise ValueError(f"Heading not found: {heading}")


def passages(body):
    lines = body.splitlines()
    start = 0
    heading = "(preamble)"
    for index, _, title in headings(lines):
        if index > start or start:
            yield heading, "\n".join(lines[start:index])
        heading, start = title, index + 1
    yield heading, "\n".join(lines[start:])


def search_files(names, query, root, database):
    terms = list(dict.fromkeys(query.lower().split()))
    if not terms:
        raise ValueError("Provide at least one search term")
    sources = {}
    for name in names:
        path = (root / name).resolve(strict=True)
        files = sorted(path.rglob("*.md")) if path.is_dir() else [path]
        for file in files:
            if file.suffix.lower() == ".md":
                sources[str(file.resolve())] = signature(file.stat())
    if not sources:
        return
    params = ",".join("?" for _ in sources)

    def indexed(connection):
        return dict(
            connection.execute(
                f"SELECT path, signature FROM search_sources WHERE path IN ({params})",
                tuple(sources),
            )
        )

    def update(connection):
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "CREATE TABLE IF NOT EXISTS search_sources(path TEXT PRIMARY KEY, signature TEXT NOT NULL)"
        )
        connection.execute(
            "CREATE VIRTUAL TABLE IF NOT EXISTS passages USING fts5(path UNINDEXED, heading, body, tokenize='trigram')"
        )
        existing = indexed(connection)
        for path, key in sources.items():
            if existing.get(path) == key:
                continue
            with open(path, encoding="utf-8") as source:
                body = source.read()
                if signature(os.fstat(source.fileno())) != key:
                    raise OSError("Source changed during indexing. Retry.")
            connection.execute("DELETE FROM passages WHERE path=?", (path,))
            connection.executemany(
                "INSERT INTO passages VALUES (?,?,?)",
                ((path, title, content) for title, content in passages(body)),
            )
            connection.execute(
                "INSERT OR REPLACE INTO search_sources VALUES (?,?)", (path, key)
            )
        connection.commit()

    connection = None
    try:
        try:
            connection = sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)
            connection.execute("BEGIN")
            if indexed(connection) != sources:
                raise sqlite3.OperationalError("Index requires refresh")
        except sqlite3.Error:
            if connection:
                connection.close()
            try:
                database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
                connection = sqlite3.connect(database)
                update(connection)
            except (sqlite3.Error, OSError):
                if connection:
                    connection.close()
                connection = sqlite3.connect(":memory:")
                update(connection)
        conditions = [f"path IN ({params})"]
        values = list(sources)
        long_terms = [term for term in terms if len(term) >= 3]
        if long_terms:
            conditions.append("passages MATCH ?")
            values.append(
                " AND ".join('"' + term.replace('"', '""') + '"' for term in long_terms)
            )
        for term in terms:
            if len(term) < 3:
                conditions.append("instr(lower(heading || ' ' || body), ?) > 0")
                values.append(term)
        rank = "bm25(passages,0,4,1)," if long_terms else ""
        sql = (
            "SELECT path,heading,body FROM passages WHERE "
            + " AND ".join(conditions)
            + " ORDER BY "
            + rank
            + "path,heading,rowid LIMIT 3"
        )
        for path, title, content in connection.execute(sql, values):
            text = " ".join(content.split())
            offsets = [text.lower().find(term) for term in terms]
            offset = max(0, min((n for n in offsets if n >= 0), default=0) - 32)
            print(f"{path} | {title}\n{text[offset : offset + 150]}")
    finally:
        if connection:
            connection.close()


WRITING_DOCUMENTS = (
    "effective-writing/SKILL.md",
    "effective-writing/references/base-writing.md",
    "ai-slop-thresher/SKILL.md",
)


def resolve_sources(arguments, root, *, search):
    # Resolve aliases before reading so a bad argument cannot produce a partial bundle.
    sources = {}
    for argument in arguments:
        names = WRITING_DOCUMENTS if argument == "ko-writing" else (argument,)
        for name in names:
            path = Path(name).expanduser()
            if not path.is_absolute():
                primary = root / path
                shared = Path.home() / ".agents" / "skills" / path
                path = shared if not primary.exists() and shared.exists() else primary
            if not search and path.is_dir():
                path = path / "SKILL.md"
            path = path.resolve(strict=True)
            if not (search and path.is_dir()) and (
                not path.is_file() or path.suffix.lower() != ".md"
            ):
                raise ValueError(f"Expected a Markdown file or skill directory: {path}")
            sources.setdefault(path, name)
    return sources


def file_digest(path):
    if not path.is_file():
        raise ValueError(f"Expected a regular file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        initial = os.fstat(stream.fileno())
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if signature(initial) != signature(path.stat()):
        raise OSError(f"File changed during lookup: {path}")
    return [initial.st_mode & 0o111, digest.hexdigest()]


def skill_digest(path, parents=()):
    if not path.is_dir():
        return file_digest(path)
    directory = path.resolve(strict=True)
    if directory in parents:
        raise ValueError(f"Circular skill directory: {path}")
    # Include references and helper scripts even when the main Markdown is unchanged.
    return {
        child.name: skill_digest(child, (*parents, directory))
        for child in sorted(path.iterdir())
        if child.name not in {".git", "__pycache__"}
    }


def fingerprint(repo, root, files, skills):
    inputs = []
    for name in files:
        path = (repo / name).resolve(strict=True)
        if Path(name).is_absolute() or not path.is_relative_to(repo):
            raise ValueError(f"Expected a path within the repository: {name}")
        inputs.append([name, file_digest(path)])
    for name in skills:
        paths = resolve_sources([name], root, search=True)
        inputs.append([name, [skill_digest(path) for path in paths]])
    return hashlib.sha256(json.dumps(inputs, sort_keys=True).encode()).hexdigest()


def has_table(connection, name):
    return connection.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (name,)
    ).fetchone() is not None


def remember(connection, args, repo, root):
    files = sorted(set(args.file))
    skills = sorted(set(args.skill))
    digest = fingerprint(repo, root, files, skills)
    connection.execute(
        "CREATE TABLE IF NOT EXISTS memories (repo TEXT, key TEXT, files TEXT, "
        "skills TEXT, context TEXT, digest TEXT, result TEXT, evidence TEXT, "
        "PRIMARY KEY (repo, key))"
    )
    connection.execute(
        "INSERT INTO memories(repo,key,files,skills,context,digest,result,evidence) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(repo,key) DO UPDATE SET "
        "files=excluded.files, skills=excluded.skills, context=excluded.context, "
        "digest=excluded.digest, result=excluded.result, evidence=excluded.evidence",
        (str(repo), args.key, json.dumps(files), json.dumps(skills),
         json.dumps(sorted(set(args.context))), digest, args.result, args.evidence),
    )
    if has_table(connection, "memory_search"):
        rowid, = connection.execute(
            "SELECT rowid FROM memories WHERE repo=? AND key=?", (str(repo), args.key)
        ).fetchone()
        connection.execute("DELETE FROM memory_search WHERE rowid=?", (rowid,))
        connection.execute(
            "INSERT INTO memory_search(rowid,key,result,evidence) VALUES (?,?,?,?)",
            (rowid, args.key, args.result, args.evidence),
        )


def search_memories(connection, query, repo):
    if not has_table(connection, "memory_search"):
        connection.execute("BEGIN IMMEDIATE")
        if not has_table(connection, "memory_search"):
            connection.execute(
                "CREATE VIRTUAL TABLE memory_search USING fts5(key, result, evidence)"
            )
            connection.execute(
                "INSERT INTO memory_search(rowid,key,result,evidence) "
                "SELECT rowid,key,result,evidence FROM memories"
            )
        connection.commit()
    expression = " AND ".join('"' + term.replace('"', '""') + '"' for term in query.split())
    return connection.execute(
        "SELECT m.* FROM memory_search JOIN memories AS m ON m.rowid=memory_search.rowid "
        "WHERE memory_search MATCH ? AND m.repo=? ORDER BY rank,m.key",
        (expression, str(repo)),
    )


def recall(connection, args, repo, root):
    if not has_table(connection, "memories"):
        return 1
    connection.row_factory = sqlite3.Row
    if args.search:
        rows = search_memories(connection, args.search, repo)
    else:
        rows = connection.execute("SELECT * FROM memories WHERE repo=? AND key=?", (str(repo), args.key))
    count = 0
    for row in rows:
        files, skills = json.loads(row["files"]), json.loads(row["skills"])
        if (sorted(set(args.context)) != json.loads(row["context"])
                or (args.file and sorted(set(args.file)) != files)
                or (args.skill and sorted(set(args.skill)) != skills)):
            continue
        try:
            current = fingerprint(repo, root, files, skills)
        except (OSError, ValueError):
            continue
        if current != row["digest"]:
            continue
        hit = {"key": row["key"]}
        if not args.search:
            hit.update(result=row["result"], evidence=row["evidence"])
        print(json.dumps(hit, ensure_ascii=False))
        count += 1
        if count == 3:
            break
    return 0 if count else 1


def memory_command(verb, argv, root, database):
    parser = argparse.ArgumentParser(prog=f"skill-lookup {verb}")
    saving = verb == "remember"
    if saving:
        parser.add_argument("key")
        parser.add_argument("--result", required=True)
        parser.add_argument("--evidence", required=True, help="How the result was verified")
    else:
        choice = parser.add_mutually_exclusive_group(required=True)
        choice.add_argument("key", nargs="?")
        choice.add_argument("--search", help="Find up to three current candidate keys with FTS5")
    parser.add_argument("--repo", default=".", type=Path, help="Repository root (default: current directory)")
    parser.add_argument("--file", action="append", required=saving, help="Repository-relative input file")
    parser.add_argument("--skill", action="append", required=saving, help="Installed skill or Markdown reference")
    parser.add_argument("--context", action="append", default=[], help="Additional condition, e.g. a tool version")
    args = parser.parse_args(argv)
    for field in ("key", "search", "result", "evidence"):
        value = getattr(args, field, None)
        if value is not None and not value.strip():
            parser.error(f"{field} must not be blank")
    repo = args.repo.resolve(strict=True)
    if not repo.is_dir():
        parser.error("--repo must be a directory")
    if saving:
        database.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        with sqlite3.connect(database) as connection:
            remember(connection, args, repo, root)
        return 0
    if not database.is_file():
        return 1
    mode = "rw" if args.search else "ro"
    with sqlite3.connect(database.as_uri() + "?mode=" + mode, uri=True) as connection:
        return recall(connection, args, repo, root)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    parser = argparse.ArgumentParser(
        description=__doc__,
        epilog="Use 'skill-lookup remember --help' or 'skill-lookup recall --help' for verified results.",
    )
    parser.add_argument(
        "files",
        nargs="+",
        help="Mix ko-writing, skill names, directories and Markdown paths in reading order",
    )
    options = parser.add_mutually_exclusive_group()
    options.add_argument(
        "--search",
        help="Find up to three sections matching all terms in specified files or skill directories",
    )
    options.add_argument("--section", help="Exact ATX heading in one Markdown document")
    parser.add_argument(
        "--status", action="store_true", help="Show cache disposition on stderr"
    )
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    database = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).absolute()
        / "codex-skill-lookup"
        / "v1.sqlite3"
    )
    previous_umask = os.umask(0o077)
    try:
        if argv and argv[0] in {"remember", "recall"}:
            return memory_command(argv[0], argv[1:], root, database)
        args = parser.parse_args(argv)
        sources = resolve_sources(args.files, root, search=args.search is not None)
        if args.search is not None:
            search_files(sources, args.search, root, database)
            return 0
        if args.section and len(sources) != 1:
            parser.error("--section requires one document")
        for path, name in sources.items():
            body, status = lookup(path, database)
            if args.status:
                print(status, name, file=sys.stderr)
            print(section(body, args.section) if args.section else body, end="")
    except (OSError, ValueError, sqlite3.Error) as error:
        parser.exit(1, f"{error}\n")
    finally:
        os.umask(previous_umask)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
