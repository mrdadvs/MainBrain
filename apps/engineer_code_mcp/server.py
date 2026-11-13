#!/usr/bin/env python3

import json
import os
import re
import shutil
import socket
import subprocess
import tempfile
import hashlib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from mcp.server import Server
from mcp.types import CallToolRequestParams, CallToolResult, ListToolsResult, TextContent, Tool
from pydantic import BaseModel

MAX_READ_BYTES = 200_000
MAX_SEARCH_RESULTS = 200
MAX_SEARCH_FILE_BYTES = 300_000
MAX_PATCH_BYTES = 350_000
MAX_DIFF_BYTES = 120_000
MAX_UNTRACKED_DIFF_FILE_BYTES = 40_000
MAX_RUNNER_RESPONSE_BYTES = 300_000
MAX_RELEASE_EXECUTOR_RESPONSE_BYTES = 300_000
MAX_COMMIT_MESSAGE_CHARS = 300
MAX_RELEASE_REPORT_BYTES = 80_000
TASK_BRANCH_PATTERN = r"engineer/task-[A-Za-z0-9._-]+"
WORKSPACE_ID_PATTERN = r"[A-Za-z0-9._-]+"
APPROVAL_ID_PATTERN = r"[A-Za-z0-9._-]{8,128}"
SHA1_PATTERN = r"[0-9a-f]{40}"
METADATA_DIRNAME = "_engineer_meta"
WORKSPACE_META_VERSION = 1

APPROVED_CHECK_IDS = {"python_unit", "python_isolation", "python_fail_demo"}
APPROVED_RENDER_PROFILE_IDS = {"python_animation_v1"}

DENIED_NAMES = {".git", ".ssh", "secrets", "credentials"}
DENIED_FILE_PREFIXES = (".env",)
PROTECTED_PATH_PREFIXES = (
    "apps/engineer_code_mcp/",
    "infra/openclaw/",
    "data/openclaw/",
)
PROTECTED_PATH_EXACT = {
    "config/allowed_projects.json",
    "apps/engineer_code_mcp/config/allowed_projects.json",
}

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


def _slug(value: str) -> str:
    normalized = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    normalized = normalized.strip("-._")
    if not normalized:
        raise ValueError("task_id must include at least one alphanumeric character")
    return normalized[:80]


def _json_result(payload: dict[str, Any], is_error: bool = False) -> CallToolResult:
    return CallToolResult(
        content=[TextContent(type="text", text=json.dumps(payload, indent=2, sort_keys=True))],
        is_error=is_error,
    )


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


def _clean_patch_path_token(token: str) -> str | None:
    cleaned = token.strip()
    if cleaned in {"/dev/null", "a/dev/null", "b/dev/null"}:
        return None
    if cleaned.startswith(("a/", "b/")):
        cleaned = cleaned[2:]
    return cleaned or None


@dataclass(frozen=True)
class AllowedProject:
    project_id: str
    root: Path
    default_branch: str


@dataclass(frozen=True)
class TrustedReleaseBaseline:
    project_id: str
    repository_id: str
    remote_name: str
    remote_path: Path
    target_branch: str


class EngineerCodeService:
    def __init__(
        self,
        projects: dict[str, AllowedProject],
        trusted_release_bases: dict[str, TrustedReleaseBaseline],
        workspaces_root: Path,
        runner_socket_path: Path,
        runner_auth_token: str,
        runner_timeout_seconds: int,
        release_executor_socket_path: Path,
        release_executor_auth_token: str,
        release_executor_timeout_seconds: int,
    ):
        self.projects = projects
        self.trusted_release_bases = trusted_release_bases
        self.workspaces_root = workspaces_root.resolve()
        self.workspaces_root.mkdir(parents=True, exist_ok=True)
        self.metadata_root = (self.workspaces_root / METADATA_DIRNAME).resolve()
        self.metadata_root.mkdir(parents=True, exist_ok=True)
        self.runner_socket_path = runner_socket_path
        self.runner_auth_token = runner_auth_token
        self.runner_timeout_seconds = runner_timeout_seconds
        self.release_executor_socket_path = release_executor_socket_path
        self.release_executor_auth_token = release_executor_auth_token
        self.release_executor_timeout_seconds = release_executor_timeout_seconds

    @classmethod
    def from_env(cls) -> "EngineerCodeService":
        projects_file = Path(
            os.getenv(
                "ENGINEER_CODE_MCP_PROJECTS_FILE",
                "/srv/engineer/config/allowed_projects.json",
            )
        )
        workspaces_root = Path(
            os.getenv(
                "ENGINEER_CODE_MCP_WORKSPACES_ROOT",
                "/srv/engineer/workspaces",
            )
        )
        runner_socket_path = Path(
            os.getenv(
                "ENGINEER_RUNNER_SOCKET_PATH",
                "/srv/engineer/runner/runner.sock",
            )
        )
        runner_auth_token = os.getenv("ENGINEER_RUNNER_AUTH_TOKEN", "")
        if not runner_auth_token:
            raise ValueError("ENGINEER_RUNNER_AUTH_TOKEN must be set")
        runner_timeout_seconds = int(os.getenv("ENGINEER_RUNNER_TIMEOUT_SECONDS", "90"))
        release_executor_socket_path = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH",
                "/srv/engineer/release-executor/release-executor.sock",
            )
        )
        release_executor_auth_token = os.getenv("ENGINEER_RELEASE_EXECUTOR_AUTH_TOKEN", "")
        if not release_executor_auth_token:
            raise ValueError("ENGINEER_RELEASE_EXECUTOR_AUTH_TOKEN must be set")
        release_executor_timeout_seconds = int(os.getenv("ENGINEER_RELEASE_EXECUTOR_TIMEOUT_SECONDS", "120"))
        projects = cls._load_projects(projects_file)
        trusted_policy_file = Path(
            os.getenv(
                "ENGINEER_RELEASE_POLICY_FILE",
                "/srv/engineer/release-policy/trusted_policy.json",
            )
        )
        trusted_remote_host_root = Path(
            os.getenv("ENGINEER_TRUSTED_REMOTE_HOST_ROOT", "/home/mdv/mainbrain/repos")
        ).resolve()
        trusted_remote_container_root = Path(
            os.getenv("ENGINEER_TRUSTED_REMOTE_CONTAINER_ROOT", "/srv/repos")
        ).resolve()
        trusted_release_bases = cls._load_trusted_release_bases(
            trusted_policy_file=trusted_policy_file,
            projects=projects,
            trusted_remote_host_root=trusted_remote_host_root,
            trusted_remote_container_root=trusted_remote_container_root,
        )
        return cls(
            projects=projects,
            trusted_release_bases=trusted_release_bases,
            workspaces_root=workspaces_root,
            runner_socket_path=runner_socket_path,
            runner_auth_token=runner_auth_token,
            runner_timeout_seconds=runner_timeout_seconds,
            release_executor_socket_path=release_executor_socket_path,
            release_executor_auth_token=release_executor_auth_token,
            release_executor_timeout_seconds=release_executor_timeout_seconds,
        )

    @staticmethod
    def _load_projects(projects_file: Path) -> dict[str, AllowedProject]:
        data = json.loads(projects_file.read_text(encoding="utf-8"))
        entries = data.get("projects")
        if not isinstance(entries, list) or not entries:
            raise ValueError("projects allowlist must contain at least one project")

        projects: dict[str, AllowedProject] = {}
        for entry in entries:
            project_id = entry.get("id")
            project_path = entry.get("path")
            default_branch = entry.get("default_branch", "main")
            if not isinstance(project_id, str) or not project_id:
                raise ValueError("project id is required")
            if not isinstance(project_path, str) or not project_path:
                raise ValueError(f"path is required for project {project_id}")
            root = Path(project_path).resolve()
            if not root.is_dir():
                raise ValueError(f"allowlisted project path does not exist: {root}")
            if not (root / ".git").exists():
                raise ValueError(f"allowlisted project is not a git repository: {root}")
            projects[project_id] = AllowedProject(
                project_id=project_id,
                root=root,
                default_branch=default_branch,
            )
        return projects

    @classmethod
    def _load_trusted_release_bases(
        cls,
        trusted_policy_file: Path,
        projects: dict[str, AllowedProject],
        trusted_remote_host_root: Path,
        trusted_remote_container_root: Path,
    ) -> dict[str, TrustedReleaseBaseline]:
        if not trusted_policy_file.exists():
            raise ValueError(f"trusted release policy file not found: {trusted_policy_file}")
        if not trusted_policy_file.is_file():
            raise ValueError(f"trusted release policy path must be a file: {trusted_policy_file}")

        policy = json.loads(trusted_policy_file.read_text(encoding="utf-8"))
        repositories = policy.get("repositories")
        if not isinstance(repositories, list) or not repositories:
            raise ValueError("trusted release policy must include repositories")

        baselines: dict[str, TrustedReleaseBaseline] = {}
        for entry in repositories:
            if not isinstance(entry, dict):
                raise ValueError("trusted release policy repository entry must be an object")
            repository_id = entry.get("id")
            project_id = entry.get("managed_project_id")
            if not isinstance(repository_id, str) or not repository_id:
                raise ValueError("trusted release policy repository id is required")
            if not isinstance(project_id, str) or not project_id:
                raise ValueError(f"trusted release policy managed_project_id is required for {repository_id}")
            if project_id not in projects:
                continue

            allowed_remotes = entry.get("allowed_remotes")
            if not isinstance(allowed_remotes, list) or len(allowed_remotes) != 1:
                raise ValueError(
                    f"trusted release policy requires exactly one allowed remote for {repository_id}"
                )
            remote_name = allowed_remotes[0]
            if not isinstance(remote_name, str) or not remote_name:
                raise ValueError(f"trusted release policy remote name invalid for {repository_id}")

            allowed_target_branches = entry.get("allowed_target_branches")
            if not isinstance(allowed_target_branches, list) or len(allowed_target_branches) != 1:
                raise ValueError(
                    f"trusted release policy requires exactly one target branch for {repository_id}"
                )
            target_branch = allowed_target_branches[0]
            if not isinstance(target_branch, str) or not target_branch:
                raise ValueError(f"trusted release policy target branch invalid for {repository_id}")

            remote_paths = entry.get("remote_paths")
            if not isinstance(remote_paths, dict):
                raise ValueError(f"trusted release policy remote_paths missing for {repository_id}")
            remote_path_value = remote_paths.get(remote_name)
            if not isinstance(remote_path_value, str) or not remote_path_value:
                raise ValueError(
                    f"trusted release policy remote path missing for {repository_id}:{remote_name}"
                )

            remote_path = cls._resolve_trusted_remote_path(
                remote_path_value=remote_path_value,
                project=projects[project_id],
                trusted_remote_host_root=trusted_remote_host_root,
                trusted_remote_container_root=trusted_remote_container_root,
            )

            if project_id in baselines:
                raise ValueError(f"duplicate trusted release policy mapping for project {project_id}")
            baselines[project_id] = TrustedReleaseBaseline(
                project_id=project_id,
                repository_id=repository_id,
                remote_name=remote_name,
                remote_path=remote_path,
                target_branch=target_branch,
            )

        missing_projects = sorted(project_id for project_id in projects if project_id not in baselines)
        if missing_projects:
            raise ValueError(
                f"trusted release policy missing managed project mapping for: {', '.join(missing_projects)}"
            )
        return baselines

    @staticmethod
    def _resolve_trusted_remote_path(
        remote_path_value: str,
        project: AllowedProject,
        trusted_remote_host_root: Path,
        trusted_remote_container_root: Path,
    ) -> Path:
        raw_remote_path = Path(remote_path_value)
        if not raw_remote_path.is_absolute():
            raise ValueError("trusted release remote path must be absolute")

        candidate_paths: list[Path] = [raw_remote_path]
        try:
            host_relative = raw_remote_path.relative_to(trusted_remote_host_root)
            candidate_paths.append(trusted_remote_container_root / host_relative)
        except ValueError:
            pass
        candidate_paths.append(project.root.parent / raw_remote_path.name)

        resolved_remote: Path | None = None
        for candidate in candidate_paths:
            if candidate.exists():
                resolved_remote = candidate.resolve()
                break

        if resolved_remote is None:
            raise ValueError(
                f"trusted release remote path is unavailable in this environment: {remote_path_value}"
            )
        if not resolved_remote.is_dir():
            raise ValueError(f"trusted release remote is not a directory: {resolved_remote}")
        if not (resolved_remote / "HEAD").is_file():
            raise ValueError(f"trusted release remote is not a bare git repository: {resolved_remote}")
        try:
            resolved_remote.relative_to(project.root.parent)
        except ValueError as exc:
            raise ValueError(
                f"trusted release remote escapes approved repository root: {resolved_remote}"
            ) from exc

        return resolved_remote

    def _release_base(self, project_id: str) -> TrustedReleaseBaseline:
        release_base = self.trusted_release_bases.get(project_id)
        if release_base is None:
            raise ValueError(f"trusted release baseline not configured for project '{project_id}'")
        return release_base

    def _trusted_release_head(self, release_base: TrustedReleaseBaseline) -> str:
        ref_name = f"refs/heads/{release_base.target_branch}"
        head_sha = self._run_git(
            ["--git-dir", str(release_base.remote_path), "rev-parse", ref_name],
            cwd=self.workspaces_root,
            trusted=True,
        )
        if not re.fullmatch(SHA1_PATTERN, head_sha):
            raise ValueError(
                f"trusted release remote returned invalid HEAD for {release_base.remote_name}/{release_base.target_branch}"
            )
        return head_sha

    def _project(self, project_id: str) -> AllowedProject:
        project = self.projects.get(project_id)
        if project is None:
            raise ValueError(f"project '{project_id}' is not in the allowlist")
        return project

    def _resolve_in_project(self, project: AllowedProject, rel_path: str, expect_exists: bool = True) -> Path:
        relative = _safe_relative(rel_path)
        root = project.root.resolve()
        candidate = (root / relative).resolve(strict=expect_exists)
        try:
            candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("path escapes the approved repository") from exc

        if candidate != root and candidate.is_symlink():
            raise ValueError("symlink targets are not allowed")

        current = root
        for part in relative.parts:
            if part in ("", "."):
                continue
            _validate_name(part)
            current = current / part
            if current.exists() and current.is_symlink():
                raise ValueError("paths through symlinks are not allowed")
        return candidate

    def _resolve_workspace(self, workspace_id: str) -> Path:
        if not workspace_id or not re.fullmatch(WORKSPACE_ID_PATTERN, workspace_id):
            raise ValueError("invalid workspace_id")

        candidates: list[Path] = []
        for project_root in self.workspaces_root.iterdir():
            if not project_root.is_dir() or project_root.is_symlink():
                continue
            candidate = project_root / workspace_id
            if not candidate.exists():
                continue
            if candidate.is_symlink():
                raise ValueError("workspace symlinks are not allowed")
            resolved = candidate.resolve()
            try:
                resolved.relative_to(self.workspaces_root)
            except ValueError as exc:
                raise ValueError("workspace escapes managed storage") from exc
            candidates.append(resolved)

        if not candidates:
            raise ValueError(f"workspace '{workspace_id}' not found")
        if len(candidates) > 1:
            raise ValueError(f"workspace '{workspace_id}' is ambiguous across projects")

        workspace = candidates[0]
        if not (workspace / ".git").exists():
            raise ValueError("workspace is not a git checkout")
        return workspace

    def _workspace_meta_path(self, workspace_id: str) -> Path:
        if not workspace_id or not re.fullmatch(WORKSPACE_ID_PATTERN, workspace_id):
            raise ValueError("invalid workspace_id")
        return self.metadata_root / f"{workspace_id}.json"

    def _read_workspace_metadata(self, workspace_id: str, *, required: bool = True) -> dict[str, Any]:
        path = self._workspace_meta_path(workspace_id)
        if not path.exists():
            if required:
                raise ValueError("workspace metadata is missing")
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            raise ValueError("workspace metadata is invalid")
        return data

    def _write_workspace_metadata(self, workspace_id: str, payload: dict[str, Any]) -> None:
        path = self._workspace_meta_path(workspace_id)
        temp_path = path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        temp_path.replace(path)

    def _resolve_in_workspace(self, workspace: Path, rel_path: str, expect_exists: bool = True) -> Path:
        relative = _safe_relative(rel_path)
        candidate = (workspace / relative).resolve(strict=expect_exists)
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
        return candidate

    @staticmethod
    def _run_git(
        args: list[str],
        cwd: Path,
        allowed_exit_codes: set[int] | None = None,
        strip_output: bool = True,
        env: dict[str, str] | None = None,
        trusted: bool = False,
        allow_file_transport: bool = False,
    ) -> str:
        allowed = allowed_exit_codes or {0}
        run_env = os.environ.copy()
        command = ["git"]
        if trusted:
            run_env.update(TRUSTED_GIT_ENV)
            command.extend(TRUSTED_GIT_ARGS)
            if allow_file_transport:
                command.extend(["-c", "protocol.file.allow=always"])
        if env:
            run_env.update(env)
        process = subprocess.run(
            [*command, *args],
            cwd=str(cwd),
            check=False,
            capture_output=True,
            text=True,
            env=run_env,
        )
        if process.returncode not in allowed:
            detail = (process.stderr or process.stdout or "git command failed").strip()
            raise ValueError(detail)
        output = process.stdout
        return output.strip() if strip_output else output

    def _validate_patch_target(self, rel_path: str) -> Path:
        relative = _safe_relative(rel_path)
        normalized = str(relative).replace("\\", "/")
        normalized_lower = normalized.lower()

        if normalized_lower in PROTECTED_PATH_EXACT:
            raise ValueError("editing configuration allowlists is denied")
        for prefix in PROTECTED_PATH_PREFIXES:
            stripped = prefix.rstrip("/")
            if normalized_lower == stripped or normalized_lower.startswith(prefix):
                raise ValueError("editing MCP/OpenClaw service code is denied")
        return relative

    def _extract_patch_targets(self, unified_diff: str) -> list[str]:
        targets: list[str] = []
        for line in unified_diff.splitlines():
            if line.startswith("diff --git "):
                parts = line.split()
                if len(parts) >= 4:
                    for token in (parts[2], parts[3]):
                        cleaned = _clean_patch_path_token(token)
                        if cleaned:
                            targets.append(cleaned)
            elif line.startswith("+++ ") or line.startswith("--- "):
                token = line[4:].strip().split("\t", 1)[0]
                cleaned = _clean_patch_path_token(token)
                if cleaned:
                    targets.append(cleaned)

        deduped = sorted(set(targets))
        if not deduped:
            raise ValueError("patch does not include any file targets")
        return deduped

    def _workspace_status_entries(self, workspace: Path) -> tuple[list[dict[str, str]], int]:
        status_text = self._run_git(
            ["status", "--porcelain=v1", "--untracked-files=all"],
            cwd=workspace,
        )
        entries: list[dict[str, str]] = []
        omitted = 0
        for line in status_text.splitlines():
            if len(line) >= 4 and line[2] == " ":
                code = line[:2]
                raw_path = line[3:]
            else:
                parts = line.split(maxsplit=1)
                if len(parts) != 2:
                    continue
                code, raw_path = parts[0], parts[1]
            if " -> " in raw_path:
                raw_path = raw_path.split(" -> ", 1)[1]
            try:
                rel = _safe_relative(raw_path)
                self._resolve_in_workspace(workspace, str(rel), expect_exists=False)
                entries.append({"code": code, "path": str(rel)})
            except ValueError:
                omitted += 1
        return entries, omitted

    def _workspace_changed_files(self, workspace: Path) -> list[str]:
        status_entries, _ = self._workspace_status_entries(workspace)
        return sorted({entry["path"] for entry in status_entries})

    def _resolve_scope_target(
        self,
        project_id: str,
        workspace_id: str,
        path: str,
        *,
        expect_exists: bool,
    ) -> tuple[Path, Path, dict[str, str]]:
        has_project = bool((project_id or "").strip())
        has_workspace = bool((workspace_id or "").strip())
        if has_project == has_workspace:
            raise ValueError("exactly one of project_id or workspace_id is required")

        if has_project:
            project = self._project(project_id)
            target = self._resolve_in_project(project, path, expect_exists=expect_exists)
            return project.root.resolve(), target, {"project_id": project.project_id}

        workspace = self._resolve_workspace(workspace_id)
        target = self._resolve_in_workspace(workspace, path, expect_exists=expect_exists)
        return workspace.resolve(), target, {"workspace_id": workspace_id}

    def _render_untracked_diff(self, workspace: Path, rel_path: str) -> str:
        file_path = self._resolve_in_workspace(workspace, rel_path, expect_exists=True)
        if file_path.is_symlink():
            raise ValueError("untracked symlink files are not allowed")
        if file_path.is_dir():
            return ""
        if file_path.stat().st_size > MAX_UNTRACKED_DIFF_FILE_BYTES:
            return (
                f"diff --git a/{rel_path} b/{rel_path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{rel_path}\n"
                "@@ -0,0 +1,0 @@\n"
                "+# file omitted from diff: too large\n"
            )

        try:
            content = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            return (
                f"diff --git a/{rel_path} b/{rel_path}\n"
                "new file mode 100644\n"
                "--- /dev/null\n"
                f"+++ b/{rel_path}\n"
                "@@ -0,0 +1,0 @@\n"
                "+# binary or non-utf8 file omitted from diff\n"
            )

        lines = content.splitlines()
        line_count = len(lines)
        body = "\n".join(f"+{line}" for line in lines)
        if content.endswith("\n"):
            body += "\n"

        return (
            f"diff --git a/{rel_path} b/{rel_path}\n"
            "new file mode 100644\n"
            "--- /dev/null\n"
            f"+++ b/{rel_path}\n"
            f"@@ -0,0 +1,{line_count} @@\n"
            f"{body}"
        )

    @staticmethod
    def _limit_text(sections: list[str], max_bytes: int) -> tuple[str, bool]:
        output_parts: list[str] = []
        used = 0
        truncated = False
        for section in sections:
            payload = section.encode("utf-8")
            remaining = max_bytes - used
            if remaining <= 0:
                truncated = True
                break
            if len(payload) <= remaining:
                output_parts.append(section)
                used += len(payload)
                continue
            output_parts.append(payload[:remaining].decode("utf-8", errors="ignore"))
            used = max_bytes
            truncated = True
            break

        if truncated:
            marker = "\n\n...diff output truncated...\n"
            marker_bytes = marker.encode("utf-8")
            if used + len(marker_bytes) <= max_bytes:
                output_parts.append(marker)
            elif max_bytes > 0:
                allowed = max_bytes - used
                if allowed > 0:
                    output_parts.append(marker_bytes[:allowed].decode("utf-8", errors="ignore"))

        return "".join(output_parts), truncated

    def list_projects(self) -> dict[str, Any]:
        rows = []
        for project in sorted(self.projects.values(), key=lambda p: p.project_id):
            rows.append(
                {
                    "id": project.project_id,
                    "default_branch": project.default_branch,
                    "path": str(project.root),
                }
            )
        return {"projects": rows}

    def list_files(
        self,
        project_id: str = "",
        workspace_id: str = "",
        path: str = ".",
        recursive: bool = False,
    ) -> dict[str, Any]:
        root, target, scope = self._resolve_scope_target(
            project_id=project_id,
            workspace_id=workspace_id,
            path=path,
            expect_exists=True,
        )
        if not target.is_dir():
            raise ValueError("path must be a directory")

        files: list[str] = []

        if recursive:
            for current_root, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
                current = Path(current_root)
                filtered_dirs: list[str] = []
                for dirname in dirnames:
                    try:
                        _validate_name(dirname)
                        entry = current / dirname
                        if entry.is_symlink():
                            continue
                        entry.resolve().relative_to(root)
                        filtered_dirs.append(dirname)
                    except (ValueError, OSError):
                        continue
                dirnames[:] = filtered_dirs

                for filename in filenames:
                    try:
                        _validate_name(filename)
                        entry = current / filename
                        if entry.is_symlink():
                            continue
                        entry.resolve().relative_to(root)
                        files.append(str(entry.relative_to(root)))
                    except (ValueError, OSError):
                        continue
        else:
            for entry in sorted(target.iterdir(), key=lambda p: p.name):
                try:
                    _validate_name(entry.name)
                    if entry.is_symlink():
                        continue
                    entry.resolve().relative_to(root)
                    files.append(str(entry.relative_to(root)))
                except (ValueError, OSError):
                    continue

        files.sort()
        return {
            **scope,
            "path": str(Path(path) if path else Path(".")),
            "recursive": recursive,
            "files": files,
        }

    def read_file(
        self,
        project_id: str = "",
        workspace_id: str = "",
        path: str = "",
        start_line: int = 1,
        end_line: int = 0,
    ) -> dict[str, Any]:
        root, target, scope = self._resolve_scope_target(
            project_id=project_id,
            workspace_id=workspace_id,
            path=path,
            expect_exists=True,
        )
        if target.is_dir():
            raise ValueError("path must be a file")
        if target.is_symlink():
            raise ValueError("symlink files are not allowed")

        size = target.stat().st_size
        if size > MAX_READ_BYTES:
            raise ValueError(f"file too large ({size} bytes), limit is {MAX_READ_BYTES}")

        content = target.read_text(encoding="utf-8", errors="strict")
        lines = content.splitlines()
        if start_line < 1:
            raise ValueError("start_line must be >= 1")
        if end_line and end_line < start_line:
            raise ValueError("end_line must be >= start_line")

        start_index = start_line - 1
        end_index = len(lines) if end_line == 0 else min(end_line, len(lines))
        selected = lines[start_index:end_index]

        return {
            **scope,
            "path": str(target.relative_to(root)),
            "start_line": start_line,
            "end_line": end_index,
            "total_lines": len(lines),
            "content": "\n".join(selected),
        }

    def search_code(
        self,
        project_id: str = "",
        workspace_id: str = "",
        query: str = "",
        path: str = ".",
        case_sensitive: bool = False,
        max_results: int = 50,
    ) -> dict[str, Any]:
        if not query or not query.strip():
            raise ValueError("query is required")
        max_results = min(max(max_results, 1), MAX_SEARCH_RESULTS)
        root, target, scope = self._resolve_scope_target(
            project_id=project_id,
            workspace_id=workspace_id,
            path=path,
            expect_exists=True,
        )

        candidates: list[Path] = []
        if target.is_file():
            candidates = [target]
        else:
            for current_root, dirnames, filenames in os.walk(target, topdown=True, followlinks=False):
                current = Path(current_root)
                filtered_dirs: list[str] = []
                for dirname in dirnames:
                    try:
                        _validate_name(dirname)
                        d = current / dirname
                        if d.is_symlink():
                            continue
                        d.resolve().relative_to(root)
                        filtered_dirs.append(dirname)
                    except (ValueError, OSError):
                        continue
                dirnames[:] = filtered_dirs

                for filename in filenames:
                    try:
                        _validate_name(filename)
                        candidate = current / filename
                        if candidate.is_symlink():
                            continue
                        resolved = candidate.resolve()
                        resolved.relative_to(root)
                        if resolved.stat().st_size <= MAX_SEARCH_FILE_BYTES:
                            candidates.append(resolved)
                    except (ValueError, OSError):
                        continue

        matches: list[dict[str, Any]] = []
        needle = query if case_sensitive else query.lower()
        for candidate in sorted(candidates):
            try:
                text = candidate.read_text(encoding="utf-8", errors="strict")
            except (UnicodeDecodeError, OSError):
                continue
            for line_number, line in enumerate(text.splitlines(), start=1):
                haystack = line if case_sensitive else line.lower()
                if needle in haystack:
                    matches.append(
                        {
                            "path": str(candidate.relative_to(root)),
                            "line": line_number,
                            "preview": line[:240],
                        }
                    )
                    if len(matches) >= max_results:
                        return {
                            **scope,
                            "query": query,
                            "path": str(Path(path) if path else Path(".")),
                            "case_sensitive": case_sensitive,
                            "matches": matches,
                            "truncated": True,
                        }

        return {
            **scope,
            "query": query,
            "path": str(Path(path) if path else Path(".")),
            "case_sensitive": case_sensitive,
            "matches": matches,
            "truncated": False,
        }

    def create_workspace(
        self,
        project_id: str,
        task_id: str,
        base_ref: str = "",
        branch_name: str = "",
    ) -> dict[str, Any]:
        project = self._project(project_id)
        task_slug = _slug(task_id)
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        workspace_id = f"{project.project_id}-{task_slug}-{timestamp}"
        workspace_path = (self.workspaces_root / project.project_id / workspace_id).resolve()
        workspace_path.parent.mkdir(parents=True, exist_ok=True)

        if workspace_path.exists():
            raise ValueError("workspace already exists")

        release_base = self._release_base(project.project_id)
        requested_base_ref = base_ref.strip()
        use_trusted_published_base = requested_base_ref == ""
        source_ref = requested_base_ref or f"{release_base.remote_name}/{release_base.target_branch}"
        branch = branch_name.strip() or f"engineer/task-{task_slug}"
        trusted_remote_head_sha = ""
        try:
            self._run_git(
                ["clone", "--no-local", str(project.root), str(workspace_path)],
                cwd=self.workspaces_root,
                trusted=True,
                allow_file_transport=True,
            )
            if use_trusted_published_base:
                trusted_remote_head_sha = self._trusted_release_head(release_base)
                self._run_git(
                    [
                        "fetch",
                        "--no-tags",
                        str(release_base.remote_path),
                        f"refs/heads/{release_base.target_branch}",
                    ],
                    cwd=workspace_path,
                    trusted=True,
                    allow_file_transport=True,
                )
                self._run_git(
                    ["cat-file", "-e", f"{trusted_remote_head_sha}^{{commit}}"],
                    cwd=workspace_path,
                    trusted=True,
                )
                source_ref = trusted_remote_head_sha
            self._run_git(["checkout", source_ref], cwd=workspace_path, trusted=True)
            self._run_git(["checkout", "-b", branch], cwd=workspace_path, trusted=True)
        except ValueError:
            if workspace_path.exists():
                shutil.rmtree(workspace_path)
            raise

        head_sha = self._run_git(["rev-parse", "HEAD"], cwd=workspace_path, trusted=True)
        if use_trusted_published_base and head_sha != trusted_remote_head_sha:
            raise ValueError("workspace HEAD does not match trusted published revision")

        self._write_workspace_metadata(
            workspace_id,
            {
                "version": WORKSPACE_META_VERSION,
                "workspace_type": "development",
                "project_id": project.project_id,
                "source_repo_path": str(project.root),
                "target_branch": release_base.target_branch,
                "target_revision": head_sha,
                "task_branch": branch,
                "base_ref": source_ref,
                "base_commit_sha": head_sha,
                "base_source": "trusted_published" if use_trusted_published_base else "explicit_ref",
                "trusted_repository_id": release_base.repository_id,
                "trusted_release_remote_name": release_base.remote_name,
                "trusted_release_remote_path": str(release_base.remote_path),
                "trusted_release_branch": release_base.target_branch,
                "trusted_release_head_at_create": trusted_remote_head_sha if use_trusted_published_base else "",
                "created_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        return {
            "project_id": project.project_id,
            "workspace_id": workspace_id,
            "workspace_path": str(workspace_path),
            "base_ref": source_ref,
            "base_source": "trusted_published" if use_trusted_published_base else "explicit_ref",
            "branch": branch,
            "head_sha": head_sha,
        }

    def apply_patch(self, workspace_id: str, unified_diff: str) -> dict[str, Any]:
        if not unified_diff or not unified_diff.strip():
            raise ValueError("unified_diff is required")
        if len(unified_diff.encode("utf-8")) > MAX_PATCH_BYTES:
            raise ValueError(f"patch too large; limit is {MAX_PATCH_BYTES} bytes")

        workspace = self._resolve_workspace(workspace_id)
        targets = self._extract_patch_targets(unified_diff)

        validation_errors: list[str] = []
        accepted_targets: list[str] = []
        for target in targets:
            try:
                rel = self._validate_patch_target(target)
                self._resolve_in_workspace(workspace, str(rel), expect_exists=False)
                accepted_targets.append(str(rel))
            except ValueError as exc:
                validation_errors.append(f"{target}: {exc}")

        if validation_errors:
            return {
                "workspace_id": workspace_id,
                "applied": False,
                "actual_changes": False,
                "files_changed": [],
                "target_files": sorted(set(accepted_targets)),
                "changed_targets": [],
                "errors": validation_errors,
            }

        unique_targets = sorted(set(accepted_targets))

        def _target_state(rel_path: str) -> str:
            target_path = self._resolve_in_workspace(workspace, rel_path, expect_exists=False)
            if not target_path.exists():
                return "missing"
            if target_path.is_symlink():
                raise ValueError("symlink files are not allowed")
            if target_path.is_dir():
                return "dir"
            digest = hashlib.sha256(target_path.read_bytes()).hexdigest()
            return f"file:{digest}"

        before_states = {rel_path: _target_state(rel_path) for rel_path in unique_targets}

        temp_patch: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                prefix=".engineer-patch-",
                suffix=".diff",
                dir=workspace,
                delete=False,
            ) as handle:
                handle.write(unified_diff)
                temp_patch = Path(handle.name)

            patch_name = temp_patch.name
            self._run_git(["apply", "--check", "--recount", "--verbose", patch_name], cwd=workspace)
            self._run_git(["apply", "--recount", "--verbose", patch_name], cwd=workspace)
        except ValueError as exc:
            return {
                "workspace_id": workspace_id,
                "applied": False,
                "actual_changes": False,
                "files_changed": [],
                "target_files": unique_targets,
                "changed_targets": [],
                "errors": [f"patch validation/apply failed: {exc}"],
            }
        finally:
            if temp_patch and temp_patch.exists():
                temp_patch.unlink()

        changed_files = self._workspace_changed_files(workspace)
        after_states = {rel_path: _target_state(rel_path) for rel_path in unique_targets}
        changed_targets = sorted(
            rel_path
            for rel_path in unique_targets
            if before_states.get(rel_path) != after_states.get(rel_path)
        )

        if not changed_targets:
            return {
                "workspace_id": workspace_id,
                "applied": False,
                "actual_changes": False,
                "files_changed": changed_files,
                "target_files": unique_targets,
                "changed_targets": [],
                "errors": ["patch produced no file changes"],
            }

        return {
            "workspace_id": workspace_id,
            "applied": True,
            "actual_changes": True,
            "files_changed": changed_files,
            "target_files": unique_targets,
            "changed_targets": changed_targets,
            "errors": [],
        }

    def get_diff(self, workspace_id: str, max_bytes: int = MAX_DIFF_BYTES) -> dict[str, Any]:
        workspace = self._resolve_workspace(workspace_id)
        bounded_max_bytes = min(max(max_bytes, 8_192), MAX_DIFF_BYTES)

        status_entries, omitted_paths = self._workspace_status_entries(workspace)
        staged_diff = self._run_git(
            ["diff", "--cached", "--no-ext-diff", "--", "."],
            cwd=workspace,
            strip_output=False,
        )
        unstaged_diff = self._run_git(
            ["diff", "--no-ext-diff", "--", "."],
            cwd=workspace,
            strip_output=False,
        )

        sections: list[str] = []
        if staged_diff:
            sections.append("## staged changes\n" + staged_diff)
        if unstaged_diff:
            sections.append("## unstaged changes\n" + unstaged_diff)

        for entry in status_entries:
            if entry["code"] != "??":
                continue
            try:
                untracked_diff = self._render_untracked_diff(workspace, entry["path"])
                if untracked_diff:
                    sections.append("## untracked file\n" + untracked_diff)
            except ValueError:
                omitted_paths += 1
                continue

        combined_diff, truncated = self._limit_text(sections, bounded_max_bytes)
        changed_files = sorted({entry["path"] for entry in status_entries})

        return {
            "workspace_id": workspace_id,
            "status": status_entries,
            "changed_files": changed_files,
            "diff": combined_diff,
            "truncated": truncated,
            "omitted_paths": omitted_paths,
            "max_bytes": bounded_max_bytes,
        }

    def _call_runner_controller(self, payload: dict[str, Any]) -> dict[str, Any]:
        request_payload = dict(payload)
        request_payload["auth_token"] = self.runner_auth_token

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.runner_timeout_seconds)
            client.connect(str(self.runner_socket_path))
            client.sendall((json.dumps(request_payload) + "\n").encode("utf-8"))

            buffer = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in chunk:
                    break
                if len(buffer) > MAX_RUNNER_RESPONSE_BYTES:
                    raise ValueError("runner response exceeded size limit")

        if not buffer:
            raise ValueError("runner returned an empty response")

        response_text = bytes(buffer).split(b"\n", 1)[0].decode("utf-8")
        response = json.loads(response_text)
        if not isinstance(response, dict):
            raise ValueError("runner response was not an object")
        return response

    def _call_release_executor(self, action: str, payload: dict[str, Any]) -> dict[str, Any]:
        if not action:
            raise ValueError("release executor action is required")
        request_payload = {
            "auth_token": self.release_executor_auth_token,
            "action": action,
            "payload": payload,
        }

        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
            client.settimeout(self.release_executor_timeout_seconds)
            client.connect(str(self.release_executor_socket_path))
            client.sendall((json.dumps(request_payload) + "\n").encode("utf-8"))

            buffer = bytearray()
            while True:
                chunk = client.recv(4096)
                if not chunk:
                    break
                buffer.extend(chunk)
                if b"\n" in chunk:
                    break
                if len(buffer) > MAX_RELEASE_EXECUTOR_RESPONSE_BYTES:
                    raise ValueError("release executor response exceeded size limit")

        if not buffer:
            raise ValueError("release executor returned an empty response")

        response_text = bytes(buffer).split(b"\n", 1)[0].decode("utf-8")
        response = json.loads(response_text)
        if not isinstance(response, dict):
            raise ValueError("release executor response was not an object")
        return response

    def run_checks(self, workspace_id: str, check_id: str) -> dict[str, Any]:
        if check_id not in APPROVED_CHECK_IDS:
            raise ValueError(f"check_id '{check_id}' is not approved")

        self._resolve_workspace(workspace_id)
        response = self._call_runner_controller(
            {
                "action": "check",
                "workspace_id": workspace_id,
                "check_id": check_id,
            }
        )
        if response.get("error"):
            raise ValueError(str(response["error"]))
        if "ok" not in response:
            raise ValueError("runner response missing 'ok' field")
        return response

    def render_artifact(self, workspace_id: str, render_profile: str, script_path: str) -> dict[str, Any]:
        if render_profile not in APPROVED_RENDER_PROFILE_IDS:
            raise ValueError(f"render_profile '{render_profile}' is not approved")
        workspace = self._resolve_workspace(workspace_id)
        relative_script = _safe_relative(script_path)
        self._resolve_in_workspace(workspace, str(relative_script), expect_exists=True)

        response = self._call_runner_controller(
            {
                "action": "render",
                "workspace_id": workspace_id,
                "render_profile": render_profile,
                "script_path": str(relative_script),
            }
        )
        if response.get("error"):
            raise ValueError(str(response["error"]))
        if "ok" not in response:
            raise ValueError("runner response missing 'ok' field")
        return response

    def resolve_artifact(self, artifact_id: str, artifact_filename: str = "") -> dict[str, Any]:
        if not artifact_id or not re.fullmatch(r"[A-Za-z0-9._-]+", artifact_id):
            raise ValueError("invalid artifact_id")
        if artifact_filename and not isinstance(artifact_filename, str):
            raise ValueError("artifact_filename must be a string")
        if artifact_filename:
            _safe_relative(artifact_filename)

        response = self._call_runner_controller(
            {
                "action": "stage_artifact",
                "artifact_id": artifact_id,
                "artifact_filename": artifact_filename,
            }
        )
        if response.get("error"):
            raise ValueError(str(response["error"]))
        if "ok" not in response:
            raise ValueError("runner response missing 'ok' field")
        return response

    def commit_changes(self, workspace_id: str, commit_message: str) -> dict[str, Any]:
        cleaned_message = (commit_message or "").strip()
        if not cleaned_message:
            raise ValueError("commit_message is required")
        if len(cleaned_message) > MAX_COMMIT_MESSAGE_CHARS:
            raise ValueError(f"commit_message exceeds {MAX_COMMIT_MESSAGE_CHARS} characters")

        workspace = self._resolve_workspace(workspace_id)
        branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace)
        if branch == "HEAD":
            raise ValueError("workspace is in detached HEAD state")
        if not re.fullmatch(TASK_BRANCH_PATTERN, branch):
            raise ValueError("workspace branch must match engineer/task-*")

        status_entries, omitted_paths = self._workspace_status_entries(workspace)
        if omitted_paths > 0:
            return {
                "workspace_id": workspace_id,
                "committed": False,
                "nothing_to_commit": False,
                "branch": branch,
                "commit_sha": None,
                "files_committed": [],
                "errors": [
                    "workspace contains forbidden or out-of-bound changed paths; commit rejected",
                ],
            }

        changed_entries = [entry for entry in status_entries if entry["code"].strip()]
        if not changed_entries:
            return {
                "workspace_id": workspace_id,
                "committed": False,
                "nothing_to_commit": True,
                "branch": branch,
                "commit_sha": None,
                "files_committed": [],
                "errors": [],
            }

        validation_errors: list[str] = []
        stage_paths: list[str] = []
        for entry in changed_entries:
            raw_path = entry["path"]
            try:
                rel = self._validate_patch_target(raw_path)
                self._resolve_in_workspace(workspace, str(rel), expect_exists=False)
                stage_paths.append(str(rel))
            except ValueError as exc:
                validation_errors.append(f"{raw_path}: {exc}")

        if validation_errors:
            return {
                "workspace_id": workspace_id,
                "committed": False,
                "nothing_to_commit": False,
                "branch": branch,
                "commit_sha": None,
                "files_committed": [],
                "errors": validation_errors,
            }

        unique_stage_paths = sorted(set(stage_paths))
        self._run_git(["add", "--all", "--", *unique_stage_paths], cwd=workspace)

        commit_env = {
            "GIT_AUTHOR_NAME": "Engineer MCP",
            "GIT_AUTHOR_EMAIL": "engineer-mcp@local",
            "GIT_COMMITTER_NAME": "Engineer MCP",
            "GIT_COMMITTER_EMAIL": "engineer-mcp@local",
        }
        try:
            self._run_git(
                ["commit", "--no-verify", "--message", cleaned_message],
                cwd=workspace,
                env=commit_env,
            )
        except ValueError as exc:
            detail = str(exc)
            if "nothing to commit" in detail.lower():
                return {
                    "workspace_id": workspace_id,
                    "committed": False,
                    "nothing_to_commit": True,
                    "branch": branch,
                    "commit_sha": None,
                    "files_committed": [],
                    "errors": [],
                }
            raise

        commit_sha = self._run_git(["rev-parse", "HEAD"], cwd=workspace)
        files_text = self._run_git(
            ["show", "--pretty=format:", "--name-only", "HEAD"],
            cwd=workspace,
            strip_output=False,
        )
        files_committed = sorted({line.strip() for line in files_text.splitlines() if line.strip()})
        metadata = self._read_workspace_metadata(workspace_id, required=False)
        if metadata:
            metadata["last_commit_sha"] = commit_sha
            metadata["last_commit_at"] = datetime.now(timezone.utc).isoformat()
            self._write_workspace_metadata(workspace_id, metadata)

        return {
            "workspace_id": workspace_id,
            "committed": True,
            "nothing_to_commit": False,
            "branch": branch,
            "commit_sha": commit_sha,
            "files_committed": files_committed,
            "errors": [],
        }

    def _workspace_project_id(self, workspace: Path) -> str:
        try:
            rel = workspace.resolve().relative_to(self.workspaces_root)
        except ValueError as exc:
            raise ValueError("workspace escapes managed storage") from exc
        if len(rel.parts) < 2:
            raise ValueError("workspace path is malformed")
        project_id = rel.parts[0]
        if project_id not in self.projects:
            raise ValueError("workspace project is not allowlisted")
        return project_id

    def merge_to_integration(self, workspace_id: str) -> dict[str, Any]:
        workspace = self._resolve_workspace(workspace_id)
        project_id = self._workspace_project_id(workspace)
        project = self._project(project_id)

        status_entries, omitted_paths = self._workspace_status_entries(workspace)
        changed_entries = [entry for entry in status_entries if entry["code"].strip()]
        if omitted_paths > 0 or changed_entries:
            raise ValueError("workspace has uncommitted changes")

        task_branch = self._run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=workspace)
        if task_branch == "HEAD":
            raise ValueError("workspace is in detached HEAD state")
        if not re.fullmatch(TASK_BRANCH_PATTERN, task_branch):
            raise ValueError("workspace branch must match engineer/task-*")
        task_commit_sha = self._run_git(["rev-parse", "HEAD"], cwd=workspace)

        metadata = self._read_workspace_metadata(workspace_id, required=True)
        if metadata.get("workspace_type") != "development":
            raise ValueError("workspace is not a development workspace")
        release_base = self._release_base(project_id)

        target_branch = str(metadata.get("target_branch", "")).strip()
        target_revision = str(metadata.get("target_revision", "")).strip()
        if not target_branch or not target_revision:
            raise ValueError("workspace metadata is missing target branch/revision")
        if target_branch != release_base.target_branch:
            raise ValueError("workspace target branch does not match trusted release policy")
        if not re.fullmatch(SHA1_PATTERN, target_revision):
            raise ValueError("workspace target revision is not a valid commit SHA")

        self._run_git(["cat-file", "-e", f"{target_revision}^{{commit}}"], cwd=workspace, trusted=True)
        target_head_sha = self._trusted_release_head(release_base)
        ancestor_check = subprocess.run(
            [
                "git",
                *TRUSTED_GIT_ARGS,
                "--git-dir",
                str(release_base.remote_path),
                "merge-base",
                "--is-ancestor",
                target_revision,
                target_head_sha,
            ],
            cwd=str(self.workspaces_root),
            check=False,
            capture_output=True,
            text=True,
            env={**os.environ.copy(), **TRUSTED_GIT_ENV},
        )
        if ancestor_check.returncode not in {0, 1}:
            detail = (ancestor_check.stderr or ancestor_check.stdout or "git merge-base failed").strip()
            if ancestor_check.returncode == 128 and "Not a valid commit name" in detail:
                raise ValueError("workspace target revision is not in trusted release history")
            raise ValueError(detail)
        if ancestor_check.returncode == 1:
            raise ValueError("target branch no longer contains recorded target revision")
        release_history_advanced = target_head_sha != target_revision

        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        integration_slug = _slug(workspace_id)
        integration_workspace_id = f"{project_id}-integration-{integration_slug}-{timestamp}"
        integration_path = (self.workspaces_root / project_id / integration_workspace_id).resolve()
        integration_path.parent.mkdir(parents=True, exist_ok=True)
        if integration_path.exists():
            raise ValueError("integration workspace already exists")

        integration_branch = f"engineer/integration-{integration_slug}-{timestamp.lower()}"
        self._run_git(
            ["clone", "--no-local", str(project.root), str(integration_path)],
            cwd=self.workspaces_root,
            trusted=True,
            allow_file_transport=True,
        )
        self._run_git(
            [
                "fetch",
                "--no-tags",
                str(release_base.remote_path),
                f"refs/heads/{release_base.target_branch}",
            ],
            cwd=integration_path,
            trusted=True,
            allow_file_transport=True,
        )
        self._run_git(
            ["cat-file", "-e", f"{target_head_sha}^{{commit}}"],
            cwd=integration_path,
            trusted=True,
        )
        self._run_git(["checkout", "-B", integration_branch, target_head_sha], cwd=integration_path, trusted=True)
        self._run_git(
            ["fetch", "--no-tags", str(workspace), task_branch],
            cwd=integration_path,
            trusted=True,
            allow_file_transport=True,
        )

        merge_conflicts: list[str] = []
        merge_error = ""
        merged = False
        merged_commit_sha: str | None = None
        try:
            merge_env = {
                "GIT_AUTHOR_NAME": "Engineer MCP",
                "GIT_AUTHOR_EMAIL": "engineer-mcp@local",
                "GIT_COMMITTER_NAME": "Engineer MCP",
                "GIT_COMMITTER_EMAIL": "engineer-mcp@local",
            }
            self._run_git(
                ["merge", "--no-ff", "--no-edit", "--no-verify", "FETCH_HEAD"],
                cwd=integration_path,
                env=merge_env,
                trusted=True,
            )
            merged = True
            merged_commit_sha = self._run_git(["rev-parse", "HEAD"], cwd=integration_path, trusted=True)
        except ValueError as exc:
            merge_error = str(exc)
            conflicts_text = self._run_git(
                ["diff", "--name-only", "--diff-filter=U"],
                cwd=integration_path,
                strip_output=False,
                trusted=True,
            )
            merge_conflicts = sorted({line.strip() for line in conflicts_text.splitlines() if line.strip()})
            try:
                self._run_git(
                    ["merge", "--abort"],
                    cwd=integration_path,
                    allowed_exit_codes={0, 1, 128},
                    trusted=True,
                )
            except ValueError:
                pass

        integration_metadata = {
            "version": WORKSPACE_META_VERSION,
            "workspace_type": "integration",
            "project_id": project_id,
            "source_repo_path": str(project.root),
            "source_workspace_id": workspace_id,
            "target_branch": target_branch,
            "target_revision": target_revision,
            "target_head_at_merge": target_head_sha,
            "task_branch": task_branch,
            "task_commit_sha": task_commit_sha,
            "integration_branch": integration_branch,
            "trusted_repository_id": release_base.repository_id,
            "trusted_release_remote_name": release_base.remote_name,
            "trusted_release_remote_path": str(release_base.remote_path),
            "trusted_release_branch": release_base.target_branch,
            "release_history_advanced": release_history_advanced,
            "merged": merged,
            "integration_commit_sha": merged_commit_sha,
            "merge_conflicts": merge_conflicts,
            "merge_error": merge_error,
            "test_runs": [],
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write_workspace_metadata(integration_workspace_id, integration_metadata)

        return {
            "workspace_id": workspace_id,
            "integration_workspace_id": integration_workspace_id,
            "integration_workspace_path": str(integration_path),
            "integration_branch": integration_branch,
            "target_branch": target_branch,
            "target_head_sha": target_head_sha,
            "release_history_advanced": release_history_advanced,
            "merged": merged,
            "merged_commit_sha": merged_commit_sha,
            "merge_conflicts": merge_conflicts,
            "error": merge_error if not merged else "",
        }

    def test_merged_code(self, integration_workspace_id: str, check_id: str) -> dict[str, Any]:
        if check_id not in APPROVED_CHECK_IDS:
            raise ValueError(f"check_id '{check_id}' is not approved")

        workspace = self._resolve_workspace(integration_workspace_id)
        metadata = self._read_workspace_metadata(integration_workspace_id, required=True)
        if metadata.get("workspace_type") != "integration":
            raise ValueError("workspace is not an integration workspace")
        if not metadata.get("merged"):
            raise ValueError("integration workspace has no successful merge")

        expected_commit = str(metadata.get("integration_commit_sha", "")).strip()
        if not expected_commit:
            raise ValueError("integration metadata is missing merged commit")
        current_commit = self._run_git(["rev-parse", "HEAD"], cwd=workspace)
        if current_commit != expected_commit:
            raise ValueError("integration workspace HEAD no longer matches merged commit")

        response = self._call_runner_controller(
            {
                "action": "check",
                "workspace_id": integration_workspace_id,
                "check_id": check_id,
            }
        )
        if response.get("error"):
            raise ValueError(str(response["error"]))
        if "ok" not in response:
            raise ValueError("runner response missing 'ok' field")

        test_runs = metadata.get("test_runs")
        if not isinstance(test_runs, list):
            test_runs = []
        test_runs.append(
            {
                "checked_at": datetime.now(timezone.utc).isoformat(),
                "check_id": check_id,
                "commit_sha": current_commit,
                "ok": bool(response.get("ok")),
                "exit_code": response.get("exit_code"),
                "timed_out": bool(response.get("timed_out")),
            }
        )
        metadata["test_runs"] = test_runs
        metadata["last_tested_commit_sha"] = current_commit
        metadata["last_tested_at"] = datetime.now(timezone.utc).isoformat()
        self._write_workspace_metadata(integration_workspace_id, metadata)

        enriched = dict(response)
        enriched["integration_workspace_id"] = integration_workspace_id
        enriched["integration_commit_sha"] = current_commit
        return enriched

    @staticmethod
    def _infer_affected_services(project_id: str, changed_files: list[str]) -> list[str]:
        services: set[str] = set()
        for path in changed_files:
            if path.startswith("apps/engineer_code_mcp/"):
                services.add("engineer-code-mcp")
            elif path.startswith("apps/engineer_code_runner/"):
                services.add("engineer-code-runner")
            elif path.startswith("infra/openclaw/"):
                services.add("openclaw")
            elif path.startswith("apps/video_pipeline/"):
                services.add("videodb-mcp")
            elif path.startswith(("src/", "tests/")) and project_id == "engineer-sandbox":
                services.add("engineer-sandbox")
            else:
                top = path.split("/", 1)[0]
                if top:
                    services.add(top)
        return sorted(services)

    def prepare_release(self, integration_workspace_id: str) -> dict[str, Any]:
        workspace = self._resolve_workspace(integration_workspace_id)
        metadata = self._read_workspace_metadata(integration_workspace_id, required=True)
        if metadata.get("workspace_type") != "integration":
            raise ValueError("workspace is not an integration workspace")
        if not metadata.get("merged"):
            raise ValueError("integration workspace merge did not succeed")

        integration_commit_sha = str(metadata.get("integration_commit_sha", "")).strip()
        if not integration_commit_sha:
            raise ValueError("integration metadata missing integration commit")

        current_head = self._run_git(["rev-parse", "HEAD"], cwd=workspace)
        if current_head != integration_commit_sha:
            raise ValueError("integration workspace HEAD differs from merged commit")

        test_runs = metadata.get("test_runs")
        if not isinstance(test_runs, list):
            test_runs = []
        commit_runs = [run for run in test_runs if isinstance(run, dict) and run.get("commit_sha") == current_head]
        if not commit_runs:
            raise ValueError("no post-merge tests recorded for this integration commit")
        failed_runs = [run for run in commit_runs if not bool(run.get("ok"))]
        if failed_runs:
            raise ValueError("post-merge tests failed for this integration commit")

        files_text = self._run_git(
            ["diff", "--name-only", f"{integration_commit_sha}^1", integration_commit_sha],
            cwd=workspace,
            strip_output=False,
        )
        changed_files = sorted({line.strip() for line in files_text.splitlines() if line.strip()})
        name_status_text = self._run_git(
            ["diff", "--name-status", f"{integration_commit_sha}^1", integration_commit_sha],
            cwd=workspace,
            strip_output=False,
        )
        status_rows: list[dict[str, str]] = []
        for line in name_status_text.splitlines():
            if not line.strip():
                continue
            parts = line.split("\t", 1)
            if len(parts) != 2:
                continue
            status_rows.append({"status": parts[0], "path": parts[1]})

        stat_text = self._run_git(
            ["show", "--stat", "--pretty=format:", integration_commit_sha],
            cwd=workspace,
            strip_output=False,
        )
        diff_summary, summary_truncated = self._limit_text([stat_text], MAX_RELEASE_REPORT_BYTES)

        project_id = str(metadata.get("project_id", "")).strip() or self._workspace_project_id(workspace)
        target_branch = str(metadata.get("target_branch", "")).strip()
        integration_branch = str(metadata.get("integration_branch", "")).strip()
        task_branch = str(metadata.get("task_branch", "")).strip()
        source_workspace_id = str(metadata.get("source_workspace_id", "")).strip()
        original_repo = str(metadata.get("source_repo_path", "")).strip()

        report = {
            "release_status": "READY FOR APPROVAL",
            "original_repository": original_repo,
            "project_id": project_id,
            "task_workspace_id": source_workspace_id,
            "task_branch": task_branch,
            "integration_workspace_id": integration_workspace_id,
            "integration_branch": integration_branch,
            "integration_commit_sha": integration_commit_sha,
            "target_branch": target_branch,
            "files_changed": status_rows,
            "changed_file_count": len(changed_files),
            "diff_summary": diff_summary,
            "diff_summary_truncated": summary_truncated,
            "test_results": commit_runs,
            "proposed_push_destination": f"origin {target_branch}".strip(),
            "proposed_affected_services": self._infer_affected_services(project_id, changed_files),
            "risks_and_rollback": [
                "Validate release content before any push; this step does not push or deploy.",
                "If release is rejected, discard the integration workspace and keep development workspace isolated.",
                "If approved and later reverted, reset target branch to prior commit or apply a revert commit.",
            ],
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        metadata["release_report"] = report
        metadata["released_ready_for_approval_at"] = datetime.now(timezone.utc).isoformat()
        self._write_workspace_metadata(integration_workspace_id, metadata)
        return report

    def execute_release(self, integration_workspace_id: str, approval_id: str) -> dict[str, Any]:
        if not approval_id or not re.fullmatch(APPROVAL_ID_PATTERN, approval_id):
            raise ValueError("invalid approval_id")

        workspace = self._resolve_workspace(integration_workspace_id)
        metadata = self._read_workspace_metadata(integration_workspace_id, required=True)
        if metadata.get("workspace_type") != "integration":
            raise ValueError("workspace is not an integration workspace")
        if not metadata.get("merged"):
            raise ValueError("integration workspace merge did not succeed")

        integration_commit_sha = str(metadata.get("integration_commit_sha", "")).strip()
        if not integration_commit_sha:
            raise ValueError("integration metadata missing integration commit")

        current_head = self._run_git(["rev-parse", "HEAD"], cwd=workspace)
        if current_head != integration_commit_sha:
            raise ValueError("integration workspace HEAD differs from merged commit")

        response = self._call_release_executor(
            action="execute_release",
            payload={
                "integration_workspace_id": integration_workspace_id,
                "approval_id": approval_id,
            },
        )
        if response.get("error") and "release_status" not in response:
            return {
                "ok": False,
                "release_status": "PUSH_FAILED",
                "deployment_status": "NOT_ATTEMPTED",
                "push_status": "FAILED",
                "approval_id": approval_id,
                "integration_workspace_id": integration_workspace_id,
                "integration_commit_sha": integration_commit_sha,
                "error": str(response["error"]),
            }
        if "ok" not in response:
            raise ValueError("release executor response missing 'ok' field")

        enriched = dict(response)
        enriched["integration_workspace_id"] = integration_workspace_id
        enriched["integration_commit_sha"] = integration_commit_sha
        return enriched


TOOLS = [
    Tool(
        name="list_projects",
        description="List approved repositories from the explicit allowlist",
        inputSchema={"type": "object", "properties": {}, "required": []},
    ),
    Tool(
        name="list_files",
        description="List files inside an approved repository or managed workspace path",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "recursive": {"type": "boolean", "default": False},
            },
            "required": [],
        },
    ),
    Tool(
        name="read_file",
        description="Read text from a file in an approved repository or managed workspace",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "path": {"type": "string"},
                "start_line": {"type": "integer", "default": 1},
                "end_line": {"type": "integer", "default": 0},
            },
            "required": ["path"],
        },
    ),
    Tool(
        name="search_code",
        description="Search text content in approved repository or managed workspace files",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "workspace_id": {"type": "string"},
                "query": {"type": "string"},
                "path": {"type": "string", "default": "."},
                "case_sensitive": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "default": 50},
            },
            "required": ["query"],
        },
    ),
    Tool(
        name="create_workspace",
        description="Create an isolated git clone + branch in managed workspace storage; defaults to latest trusted published release branch head",
        inputSchema={
            "type": "object",
            "properties": {
                "project_id": {"type": "string"},
                "task_id": {"type": "string"},
                "base_ref": {"type": "string", "default": ""},
                "branch_name": {"type": "string", "default": ""},
            },
            "required": ["project_id", "task_id"],
        },
    ),
    Tool(
        name="apply_patch",
        description="Validate and apply a unified diff within an isolated workspace",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "unified_diff": {"type": "string"},
            },
            "required": ["workspace_id", "unified_diff"],
        },
    ),
    Tool(
        name="get_diff",
        description="Get git status and diff for an isolated workspace, including untracked files",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "max_bytes": {"type": "integer", "default": MAX_DIFF_BYTES},
            },
            "required": ["workspace_id"],
        },
    ),
    Tool(
        name="run_checks",
        description="Run one approved predefined check in an isolated workspace via trusted runner",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "check_id": {
                    "type": "string",
                    "enum": sorted(APPROVED_CHECK_IDS),
                },
            },
            "required": ["workspace_id", "check_id"],
        },
    ),
    Tool(
        name="render_artifact",
        description="Render an approved artifact script in an isolated workspace via trusted runner",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "render_profile": {
                    "type": "string",
                    "enum": sorted(APPROVED_RENDER_PROFILE_IDS),
                },
                "script_path": {"type": "string"},
            },
            "required": ["workspace_id", "render_profile", "script_path"],
        },
    ),
    Tool(
        name="resolve_artifact",
        description="Stage an approved rendered artifact for gateway media delivery and return MEDIA reference",
        inputSchema={
            "type": "object",
            "properties": {
                "artifact_id": {"type": "string"},
                "artifact_filename": {"type": "string", "default": ""},
            },
            "required": ["artifact_id"],
        },
    ),
    Tool(
        name="commit_changes",
        description="Commit validated workspace changes on engineer/task-* branches without hooks",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
                "commit_message": {"type": "string"},
            },
            "required": ["workspace_id", "commit_message"],
        },
    ),
    Tool(
        name="merge_to_integration",
        description="Merge a committed task workspace branch into an isolated integration workspace rebased on current trusted release branch head",
        inputSchema={
            "type": "object",
            "properties": {
                "workspace_id": {"type": "string"},
            },
            "required": ["workspace_id"],
        },
    ),
    Tool(
        name="test_merged_code",
        description="Run one approved predefined check against a merged integration workspace",
        inputSchema={
            "type": "object",
            "properties": {
                "integration_workspace_id": {"type": "string"},
                "check_id": {
                    "type": "string",
                    "enum": sorted(APPROVED_CHECK_IDS),
                },
            },
            "required": ["integration_workspace_id", "check_id"],
        },
    ),
    Tool(
        name="prepare_release",
        description="Produce a release report from a tested integration workspace without pushing/deploying",
        inputSchema={
            "type": "object",
            "properties": {
                "integration_workspace_id": {"type": "string"},
            },
            "required": ["integration_workspace_id"],
        },
    ),
    Tool(
        name="execute_release",
        description="Execute an approval-gated sandbox release for an integration workspace (trusted push/deploy/health/rollback + verified host access URLs)",
        inputSchema={
            "type": "object",
            "properties": {
                "integration_workspace_id": {"type": "string"},
                "approval_id": {"type": "string"},
            },
            "required": ["integration_workspace_id", "approval_id"],
        },
    ),
]


def setup_server(server: Server, service: EngineerCodeService) -> None:
    class EmptyParams(BaseModel):
        pass

    async def handle_list_tools(_: Any, __: EmptyParams) -> ListToolsResult:
        return ListToolsResult(tools=TOOLS)

    async def handle_call_tool(_: Any, params: CallToolRequestParams) -> CallToolResult:
        args = params.arguments or {}
        try:
            if params.name == "list_projects":
                return _json_result(service.list_projects())
            if params.name == "list_files":
                return _json_result(
                    service.list_files(
                        project_id=args.get("project_id", ""),
                        workspace_id=args.get("workspace_id", ""),
                        path=args.get("path", "."),
                        recursive=bool(args.get("recursive", False)),
                    )
                )
            if params.name == "read_file":
                return _json_result(
                    service.read_file(
                        project_id=args.get("project_id", ""),
                        workspace_id=args.get("workspace_id", ""),
                        path=args.get("path", ""),
                        start_line=int(args.get("start_line", 1)),
                        end_line=int(args.get("end_line", 0)),
                    )
                )
            if params.name == "search_code":
                return _json_result(
                    service.search_code(
                        project_id=args.get("project_id", ""),
                        workspace_id=args.get("workspace_id", ""),
                        query=args.get("query", ""),
                        path=args.get("path", "."),
                        case_sensitive=bool(args.get("case_sensitive", False)),
                        max_results=int(args.get("max_results", 50)),
                    )
                )
            if params.name == "create_workspace":
                return _json_result(
                    service.create_workspace(
                        project_id=args.get("project_id", ""),
                        task_id=args.get("task_id", ""),
                        base_ref=args.get("base_ref", ""),
                        branch_name=args.get("branch_name", ""),
                    )
                )
            if params.name == "apply_patch":
                return _json_result(
                    service.apply_patch(
                        workspace_id=args.get("workspace_id", ""),
                        unified_diff=args.get("unified_diff", ""),
                    )
                )
            if params.name == "get_diff":
                return _json_result(
                    service.get_diff(
                        workspace_id=args.get("workspace_id", ""),
                        max_bytes=int(args.get("max_bytes", MAX_DIFF_BYTES)),
                    )
                )
            if params.name == "run_checks":
                allowed_keys = {"workspace_id", "check_id"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported run_checks fields: {sorted(unknown)}")
                return _json_result(
                    service.run_checks(
                        workspace_id=args.get("workspace_id", ""),
                        check_id=args.get("check_id", ""),
                    )
                )
            if params.name == "render_artifact":
                allowed_keys = {"workspace_id", "render_profile", "script_path"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported render_artifact fields: {sorted(unknown)}")
                return _json_result(
                    service.render_artifact(
                        workspace_id=args.get("workspace_id", ""),
                        render_profile=args.get("render_profile", ""),
                        script_path=args.get("script_path", ""),
                    )
                )
            if params.name == "resolve_artifact":
                allowed_keys = {"artifact_id", "artifact_filename"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported resolve_artifact fields: {sorted(unknown)}")
                return _json_result(
                    service.resolve_artifact(
                        artifact_id=args.get("artifact_id", ""),
                        artifact_filename=args.get("artifact_filename", ""),
                    )
                )
            if params.name == "commit_changes":
                allowed_keys = {"workspace_id", "commit_message"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported commit_changes fields: {sorted(unknown)}")
                return _json_result(
                    service.commit_changes(
                        workspace_id=args.get("workspace_id", ""),
                        commit_message=args.get("commit_message", ""),
                    )
                )
            if params.name == "merge_to_integration":
                allowed_keys = {"workspace_id"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported merge_to_integration fields: {sorted(unknown)}")
                return _json_result(
                    service.merge_to_integration(
                        workspace_id=args.get("workspace_id", ""),
                    )
                )
            if params.name == "test_merged_code":
                allowed_keys = {"integration_workspace_id", "check_id"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported test_merged_code fields: {sorted(unknown)}")
                return _json_result(
                    service.test_merged_code(
                        integration_workspace_id=args.get("integration_workspace_id", ""),
                        check_id=args.get("check_id", ""),
                    )
                )
            if params.name == "prepare_release":
                allowed_keys = {"integration_workspace_id"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported prepare_release fields: {sorted(unknown)}")
                return _json_result(
                    service.prepare_release(
                        integration_workspace_id=args.get("integration_workspace_id", ""),
                    )
                )
            if params.name == "execute_release":
                allowed_keys = {"integration_workspace_id", "approval_id"}
                unknown = set(args.keys()) - allowed_keys
                if unknown:
                    raise ValueError(f"unsupported execute_release fields: {sorted(unknown)}")
                return _json_result(
                    service.execute_release(
                        integration_workspace_id=args.get("integration_workspace_id", ""),
                        approval_id=args.get("approval_id", ""),
                    )
                )
            return _json_result({"error": f"unknown tool: {params.name}"}, is_error=True)
        except ValueError as exc:
            return _json_result({"error": str(exc)}, is_error=True)
        except Exception as exc:  # pragma: no cover
            return _json_result({"error": f"internal error: {exc}"}, is_error=True)

    server.add_request_handler("tools/list", EmptyParams, handle_list_tools)
    server.add_request_handler("tools/call", CallToolRequestParams, handle_call_tool)
