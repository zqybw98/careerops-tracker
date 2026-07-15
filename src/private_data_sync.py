from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Literal, Protocol

from src.private_data_export import ExportResult, export_private_data

EXPECTED_REPOSITORY = "zqybw98/careerops-private-data"
ALLOWED_REMOTE_URLS = {
    "https://github.com/zqybw98/careerops-private-data.git",
    "git@github.com:zqybw98/careerops-private-data.git",
}
SyncMode = Literal["initialize", "sync", "dry-run"]
Exporter = Callable[[Path, Path], ExportResult]


class SyncError(RuntimeError):
    """Raised when a synchronization safety check or command fails."""


@dataclass(frozen=True)
class CommandResult:
    returncode: int
    stdout: str
    stderr: str


class CommandRunner(Protocol):
    def run(self, args: Sequence[str], cwd: Path) -> CommandResult: ...


@dataclass(frozen=True)
class SyncConfig:
    project_root: Path
    target: Path
    db_path: Path
    mode: SyncMode


@dataclass(frozen=True)
class SyncResult:
    status: str
    changed: bool
    pushed: bool
    files: tuple[Path, ...] = ()
    message: str = ""


class SubprocessRunner:
    def run(self, args: Sequence[str], cwd: Path) -> CommandResult:
        completed = subprocess.run(
            list(args),
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
        )
        return CommandResult(completed.returncode, completed.stdout, completed.stderr)


def run_sync(
    config: SyncConfig,
    runner: CommandRunner | None = None,
    exporter: Exporter = export_private_data,
) -> SyncResult:
    command_runner = runner or SubprocessRunner()
    if config.mode == "initialize":
        return _initialize_private_repository(config, command_runner)
    if config.mode not in {"sync", "dry-run"}:
        raise SyncError(f"Unsupported synchronization mode: {config.mode}")

    _require_initialized_target(config.target)
    _validate_remote(config.target, command_runner)
    _validate_private_repository(config.target, command_runner)

    if config.mode == "dry-run":
        return _run_dry_run(config, exporter)
    return _run_daily_sync(config, command_runner, exporter)


def build_sync_config(
    mode: SyncMode,
    target: Path | None,
    project_root: Path,
    environ: Mapping[str, str],
) -> SyncConfig:
    root = project_root.resolve()
    destination = target
    if destination is None:
        configured_target = environ.get("CAREEROPS_PRIVATE_DATA_DIR", "").strip()
        if configured_target:
            destination = Path(configured_target)
        else:
            user_profile = Path(environ.get("USERPROFILE") or Path.home())
            destination = user_profile / "Documents" / "CareerOps Private Data"
    return SyncConfig(
        project_root=root,
        target=destination.resolve(),
        db_path=root / "data" / "applications.db",
        mode=mode,
    )


def main(
    argv: Sequence[str] | None = None,
    *,
    project_root: Path | None = None,
    environ: Mapping[str, str] | None = None,
) -> int:
    parser = argparse.ArgumentParser(description="Safely synchronize private CareerOps data.")
    parser.add_argument("mode", choices=("initialize", "sync", "dry-run"))
    parser.add_argument("--target", type=Path, help="Local checkout for the private data repository.")
    args = parser.parse_args(argv)
    root = (project_root or Path.cwd()).resolve()
    config = build_sync_config(args.mode, args.target, root, environ or os.environ)

    print(f"Mode: {config.mode}")
    print(f"Target repository: {EXPECTED_REPOSITORY}")
    print(f"Local target: {config.target}")
    try:
        result = run_sync(config)
    except SyncError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1

    print(result.message)
    if result.files:
        print("Export files:")
        for path in result.files:
            print(f"  - {path}")
    if config.mode == "dry-run":
        print(f"Changes detected: {'yes' if result.changed else 'no'}")
        print("Dry-run complete: no files were staged, committed, or pushed.")
    return 0


def validate_remote_url(url: str) -> None:
    normalized = str(url or "").strip()
    if normalized not in ALLOWED_REMOTE_URLS:
        raise SyncError(
            "Configured Git remote does not match the allowed private data repository: "
            f"{EXPECTED_REPOSITORY}. Sync stopped before staging, committing, or pushing."
        )


def _require_initialized_target(target: Path) -> None:
    if not (target / ".git").exists():
        raise SyncError("Private data repository is not initialized. Run init_private_data_repo.bat first.")


def _validate_remote(target: Path, runner: CommandRunner) -> None:
    result = runner.run(("git", "remote", "get-url", "origin"), cwd=target)
    if result.returncode != 0:
        raise SyncError(
            "Could not validate the configured Git remote for the allowed private data repository: "
            f"{EXPECTED_REPOSITORY}. Sync stopped before staging, committing, or pushing."
        )
    validate_remote_url(result.stdout)


def _validate_private_repository(target: Path, runner: CommandRunner) -> None:
    result = runner.run(
        (
            "gh",
            "repo",
            "view",
            EXPECTED_REPOSITORY,
            "--json",
            "nameWithOwner,visibility",
        ),
        cwd=target,
    )
    if result.returncode != 0:
        raise SyncError(f"Could not verify private repository visibility: {_command_error(result)}")
    try:
        repository = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise SyncError("Could not verify private repository visibility: invalid GitHub response.") from error

    if repository.get("nameWithOwner") != EXPECTED_REPOSITORY:
        raise SyncError("GitHub returned a different repository owner or name.")
    if repository.get("visibility") != "PRIVATE":
        raise SyncError("Configured GitHub repository is not private. Synchronization is blocked.")


def _initialize_private_repository(config: SyncConfig, runner: CommandRunner) -> SyncResult:
    if (config.target / ".git").exists():
        raise SyncError("Private data repository is already initialized; use sync_private_data.bat.")
    if config.target.exists() and any(config.target.iterdir()):
        raise SyncError(f"Initialization target is not empty: {config.target}")

    auth = runner.run(("gh", "auth", "status"), cwd=config.project_root)
    if auth.returncode != 0:
        raise SyncError(f"GitHub CLI is not authenticated: {_command_error(auth)}")

    view_command = (
        "gh",
        "repo",
        "view",
        EXPECTED_REPOSITORY,
        "--json",
        "nameWithOwner,visibility",
    )
    existing = runner.run(view_command, cwd=config.project_root)
    if existing.returncode == 0:
        _validate_private_repository_payload(existing.stdout)
        clone = runner.run(
            ("gh", "repo", "clone", EXPECTED_REPOSITORY, str(config.target)),
            cwd=config.project_root,
        )
        if clone.returncode != 0:
            raise SyncError(f"Private repository clone failed: {_command_error(clone)}")
    else:
        create = runner.run(
            (
                "gh",
                "repo",
                "create",
                EXPECTED_REPOSITORY,
                "--private",
            ),
            cwd=config.project_root,
        )
        if create.returncode != 0:
            raise SyncError(f"Private repository creation failed: {_command_error(create)}")
        clone = runner.run(
            ("gh", "repo", "clone", EXPECTED_REPOSITORY, str(config.target)),
            cwd=config.project_root,
        )
        if clone.returncode != 0:
            raise SyncError(f"Private repository clone failed: {_command_error(clone)}")

    verified = runner.run(view_command, cwd=config.project_root)
    if verified.returncode != 0:
        raise SyncError(f"Could not verify repository after initialization: {_command_error(verified)}")
    _validate_private_repository_payload(verified.stdout)
    return SyncResult(
        status="initialized",
        changed=False,
        pushed=False,
        message="Private repository initialized. Run dry-run before the first synchronization.",
    )


def _validate_private_repository_payload(payload: str) -> None:
    try:
        repository = json.loads(payload)
    except json.JSONDecodeError as error:
        raise SyncError("Could not verify private repository visibility: invalid GitHub response.") from error
    if repository.get("nameWithOwner") != EXPECTED_REPOSITORY:
        raise SyncError("GitHub returned a different repository owner or name.")
    if repository.get("visibility") != "PRIVATE":
        raise SyncError("Configured GitHub repository is not private. Initialization is blocked.")


def _run_dry_run(config: SyncConfig, exporter: Exporter) -> SyncResult:
    try:
        with tempfile.TemporaryDirectory(prefix="careerops-dry-run-") as temp_dir:
            preview_root = Path(temp_dir)
            export_result = exporter(config.db_path, preview_root)
            relative_files = _validated_relative_export_paths(export_result.files, preview_root)
            changed = _export_differs(relative_files, preview_root, config.target)
    except Exception as error:
        raise SyncError(f"Export failed during dry-run: {error}") from error

    return SyncResult(
        status="dry-run",
        changed=changed,
        pushed=False,
        files=tuple(config.target / path for path in relative_files),
        message="Export changes detected." if changed else "Private export is already up to date.",
    )


def _run_daily_sync(config: SyncConfig, runner: CommandRunner, exporter: Exporter) -> SyncResult:
    try:
        export_result = exporter(config.db_path, config.target)
    except Exception as error:
        raise SyncError(f"Export failed: {error}") from error

    relative_files = _validated_relative_export_paths(export_result.files, config.target)
    status = runner.run(
        ("git", "status", "--porcelain", "--", *relative_files),
        cwd=config.target,
    )
    if status.returncode != 0:
        raise SyncError(f"Could not inspect exported changes: {_command_error(status)}")
    if not status.stdout.strip():
        return SyncResult(
            status="unchanged",
            changed=False,
            pushed=False,
            files=export_result.files,
            message="No private data changes detected; no commit or push was created.",
        )

    add = runner.run(("git", "add", "--", *relative_files), cwd=config.target)
    if add.returncode != 0:
        raise SyncError(f"Could not stage private export: {_command_error(add)}")

    branch_result = runner.run(("git", "branch", "--show-current"), cwd=config.target)
    if branch_result.returncode != 0:
        raise SyncError(f"Could not determine private repository branch: {_command_error(branch_result)}")
    branch = branch_result.stdout.strip()
    if not branch:
        switch = runner.run(("git", "switch", "-c", "main"), cwd=config.target)
        if switch.returncode != 0:
            raise SyncError(f"Could not create the private main branch: {_command_error(switch)}")
        branch = "main"
    if branch != "main":
        raise SyncError(f"Private data synchronization requires the main branch, found: {branch}")

    commit_message = f"Sync CareerOps data {datetime.now().astimezone():%Y-%m-%d %H:%M}"
    commit = runner.run(("git", "commit", "-m", commit_message), cwd=config.target)
    if commit.returncode != 0:
        raise SyncError(f"Could not commit private export: {_command_error(commit)}")

    push = runner.run(("git", "push", "origin", "main"), cwd=config.target)
    if push.returncode != 0:
        raise SyncError(
            "Push failed. The export and local commit were preserved; retry after fixing the connection: "
            f"{_command_error(push)}"
        )
    return SyncResult(
        status="pushed",
        changed=True,
        pushed=True,
        files=export_result.files,
        message="Private CareerOps data committed and pushed successfully.",
    )


def _validated_relative_export_paths(files: Sequence[Path], repository_root: Path) -> tuple[str, ...]:
    root = repository_root.resolve()
    relative_paths: set[str] = set()
    for exported_file in files:
        candidate = Path(exported_file)
        if not candidate.is_absolute():
            candidate = root / candidate
        resolved_file = candidate.resolve()
        if not resolved_file.is_relative_to(root) or resolved_file == root:
            raise SyncError(
                "Exporter returned a path outside the private repository. "
                "Sync stopped before staging, committing, or pushing."
            )
        if not resolved_file.is_file():
            raise SyncError(
                "Exporter returned a path that is not a regular file. "
                "Sync stopped before staging, committing, or pushing."
            )
        relative_path = resolved_file.relative_to(root).as_posix()
        if relative_path in {"-A", "--all"}:
            raise SyncError(
                "Exporter returned an unsafe Git path. Sync stopped before staging, committing, or pushing."
            )
        relative_paths.add(relative_path)
    if not relative_paths:
        raise SyncError("Exporter did not return any files. Sync stopped before staging, committing, or pushing.")
    return tuple(sorted(relative_paths))


def _export_differs(relative_files: Sequence[str], preview_root: Path, target: Path) -> bool:
    for relative_path in relative_files:
        preview_file = preview_root / relative_path
        current_file = target / relative_path
        if not current_file.is_file() or current_file.read_bytes() != preview_file.read_bytes():
            return True
    return False


def _command_error(result: CommandResult) -> str:
    return (result.stderr or result.stdout or f"exit code {result.returncode}").strip()
