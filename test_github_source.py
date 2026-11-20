"""GitHub-link support for Fix: parsing, allow-list, safe clone, cleanup, e2e."""
import shutil
import subprocess
from pathlib import Path

import pytest

import fixer
import github_source
from test_fixer import _ApprovingRun, _failing_repo


@pytest.fixture(autouse=True)
def isolated_clones(tmp_path, monkeypatch):
    monkeypatch.setenv("LEDGER_CLONE_ROOT", str(tmp_path / "clones"))
    monkeypatch.setenv("LEDGER_GITHUB_OWNERS", "Owner")


def fake_git(monkeypatch, populate=None, returncode=0, stderr=""):
    calls = []

    def run(argv, **kwargs):
        calls.append((argv, kwargs))
        destination = Path(argv[-1])
        if returncode == 0:
            destination.mkdir(parents=True)
            if populate:
                populate(destination)
        return subprocess.CompletedProcess(argv, returncode, "", stderr)

    monkeypatch.setattr(github_source.subprocess, "run", run)
    return calls


# --- parsing ---------------------------------------------------------------

@pytest.mark.parametrize("link,expected", [
    ("https://github.com/Owner/repo", ("Owner", "repo")),
    ("https://github.com/Owner/repo.git", ("Owner", "repo")),
    ("https://github.com/Owner/repo/", ("Owner", "repo")),
    ("  https://github.com/Owner/my.repo_1  ", ("Owner", "my.repo_1")),
    ("github.com/Owner/repo", ("Owner", "repo")),
    ("www.github.com/Owner/repo", ("Owner", "repo")),
])
def test_parse_accepts_plain_repository_links(link, expected):
    assert github_source.parse_github_url(link) == expected


@pytest.mark.parametrize("link", [
    "http://github.com/Owner/repo",
    "https://gitlab.com/Owner/repo",
    "https://evil.com/github.com/Owner/repo",
    "https://user:pw@github.com/Owner/repo",
    "https://github.com:8443/Owner/repo",
    "https://github.com/Owner/repo/tree/main",
    "https://github.com/Owner",
    "https://github.com/Owner/..",
    "https://github.com/Owner/.hidden",
    "https://github.com/Owner/repo?x=1",
    "https://github.com/Owner/repo#frag",
    "https://github.com/-bad/repo",
    "file:///etc/passwd",
    "ssh://git@github.com/Owner/repo",
    "git@github.com:Owner/repo.git",
    "https://github.com/Owner/repo name",
])
def test_parse_rejects_everything_else(link):
    with pytest.raises(ValueError):
        github_source.parse_github_url(link)


def test_only_urls_are_treated_as_links_not_local_paths():
    assert github_source.looks_like_url("https://github.com/o/r")
    assert github_source.looks_like_url("github.com/o/r")
    assert not github_source.looks_like_url("/Users/me/work/repo")
    assert not github_source.looks_like_url("C:\\work\\repo")
    assert not github_source.looks_like_url(None)


# --- allow-list ------------------------------------------------------------

def test_disabled_until_owners_are_configured(monkeypatch):
    monkeypatch.delenv("LEDGER_GITHUB_OWNERS")
    calls = fake_git(monkeypatch)
    with pytest.raises(ValueError, match="disabled"):
        with github_source.cloned_repo("https://github.com/Owner/repo"):
            pass
    assert calls == []


def test_owner_must_be_listed_case_insensitively(monkeypatch):
    calls = fake_git(monkeypatch)
    with pytest.raises(ValueError, match="not listed"):
        with github_source.cloned_repo("https://github.com/Stranger/repo"):
            pass
    assert calls == []
    with github_source.cloned_repo("https://github.com/OWNER/repo"):
        pass
    assert len(calls) == 1


def test_wildcard_allows_any_owner_only_when_explicit(monkeypatch):
    monkeypatch.setenv("LEDGER_GITHUB_OWNERS", "*")
    fake_git(monkeypatch)
    with github_source.cloned_repo("https://github.com/Anyone/repo") as (_, url):
        assert url == "https://github.com/Anyone/repo"


# --- clone safety ----------------------------------------------------------

def test_clone_command_is_hardened_and_leaks_no_secrets(monkeypatch):
    monkeypatch.setenv("TAVILY_API_KEY", "tvly-secret")
    monkeypatch.setenv("BIFROST_VK", "vk-secret")
    calls = fake_git(monkeypatch)
    with github_source.cloned_repo("https://github.com/Owner/repo.git"):
        pass
    argv, kwargs = calls[0]
    assert argv[:2] == ["git", "clone"]
    assert "--depth" in argv and argv[argv.index("--depth") + 1] == "1"
    assert "--single-branch" in argv and "--no-tags" in argv
    assert argv[argv.index("--") + 1] == "https://github.com/Owner/repo.git"
    env = kwargs["env"]
    assert env["GIT_ALLOW_PROTOCOL"] == "https"
    assert env["GIT_TERMINAL_PROMPT"] == "0"
    assert not any("secret" in value for value in env.values())
    assert "TAVILY_API_KEY" not in env and "BIFROST_VK" not in env
    assert kwargs["timeout"] == github_source.CLONE_TIMEOUT_SECONDS
    assert kwargs.get("shell") is not True


def test_failed_clone_reports_public_repo_hint(monkeypatch):
    fake_git(monkeypatch, returncode=128, stderr="fatal: repository not found\n")
    with pytest.raises(ValueError, match="exist and be public.*not found"):
        with github_source.cloned_repo("https://github.com/Owner/private"):
            pass


def test_timeout_and_missing_git_have_clear_errors(monkeypatch):
    def boom(exc):
        def run(argv, **kwargs):
            raise exc
        monkeypatch.setattr(github_source.subprocess, "run", run)

    boom(subprocess.TimeoutExpired("git", 90))
    with pytest.raises(ValueError, match="timed out"):
        with github_source.cloned_repo("https://github.com/Owner/repo"):
            pass
    boom(FileNotFoundError())
    with pytest.raises(ValueError, match="git is not installed"):
        with github_source.cloned_repo("https://github.com/Owner/repo"):
            pass


def test_oversized_clone_is_rejected_and_removed(monkeypatch, tmp_path):
    monkeypatch.setattr(github_source, "MAX_CLONE_BYTES", 10)
    fake_git(monkeypatch, populate=lambda d: (d / "big.bin").write_bytes(b"x" * 100))
    with pytest.raises(ValueError, match="200 MB"):
        with github_source.cloned_repo("https://github.com/Owner/repo"):
            pass
    assert list((tmp_path / "clones").iterdir()) == []


def test_clone_is_deleted_after_success_and_after_errors(monkeypatch, tmp_path):
    fake_git(monkeypatch, populate=lambda d: (d / "a.py").write_text("x"))
    with github_source.cloned_repo("https://github.com/Owner/repo") as (path, _):
        assert path.is_dir() and github_source.is_managed_clone(path)
        assert github_source.is_managed_clone(path / "a.py")
    assert not path.exists() and not github_source.is_managed_clone(path)
    assert list((tmp_path / "clones").iterdir()) == []

    with pytest.raises(RuntimeError):
        with github_source.cloned_repo("https://github.com/Owner/repo") as (path, _):
            raise RuntimeError("boom")
    assert not path.exists()
    assert list((tmp_path / "clones").iterdir()) == []


def test_managed_clone_registry_does_not_widen_allowed_roots(monkeypatch, tmp_path):
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(allowed))
    with pytest.raises(ValueError, match="LEDGER_ALLOWED_ROOTS"):
        fixer.resolve_repo_path(elsewhere)
    fake_git(monkeypatch)
    with github_source.cloned_repo("https://github.com/Owner/repo") as (path, _):
        assert fixer.resolve_repo_path(path) == path
    with pytest.raises(FileNotFoundError):
        fixer.resolve_repo_path(path)  # deleted clone is no longer accepted
    with pytest.raises(ValueError, match="LEDGER_ALLOWED_ROOTS"):
        fixer.resolve_repo_path(elsewhere)


def test_bad_links_never_reach_the_filesystem_or_git(monkeypatch, tmp_path):
    calls = fake_git(monkeypatch)
    for link in ("https://evil.example/Owner/repo", "https://github.com/Owner/repo/tree/x"):
        with pytest.raises(ValueError):
            fixer.run_fix(repo_path=link, run=_ApprovingRun())
    assert calls == []
    assert not (tmp_path / "clones").exists()


# --- end to end ------------------------------------------------------------

def test_fix_runs_on_a_github_link_and_returns_diff_without_writing(
    monkeypatch, tmp_path
):
    source = tmp_path / "source"
    source.mkdir()
    _failing_repo(source)
    fake_git(monkeypatch, populate=lambda d: shutil.copytree(source, d, dirs_exist_ok=True))
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(tmp_path / "unrelated"))
    monkeypatch.setenv("LEDGER_OFFLINE_STUB", "0")
    monkeypatch.setattr(fixer, "live_llm", lambda: True)
    test_runs = []

    def run_tests(*args, **kwargs):
        test_runs.append(kwargs.get("test_selector"))
        if len(test_runs) == 1:
            return False, (
                "test_calc.py:3: in test_calculate\n"
                "FAILED test_calc.py::test_calculate - AssertionError\n"
                "E assert 1 == 2\n"
            )
        return True, ""

    monkeypatch.setattr(fixer, "_run_test_command", run_tests)
    monkeypatch.setattr(
        fixer, "chat",
        lambda meter, label, tier, system, user: (
            "<<<SEARCH\n    return internal_value\n===\n    return value + 1\n>>>REPLACE"
        ),
    )

    result = fixer.run_fix(
        repo_path="https://github.com/Owner/repo",
        test_cmd=["python", "-m", "pytest"],
        run=_ApprovingRun(),
    )

    assert result["status"] == "green"
    assert "return value + 1" in result["diff"]
    assert "https://github.com/Owner/repo" in result["message"]
    assert "Nothing was pushed" in result["message"]
    assert list((tmp_path / "clones").iterdir()) == []  # clone cleaned up
