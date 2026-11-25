import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class LookupCLI(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.skills = self.home / "codex" / "skills"
        self.shared = self.home / ".agents" / "skills"
        self.cache = self.home / "cache"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "CODEX_HOME": str(self.skills.parent),
            "XDG_CACHE_HOME": str(self.cache),
            "PYTHONIOENCODING": "utf-8",
        }
        binary = os.environ.get("SKILL_LOOKUP_BIN")
        self.command = [binary] if binary else [sys.executable, "-m", "skill_lookup"]

    def lookup(self, *arguments, check=True):
        return subprocess.run(
            [*self.command, *arguments],
            cwd=self.home,
            env=self.env,
            capture_output=True,
            encoding="utf-8",
            check=check,
        )

    def document(self, path, body):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(body, encoding="utf-8")
        return path

    def tables(self):
        database = self.cache / "codex-skill-lookup" / "v1.sqlite3"
        with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as db:
            return {name for (name,) in db.execute("SELECT name FROM sqlite_master")}

    def test_bundle_deduplicates_and_reuses_unchanged_documents(self):
        self.document(self.skills / "effective-writing/SKILL.md", "writing\n")
        base = self.document(
            self.skills / "effective-writing/references/base-writing.md", "base\n"
        )
        self.document(self.skills / "ai-slop-thresher/SKILL.md", "한국어\n")
        clang = self.document(self.shared / "clang/SKILL.md", "clang\n")
        self.document(self.shared / "dynamic-linking/SKILL.md", "linker\n")
        arguments = (
            "--status", "ko-writing", "clang", "dynamic-linking", str(base), str(clang)
        )
        expected = "writing\nbase\n한국어\nclang\nlinker\n"
        for status in ("refreshed", "hit"):
            with self.subTest(status=status):
                result = self.lookup(*arguments)
                self.assertEqual(result.stdout, expected)
                self.assertEqual(
                    [line.split()[0] for line in result.stderr.splitlines()], [status] * 5
                )

        self.document(clang, "updated clang\n")
        refreshed = self.lookup(*arguments)
        self.assertEqual(refreshed.stdout, expected.replace("clang", "updated clang"))
        self.assertEqual(
            [line.split()[0] for line in refreshed.stderr.splitlines()],
            ["hit", "hit", "hit", "refreshed", "hit"],
        )
        self.assertNotIn("passages", self.tables())

    def test_missing_required_reference_fails_before_printing(self):
        self.document(self.skills / "effective-writing/SKILL.md", "writing\n")
        (self.skills / "effective-writing/references").mkdir()
        self.document(self.skills / "ai-slop-thresher/SKILL.md", "한국어\n")
        result = self.lookup("ko-writing", check=False)
        self.assertNotEqual(result.returncode, 0)
        self.assertEqual(result.stdout, "")
        self.assertIn("base-writing.md", result.stderr)

    def test_known_section_needs_no_search_index(self):
        section = "## Compile\ncompiler options\n### Flags\n-g\n"
        self.document(
            self.skills / "clang/SKILL.md", "# Guide\n" + section + "## Link\nlinker flags\n"
        )
        result = self.lookup("--section", "Compile", "clang")
        self.assertEqual(result.stdout, section)
        self.assertNotIn("passages", self.tables())

    def test_searches_reference_and_refreshes_changed_passage(self):
        with closing(sqlite3.connect(":memory:")) as db:
            try:
                db.execute("CREATE VIRTUAL TABLE probe USING fts5(body, tokenize='trigram')")
            except sqlite3.OperationalError as error:
                self.skipTest(f"SQLite FTS5 trigram tokenizer unavailable: {error}")

        self.document(self.skills / "clang/SKILL.md", "# Overview\nSee references.\n")
        reference = self.document(
            self.skills / "clang/references/flags.md", "## Flags\nUse firstmarker here.\n"
        )
        result = self.lookup("--search", "firstmarker", "clang")
        self.assertEqual(result.stdout, f"{reference.resolve()} | Flags\nUse firstmarker here.\n")
        self.assertIn("passages", self.tables())

        self.document(reference, "## New flags\nUse replacementmarker here.\n")
        self.assertEqual(self.lookup("--search", "firstmarker", "clang").stdout, "")
        updated = self.lookup("--search", "replacementmarker", "clang")
        self.assertEqual(
            updated.stdout, f"{reference.resolve()} | New flags\nUse replacementmarker here.\n"
        )


if __name__ == "__main__":
    unittest.main()
