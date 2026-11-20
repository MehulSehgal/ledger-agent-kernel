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
import shutil
import subprocess
import tempfile
import threading
from contextlib import contextmanager
from pathlib import Path

CLONE_TIMEOUT_SECONDS = 90
MAX_CLONE_BYTES = 200 * 1024 * 1024

_URL = re.compile(
    r"^https://github\.com/"
    r"(?P<owner>[A-Za-z0-9][A-Za-z0-9-]{0,38})/"
    r"(?P<repo>[A-Za-z0-9._-]{1,100}?)(?:\.git)?/?$"
)

_ACTIVE = set()
_ACTIVE_LOCK = threading.Lock()


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


def is_managed_clone(path):
    """True only for a folder this module created and has not yet deleted."""
    try:
        resolved = Path(path).resolve()
    except OSError:
        return False
    with _ACTIVE_LOCK:
        return any(resolved == active or active in resolved.parents for active in _ACTIVE)


def _git_environment(home):
    return {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": str(home),
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "https",
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
    }


def _git_clone(url, destination, home):
    argv = [
        "git", "clone", "--quiet", "--depth", "1", "--single-branch", "--no-tags",
        "--config", "core.symlinks=false",
        "--", url, str(destination),
    ]
    try:
        result = subprocess.run(
            argv,
            capture_output=True,
            text=True,
            env=_git_environment(home),
            timeout=CLONE_TIMEOUT_SECONDS,
        )
    except FileNotFoundError:
        raise ValueError("git is not installed on this server") from None
    except subprocess.TimeoutExpired:
        raise ValueError(
            f"git clone timed out after {CLONE_TIMEOUT_SECONDS} seconds"
        ) from None
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip().splitlines()
        reason = detail[-1][:200] if detail else "unknown error"
        raise ValueError(
            f"could not clone the repository (it must exist and be public): {reason}"
        )


def _directory_bytes(path):
    total = 0
    for current, _dirs, names in os.walk(path, followlinks=False):
        for name in names:
            try:
                total += (Path(current) / name).lstat().st_size
            except OSError:
                continue
            if total > MAX_CLONE_BYTES:
                return total
    return total


@contextmanager
def cloned_repo(link):
    """Yield ``(path, canonical_url)`` for a fresh clone; delete it on exit."""
    owner, repo = parse_github_url(link)
    _check_owner(owner)
    canonical = f"https://github.com/{owner}/{repo}"
    base = clone_root()
    base.mkdir(parents=True, exist_ok=True)
    workdir = Path(tempfile.mkdtemp(prefix="clone-", dir=base)).resolve()
    destination = workdir / "repo"
    with _ACTIVE_LOCK:
        _ACTIVE.add(destination)
    try:
        _git_clone(canonical + ".git", destination, workdir)
        if not destination.is_dir():
            raise ValueError("clone produced no repository")
        if _directory_bytes(destination) > MAX_CLONE_BYTES:
            raise ValueError("repository is larger than the 200 MB clone limit")
        yield destination, canonical
    finally:
        with _ACTIVE_LOCK:
            _ACTIVE.discard(destination)
        shutil.rmtree(workdir, ignore_errors=True)
