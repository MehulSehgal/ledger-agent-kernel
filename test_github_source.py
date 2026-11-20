"""GitHub-link support for Fix: parsing, allow-list, safe clone, cleanup, e2e."""
import pytest

import github_source


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
