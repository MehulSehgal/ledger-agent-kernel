"""Parse and validate GitHub repository links for Fix."""
import re

_URL = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)

def looks_like_url(value):
    if not isinstance(value, str):
        return False
    text = value.strip().lower()
    return "://" in text or text.startswith(("github.com/", "www.github.com/", "git@github.com"))


def parse_github_url(value):
    text = value.strip()
    if text.lower().startswith(("github.com/", "www.github.com/")):
        text = "https://github.com/" + text.split("/", 1)[1]
    match = _URL.match(text)
    owner = match and match.group("owner")
    repo = match and match.group("repo")
    if not match or repo.startswith(".") or repo.lower() == "..":
        raise ValueError("repository link must look like https://github.com/OWNER/REPO")
    return owner, repo
