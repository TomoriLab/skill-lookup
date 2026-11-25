import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


class ResultMemoryCLI(unittest.TestCase):
    key = "swift-loader"
    result = "Verified loader observation"
    evidence = "Collected loader evidence"

    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.home = Path(temporary.name)
        self.repo = self.home / "project"
        self.skills = self.home / "codex" / "skills"
        self.env = {
            **os.environ,
            "HOME": str(self.home),
            "USERPROFILE": str(self.home),
            "CODEX_HOME": str(self.skills.parent),
            "XDG_CACHE_HOME": str(self.home / "cache"),
            "PYTHONIOENCODING": "utf-8",
        }
        binary = os.environ.get("SKILL_LOOKUP_BIN")
        self.command = [binary] if binary else [sys.executable, "-m", "skill_lookup"]
        self.source = self.repo / "loader.c"
        self.skill = self.skills / "clang" / "SKILL.md"
        self.reference = self.skills / "clang" / "references" / "flags.md"
        self.skill.parent.mkdir(parents=True)
        self.reference.parent.mkdir()
        self.skill.write_text("# Clang\n", encoding="utf-8")
        self.reference.write_text("Flags 1\n", encoding="utf-8")
        self.init_repo(self.repo)

    def init_repo(self, repo):
        subprocess.run(["git", "init", "-q", str(repo)], env=self.env, check=True)
        (repo / "loader.c").write_text("return 1;\n", encoding="utf-8")
        subprocess.run(["git", "add", "loader.c"], cwd=repo, env=self.env, check=True)
        subprocess.run(
            ["git", "-c", "user.name=Fixture", "-c", "user.email=fixture@example.invalid",
             "-c", "commit.gpgsign=false", "commit", "-qm", "Add fixture"],
            cwd=repo, env=self.env, check=True,
        )

    def run_cli(self, verb, *options, repo=None):
        return subprocess.run(
            [*self.command, verb, "--repo", str(repo or self.repo), *options],
            cwd=self.home, env=self.env, capture_output=True, encoding="utf-8",
        )

    def remember(self, *extra, key=None, result=None):
        saved = self.run_cli(
            "remember", key or self.key, "--file", "loader.c", "--skill", "clang",
            "--result", result or self.result, "--evidence", self.evidence, *extra,
        )
        self.assertEqual(saved.returncode, 0, saved.stderr)

    def assert_hit(self, *options):
        found = self.run_cli("recall", self.key, *options)
        self.assertEqual(found.returncode, 0, found.stderr)
        self.assertIn(self.result, found.stdout)
        self.assertIn(self.evidence, found.stdout)

    def assert_miss(self, key, *options, repo=None):
        found = self.run_cli("recall", key, *options, repo=repo)
        self.assertEqual(found.returncode, 1, found.stderr)
        self.assertEqual(found.stdout, "")
        self.assertNotIn(self.result, found.stderr)
        self.assertNotIn(self.evidence, found.stderr)

    def require_fts5(self):
        with closing(sqlite3.connect(":memory:")) as db:
            try:
                db.execute("CREATE VIRTUAL TABLE probe USING fts5(body)")
            except sqlite3.OperationalError as error:
                self.skipTest(f"SQLite FTS5 unavailable: {error}")

    def search(self, query):
        found = self.run_cli("recall", "--search", query)
        self.assertEqual(found.returncode, 0, found.stderr)
        rows = [json.loads(line) for line in found.stdout.splitlines()]
        for row in rows:
            self.assertEqual(set(row), {"key"})
        return [row["key"] for row in rows]

    def test_exact_hit_after_unrelated_edit_and_miss_for_similar_key_or_other_repo(self):
        self.remember()
        (self.repo / "notes.txt").write_text("unrelated\n", encoding="utf-8")
        self.assert_hit()
        self.assert_hit("--skill", "clang", "--file", "loader.c")
        self.assert_miss("swift-loader-similar")
        other = self.home / "other-project"
        self.init_repo(other)
        self.assert_miss(self.key, repo=other)

    def test_changed_code_or_skill_with_identical_size_and_timestamp_is_a_miss(self):
        for tracked in (self.source, self.skill, self.reference):
            with self.subTest(tracked=tracked.name):
                self.remember("--skill", "clang/references/flags.md")
                original = tracked.read_bytes()
                stat = tracked.stat()
                tracked.write_bytes(original.swapcase())
                os.utime(tracked, ns=(stat.st_atime_ns, stat.st_mtime_ns))
                self.assert_miss(self.key)
                tracked.write_bytes(original)

    def test_requested_dependency_set_must_match_recorded_dependencies(self):
        linker = self.skills / "dynamic-linking" / "SKILL.md"
        linker.parent.mkdir()
        linker.write_text("# Linker\n", encoding="utf-8")
        self.remember("--skill", "dynamic-linking")
        self.assert_hit("--skill", "dynamic-linking", "--skill", "clang")
        self.assert_miss(self.key, "--skill", "clang")
        extra = self.repo / "extra.c"
        extra.write_text("extra\n", encoding="utf-8")
        self.assert_miss(self.key, "--file", extra.name, "--file", self.source.name)

    def test_removing_declared_source_is_a_miss(self):
        self.remember()
        self.source.unlink()
        self.assert_miss(self.key)

    def test_bad_dependency_does_not_overwrite_a_valid_result(self):
        self.remember()
        outside = self.home / "outside.txt"
        outside.write_text("outside\n", encoding="utf-8")
        for option, path in (("--file", "../outside.txt"), ("--file", "missing.c"),
                             ("--skill", "absent-skill")):
            with self.subTest(path=path):
                attempt = self.run_cli(
                    "remember", self.key, "--file", "loader.c", "--skill", "clang",
                    option, path, "--result", "replacement", "--evidence", "replacement",
                )
                self.assertNotEqual(attempt.returncode, 0)
                self.assert_hit()

    def test_required_context_must_match_on_every_recall(self):
        self.remember("--context", "swift=6.3", "--context", "arch=x86_64")
        self.assert_hit("--context", "arch=x86_64", "--context", "swift=6.3")
        self.assert_miss(self.key)
        self.assert_miss(self.key, "--context", "swift=6.3")
        self.assert_miss(self.key, "--context", "swift=6.4", "--context", "arch=x86_64")

    def test_search_returns_up_to_three_keys_and_tracks_replacements(self):
        self.require_fts5()
        self.remember(result="oldmarker")
        self.assertEqual(self.search("oldmarker"), [self.key])
        self.remember(result="newmarker")
        self.assert_miss("--search", "oldmarker")
        self.assertEqual(self.search("newmarker"), [self.key])
        keys = {f"loader-{index}" for index in range(4)}
        for key in sorted(keys):
            self.remember(key=key, result="newmarker")
        found = self.search("newmarker")
        self.assertEqual(len(found), 3)
        self.assertEqual(len(set(found)), 3)
        self.assertTrue(set(found) <= (keys | {self.key}))

    def test_search_skips_stale_results_after_skill_reference_edits_or_additions(self):
        self.require_fts5()
        self.remember()
        self.assertEqual(self.search("observation"), [self.key])
        self.reference.write_text("New flags\n", encoding="utf-8")
        self.assert_miss("--search", "observation")
        self.remember()
        self.assertEqual(self.search("observation"), [self.key])
        self.reference.with_name("more.md").write_text("More flags\n", encoding="utf-8")
        self.assert_miss("--search", "observation")
        self.assert_miss(self.key)

    def test_ko_writing_alias_tracks_writing_references_alongside_technical_skill(self):
        for name in ("effective-writing/SKILL.md", "ai-slop-thresher/SKILL.md",
                     "effective-writing/references/base-writing.md"):
            document = self.skills / name
            document.parent.mkdir(parents=True, exist_ok=True)
            document.write_text("Writing rules\n", encoding="utf-8")
        self.remember("--skill", "ko-writing")
        self.assert_hit()
        base = self.skills / "effective-writing/references/base-writing.md"
        base.write_text("Updated rules\n", encoding="utf-8")
        self.assert_miss(self.key)

    def test_symlink_outside_repository_cannot_replace_a_declared_file(self):
        self.remember()
        outside = self.home / "outside.c"
        self.source.rename(outside)
        try:
            self.source.symlink_to(outside)
        except OSError as error:
            self.skipTest(f"Symlinks unavailable: {error}")
        self.assert_miss(self.key)


if __name__ == "__main__":
    unittest.main()
