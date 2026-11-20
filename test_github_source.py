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
