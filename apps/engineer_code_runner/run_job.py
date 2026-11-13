#!/usr/bin/env python3

import argparse
import json
import os
import re
import secrets
import shutil
import socket
import struct
import subprocess
import tempfile
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

DEFAULT_IMAGE = "python:3.12.8-slim"
DEFAULT_RENDER_IMAGE = os.getenv("ENGINEER_RENDER_IMAGE", "mainbrain-engineer-render:py312-mpl-ffmpeg")
MANAGED_WORKSPACES_ROOT = Path("/home/mdv/mainbrain/data/engineer-code-mcp/workspaces")
ARTIFACTS_ROOT = Path("/home/mdv/mainbrain/data/engineer-artifacts")
ARTIFACT_STAGING_HOST_ROOT = Path("/home/mdv/mainbrain/data/openclaw/workspace/engineer/artifact-staging")
ARTIFACT_STAGING_GATEWAY_ROOT = Path("/home/node/.openclaw/workspace/engineer/artifact-staging")
MAX_SOCKET_REQUEST_BYTES = 32_000
MAX_OUTPUT_BYTES = 12_000
MAX_RENDER_LOG_BYTES = 40_000
MAX_ARTIFACT_BYTES_DEFAULT = 200_000_000
WORKSPACE_METADATA_ROOT = MANAGED_WORKSPACES_ROOT / "_engineer_meta"
RELEASE_EXECUTOR_SOCKET_PATH = Path(
    os.getenv(
        "ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH",
        "/home/mdv/mainbrain/data/engineer-release-executor/release-executor.sock",
    )
)
RELEASE_EXECUTOR_TIMEOUT_SECONDS = int(os.getenv("ENGINEER_RELEASE_EXECUTOR_TIMEOUT_SECONDS", "30"))
RUNNER_EVIDENCE_AUTH_TOKEN = os.getenv("ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN", "")
RUNNER_CONTROLLER_NAME = "engineer-code-runner"
TRUSTED_GIT_ENV = {
    "GIT_CONFIG_NOSYSTEM": "1",
    "GIT_CONFIG_GLOBAL": "/dev/null",
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_ASKPASS": "/bin/false",
    "GIT_PAGER": "cat",
    "HUSKY": "0",
}
TRUSTED_GIT_ARGS = [
    "-c",
    "core.hooksPath=/dev/null",
    "-c",
    "commit.gpgSign=false",
    "-c",
    "advice.detachedHead=false",
    "-c",
    "protocol.file.allow=never",
]
SHA1_PATTERN = r"[0-9a-f]{40}"

APPROVED_CHECKS: dict[str, dict[str, Any]] = {
    "python_unit": {
        "timeout_seconds": 30,
        "config_version": "python_unit_v2",
        "mode": "discover",
        "discover": {
            "root": "tests",
            "pattern": "test_*.py",
            "exclude_files": [
                "test_intentional_failure.py",
                "test_isolation.py",
            ],
        },
    },
    "python_isolation": {
        "tests": ["tests.test_isolation"],
        "timeout_seconds": 30,
        "mode": "explicit",
        "config_version": "python_isolation_v1",
    },
    "python_fail_demo": {
        "tests": ["tests.test_intentional_failure"],
        "timeout_seconds": 30,
        "mode": "explicit",
        "config_version": "python_fail_demo_v1",
    },
}

APPROVED_RENDER_PROFILES: dict[str, dict[str, Any]] = {
    "python_animation_v1": {
        "image": DEFAULT_RENDER_IMAGE,
        "timeout_seconds": 180,
        "memory": "768m",
        "cpus": "1.5",
        "pids": 128,
        "user": "1000:1000",
        "max_output_bytes": 120_000_000,
        "allowed_script_patterns": ["animation_*.py"],
        "output_name": "animation.mp4",
        "output_exts": [".mp4", ".gif"],
    }
}

DENIED_NAMES = {".git", ".ssh", "secrets", "credentials"}
DENIED_FILE_PREFIXES = (".env",)
ALLOWED_ARTIFACT_EXTENSIONS = {".mp4", ".gif", ".png", ".jpg", ".jpeg", ".webm"}


def _truncate_output(value: str, max_bytes: int = MAX_OUTPUT_BYTES) -> tuple[str, bool]:
    payload = value.encode("utf-8")
    if len(payload) <= max_bytes:
        return value, False
    truncated = payload[:max_bytes].decode("utf-8", errors="ignore")
    return f"{truncated}\n...output truncated...\n", True


def _trusted_git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(TRUSTED_GIT_ENV)
    return env


def _run_git(
    worktree: Path,
    args: list[str],
    *,
    allowed_exit_codes: set[int] | None = None,
    strip_output: bool = True,
) -> str:
    exit_codes = allowed_exit_codes or {0}
    command = ["git", *TRUSTED_GIT_ARGS, *args]
    proc = subprocess.run(
        command,
        cwd=str(worktree),
        capture_output=True,
        text=True,
        check=False,
        env=_trusted_git_env(),
    )
    if proc.returncode not in exit_codes:
        detail = (proc.stderr or proc.stdout or "git command failed").strip()
        raise ValueError(detail)
    output = proc.stdout or ""
    return output.strip() if strip_output else output


def _validate_name(name: str) -> None:
    lowered = name.lower()
    if lowered in DENIED_NAMES or lowered.startswith(".git"):
        raise ValueError("access to Git internals is denied")
    if any(lowered == prefix or lowered.startswith(f"{prefix}.") for prefix in DENIED_FILE_PREFIXES):
        raise ValueError("access to secret files is denied")


def _safe_relative(path_value: str) -> Path:
    if not path_value or path_value == ".":
        return Path(".")
    rel = Path(path_value)
    if rel.is_absolute():
        raise ValueError("absolute paths are not allowed")
    for part in rel.parts:
        if part in ("", "."):
            continue
        if part == "..":
            raise ValueError("path traversal is not allowed")
        _validate_name(part)
    return rel


def _resolve_workspace_id(workspace_id: str) -> Path:
    if not workspace_id or not re.fullmatch(r"[A-Za-z0-9._-]+", workspace_id):
        raise ValueError("invalid workspace_id format")
    if not MANAGED_WORKSPACES_ROOT.exists():
        raise ValueError("managed workspaces root is missing")

    matches: list[Path] = []
    for project_root in MANAGED_WORKSPACES_ROOT.iterdir():
        if not project_root.is_dir() or project_root.is_symlink():
            continue
        candidate = project_root / workspace_id
        if not candidate.exists():
            continue
        if candidate.is_symlink():
            raise ValueError("workspace symlinks are not allowed")
        resolved = candidate.resolve()
        if MANAGED_WORKSPACES_ROOT.resolve() not in resolved.parents:
            raise ValueError("workspace escapes managed root")
        if not (resolved / ".git").exists():
            raise ValueError("workspace is not a git checkout")
        matches.append(resolved)

    if not matches:
        raise ValueError(f"workspace '{workspace_id}' was not found")
    if len(matches) > 1:
        raise ValueError(f"workspace '{workspace_id}' is ambiguous across projects")
    return matches[0]


def _resolve_in_workspace(workspace: Path, rel_path: str) -> Path:
    relative = _safe_relative(rel_path)
    candidate = (workspace / relative).resolve(strict=True)
    try:
        candidate.relative_to(workspace)
    except ValueError as exc:
        raise ValueError("path escapes the approved workspace") from exc

    current = workspace
    for part in relative.parts:
        if part in ("", "."):
            continue
        _validate_name(part)
        current = current / part
        if current.exists() and current.is_symlink():
            raise ValueError("paths through symlinks are not allowed")
    if candidate.is_dir():
        raise ValueError("script path must be a file")
    return candidate


def _make_readable_tree(root: Path) -> None:
    if root.exists():
        root.chmod(root.stat().st_mode | 0o555)
    for entry in root.rglob("*"):
        mode = entry.stat().st_mode
        if entry.is_dir():
            entry.chmod(mode | 0o555)
        elif entry.is_file():
            entry.chmod(mode | 0o444)


def _read_workspace_metadata(workspace_id: str) -> dict[str, Any]:
    metadata_path = (WORKSPACE_METADATA_ROOT / f"{workspace_id}.json").resolve()
    if not metadata_path.exists():
        return {}
    try:
        metadata_path.relative_to(WORKSPACE_METADATA_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("workspace metadata escaped approved root") from exc
    if metadata_path.is_symlink():
        raise ValueError("workspace metadata symlinks are not allowed")
    payload = json.loads(metadata_path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("workspace metadata is invalid")
    return payload


def _workspace_project_id(workspace: Path) -> str:
    rel = workspace.resolve().relative_to(MANAGED_WORKSPACES_ROOT.resolve())
    if len(rel.parts) < 2:
        raise ValueError("workspace path is malformed")
    project_id = rel.parts[0]
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project_id):
        raise ValueError("workspace project id is invalid")
    return project_id


def _integration_context(workspace: Path, workspace_id: str) -> dict[str, Any]:
    metadata = _read_workspace_metadata(workspace_id)
    if metadata.get("workspace_type") != "integration":
        raise ValueError("workspace is not an integration workspace")
    if not bool(metadata.get("merged")):
        raise ValueError("integration workspace has no successful merge")
    expected_commit = str(metadata.get("integration_commit_sha", "")).strip()
    if not re.fullmatch(SHA1_PATTERN, expected_commit):
        raise ValueError("integration metadata missing valid integration commit SHA")

    current_commit = _run_git(workspace, ["rev-parse", "HEAD"])
    if current_commit != expected_commit:
        raise ValueError("integration workspace HEAD differs from metadata integration commit")

    status = _run_git(
        workspace,
        ["status", "--porcelain=1", "--untracked-files=all", "--", "."],
        strip_output=False,
    )
    if status.strip():
        raise ValueError("integration workspace has uncommitted changes; exact commit evidence requires a clean tree")

    project_id = str(metadata.get("project_id", "")).strip() or _workspace_project_id(workspace)
    if not re.fullmatch(r"[A-Za-z0-9._-]+", project_id):
        raise ValueError("integration metadata project_id is invalid")
    return {
        "project_id": project_id,
        "integration_workspace_id": workspace_id,
        "integration_commit_sha": expected_commit,
    }


def _copy_commit_snapshot(worktree: Path, commit_sha: str) -> tuple[Path, Path]:
    snapshot_root = Path(tempfile.mkdtemp(prefix="engineer-runner-commit-"))
    snapshot_worktree = snapshot_root / "worktree"
    snapshot_worktree.mkdir(parents=True, exist_ok=True)
    archive_path = snapshot_root / "source.tar"
    _run_git(worktree, ["cat-file", "-e", f"{commit_sha}^{{commit}}"])
    _run_git(worktree, ["archive", "--format=tar", commit_sha, "-o", str(archive_path)])
    subprocess.run(
        ["tar", "-xf", str(archive_path), "-C", str(snapshot_worktree)],
        check=True,
        capture_output=True,
        text=True,
    )
    _make_readable_tree(snapshot_worktree)
    return snapshot_root, snapshot_worktree


def _runner_execution_id() -> str:
    return f"runner-exec-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"


def _record_runner_evidence(payload: dict[str, Any]) -> dict[str, Any]:
    if not RUNNER_EVIDENCE_AUTH_TOKEN:
        raise ValueError("ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN must be set for trusted evidence recording")
    request = {
        "auth_token": RUNNER_EVIDENCE_AUTH_TOKEN,
        "action": "record_test_evidence",
        "payload": payload,
    }
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.settimeout(RELEASE_EXECUTOR_TIMEOUT_SECONDS)
        client.connect(str(RELEASE_EXECUTOR_SOCKET_PATH))
        client.sendall((json.dumps(request) + "\n").encode("utf-8"))
        buffer = bytearray()
        while True:
            chunk = client.recv(4096)
            if not chunk:
                break
            buffer.extend(chunk)
            if b"\n" in chunk:
                break
            if len(buffer) > MAX_SOCKET_REQUEST_BYTES:
                raise ValueError("release executor evidence response exceeded size limit")
    if not buffer:
        raise ValueError("release executor evidence response was empty")
    response = json.loads(bytes(buffer).split(b"\n", 1)[0].decode("utf-8"))
    if not isinstance(response, dict):
        raise ValueError("release executor evidence response was invalid")
    if response.get("error"):
        raise ValueError(str(response["error"]))
    if not bool(response.get("ok")):
        raise ValueError("release executor evidence recording failed")
    return response


def _copy_snapshot(worktree: Path) -> tuple[Path, Path]:
    snapshot_root = Path(tempfile.mkdtemp(prefix="engineer-runner-"))
    snapshot_worktree = snapshot_root / "worktree"
    shutil.copytree(
        worktree,
        snapshot_worktree,
        symlinks=False,
        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.pyc", ".pytest_cache", ".mypy_cache"),
    )
    _make_readable_tree(snapshot_worktree)
    return snapshot_root, snapshot_worktree


def _discover_unittest_modules(worktree: Path, discover: dict[str, Any]) -> list[str]:
    root_name = discover.get("root", "tests")
    pattern = discover.get("pattern", "test_*.py")
    raw_exclude_files = discover.get("exclude_files", [])
    if not isinstance(root_name, str) or not root_name:
        raise ValueError("invalid discovery root")
    if not isinstance(pattern, str) or not pattern:
        raise ValueError("invalid discovery pattern")
    if not isinstance(raw_exclude_files, list) or not all(isinstance(name, str) for name in raw_exclude_files):
        raise ValueError("invalid discovery exclude_files")
    exclude_files = set(raw_exclude_files)

    root = (worktree / root_name).resolve()
    if not root.exists() or not root.is_dir():
        raise ValueError(f"discovery root '{root_name}' is missing")
    if worktree.resolve() not in root.parents and root != worktree.resolve():
        raise ValueError("discovery root escapes workspace")

    modules: list[str] = []
    for candidate in sorted(root.rglob(pattern)):
        if candidate.is_dir() or candidate.is_symlink():
            continue
        if candidate.name in exclude_files:
            continue
        rel = candidate.relative_to(worktree)
        module = ".".join(rel.with_suffix("").parts)
        modules.append(module)

    if not modules:
        raise ValueError("no discoverable tests found for python_unit")
    return modules


def _resolve_tests_for_check(worktree: Path, check: dict[str, Any], check_id: str) -> list[str]:
    mode = check.get("mode", "explicit")
    if mode == "discover":
        discover = check.get("discover", {})
        if not isinstance(discover, dict):
            raise ValueError(f"invalid discovery config for {check_id}")
        return _discover_unittest_modules(worktree, discover)

    tests = check.get("tests", [])
    if not isinstance(tests, list) or not tests or not all(isinstance(test, str) and test for test in tests):
        raise ValueError(f"invalid explicit test config for {check_id}")
    return list(tests)


def _force_remove_container(run_id: str) -> None:
    subprocess.run(
        ["docker", "rm", "-f", run_id],
        check=False,
        capture_output=True,
        text=True,
    )


def run_job(
    worktree_path: str,
    tests: list[str],
    timeout_seconds: int = 30,
    commit_sha: str | None = None,
    prebuilt_snapshot: tuple[Path, Path] | None = None,
) -> dict:
    worktree = Path(worktree_path).resolve()
    if prebuilt_snapshot is not None:
        snapshot_root, snapshot_worktree = prebuilt_snapshot
    elif commit_sha:
        snapshot_root, snapshot_worktree = _copy_commit_snapshot(worktree, commit_sha=commit_sha)
    else:
        snapshot_root, snapshot_worktree = _copy_snapshot(worktree)

    run_id = f"engineer-run-{uuid.uuid4().hex[:10]}"
    cleanup_ok = False
    timed_out = False
    exit_code = 0
    stdout = ""
    stderr = ""

    try:
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            run_id,
            "--network",
            "none",
            "--cpus",
            "1.0",
            "--memory",
            "256m",
            "--pids-limit",
            "64",
            "--read-only",
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=64m",
            "--tmpfs",
            "/run:rw,nosuid,nodev,size=16m",
            "--user",
            "65534:65534",
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "PYTHONPATH=/workspace",
            "-v",
            f"{snapshot_worktree}:/workspace:ro",
            "-w",
            "/workspace",
            DEFAULT_IMAGE,
            "python",
            "-m",
            "unittest",
            "-v",
            *tests,
        ]

        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nRunner timeout after {timeout_seconds}s\n"
            _force_remove_container(run_id)

        truncated_stdout, stdout_truncated = _truncate_output(stdout)
        truncated_stderr, stderr_truncated = _truncate_output(stderr)

        return {
            "run_id": run_id,
            "worktree": str(worktree),
            "snapshot_root": str(snapshot_root),
            "snapshot_worktree": str(snapshot_worktree),
            "snapshot_commit_sha": commit_sha or "",
            "tests": tests,
            "timeout_seconds": timeout_seconds,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "stdout": truncated_stdout,
            "stderr": truncated_stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "limits": {
                "network": "none",
                "cpus": "1.0",
                "memory": "256m",
                "pids": 64,
                "readonly_rootfs": True,
                "non_root_uid": 65534,
            },
        }
    finally:
        try:
            shutil.rmtree(snapshot_root)
            cleanup_ok = True
        finally:
            if not cleanup_ok:
                print(f"WARNING: snapshot cleanup failed for {snapshot_root}")


def _ensure_render_image(image: str) -> None:
    probe = subprocess.run(
        ["docker", "image", "inspect", image],
        check=False,
        capture_output=True,
        text=True,
    )
    if probe.returncode == 0:
        return
    raise ValueError(
        f"render profile image '{image}' is not available; build it before rendering"
    )


def _match_allowed_script(script_rel: Path, allowed_patterns: list[str]) -> bool:
    normalized = script_rel.as_posix()
    return any(script_rel.match(pattern) or Path(normalized).match(pattern) for pattern in allowed_patterns)


def _probe_media_duration_seconds(path: Path, image: str) -> float | None:
    if path.suffix.lower() not in {".mp4", ".mov", ".mkv", ".webm"}:
        return None
    cmd = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-v",
        f"{path.parent}:/probe:ro",
        image,
        "ffprobe",
        "-v",
        "error",
        "-show_entries",
        "format=duration",
        "-of",
        "default=noprint_wrappers=1:nokey=1",
        f"/probe/{path.name}",
    ]
    proc = subprocess.run(
        cmd,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    if proc.returncode != 0:
        return None
    output = (proc.stdout or "").strip()
    if not output:
        return None
    try:
        return round(float(output), 3)
    except ValueError:
        return None


def run_render_job(
    workspace_id: str,
    worktree_path: str,
    render_profile: str,
    script_path: str,
) -> dict[str, Any]:
    profile = APPROVED_RENDER_PROFILES.get(render_profile)
    if profile is None:
        raise ValueError(f"render_profile '{render_profile}' is not approved")

    worktree = Path(worktree_path).resolve()
    script_rel = _safe_relative(script_path)
    if script_rel.suffix.lower() != ".py":
        raise ValueError("script_path must reference a Python file")
    allowed_patterns = profile.get("allowed_script_patterns", [])
    if not isinstance(allowed_patterns, list) or not all(isinstance(item, str) for item in allowed_patterns):
        raise ValueError("render profile allowed_script_patterns is invalid")
    if not _match_allowed_script(script_rel, allowed_patterns):
        raise ValueError("script_path is not allowed for the render profile")

    _resolve_in_workspace(worktree, str(script_rel))
    image = str(profile["image"])
    _ensure_render_image(image)

    timeout_seconds = int(profile.get("timeout_seconds", 180))
    cpus = str(profile.get("cpus", "1.0"))
    memory = str(profile.get("memory", "512m"))
    pids = int(profile.get("pids", 96))
    run_user = str(profile.get("user", "65534:65534"))
    max_output_bytes = int(profile.get("max_output_bytes", MAX_ARTIFACT_BYTES_DEFAULT))
    output_name = str(profile.get("output_name", "artifact.mp4"))
    output_exts = profile.get("output_exts", [".mp4"])
    if not isinstance(output_exts, list) or not all(isinstance(ext, str) for ext in output_exts):
        raise ValueError("render profile output_exts is invalid")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    artifact_id = f"{workspace_id}-{render_profile}-{timestamp}-{uuid.uuid4().hex[:8]}"
    artifact_dir = (ARTIFACTS_ROOT / artifact_id).resolve()
    artifact_dir.mkdir(parents=True, exist_ok=False)

    snapshot_root, snapshot_worktree = _copy_snapshot(worktree)
    run_id = f"engineer-render-{uuid.uuid4().hex[:10]}"
    timed_out = False
    exit_code = 0
    stdout = ""
    stderr = ""

    output_target = artifact_dir / output_name
    output_container_path = f"/outputs/{output_name}"
    script_container_path = script_rel.as_posix()
    if script_container_path.startswith("/"):
        raise ValueError("script_path must be relative")

    try:
        command = [
            "docker",
            "run",
            "--rm",
            "--name",
            run_id,
            "--network",
            "none",
            "--cpus",
            cpus,
            "--memory",
            memory,
            "--pids-limit",
            str(pids),
            "--read-only",
            "--security-opt",
            "no-new-privileges:true",
            "--cap-drop",
            "ALL",
            "--tmpfs",
            "/tmp:rw,nosuid,nodev,size=128m",
            "--tmpfs",
            "/run:rw,nosuid,nodev,size=16m",
            "--user",
            run_user,
            "-e",
            "PYTHONDONTWRITEBYTECODE=1",
            "-e",
            "PYTHONUNBUFFERED=1",
            "-e",
            "PYTHONPATH=/workspace",
            "-e",
            "HOME=/tmp",
            "-e",
            "MPLCONFIGDIR=/tmp/mpl",
            "-v",
            f"{snapshot_worktree}:/workspace:ro",
            "-v",
            f"{artifact_dir}:/outputs:rw",
            "-w",
            "/workspace",
            image,
            "python",
            script_container_path,
            "--output",
            output_container_path,
        ]
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                timeout=timeout_seconds,
            )
            exit_code = completed.returncode
            stdout = completed.stdout
            stderr = completed.stderr
        except subprocess.TimeoutExpired as exc:
            timed_out = True
            exit_code = 124
            stdout = exc.stdout or ""
            stderr = (exc.stderr or "") + f"\nRender timeout after {timeout_seconds}s\n"
            _force_remove_container(run_id)

        truncated_stdout, stdout_truncated = _truncate_output(stdout, max_bytes=MAX_RENDER_LOG_BYTES)
        truncated_stderr, stderr_truncated = _truncate_output(stderr, max_bytes=MAX_RENDER_LOG_BYTES)

        file_entries: list[dict[str, Any]] = []
        total_bytes = 0
        for entry in sorted(artifact_dir.rglob("*")):
            resolved = entry.resolve(strict=False)
            try:
                resolved.relative_to(artifact_dir)
            except ValueError as exc:
                raise ValueError("artifact output escaped output directory") from exc
            if entry.is_symlink():
                raise ValueError("artifact output contains symlink entries")
            if entry.is_file():
                size = entry.stat().st_size
                total_bytes += size
                file_entries.append(
                    {
                        "name": entry.name,
                        "path": str(entry),
                        "size_bytes": size,
                    }
                )

        if total_bytes > max_output_bytes:
            raise ValueError("artifact output exceeded max_output_bytes limit")
        if not file_entries:
            return {
                "ok": False,
                "error": "rendering produced no output files",
                "workspace_id": workspace_id,
                "workspace_path": str(worktree),
                "render_profile": render_profile,
                "script_path": str(script_rel),
                "artifact_id": artifact_id,
                "artifact_filename": None,
                "artifact_host_path": None,
                "artifact_size_bytes": 0,
                "artifact_duration_seconds": None,
                "all_output_files": [],
                "total_output_bytes": 0,
                "max_output_bytes": max_output_bytes,
                "timeout_seconds": timeout_seconds,
                "timed_out": timed_out,
                "exit_code": exit_code,
                "stdout": truncated_stdout,
                "stderr": truncated_stderr,
                "stdout_truncated": stdout_truncated,
                "stderr_truncated": stderr_truncated,
                "limits": {
                    "network": "none",
                    "cpus": cpus,
                    "memory": memory,
                    "pids": pids,
                    "readonly_rootfs": True,
                    "non_root_uid": run_user.split(":", 1)[0],
                },
            }

        primary = next((item for item in file_entries if item["path"] == str(output_target)), None)
        if primary is None:
            primary = max(file_entries, key=lambda item: item["size_bytes"])

        primary_suffix = Path(primary["name"]).suffix.lower()
        allowed_suffixes = {ext.lower() for ext in output_exts}
        if primary_suffix not in allowed_suffixes:
            raise ValueError(f"unexpected artifact extension '{primary_suffix}'")

        duration_seconds = _probe_media_duration_seconds(Path(primary["path"]), image=image)
        ok = exit_code == 0 and not timed_out
        return {
            "ok": ok,
            "workspace_id": workspace_id,
            "workspace_path": str(worktree),
            "render_profile": render_profile,
            "script_path": str(script_rel),
            "artifact_id": artifact_id,
            "artifact_filename": primary["name"],
            "artifact_host_path": primary["path"],
            "artifact_size_bytes": primary["size_bytes"],
            "artifact_duration_seconds": duration_seconds,
            "all_output_files": file_entries,
            "total_output_bytes": total_bytes,
            "max_output_bytes": max_output_bytes,
            "timeout_seconds": timeout_seconds,
            "timed_out": timed_out,
            "exit_code": exit_code,
            "stdout": truncated_stdout,
            "stderr": truncated_stderr,
            "stdout_truncated": stdout_truncated,
            "stderr_truncated": stderr_truncated,
            "limits": {
                "network": "none",
                "cpus": cpus,
                "memory": memory,
                "pids": pids,
                "readonly_rootfs": True,
                "non_root_uid": run_user.split(":", 1)[0],
            },
        }
    except Exception:
        shutil.rmtree(artifact_dir, ignore_errors=True)
        raise
    finally:
        shutil.rmtree(snapshot_root, ignore_errors=True)


def stage_artifact_for_delivery(artifact_id: str, artifact_filename: str = "") -> dict[str, Any]:
    if not artifact_id or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact_id):
        raise ValueError("invalid artifact_id format")

    artifact_dir = (ARTIFACTS_ROOT / artifact_id).resolve(strict=True)
    if artifact_dir.is_symlink() or not artifact_dir.is_dir():
        raise ValueError("artifact_id is not a valid artifact directory")
    try:
        artifact_dir.relative_to(ARTIFACTS_ROOT.resolve())
    except ValueError as exc:
        raise ValueError("artifact directory escapes approved root") from exc

    selected: Path | None = None
    if artifact_filename:
        rel = _safe_relative(artifact_filename)
        candidate = (artifact_dir / rel).resolve(strict=True)
        try:
            candidate.relative_to(artifact_dir)
        except ValueError as exc:
            raise ValueError("artifact filename escapes artifact directory") from exc
        if candidate.is_symlink() or not candidate.is_file():
            raise ValueError("artifact filename must resolve to a regular file")
        selected = candidate
    else:
        candidates: list[Path] = []
        for item in sorted(artifact_dir.rglob("*")):
            if item.is_symlink() or not item.is_file():
                continue
            try:
                item.relative_to(artifact_dir)
            except ValueError as exc:
                raise ValueError("artifact candidate escapes artifact directory") from exc
            if item.suffix.lower() in ALLOWED_ARTIFACT_EXTENSIONS:
                candidates.append(item)
        if not candidates:
            raise ValueError("artifact directory has no allowed deliverable files")
        if len(candidates) > 1:
            raise ValueError("artifact directory has multiple deliverable files; specify artifact_filename")
        selected = candidates[0]

    suffix = selected.suffix.lower()
    if suffix not in ALLOWED_ARTIFACT_EXTENSIONS:
        raise ValueError(f"artifact extension '{suffix}' is not allowed for delivery")
    size_bytes = selected.stat().st_size
    if size_bytes <= 0:
        raise ValueError("artifact file is empty")
    if size_bytes > MAX_ARTIFACT_BYTES_DEFAULT:
        raise ValueError("artifact file exceeds allowed delivery size")

    stage_token = f"{artifact_id}-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}-{uuid.uuid4().hex[:8]}"
    host_stage_dir = (ARTIFACT_STAGING_HOST_ROOT / stage_token).resolve()
    host_stage_dir.mkdir(parents=True, exist_ok=False)
    staged_host_path = (host_stage_dir / selected.name).resolve()
    shutil.copy2(selected, staged_host_path)
    if staged_host_path.is_symlink() or not staged_host_path.is_file():
        raise ValueError("staged artifact is invalid")
    staged_size = staged_host_path.stat().st_size

    gateway_media_path = str((ARTIFACT_STAGING_GATEWAY_ROOT / stage_token / selected.name).as_posix())
    return {
        "ok": True,
        "artifact_id": artifact_id,
        "artifact_filename": selected.name,
        "artifact_host_path": str(selected),
        "staged_host_path": str(staged_host_path),
        "gateway_media_path": gateway_media_path,
        "media_directive": f"MEDIA:{gateway_media_path}",
        "size_bytes": staged_size,
    }


def _peer_uid(conn: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    pid, uid, gid = struct.unpack("3i", creds)
    _ = pid, gid
    return uid


def _read_request(conn: socket.socket) -> dict[str, Any]:
    chunks = bytearray()
    while True:
        data = conn.recv(4096)
        if not data:
            break
        chunks.extend(data)
        if b"\n" in data:
            break
        if len(chunks) > MAX_SOCKET_REQUEST_BYTES:
            raise ValueError("request too large")
    if not chunks:
        raise ValueError("empty request")
    line = bytes(chunks).split(b"\n", 1)[0]
    return json.loads(line.decode("utf-8"))


def _handle_request(request: dict[str, Any], auth_token: str) -> dict[str, Any]:
    allowed_keys = {
        "auth_token",
        "action",
        "workspace_id",
        "check_id",
        "render_profile",
        "script_path",
        "artifact_id",
        "artifact_filename",
    }
    unknown_keys = set(request.keys()) - allowed_keys
    if unknown_keys:
        raise ValueError(f"unsupported request fields: {sorted(unknown_keys)}")

    token = request.get("auth_token", "")
    if not isinstance(token, str) or not secrets.compare_digest(token, auth_token):
        raise ValueError("authentication failed")

    action = request.get("action", "check")
    if not isinstance(action, str) or action not in {"check", "render", "stage_artifact"}:
        raise ValueError("action must be one of: check, render, stage_artifact")

    if action == "stage_artifact":
        artifact_id = request.get("artifact_id", "")
        artifact_filename = request.get("artifact_filename", "")
        if not isinstance(artifact_id, str) or not artifact_id:
            raise ValueError("artifact_id is required for stage_artifact action")
        if not isinstance(artifact_filename, str):
            raise ValueError("artifact_filename must be a string when provided")
        return stage_artifact_for_delivery(artifact_id=artifact_id, artifact_filename=artifact_filename)

    workspace_id = request.get("workspace_id", "")
    if not isinstance(workspace_id, str) or not workspace_id:
        raise ValueError("workspace_id is required")
    workspace = _resolve_workspace_id(workspace_id)
    if action == "check":
        check_id = request.get("check_id", "")
        if not isinstance(check_id, str) or not check_id:
            raise ValueError("check_id is required")
        check = APPROVED_CHECKS.get(check_id)
        if check is None:
            raise ValueError(f"check_id '{check_id}' is not approved")
        check_config_version = str(check.get("config_version", "")).strip()
        if not re.fullmatch(r"[A-Za-z0-9._-]{1,120}", check_config_version):
            raise ValueError(f"check_id '{check_id}' is missing a valid config_version")
        integration_context: dict[str, Any] | None = None
        metadata = _read_workspace_metadata(workspace_id)
        if metadata.get("workspace_type") == "integration":
            integration_context = _integration_context(workspace=workspace, workspace_id=workspace_id)
            snapshot_root, snapshot_worktree = _copy_commit_snapshot(
                workspace,
                commit_sha=integration_context["integration_commit_sha"],
            )
            try:
                tests = _resolve_tests_for_check(worktree=snapshot_worktree, check=check, check_id=check_id)
                run = run_job(
                    worktree_path=str(workspace),
                    tests=tests,
                    timeout_seconds=int(check["timeout_seconds"]),
                    commit_sha=integration_context["integration_commit_sha"],
                    prebuilt_snapshot=(snapshot_root, snapshot_worktree),
                )
            except Exception:
                shutil.rmtree(snapshot_root, ignore_errors=True)
                raise
        else:
            tests = _resolve_tests_for_check(worktree=workspace, check=check, check_id=check_id)
            run = run_job(
                worktree_path=str(workspace),
                tests=tests,
                timeout_seconds=int(check["timeout_seconds"]),
            )
        evidence: dict[str, Any] | None = None
        if integration_context is not None:
            execution_id = _runner_execution_id()
            observed_at = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            evidence_payload = {
                "workspace_path": str(workspace),
                "check_id": check_id,
                "check_config_version": check_config_version,
                "tests": run["tests"],
                "timeout_seconds": run["timeout_seconds"],
                "exit_code": run["exit_code"],
                "timed_out": run["timed_out"],
                "stdout_truncated": run["stdout_truncated"],
                "stderr_truncated": run["stderr_truncated"],
                "limits": run["limits"],
                "snapshot_commit_sha": run.get("snapshot_commit_sha", ""),
            }
            evidence = _record_runner_evidence(
                {
                    "repository_id": integration_context["project_id"],
                    "integration_workspace_id": integration_context["integration_workspace_id"],
                    "integration_commit_sha": integration_context["integration_commit_sha"],
                    "check_id": check_id,
                    "check_config_version": check_config_version,
                    "execution_id": execution_id,
                    "source_controller": RUNNER_CONTROLLER_NAME,
                    "source_run_id": run["run_id"],
                    "result_state": "passed" if run["exit_code"] == 0 and not run["timed_out"] else "failed",
                    "exit_code": int(run["exit_code"]),
                    "timed_out": bool(run["timed_out"]),
                    "observed_at": observed_at,
                    "evidence_payload": evidence_payload,
                }
            )
        return {
            "ok": run["exit_code"] == 0 and not run["timed_out"],
            "workspace_id": workspace_id,
            "workspace_path": str(workspace),
            "check_id": check_id,
            "check_config_version": check_config_version,
            "tests": run["tests"],
            "exit_code": run["exit_code"],
            "timed_out": run["timed_out"],
            "stdout": run["stdout"],
            "stderr": run["stderr"],
            "stdout_truncated": run["stdout_truncated"],
            "stderr_truncated": run["stderr_truncated"],
            "limits": run["limits"],
            "timeout_seconds": run["timeout_seconds"],
            "tested_commit_sha": run.get("snapshot_commit_sha", "") or _run_git(workspace, ["rev-parse", "HEAD"]),
            "evidence_recorded": evidence is not None,
            "evidence": evidence,
        }

    render_profile = request.get("render_profile", "")
    script_path = request.get("script_path", "")
    if not isinstance(render_profile, str) or not render_profile:
        raise ValueError("render_profile is required for render action")
    if not isinstance(script_path, str) or not script_path:
        raise ValueError("script_path is required for render action")
    return run_render_job(
        workspace_id=workspace_id,
        worktree_path=str(workspace),
        render_profile=render_profile,
        script_path=script_path,
    )


def serve(socket_path: Path, auth_token: str, allowed_uid: int) -> None:
    socket_path.parent.mkdir(parents=True, exist_ok=True)
    if socket_path.exists():
        socket_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(socket_path))
        os.chmod(socket_path, 0o660)
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    uid = _peer_uid(conn)
                    if uid is not None and uid != allowed_uid:
                        raise ValueError("peer UID is not allowed")
                    request = _read_request(conn)
                    response = _handle_request(request, auth_token=auth_token)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                try:
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except BrokenPipeError:
                    continue
    finally:
        server.close()
        if socket_path.exists():
            socket_path.unlink()


def main() -> None:
    parser = argparse.ArgumentParser(description="Trusted controller for disposable Python test jobs.")
    subparsers = parser.add_subparsers(dest="mode", required=True)

    run_parser = subparsers.add_parser("run", help="Run one test job directly")
    run_parser.add_argument("--worktree", required=True, help="Absolute path to approved worktree")
    run_parser.add_argument("--test", dest="tests", action="append", required=True, help="unittest module path")
    run_parser.add_argument("--timeout-seconds", type=int, default=30, help="Execution timeout")

    serve_parser = subparsers.add_parser("serve", help="Run Unix-socket controller server")
    serve_parser.add_argument(
        "--socket-path",
        required=True,
        help="Unix socket path for controller API",
    )
    serve_parser.add_argument(
        "--auth-token",
        default=None,
        help="Shared authentication token for controller API",
    )
    serve_parser.add_argument(
        "--allowed-peer-uid",
        type=int,
        default=1000,
        help="Only accept Unix socket clients from this UID",
    )

    args = parser.parse_args()
    if args.mode == "run":
        result = run_job(worktree_path=args.worktree, tests=args.tests, timeout_seconds=args.timeout_seconds)
        print(json.dumps(result, indent=2))
        return

    auth_token = args.auth_token or os.getenv("ENGINEER_RUNNER_AUTH_TOKEN", "")
    if not auth_token:
        raise SystemExit("ENGINEER_RUNNER_AUTH_TOKEN must be set or --auth-token must be provided")

    serve(
        socket_path=Path(args.socket_path),
        auth_token=auth_token,
        allowed_uid=args.allowed_peer_uid,
    )


if __name__ == "__main__":
    main()
