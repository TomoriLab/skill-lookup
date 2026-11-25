#!/usr/bin/env python3
"""Retrieve installed Markdown skills and references in one call."""

import argparse
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


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
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
    args = parser.parse_args(argv)
    root = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex")) / "skills"
    database = (
        Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).absolute()
        / "codex-skill-lookup"
        / "v1.sqlite3"
    )
    previous_umask = os.umask(0o077)
    try:
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
