"""GitHub-link support for Fix: parsing, allow-list, safe clone, cleanup, e2e."""
import subprocess
from pathlib import Path

import pytest

import github_source


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
