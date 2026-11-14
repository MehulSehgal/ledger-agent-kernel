import hashlib
import json

import pytest

from policy import Action, PolicyEngine


def test_action_hash_is_canonical_and_payload_specific(tmp_path):
    engine = PolicyEngine(tmp_path)
    first = Action("WRITE", "src/app.py", {"content": "one"})
    reordered = Action("WRITE", "src/app.py", {"content": "one"})
    different = Action("WRITE", "src/app.py", {"content": "two"})

    assert engine.action_hash(first) == engine.action_hash(reordered)
    assert engine.action_hash(first) != engine.action_hash(different)
    canonical = json.dumps(
        {"kind": "WRITE", "target": "src/app.py", "payload": {"content": "one"}},
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    assert engine.action_hash(first) == hashlib.sha256(canonical.encode()).hexdigest()


def test_read_policy_blocks_traversal_and_sensitive_files(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    (root / ".env").write_text("secret")
    engine = PolicyEngine(root)

    assert engine.decide(Action("READ", "../outside.txt")) == "deny"
    assert engine.decide(Action("READ", ".env")) == "deny"
    assert engine.decide(Action("READ", "cert.pem")) == "deny"
    assert engine.decide(Action("READ", "id_rsa_backup")) == "deny"
    assert engine.decide(Action("READ", ".git/config")) == "deny"
    assert engine.decide(Action("READ", "README.md")) == "allow"


def test_read_policy_resolves_symlinks(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    outside = tmp_path / "outside.txt"
    outside.write_text("outside")
    try:
        (root / "linked.txt").symlink_to(outside)
    except OSError as exc:
        if getattr(exc, "winerror", None) == 1314:
            pytest.skip("creating symlinks requires an elevated Windows process")
        raise

    assert PolicyEngine(root).decide(Action("READ", "linked.txt")) == "deny"


def test_shell_and_network_allowlists(tmp_path, monkeypatch):
    monkeypatch.setenv("BIFROST_URL", "https://gateway.example.test/v1")
    engine = PolicyEngine(tmp_path)

    assert engine.decide(Action("SHELL", ["python", "-m", "pytest"])) == "ask"
    for command in (
        ["rm", "-rf", "/"],
        ["curl", "https://example.test"],
        ["pip", "install", "thing"],
        ["git", "push"],
    ):
        assert engine.decide(Action("SHELL", command)) == "deny"
    assert engine.decide(Action("NETWORK", "https://api.tavily.com/search")) == "allow"
    assert engine.decide(Action("NETWORK", "https://gateway.example.test/v1")) == "allow"
    assert engine.decide(Action("NETWORK", "https://example.test")) == "deny"


def test_write_and_git_require_approval(tmp_path):
    engine = PolicyEngine(tmp_path)

    assert engine.decide(Action("WRITE", "app.py", {"content": "changed"})) == "ask"
    assert engine.decide(Action("GIT", ["git", "commit"])) == "ask"
