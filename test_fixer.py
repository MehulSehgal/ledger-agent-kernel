from pathlib import Path

import pytest

import fixer
from server import FixIn


def test_repo_path_must_resolve_inside_an_allowed_root(tmp_path, monkeypatch):
    allowed = tmp_path / "workspace"
    repo = allowed / "project"
    repo.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(allowed))

    assert fixer.resolve_repo_path(repo) == repo.resolve()
    with pytest.raises(ValueError, match="LEDGER_ALLOWED_ROOTS"):
        fixer.resolve_repo_path(outside)


def test_fix_request_rejects_a_blank_repo_path():
    with pytest.raises(ValueError, match="repo_path"):
        FixIn(repo_path=" ")


def test_repo_copy_skips_generated_and_dependency_directories(tmp_path):
    root = tmp_path / "repo"
    root.mkdir()
    for dirname in (".git", ".venv", "venv", "node_modules", "__pycache__"):
        directory = root / dirname
        directory.mkdir()
        (directory / "secret.py").write_text("raise RuntimeError('must not copy')")
    (root / "app.py").write_text("def run():\n    return 1\n")
    destination = tmp_path / "sandbox"

    fixer.copy_repo(root, destination)

    assert (destination / "app.py").exists()
    assert all(not (destination / name).exists() for name in (
        ".git", ".venv", "venv", "node_modules", "__pycache__"
    ))


def test_repo_copy_enforces_cumulative_size_limit(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    root.mkdir()
    (root / "large.py").write_text("12345")
    monkeypatch.setattr(fixer, "MAX_REPO_BYTES", 4)

    with pytest.raises(fixer.RepoSizeLimitError):
        fixer.copy_repo(root, tmp_path / "sandbox")


def test_localization_parses_both_traceback_formats_and_method_calls(tmp_path):
    (tmp_path / "service.py").write_text(
        "class Service:\n"
        "    def update(self, value):\n"
        "        return value\n"
        "\n"
        "def helper(value):\n"
        "    return value\n"
    )
    (tmp_path / "test_service.py").write_text(
        "from service import Service, helper\n"
        "def test_update():\n"
        "    service = Service()\n"
        "    service.update(helper(1))\n"
    )
    output = (
        'File "service.py", line 3, in update\n'
        "test_service.py:4: in test_update\n"
        "FAILED test_service.py::test_update - AssertionError\n"
    )

    localized = fixer.localize_failure(tmp_path, output)

    candidate_names = {candidate["name"] for candidate in localized["candidates"]}
    assert {"update", "test_update", "helper"} <= candidate_names
    assert localized["failing_test"] == "test_service.py::test_update"
    assert "Service.update(self, value)" in localized["repo_map"]
    assert "return value" not in localized["repo_map"]


def test_repository_map_is_signature_only_and_capped(tmp_path):
    (tmp_path / "module.py").write_text(
        "def calculate(value: int) -> int:\n"
        "    secret_body = 'x' * 10000\n"
        "    return value\n"
    )

    localized = fixer.localize_failure(tmp_path, "")

    assert len(localized["repo_map"]) <= 2000
    assert "calculate(value)" in localized["repo_map"]
    assert "secret_body" not in localized["repo_map"]


def test_candidate_triage_never_returns_more_than_four(monkeypatch):
    candidates = [
        {"name": "same", "path": f"module_{index}.py", "line": index, "source": "def same(): pass"}
        for index in range(5)
    ]
    monkeypatch.setattr(fixer, "live_llm", lambda: True)

    selected = fixer._triage_candidates(
        None,
        {"candidates": candidates, "failing_test": "test_module.py::test_case"},
        lambda *args: '["same"]',
        confidential=False,
    )

    assert len(selected) == 4


def test_test_command_allowlist_rejects_non_pytest_commands():
    assert fixer.validate_test_cmd(["python", "-m", "pytest"]) == [
        "python", "-m", "pytest"
    ]
    for command in (
        ["rm", "-rf", "/"],
        ["python", "-c", "print(1)"],
        ["pip", "install", "pytest"],
    ):
        with pytest.raises(ValueError):
            fixer.validate_test_cmd(command)


def test_failing_test_selector_must_be_a_relative_pytest_node_id():
    assert fixer.validate_test_selector(
        "tests/test_calc.py::TestCalc::test_value[param]"
    ) == "tests/test_calc.py::TestCalc::test_value[param]"
    for selector in ("-k test_calc", "../outside.py::test", "C:\\outside.py::test", ""):
        with pytest.raises(ValueError):
            fixer.validate_test_selector(selector)


def test_test_subprocess_environment_does_not_inherit_virtual_keys(monkeypatch):
    monkeypatch.setenv("BIFROST_VK_LOCAL", "sensitive")
    monkeypatch.setenv("LEDGER_VK_USER", "sensitive")

    env = fixer._test_environment()

    assert "BIFROST_VK_LOCAL" not in env
    assert "LEDGER_VK_USER" not in env


def test_multiple_replacements_in_one_file_are_applied_sequentially(tmp_path):
    source = tmp_path / "module.py"
    source.write_text("first = 1\nsecond = 2\n")

    applied, _ = fixer._apply_patches(
        tmp_path,
        {"module.py": source.read_bytes()},
        [("first = 1", "first = 3"), ("second = 2", "second = 4")],
    )

    assert applied
    assert source.read_text() == "first = 3\nsecond = 4\n"


def test_replacements_preserve_crlf_line_endings(tmp_path):
    source = tmp_path / "module.py"
    source.write_bytes(b"first = 1\r\nsecond = 2\r\n")

    fixer._apply_patches(
        tmp_path,
        {"module.py": source.read_bytes()},
        [("first = 1", "first = 3")],
    )

    assert source.read_bytes() == b"first = 3\r\nsecond = 2\r\n"


def test_api_error_query_uses_only_library_symbol_and_installed_version(
    tmp_path, monkeypatch
):
    (tmp_path / "test_api.py").write_text(
        "import examplelib\n"
        "def test_api():\n"
        "    examplelib.fast_call()\n"
    )
    monkeypatch.setattr(
        fixer.importlib.metadata,
        "packages_distributions",
        lambda: {"examplelib": ["Example-Lib"]},
    )
    monkeypatch.setattr(
        fixer.importlib.metadata,
        "version",
        lambda name: "3.2.1",
    )

    query = fixer.api_error_query(
        "AttributeError: module 'examplelib' has no attribute 'fast_call'",
        tmp_path,
    )

    assert query == "examplelib fast_call 3.2.1"


def test_docs_lookup_requires_network_approval_with_exact_redacted_query(
    tmp_path, monkeypatch
):
    run = _ApprovingRun()
    calls = []
    monkeypatch.setattr(
        fixer,
        "tavily_news",
        lambda query, today: (
            calls.append(("search", query))
            or [{"url": "https://docs.example/api", "title": "API docs"}]
        ),
    )
    def extract(urls, query, chunks):
        calls.append(("extract", query, urls))
        return {urls[0]: "x" * 2000}, []

    monkeypatch.setattr(fixer, "tavily_extract", extract)

    docs = fixer.lookup_api_docs(
        "examplelib fast_call 3.2.1",
        tmp_path,
        run,
        confidential=False,
    )

    assert run.events[0]["data"]["kind"] == "NETWORK"
    assert run.approval_payloads[0]["query"] == "examplelib fast_call 3.2.1"
    assert calls[0] == ("search", "examplelib fast_call 3.2.1")
    assert calls[1][1] == "examplelib fast_call 3.2.1"
    assert docs["text"] == "x" * 1500
    assert docs["url"] == "https://docs.example/api"


def test_offline_stub_is_explicit_and_uses_toy_benchmark_only(monkeypatch):
    repo = Path(__file__).parent / "bench" / "tasks" / "toy_cart"
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(repo.parent.parent.parent))
    monkeypatch.setenv("LEDGER_OFFLINE_STUB", "1")
    monkeypatch.delenv("BIFROST_URL", raising=False)
    monkeypatch.setattr(fixer, "_apply_changes", lambda *args, **kwargs: None)

    result = fixer.run_fix(
        repo_path=repo,
        test_cmd=["python", "-m", "pytest"],
        run=_ApprovingRun(),
    )

    assert result["status"] == "green"
    assert result["engine"] == "offline stub"


class _ApprovingRun:
    approval_channel = True

    def __init__(self):
        self.events = []
        self.approval_payloads = []

    def check_cancelled(self):
        return None

    def emit(self, event_type, data):
        self.events.append({"type": event_type, "data": data})

    def wait_for_approval(self, action_hash, timeout, **kwargs):
        self.approval_payloads.append(kwargs.get("payload", {}))
        self.events.append({
            "type": "approval_request",
            "data": {"hash": action_hash, "kind": kwargs.get("kind")},
        })
        return "approved"

    def consume_approval(self, action_hash):
        return True

    def get_cached(self, key):
        return None

    def set_cached(self, key, value):
        return None


def _failing_repo(root):
    (root / "calc.py").write_text(
        "def calculate(value):\n"
        "    internal_value = value\n"
        "    return internal_value\n"
    )
    (root / "test_calc.py").write_text(
        "from calc import calculate\n"
        "def test_calculate():\n"
        "    assert calculate(1) == 2\n"
    )


def test_fix_attempt_limit_and_full_suite_completion(tmp_path, monkeypatch):
    _failing_repo(tmp_path)
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(tmp_path.parent))
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
    strong_calls = []
    monkeypatch.setattr(
        fixer,
        "chat",
        lambda meter, label, tier, system, user: (
            strong_calls.append((tier, system, user)) or
            "<<<SEARCH\nnot present\n===\nreplacement\n>>>REPLACE"
        ),
    )

    result = fixer.run_fix(
        repo_path=tmp_path,
        test_cmd=["python", "-m", "pytest"],
        run=_ApprovingRun(),
    )

    assert result["status"] == "partial"
    assert len(strong_calls) == 3
    assert all(call[0] == "strong" for call in strong_calls)
    assert len(test_runs) == 1


def test_baseline_uses_full_file_context_and_finishes_with_full_test_run(
    tmp_path, monkeypatch
):
    _failing_repo(tmp_path)
    monkeypatch.setenv("LEDGER_ALLOWED_ROOTS", str(tmp_path.parent))
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
    calls = []

    def chat(meter, label, tier, system, user):
        calls.append((tier, system, user))
        return "<<<SEARCH\n    return internal_value\n===\n    return value + 1\n>>>REPLACE"

    monkeypatch.setattr(fixer, "chat", chat)

    result = fixer.run_baseline(
        repo_path=tmp_path,
        task="Fix the calculation",
        test_cmd=["python", "-m", "pytest"],
        run=_ApprovingRun(),
    )

    assert result["status"] == "green"
    assert calls[0][0] == "strong"
    assert "internal_value = value" in calls[0][1]
    assert len(test_runs) == 3
    assert test_runs[0] is None
    assert test_runs[1] == "test_calc.py::test_calculate"
    assert test_runs[2] is None
