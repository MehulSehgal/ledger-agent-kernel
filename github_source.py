"""Clone a public GitHub repository into a managed scratch folder for Fix.

Security model (Fix executes the repository's own pytest suite, so a GitHub
link means running that repository's code on the server):

* Disabled unless LEDGER_GITHUB_OWNERS lists the GitHub users/orgs that may be
  cloned (comma separated). "*" allows any owner and is an explicit opt-in.
* Only ``https://github.com/OWNER/REPO`` links are accepted: no other hosts,
  credentials, ports, query strings or extra path segments.
* Shallow, single-branch clone with a timeout, no prompts, https only, no
  user/system git config and no inherited secrets.
* The clone lives in a private temporary folder that is deleted afterwards.
  Fix then copies it into its own sandbox exactly as it does for local repos.
"""
import os
import re
import tempfile
from pathlib import Path

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


def allowed_owners():
    raw = os.getenv("LEDGER_GITHUB_OWNERS", "")
    return {item.strip().casefold() for item in raw.split(",") if item.strip()}


def _check_owner(owner):
    owners = allowed_owners()
    if not owners:
        raise ValueError(
            "GitHub links are disabled on this server: set LEDGER_GITHUB_OWNERS "
            "to the GitHub users or organisations that may be cloned"
        )
    if "*" not in owners and owner.casefold() not in owners:
        raise ValueError(f"GitHub owner '{owner}' is not listed in LEDGER_GITHUB_OWNERS")


def clone_root():
    configured = os.getenv("LEDGER_CLONE_ROOT")
    return Path(configured) if configured else Path(tempfile.gettempdir()) / "ledger-clones"
