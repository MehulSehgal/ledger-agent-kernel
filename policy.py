"""Deterministic policy decisions for actions performed by a run."""
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import sys
from urllib.parse import urlsplit


ACTION_KINDS = frozenset({"READ", "WRITE", "SHELL", "GIT", "NETWORK"})


class ConfidentialViolation(RuntimeError):
    """Raised when a confidential action would cross its local-only boundary."""


def classify_confidential(repo_root, request_flag=False):
    if request_flag:
        return True
    root = Path(repo_root).resolve()
    policy_dir = root / ".ledger"
    policy_file = policy_dir / "policy.json"
    if policy_dir.is_symlink() or policy_file.is_symlink():
        return True
    try:
        resolved = policy_file.resolve(strict=True)
        resolved.relative_to(root)
        payload = json.loads(resolved.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return False
    except (OSError, ValueError):
        return True
    if not isinstance(payload, dict):
        return True
    return payload.get("confidential") is True


@dataclass(frozen=True)
class Action:
    kind: str
    target: object
    payload: object = None


def action_hash(action):
    canonical = json.dumps(
        {
            "kind": action.kind,
            "target": action.target,
            "payload": action.payload,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class PolicyEngine:
    def __init__(self, repo_root, bifrost_url=None):
        self.repo_root = Path(repo_root).resolve()
        self.bifrost_url = bifrost_url if bifrost_url is not None else os.getenv("BIFROST_URL")

    def action_hash(self, action):
        return action_hash(action)

    def decide(self, action):
        if not isinstance(action, Action) or action.kind not in ACTION_KINDS:
            return "deny"
        if action.kind == "READ":
            return "allow" if self._safe_repo_path(action.target) else "deny"
        if action.kind == "WRITE":
            targets = action.target if isinstance(action.target, (list, tuple)) else [action.target]
            return "ask" if targets and all(self._safe_repo_path(target) for target in targets) else "deny"
        if action.kind == "SHELL":
            return "ask" if self._pytest_command(action.target) else "deny"
        if action.kind == "GIT":
            return "ask"
        if action.kind == "NETWORK":
            return "allow" if self._allowed_network(action.target) else "deny"
        return "deny"

    def _safe_repo_path(self, target):
        if not isinstance(target, (str, os.PathLike)):
            return False
        path = Path(target)
        resolved = (self.repo_root / path).resolve() if not path.is_absolute() else path.resolve()
        try:
            relative = resolved.relative_to(self.repo_root)
        except ValueError:
            return False
        parts = [part.casefold() for part in relative.parts]
        if any(part == ".env" or part.startswith(".env.") for part in parts):
            return False
        if any(part.endswith(".pem") or part.startswith("id_rsa") for part in parts):
            return False
        if len(parts) >= 2 and parts[-2:] == [".git", "config"]:
            return False
        return True

    @staticmethod
    def _pytest_command(target):
        if not isinstance(target, (list, tuple)) or len(target) < 3:
            return False
        if not all(isinstance(part, str) for part in target):
            return False
        executable = target[0].casefold()
        allowed = {"python", "python.exe", os.path.abspath(sys.executable).casefold()}
        if executable not in allowed:
            return False
        if target[1:3] != ["-m", "pytest"]:
            return False
        return True

    def _allowed_network(self, target):
        if not isinstance(target, str):
            return False
        url = target if "://" in target else f"https://{target}"
        try:
            host = urlsplit(url).hostname
        except ValueError:
            return False
        if not host:
            return False
        allowed = {"api.tavily.com"}
        if self.bifrost_url:
            try:
                bifrost_host = urlsplit(
                    self.bifrost_url if "://" in self.bifrost_url else f"https://{self.bifrost_url}"
                ).hostname
            except ValueError:
                bifrost_host = None
            if bifrost_host:
                allowed.add(bifrost_host.casefold())
        return host.casefold() in allowed
