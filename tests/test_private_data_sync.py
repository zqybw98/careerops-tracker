from __future__ import annotations

import json
import subprocess
from collections.abc import Sequence
from pathlib import Path

import pytest
from src.private_data_export import ExportResult
from src.private_data_sync import (
    EXPECTED_REPOSITORY,
    CommandResult,
    SubprocessRunner,
    SyncConfig,
    SyncError,
    build_sync_config,
    main,
    run_sync,
)


class FakeRunner:
    def __init__(
        self,
        responses: dict[tuple[str, ...], CommandResult | list[CommandResult]],
    ) -> None:
        self.responses = responses
        self.calls: list[tuple[tuple[str, ...], Path]] = []

    def run(self, args: Sequence[str], cwd: Path) -> CommandResult:
        command = tuple(args)
        self.calls.append((command, cwd))
        response = self.responses.get(command, CommandResult(0, "", ""))
        if isinstance(response, list):
            return response.pop(0)
        return response


class LocalGitRunner(SubprocessRunner):
    def __init__(self) -> None:
        self.calls: list[tuple[tuple[str, ...], Path]] = []
        self.staged_before_commit: tuple[str, ...] = ()

    def run(self, args: Sequence[str], cwd: Path) -> CommandResult:
        command = tuple(args)
        self.calls.append((command, cwd))
        if command == (
            "gh",
            "repo",
            "view",
            EXPECTED_REPOSITORY,
            "--json",
            "nameWithOwner,visibility",
        ):
            return _private_repo_response()
        if command == ("git", "push", "origin", "main"):
            return CommandResult(0, "push intercepted for local test\n", "")
        if command[:2] == ("git", "commit"):
            staged = super().run(("git", "diff", "--cached", "--name-only"), cwd)
            self.staged_before_commit = tuple(line for line in staged.stdout.splitlines() if line)
        return super().run(args, cwd)


def _private_repo_response() -> CommandResult:
    return CommandResult(
        0,
        json.dumps({"nameWithOwner": EXPECTED_REPOSITORY, "visibility": "PRIVATE"}),
        "",
    )


def _base_responses(status: str = "") -> dict[tuple[str, ...], CommandResult]:
    status_result = CommandResult(0, status, "")
    return {
        ("git", "remote", "get-url", "origin"): CommandResult(
            0,
            "https://github.com/zqybw98/careerops-private-data.git\n",
            "",
        ),
        (
            "gh",
            "repo",
            "view",
            EXPECTED_REPOSITORY,
            "--json",
            "nameWithOwner,visibility",
        ): _private_repo_response(),
        (
            "git",
            "status",
            "--porcelain",
            "--",
            "exports",
            "snapshot",
            "sync_manifest.json",
        ): status_result,
        (
            "git",
            "status",
            "--porcelain",
            "--",
            "exports/applications.csv",
        ): status_result,
        ("git", "branch", "--show-current"): CommandResult(0, "main\n", ""),
    }


def _config(tmp_path: Path, mode: str = "sync") -> SyncConfig:
    project_root = tmp_path / "project"
    project_root.mkdir()
    db_path = project_root / "data" / "applications.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"fixture")
    target = tmp_path / "private-data"
    if mode != "initialize":
        (target / ".git").mkdir(parents=True)
    return SyncConfig(project_root=project_root, target=target, db_path=db_path, mode=mode)


def _exporter(db_path: Path, destination: Path) -> ExportResult:
    del db_path
    export_path = destination / "exports" / "applications.csv"
    export_path.parent.mkdir(parents=True, exist_ok=True)
    export_path.write_text("id,company\n1,Example GmbH\n", encoding="utf-8")
    return ExportResult(files=(export_path,), row_counts={"applications": 1}, fingerprint="abc123")


def _command_names(runner: FakeRunner) -> list[tuple[str, ...]]:
    return [command for command, _ in runner.calls]


def _run_git(cwd: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        ("git", *args),
        cwd=cwd,
        capture_output=True,
        text=True,
        check=True,
    )


@pytest.mark.parametrize(
    "remote_url",
    [
        "https://user:synthetic-secret-value@github.com/wrong/repository.git",
        "https://github.com/wrong/repository.git?credential=synthetic-secret-value",
        "https://github.com/wrong/repository.git",
        "git@github.com:wrong/repository.git",
    ],
)
def test_sync_rejects_wrong_remote_without_exposing_url_or_writing(
    tmp_path: Path,
    remote_url: str,
) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(
        {
            ("git", "remote", "get-url", "origin"): CommandResult(
                0,
                f"{remote_url}\n",
                "",
            )
        }
    )
    exported = False

    def tracking_exporter(db_path: Path, destination: Path) -> ExportResult:
        nonlocal exported
        exported = True
        return _exporter(db_path, destination)

    with pytest.raises(SyncError) as raised:
        run_sync(config, runner=runner, exporter=tracking_exporter)

    error_text = str(raised.value)
    assert remote_url not in error_text
    assert "synthetic-secret-value" not in error_text
    assert EXPECTED_REPOSITORY in error_text
    assert exported is False
    commands = _command_names(runner)
    assert commands == [("git", "remote", "get-url", "origin")]
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_remote_read_failure_does_not_expose_command_output(tmp_path: Path) -> None:
    config = _config(tmp_path)
    sensitive_output = "fatal: unable to access 'https://user:synthetic-secret-value@github.com/wrong/repository.git'"
    runner = FakeRunner(
        {
            ("git", "remote", "get-url", "origin"): CommandResult(
                1,
                "",
                sensitive_output,
            )
        }
    )

    with pytest.raises(SyncError) as raised:
        run_sync(config, runner=runner, exporter=_exporter)

    error_text = str(raised.value)
    assert sensitive_output not in error_text
    assert "synthetic-secret-value" not in error_text
    assert EXPECTED_REPOSITORY in error_text
    commands = _command_names(runner)
    assert commands == [("git", "remote", "get-url", "origin")]
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


@pytest.mark.parametrize("visibility", ["PUBLIC", "INTERNAL"])
def test_sync_rejects_non_private_repository(tmp_path: Path, visibility: str) -> None:
    config = _config(tmp_path)
    responses = _base_responses()
    responses[("gh", "repo", "view", EXPECTED_REPOSITORY, "--json", "nameWithOwner,visibility")] = CommandResult(
        0, json.dumps({"nameWithOwner": EXPECTED_REPOSITORY, "visibility": visibility}), ""
    )
    runner = FakeRunner(responses)

    with pytest.raises(SyncError, match="not private"):
        run_sync(config, runner=runner, exporter=_exporter)

    assert not (config.target / "exports").exists()


def test_sync_rejects_unverifiable_repository_visibility(tmp_path: Path) -> None:
    config = _config(tmp_path)
    responses = _base_responses()
    responses[("gh", "repo", "view", EXPECTED_REPOSITORY, "--json", "nameWithOwner,visibility")] = CommandResult(
        1, "", "authentication required"
    )
    runner = FakeRunner(responses)

    with pytest.raises(SyncError, match="Could not verify"):
        run_sync(config, runner=runner, exporter=_exporter)

    assert not (config.target / "exports").exists()


def test_sync_skips_commit_and_push_when_export_is_unchanged(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status=""))

    result = run_sync(config, runner=runner, exporter=_exporter)

    assert result.status == "unchanged"
    assert result.changed is False
    assert result.pushed is False
    commands = _command_names(runner)
    assert not any(command[:2] == ("git", "add") for command in commands)
    assert not any(command[:2] == ("git", "commit") for command in commands)
    assert not any(command[:2] == ("git", "push") for command in commands)


def test_sync_commits_and_pushes_changed_export(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status=" M exports/applications.csv\n"))

    result = run_sync(config, runner=runner, exporter=_exporter)

    assert result.status == "pushed"
    assert result.changed is True
    assert result.pushed is True
    commands = _command_names(runner)
    assert (
        "git",
        "add",
        "--",
        "exports/applications.csv",
    ) in commands
    assert any(command[:2] == ("git", "commit") for command in commands)
    assert ("git", "push", "origin", "main") in commands


def test_export_failure_prevents_git_write_commands(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status=" M exports/applications.csv\n"))

    def failing_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path, destination
        raise RuntimeError("export failed")

    with pytest.raises(SyncError, match="Export failed"):
        run_sync(config, runner=runner, exporter=failing_exporter)

    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_push_failure_is_reported_and_export_files_remain(tmp_path: Path) -> None:
    config = _config(tmp_path)
    responses = _base_responses(status=" M exports/applications.csv\n")
    responses[("git", "push", "origin", "main")] = CommandResult(1, "", "network unavailable")
    runner = FakeRunner(responses)

    with pytest.raises(SyncError, match="Push failed"):
        run_sync(config, runner=runner, exporter=_exporter)

    assert (config.target / "exports" / "applications.csv").exists()


def test_sync_stages_exported_files_in_stable_deduplicated_order(tmp_path: Path) -> None:
    config = _config(tmp_path)

    def unordered_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path
        first = destination / "exports" / "applications.csv"
        second = destination / "sync_manifest.json"
        first.parent.mkdir(parents=True, exist_ok=True)
        first.write_text("id,company\n1,Example GmbH\n", encoding="utf-8")
        second.write_text("{}\n", encoding="utf-8")
        return ExportResult(
            files=(second, first, second),
            row_counts={"applications": 1},
            fingerprint="abc123",
        )

    responses = _base_responses()
    exact_status = (
        "git",
        "status",
        "--porcelain",
        "--",
        "exports/applications.csv",
        "sync_manifest.json",
    )
    responses[exact_status] = CommandResult(0, "?? exports/applications.csv\n?? sync_manifest.json\n", "")
    runner = FakeRunner(responses)

    result = run_sync(config, runner=runner, exporter=unordered_exporter)

    assert result.status == "pushed"
    assert (
        "git",
        "add",
        "--",
        "exports/applications.csv",
        "sync_manifest.json",
    ) in _command_names(runner)


@pytest.mark.parametrize("path_form", ["absolute", "dotdot"])
def test_sync_rejects_exported_paths_outside_private_repository(
    tmp_path: Path,
    path_form: str,
) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status="?? exports/applications.csv\n"))

    def outside_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path
        outside = destination.parent / "outside.csv"
        outside.write_text("private data\n", encoding="utf-8")
        returned_path = outside.resolve() if path_form == "absolute" else destination / ".." / "outside.csv"
        return ExportResult(
            files=(returned_path,),
            row_counts={"applications": 1},
            fingerprint="abc123",
        )

    with pytest.raises(SyncError, match="outside the private repository"):
        run_sync(config, runner=runner, exporter=outside_exporter)

    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_sync_rejects_exported_directory_before_git_writes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status="?? exports/applications.csv\n"))

    def directory_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path
        export_directory = destination / "exports"
        export_directory.mkdir(parents=True, exist_ok=True)
        (export_directory / "applications.csv").write_text(
            "id,company\n1,Example GmbH\n",
            encoding="utf-8",
        )
        return ExportResult(
            files=(export_directory,),
            row_counts={"applications": 1},
            fingerprint="abc123",
        )

    with pytest.raises(SyncError, match="regular file"):
        run_sync(config, runner=runner, exporter=directory_exporter)

    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


@pytest.mark.parametrize("unsafe_name", ["-A", "--all"])
def test_sync_rejects_git_option_like_export_paths(
    tmp_path: Path,
    unsafe_name: str,
) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status=f"?? {unsafe_name}\n"))

    def unsafe_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path
        exported_file = destination / unsafe_name
        exported_file.write_text("private data\n", encoding="utf-8")
        return ExportResult(
            files=(exported_file,),
            row_counts={"applications": 1},
            fingerprint="abc123",
        )

    with pytest.raises(SyncError, match="unsafe Git path"):
        run_sync(config, runner=runner, exporter=unsafe_exporter)

    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_sync_rejects_empty_export_file_list_before_git_writes(tmp_path: Path) -> None:
    config = _config(tmp_path)
    runner = FakeRunner(_base_responses(status="?? unrelated.txt\n"))

    def empty_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path, destination
        return ExportResult(files=(), row_counts={}, fingerprint="abc123")

    with pytest.raises(SyncError, match="did not return any files"):
        run_sync(config, runner=runner, exporter=empty_exporter)

    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_real_git_sync_commit_excludes_unapproved_extra_files(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    project_root.mkdir()
    db_path = project_root / "data" / "applications.db"
    db_path.parent.mkdir()
    db_path.write_bytes(b"fixture")
    target = tmp_path / "private-data"
    target.mkdir()
    _run_git(target, "init")
    _run_git(target, "checkout", "-b", "main")
    _run_git(target, "config", "user.name", "CareerOps Test")
    _run_git(target, "config", "user.email", "careerops-test@example.invalid")
    _run_git(target, "remote", "add", "origin", "https://github.com/zqybw98/careerops-private-data.git")

    extra_files = (
        target / "exports" / "token.txt",
        target / "exports" / "extra.csv",
        target / "snapshot" / "local.sqlite",
        target / "snapshot" / "temp.db",
        target / "unrelated.txt",
    )
    for path in extra_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("must remain untracked\n", encoding="utf-8")

    def integration_exporter(db_path: Path, destination: Path) -> ExportResult:
        del db_path
        application_export = destination / "exports" / "applications.csv"
        manifest = destination / "sync_manifest.json"
        application_export.write_text("id,company\n1,Example GmbH\n", encoding="utf-8")
        manifest.write_text("{}\n", encoding="utf-8")
        return ExportResult(
            files=(manifest, application_export),
            row_counts={"applications": 1},
            fingerprint="abc123",
        )

    config = SyncConfig(project_root=project_root, target=target, db_path=db_path, mode="sync")
    runner = LocalGitRunner()

    result = run_sync(config, runner=runner, exporter=integration_exporter)

    committed_files = {
        line.strip()
        for line in _run_git(target, "show", "--name-only", "--format=").stdout.splitlines()
        if line.strip()
    }
    assert result.status == "pushed"
    assert runner.staged_before_commit == (
        "exports/applications.csv",
        "sync_manifest.json",
    )
    assert committed_files == {"exports/applications.csv", "sync_manifest.json"}
    assert set(_run_git(target, "diff", "--cached", "--name-only").stdout.splitlines()) == set()
    untracked_files = _run_git(target, "ls-files", "--others", "--exclude-standard").stdout.splitlines()
    assert set(untracked_files) == {
        "exports/extra.csv",
        "exports/token.txt",
        "snapshot/local.sqlite",
        "snapshot/temp.db",
        "unrelated.txt",
    }
    assert all(path.exists() for path in extra_files)


def test_dry_run_reports_changes_without_writing_private_checkout(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="dry-run")
    runner = FakeRunner(_base_responses())

    result = run_sync(config, runner=runner, exporter=_exporter)

    assert result.status == "dry-run"
    assert result.changed is True
    assert result.pushed is False
    assert not (config.target / "exports").exists()
    commands = _command_names(runner)
    assert not any(command[:2] in {("git", "add"), ("git", "commit"), ("git", "push")} for command in commands)


def test_daily_sync_refuses_uninitialized_target(tmp_path: Path) -> None:
    config = _config(tmp_path)
    (config.target / ".git").rmdir()
    config.target.rmdir()
    runner = FakeRunner({})

    with pytest.raises(SyncError, match="not initialized"):
        run_sync(config, runner=runner, exporter=_exporter)

    assert runner.calls == []


def test_initialize_creates_only_private_named_repository(tmp_path: Path) -> None:
    config = _config(tmp_path, mode="initialize")
    runner = FakeRunner(
        {
            ("gh", "auth", "status"): CommandResult(0, "authenticated", ""),
            (
                "gh",
                "repo",
                "view",
                EXPECTED_REPOSITORY,
                "--json",
                "nameWithOwner,visibility",
            ): [CommandResult(1, "", "not found"), _private_repo_response()],
        }
    )

    result = run_sync(config, runner=runner, exporter=_exporter)

    assert result.status == "initialized"
    assert (
        "gh",
        "repo",
        "create",
        EXPECTED_REPOSITORY,
        "--private",
    ) in _command_names(runner)
    assert (
        "gh",
        "repo",
        "clone",
        EXPECTED_REPOSITORY,
        str(config.target),
    ) in _command_names(runner)
    assert not (config.target / "exports").exists()


def test_build_sync_config_uses_userprofile_documents_by_default(tmp_path: Path) -> None:
    project_root = tmp_path / "project"

    config = build_sync_config(
        mode="dry-run",
        target=None,
        project_root=project_root,
        environ={"USERPROFILE": str(tmp_path / "Yibo")},
    )

    assert config.target == tmp_path / "Yibo" / "Documents" / "CareerOps Private Data"
    assert config.db_path == project_root / "data" / "applications.db"


def test_build_sync_config_accepts_explicit_target(tmp_path: Path) -> None:
    target = tmp_path / "chosen-private-data"

    config = build_sync_config(
        mode="sync",
        target=target,
        project_root=tmp_path / "project",
        environ={},
    )

    assert config.target == target.resolve()


def test_cli_returns_nonzero_and_prints_safe_error(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(
        ["sync", "--target", str(tmp_path / "missing")],
        project_root=tmp_path / "project",
        environ={"USERPROFILE": str(tmp_path)},
    )

    captured = capsys.readouterr()
    assert exit_code == 1
    assert "not initialized" in captured.err
    assert "token" not in captured.err.casefold()
