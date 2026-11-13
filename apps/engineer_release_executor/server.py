#!/usr/bin/env python3

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import socket
import sqlite3
import struct
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

MAX_SOCKET_REQUEST_BYTES = 48_000
MAX_APPROVAL_LIST_LIMIT = 500

APPROVAL_ID_PATTERN = r"[A-Za-z0-9._-]{8,128}"
WORKSPACE_ID_PATTERN = r"[A-Za-z0-9._-]{8,200}"
REPO_ID_PATTERN = r"[A-Za-z0-9._-]{1,120}"
SHA1_PATTERN = r"[0-9a-f]{40}"
REMOTE_PATTERN = r"[A-Za-z0-9._/-]{1,120}"
BRANCH_PATTERN = r"[A-Za-z0-9._/-]{1,200}"
PROFILE_PATTERN = r"[A-Za-z0-9._-]{1,120}"
SERVICE_PATTERN = r"[A-Za-z0-9._-]{1,120}"
CHECK_ID_PATTERN = r"[A-Za-z0-9._-]{1,120}"
CONTROLLER_PATTERN = r"[A-Za-z0-9._:-]{1,120}"
RUN_ID_PATTERN = r"[A-Za-z0-9._:-]{1,200}"
CONFIG_VERSION_PATTERN = r"[A-Za-z0-9._-]{1,120}"
REMOTE_PATH_PATTERN = r"/[A-Za-z0-9._/\-]{1,400}"
PROJECT_NAME_PATTERN = r"[A-Za-z0-9._-]{1,80}"
COMPOSE_SERVICE_PATTERN = r"[A-Za-z0-9._-]{1,80}"
RELATIVE_PATH_PATTERN = r"[A-Za-z0-9._/\-]{1,240}"
DISCORD_SNOWFLAKE_PATTERN = r"[0-9]{17,22}"
DISCORD_INTENT_ID_PATTERN = r"intent-[A-Za-z0-9]{20}"

APPROVAL_STATES = ("approved", "consumed", "revoked", "expired")
RELEASE_STATES = (
    "locked",
    "verifying",
    "pushing",
    "deploying",
    "health_checking",
    "completed",
    "failed",
    "rolled_back",
    "rollback_failed",
    "rejected",
)
EVIDENCE_STATES = ("passed", "failed", "error")
EVIDENCE_KINDS = ("actual_runner", "fixture")

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
TRUSTED_REMOTE_ROOT = Path("/home/mdv/mainbrain/repos").resolve()
TRUSTED_DEPLOYMENT_CONFIG_ROOT = Path("/home/mdv/mainbrain/infra/engineer_sandbox_deploy").resolve()

APPROVAL_RECORD_SCHEMA = {
    "approval_id": {"type": "string", "pattern": APPROVAL_ID_PATTERN},
    "repository_id": {"type": "string", "pattern": REPO_ID_PATTERN},
    "integration_workspace_id": {"type": "string", "pattern": WORKSPACE_ID_PATTERN},
    "integration_commit_sha": {"type": "string", "pattern": SHA1_PATTERN},
    "remote_name": {"type": "string", "pattern": REMOTE_PATTERN},
    "target_branch": {"type": "string", "pattern": BRANCH_PATTERN},
    "expected_remote_head_sha": {"type": "string", "pattern": SHA1_PATTERN},
    "deployment_profile_id": {"type": "string", "pattern": PROFILE_PATTERN},
    "allowed_services": {
        "type": "array",
        "items_pattern": SERVICE_PATTERN,
        "min_items": 1,
        "max_items": 32,
        "unique": True,
    },
    "expires_at": {"type": "rfc3339_utc"},
    "state": {"type": "enum", "values": list(APPROVAL_STATES)},
    "created_at": {"type": "rfc3339_utc"},
    "created_by": {"type": "string", "pattern": r"[A-Za-z0-9._-]{1,120}"},
    "consumed_at": {"type": "rfc3339_utc_or_null"},
    "consumed_execution_id": {"type": "string_or_null", "pattern": r"[A-Za-z0-9._-]{8,128}"},
}

REQUEST_SCHEMAS = {
    "ping": {"required": set(), "optional": set()},
    "describe_contract": {"required": set(), "optional": set()},
    "validate_execute_release_request": {
        "required": {
            "approval_id",
            "repository_id",
            "integration_workspace_id",
            "integration_commit_sha",
            "remote_name",
            "target_branch",
            "expected_remote_head_sha",
            "deployment_profile_id",
            "allowed_services",
        },
        "optional": set(),
    },
    "execute_release": {
        "required": {
            "approval_id",
            "integration_workspace_id",
        },
        "optional": set(),
    },
    "authorize_release_preview": {
        "required": {
            "approval_id",
            "integration_workspace_id",
        },
        "optional": set(),
    },
    "authorize_release": {
        "required": {
            "approval_id",
            "repository_id",
            "integration_workspace_id",
            "integration_commit_sha",
            "remote_name",
            "target_branch",
            "expected_remote_head_sha",
            "deployment_profile_id",
            "allowed_services",
        },
        "optional": set(),
    },
    "record_test_evidence": {
        "required": {
            "repository_id",
            "integration_workspace_id",
            "integration_commit_sha",
            "check_id",
            "check_config_version",
            "execution_id",
            "source_controller",
            "source_run_id",
            "result_state",
            "exit_code",
            "timed_out",
            "observed_at",
            "evidence_payload",
        },
        "optional": set(),
    },
    "discord_prepare_approval": {
        "required": {
            "interaction_id",
            "discord_user_id",
            "discord_guild_id",
            "discord_channel_id",
            "integration_workspace_id",
        },
        "optional": set(),
    },
    "discord_confirm_approval": {
        "required": {
            "interaction_id",
            "discord_user_id",
            "discord_guild_id",
            "discord_channel_id",
            "intent_id",
        },
        "optional": set(),
    },
}


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _parse_utc(value: str) -> datetime:
    if not isinstance(value, str):
        raise ValueError("timestamp must be a string")
    normalized = value
    if value.endswith("Z"):
        normalized = f"{value[:-1]}+00:00"
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ValueError("timestamp must be RFC3339") from exc
    if parsed.tzinfo is None:
        raise ValueError("timestamp must include timezone")
    return parsed.astimezone(timezone.utc)


def _normalize_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _validate_pattern(value: str, pattern: str, field_name: str) -> None:
    if not isinstance(value, str) or not re.fullmatch(pattern, value):
        raise ValueError(f"invalid {field_name}")


def _validate_array_of_strings(
    values: Any,
    *,
    field_name: str,
    item_pattern: str,
    min_items: int,
    max_items: int,
    unique: bool,
) -> list[str]:
    if not isinstance(values, list):
        raise ValueError(f"{field_name} must be an array")
    if len(values) < min_items or len(values) > max_items:
        raise ValueError(f"{field_name} item count out of bounds")
    normalized: list[str] = []
    for value in values:
        if not isinstance(value, str):
            raise ValueError(f"{field_name} items must be strings")
        _validate_pattern(value, item_pattern, f"{field_name} item")
        normalized.append(value)
    if unique and len(set(normalized)) != len(normalized):
        raise ValueError(f"{field_name} must contain unique entries")
    return sorted(set(normalized))


def _parse_id_set(raw: str, *, field_name: str) -> frozenset[str]:
    values = [item.strip() for item in raw.split(",") if item.strip()]
    if not values:
        raise SystemExit(f"{field_name} must contain at least one Discord ID")
    for value in values:
        _validate_pattern(value, DISCORD_SNOWFLAKE_PATTERN, field_name)
    return frozenset(values)


def _release_lock_key(repository_id: str, remote_name: str, target_branch: str) -> str:
    return f"{repository_id}::{remote_name}::{target_branch}"


def _new_approval_id() -> str:
    return f"approval-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


def _new_execution_id() -> str:
    return f"release-exec-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:10]}"


def _new_discord_intent_id() -> str:
    return f"intent-{uuid.uuid4().hex[:20]}"


def _trusted_git_env() -> dict[str, str]:
    env = dict(os.environ)
    env.update(TRUSTED_GIT_ENV)
    return env


def _validate_release_details_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_pattern(payload["repository_id"], REPO_ID_PATTERN, "repository_id")
    _validate_pattern(payload["integration_workspace_id"], WORKSPACE_ID_PATTERN, "integration_workspace_id")
    _validate_pattern(payload["integration_commit_sha"], SHA1_PATTERN, "integration_commit_sha")
    _validate_pattern(payload["remote_name"], REMOTE_PATTERN, "remote_name")
    _validate_pattern(payload["target_branch"], BRANCH_PATTERN, "target_branch")
    _validate_pattern(payload["expected_remote_head_sha"], SHA1_PATTERN, "expected_remote_head_sha")
    _validate_pattern(payload["deployment_profile_id"], PROFILE_PATTERN, "deployment_profile_id")
    allowed_services = _validate_array_of_strings(
        payload["allowed_services"],
        field_name="allowed_services",
        item_pattern=SERVICE_PATTERN,
        min_items=1,
        max_items=32,
        unique=True,
    )
    return {
        "repository_id": payload["repository_id"],
        "integration_workspace_id": payload["integration_workspace_id"],
        "integration_commit_sha": payload["integration_commit_sha"],
        "remote_name": payload["remote_name"],
        "target_branch": payload["target_branch"],
        "expected_remote_head_sha": payload["expected_remote_head_sha"],
        "deployment_profile_id": payload["deployment_profile_id"],
        "allowed_services": allowed_services,
    }


def _validate_authorize_release_payload(payload: dict[str, Any]) -> dict[str, Any]:
    _validate_pattern(payload["approval_id"], APPROVAL_ID_PATTERN, "approval_id")
    details = _validate_release_details_payload(payload)
    details["approval_id"] = payload["approval_id"]
    return details


def _validate_authorize_release_preview_payload(payload: dict[str, Any]) -> dict[str, str]:
    _validate_pattern(payload["approval_id"], APPROVAL_ID_PATTERN, "approval_id")
    _validate_pattern(payload["integration_workspace_id"], WORKSPACE_ID_PATTERN, "integration_workspace_id")
    return {
        "approval_id": payload["approval_id"],
        "integration_workspace_id": payload["integration_workspace_id"],
    }


def _validate_discord_prepare_payload(payload: dict[str, Any]) -> dict[str, str]:
    _validate_pattern(payload["interaction_id"], DISCORD_SNOWFLAKE_PATTERN, "interaction_id")
    _validate_pattern(payload["discord_user_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_user_id")
    _validate_pattern(payload["discord_guild_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_guild_id")
    _validate_pattern(payload["discord_channel_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_channel_id")
    _validate_pattern(payload["integration_workspace_id"], WORKSPACE_ID_PATTERN, "integration_workspace_id")
    return {
        "interaction_id": payload["interaction_id"],
        "discord_user_id": payload["discord_user_id"],
        "discord_guild_id": payload["discord_guild_id"],
        "discord_channel_id": payload["discord_channel_id"],
        "integration_workspace_id": payload["integration_workspace_id"],
    }


def _validate_discord_confirm_payload(payload: dict[str, Any]) -> dict[str, str]:
    _validate_pattern(payload["interaction_id"], DISCORD_SNOWFLAKE_PATTERN, "interaction_id")
    _validate_pattern(payload["discord_user_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_user_id")
    _validate_pattern(payload["discord_guild_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_guild_id")
    _validate_pattern(payload["discord_channel_id"], DISCORD_SNOWFLAKE_PATTERN, "discord_channel_id")
    _validate_pattern(payload["intent_id"], DISCORD_INTENT_ID_PATTERN, "intent_id")
    return {
        "interaction_id": payload["interaction_id"],
        "discord_user_id": payload["discord_user_id"],
        "discord_guild_id": payload["discord_guild_id"],
        "discord_channel_id": payload["discord_channel_id"],
        "intent_id": payload["intent_id"],
    }


@dataclass(frozen=True)
class DeploymentProfilePolicy:
    profile_id: str
    allowed_services: set[str]
    required_check_profiles: list["CheckProfilePolicy"]
    deployment_target: "DeploymentTargetPolicy"


@dataclass(frozen=True)
class CheckProfilePolicy:
    check_id: str
    check_config_version: str


@dataclass(frozen=True)
class DeploymentTargetPolicy:
    service_id: str
    compose_file: str
    compose_project: str
    compose_service: str
    source_subpath: str
    application_base_url: str
    container_port: int
    healthcheck_url: str
    version_url: str
    health_timeout_seconds: int
    health_interval_seconds: float
    deploy_failure_marker: str
    rollback_failure_marker: str


@dataclass(frozen=True)
class RepositoryPolicy:
    repository_id: str
    managed_project_id: str
    allowed_remotes: set[str]
    remote_paths: dict[str, str]
    allowed_target_branches: set[str]
    deployment_profiles: dict[str, DeploymentProfilePolicy]


class TrustedPolicy:
    def __init__(self, repositories: dict[str, RepositoryPolicy], source_file: Path):
        self._repositories = repositories
        self.source_file = source_file

    @classmethod
    def load(cls, path: Path) -> "TrustedPolicy":
        payload = json.loads(path.read_text(encoding="utf-8"))
        version = payload.get("version")
        if version != 1:
            raise ValueError("trusted policy version must be 1")
        repositories = payload.get("repositories")
        if not isinstance(repositories, list) or not repositories:
            raise ValueError("trusted policy must define at least one repository")

        parsed: dict[str, RepositoryPolicy] = {}
        for item in repositories:
            repository_id = item.get("id")
            managed_project_id = item.get("managed_project_id")
            if not isinstance(repository_id, str):
                raise ValueError("policy repository id must be a string")
            if not isinstance(managed_project_id, str):
                raise ValueError(f"managed_project_id is required for repository '{repository_id}'")
            _validate_pattern(repository_id, REPO_ID_PATTERN, "policy repository id")
            _validate_pattern(managed_project_id, REPO_ID_PATTERN, "policy managed_project_id")

            allowed_remotes = _validate_array_of_strings(
                item.get("allowed_remotes", []),
                field_name=f"{repository_id}.allowed_remotes",
                item_pattern=REMOTE_PATTERN,
                min_items=1,
                max_items=16,
                unique=True,
            )
            allowed_target_branches = _validate_array_of_strings(
                item.get("allowed_target_branches", []),
                field_name=f"{repository_id}.allowed_target_branches",
                item_pattern=BRANCH_PATTERN,
                min_items=1,
                max_items=64,
                unique=True,
            )
            remote_paths_raw = item.get("remote_paths")
            if not isinstance(remote_paths_raw, dict):
                raise ValueError(f"repository '{repository_id}' must declare remote_paths")
            parsed_remote_paths: dict[str, str] = {}
            for remote_name in allowed_remotes:
                remote_path_raw = remote_paths_raw.get(remote_name)
                if not isinstance(remote_path_raw, str):
                    raise ValueError(
                        f"repository '{repository_id}' remote_paths must include a path for remote '{remote_name}'"
                    )
                _validate_pattern(remote_path_raw, REMOTE_PATH_PATTERN, f"{repository_id}.remote_paths.{remote_name}")
                remote_path = Path(remote_path_raw).resolve()
                try:
                    remote_path.relative_to(TRUSTED_REMOTE_ROOT)
                except ValueError as exc:
                    raise ValueError(
                        f"repository '{repository_id}' remote '{remote_name}' path escapes trusted remote root"
                    ) from exc
                parsed_remote_paths[remote_name] = str(remote_path)
            extra_remote_names = sorted(set(remote_paths_raw.keys()) - set(allowed_remotes))
            if extra_remote_names:
                raise ValueError(
                    f"repository '{repository_id}' remote_paths contains unknown remote names: {extra_remote_names}"
                )

            profiles = item.get("deployment_profiles")
            if not isinstance(profiles, list) or not profiles:
                raise ValueError(f"repository '{repository_id}' must declare deployment_profiles")
            parsed_profiles: dict[str, DeploymentProfilePolicy] = {}
            for profile in profiles:
                profile_id = profile.get("id")
                if not isinstance(profile_id, str):
                    raise ValueError(f"repository '{repository_id}' has invalid deployment profile id")
                _validate_pattern(profile_id, PROFILE_PATTERN, "deployment profile id")
                allowed_services = _validate_array_of_strings(
                    profile.get("allowed_services", []),
                    field_name=f"{repository_id}.{profile_id}.allowed_services",
                    item_pattern=SERVICE_PATTERN,
                    min_items=1,
                    max_items=128,
                    unique=True,
                )
                raw_required_checks = profile.get("required_check_profiles", [])
                if not isinstance(raw_required_checks, list):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' required_check_profiles must be an array"
                    )
                parsed_required_checks: list[CheckProfilePolicy] = []
                for check_profile in raw_required_checks:
                    if not isinstance(check_profile, dict):
                        raise ValueError(
                            f"repository '{repository_id}' profile '{profile_id}' contains invalid required check profile"
                        )
                    check_id = check_profile.get("check_id")
                    check_config_version = check_profile.get("check_config_version")
                    if not isinstance(check_id, str) or not isinstance(check_config_version, str):
                        raise ValueError(
                            f"repository '{repository_id}' profile '{profile_id}' required checks need check_id and check_config_version"
                        )
                    _validate_pattern(check_id, CHECK_ID_PATTERN, "required check_id")
                    _validate_pattern(check_config_version, CONFIG_VERSION_PATTERN, "required check_config_version")
                    parsed_required_checks.append(
                        CheckProfilePolicy(
                            check_id=check_id,
                            check_config_version=check_config_version,
                        )
                    )
                deployment_target_raw = profile.get("deployment_target")
                if not isinstance(deployment_target_raw, dict):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' must define deployment_target"
                    )
                service_id = deployment_target_raw.get("service_id")
                compose_file_raw = deployment_target_raw.get("compose_file")
                compose_project = deployment_target_raw.get("compose_project")
                compose_service = deployment_target_raw.get("compose_service")
                source_subpath = deployment_target_raw.get("source_subpath")
                application_base_url = deployment_target_raw.get("application_base_url")
                container_port = deployment_target_raw.get("container_port")
                healthcheck_url = deployment_target_raw.get("healthcheck_url")
                version_url = deployment_target_raw.get("version_url")
                deploy_failure_marker = deployment_target_raw.get("deploy_failure_marker", "")
                rollback_failure_marker = deployment_target_raw.get("rollback_failure_marker", "")
                timeout_value = deployment_target_raw.get("health_timeout_seconds", 30)
                interval_value = deployment_target_raw.get("health_interval_seconds", 1.0)
                if not isinstance(service_id, str):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.service_id is required"
                    )
                _validate_pattern(service_id, SERVICE_PATTERN, "deployment_target.service_id")
                if service_id not in allowed_services:
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.service_id must be in allowed_services"
                    )
                if not isinstance(compose_file_raw, str):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.compose_file is required"
                    )
                _validate_pattern(compose_file_raw, REMOTE_PATH_PATTERN, "deployment_target.compose_file")
                compose_file = Path(compose_file_raw).resolve()
                try:
                    compose_file.relative_to(TRUSTED_DEPLOYMENT_CONFIG_ROOT)
                except ValueError as exc:
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.compose_file escapes trusted deployment config root"
                    ) from exc
                if not compose_file.exists():
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.compose_file does not exist"
                    )
                if not isinstance(compose_project, str):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.compose_project is required"
                    )
                _validate_pattern(compose_project, PROJECT_NAME_PATTERN, "deployment_target.compose_project")
                if not isinstance(compose_service, str):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.compose_service is required"
                    )
                _validate_pattern(compose_service, COMPOSE_SERVICE_PATTERN, "deployment_target.compose_service")
                if not isinstance(source_subpath, str):
                    raise ValueError(
                        f"repository '{repository_id}' profile '{profile_id}' deployment_target.source_subpath is required"
                    )
                _validate_pattern(source_subpath, RELATIVE_PATH_PATTERN, "deployment_target.source_subpath")
                source_path = Path(source_subpath)
                if source_path.is_absolute() or ".." in source_path.parts:
                    raise ValueError("deployment_target.source_subpath must be a safe relative path")
                if not isinstance(application_base_url, str) or not application_base_url.startswith("http://127.0.0.1:"):
                    raise ValueError("deployment_target.application_base_url must be localhost-only")
                parsed_base = urllib.parse.urlparse(application_base_url)
                if parsed_base.scheme != "http" or parsed_base.hostname != "127.0.0.1" or parsed_base.query or parsed_base.fragment:
                    raise ValueError("deployment_target.application_base_url must be a plain localhost URL")
                if parsed_base.path not in {"", "/"}:
                    raise ValueError("deployment_target.application_base_url must not contain a path")
                if not isinstance(container_port, int) or container_port <= 0 or container_port > 65535:
                    raise ValueError("deployment_target.container_port must be an integer between 1 and 65535")
                if not isinstance(healthcheck_url, str) or not healthcheck_url.startswith("http://127.0.0.1:"):
                    raise ValueError("deployment_target.healthcheck_url must be localhost-only")
                if not isinstance(version_url, str) or not version_url.startswith("http://127.0.0.1:"):
                    raise ValueError("deployment_target.version_url must be localhost-only")
                parsed_health = urllib.parse.urlparse(healthcheck_url)
                parsed_version = urllib.parse.urlparse(version_url)
                if (
                    parsed_health.scheme != "http"
                    or parsed_health.hostname != "127.0.0.1"
                    or parsed_version.scheme != "http"
                    or parsed_version.hostname != "127.0.0.1"
                ):
                    raise ValueError("deployment_target health/version URLs must be localhost HTTP URLs")
                if parsed_health.port != parsed_base.port or parsed_version.port != parsed_base.port:
                    raise ValueError("deployment_target URLs must share the application_base_url port")
                if not isinstance(timeout_value, int) or timeout_value < 5 or timeout_value > 180:
                    raise ValueError("deployment_target.health_timeout_seconds must be an integer between 5 and 180")
                if not isinstance(interval_value, (int, float)) or interval_value <= 0 or interval_value > 5:
                    raise ValueError("deployment_target.health_interval_seconds must be between 0 and 5 seconds")
                if not isinstance(deploy_failure_marker, str):
                    raise ValueError("deployment_target.deploy_failure_marker must be a string")
                if not isinstance(rollback_failure_marker, str):
                    raise ValueError("deployment_target.rollback_failure_marker must be a string")
                if deploy_failure_marker:
                    _validate_pattern(deploy_failure_marker, RELATIVE_PATH_PATTERN, "deploy_failure_marker")
                if rollback_failure_marker:
                    _validate_pattern(rollback_failure_marker, RELATIVE_PATH_PATTERN, "rollback_failure_marker")
                if deploy_failure_marker:
                    marker_path = Path(deploy_failure_marker)
                    if marker_path.is_absolute() or ".." in marker_path.parts:
                        raise ValueError("deployment_target.deploy_failure_marker must be relative and safe")
                if rollback_failure_marker:
                    marker_path = Path(rollback_failure_marker)
                    if marker_path.is_absolute() or ".." in marker_path.parts:
                        raise ValueError("deployment_target.rollback_failure_marker must be relative and safe")
                deployment_target = DeploymentTargetPolicy(
                    service_id=service_id,
                    compose_file=str(compose_file),
                    compose_project=compose_project,
                    compose_service=compose_service,
                    source_subpath=source_subpath,
                    application_base_url=application_base_url,
                    container_port=container_port,
                    healthcheck_url=healthcheck_url,
                    version_url=version_url,
                    health_timeout_seconds=timeout_value,
                    health_interval_seconds=float(interval_value),
                    deploy_failure_marker=deploy_failure_marker,
                    rollback_failure_marker=rollback_failure_marker,
                )
                parsed_profiles[profile_id] = DeploymentProfilePolicy(
                    profile_id=profile_id,
                    allowed_services=set(allowed_services),
                    required_check_profiles=parsed_required_checks,
                    deployment_target=deployment_target,
                )

            parsed[repository_id] = RepositoryPolicy(
                repository_id=repository_id,
                managed_project_id=managed_project_id,
                allowed_remotes=set(allowed_remotes),
                remote_paths=parsed_remote_paths,
                allowed_target_branches=set(allowed_target_branches),
                deployment_profiles=parsed_profiles,
            )
        return cls(parsed, source_file=path)

    def repository(self, repository_id: str) -> RepositoryPolicy:
        repo = self._repositories.get(repository_id)
        if repo is None:
            raise ValueError(f"repository '{repository_id}' is not allowed by trusted policy")
        return repo

    def repository_for_managed_project(self, managed_project_id: str) -> RepositoryPolicy:
        matches = [repo for repo in self._repositories.values() if repo.managed_project_id == managed_project_id]
        if not matches:
            raise ValueError(f"managed project '{managed_project_id}' is not mapped to a trusted repository")
        if len(matches) != 1:
            ids = sorted(repo.repository_id for repo in matches)
            raise ValueError(
                f"managed project '{managed_project_id}' maps to multiple repositories; explicit policy disambiguation is required: {ids}"
            )
        return matches[0]

    def resolve_release_scope(
        self,
        *,
        repository_id: str,
        remote_name: str,
        target_branch: str,
        deployment_profile_id: str,
        allowed_services: list[str],
    ) -> dict[str, Any]:
        repo = self.repository(repository_id)
        if remote_name not in repo.allowed_remotes:
            raise ValueError(f"remote '{remote_name}' is not allowed for repository '{repository_id}'")
        if target_branch not in repo.allowed_target_branches:
            raise ValueError(f"target branch '{target_branch}' is not allowed for repository '{repository_id}'")

        profile = repo.deployment_profiles.get(deployment_profile_id)
        if profile is None:
            raise ValueError(
                f"deployment profile '{deployment_profile_id}' is not allowed for repository '{repository_id}'"
            )
        unauthorized = sorted(set(allowed_services) - profile.allowed_services)
        if unauthorized:
            raise ValueError(
                f"services {unauthorized} are not allowed by deployment profile '{deployment_profile_id}'"
            )
        if profile.deployment_target.service_id not in allowed_services:
            raise ValueError(
                f"deployment target service '{profile.deployment_target.service_id}' is not present in approved allowed_services"
            )
        return {
            "repository_id": repository_id,
            "managed_project_id": repo.managed_project_id,
            "remote_name": remote_name,
            "remote_path": repo.remote_paths[remote_name],
            "target_branch": target_branch,
            "deployment_profile_id": deployment_profile_id,
            "allowed_services": sorted(set(allowed_services)),
            "deployment_target": {
                "service_id": profile.deployment_target.service_id,
                "compose_file": profile.deployment_target.compose_file,
                "compose_project": profile.deployment_target.compose_project,
                "compose_service": profile.deployment_target.compose_service,
                "source_subpath": profile.deployment_target.source_subpath,
                "application_base_url": profile.deployment_target.application_base_url,
                "container_port": profile.deployment_target.container_port,
                "healthcheck_url": profile.deployment_target.healthcheck_url,
                "version_url": profile.deployment_target.version_url,
                "health_timeout_seconds": profile.deployment_target.health_timeout_seconds,
                "health_interval_seconds": profile.deployment_target.health_interval_seconds,
                "deploy_failure_marker": profile.deployment_target.deploy_failure_marker,
                "rollback_failure_marker": profile.deployment_target.rollback_failure_marker,
            },
            "required_check_profiles": [
                {
                    "check_id": item.check_id,
                    "check_config_version": item.check_config_version,
                }
                for item in profile.required_check_profiles
            ],
        }


@dataclass(frozen=True)
class ExecutorConfig:
    socket_path: Path
    state_dir: Path
    state_db_path: Path
    policy_file: Path
    workspaces_root: Path
    workspace_metadata_root: Path
    auth_token: str
    evidence_auth_token: str
    discord_auth_token: str
    discord_allowed_user_ids: frozenset[str]
    discord_allowed_guild_ids: frozenset[str]
    discord_allowed_channel_ids: frozenset[str]
    discord_intent_ttl_minutes: int
    discord_approval_ttl_minutes: int
    allowed_peer_uid: int

    @classmethod
    def from_server_args(cls, args: argparse.Namespace) -> "ExecutorConfig":
        root = Path("/home/mdv/mainbrain")
        state_dir = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_STATE_DIR",
                str(Path.home() / ".local/state/mainbrain/engineer-release-executor"),
            )
        ).resolve()
        state_db_path = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_STATE_DB",
                str(state_dir / "state.db"),
            )
        ).resolve()
        policy_file = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_POLICY_FILE",
                str(root / "apps/engineer_release_executor/config/trusted_policy.json"),
            )
        ).resolve()
        workspaces_root = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_WORKSPACES_ROOT",
                str(root / "data/engineer-code-mcp/workspaces"),
            )
        ).resolve()
        workspace_metadata_root = Path(
            os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_WORKSPACE_META_ROOT",
                str(workspaces_root / "_engineer_meta"),
            )
        ).resolve()
        socket_path = Path(
            args.socket_path
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_SOCKET_PATH",
                str(root / "data/engineer-release-executor/release-executor.sock"),
            )
        ).resolve()
        auth_token = args.auth_token or os.getenv("ENGINEER_RELEASE_EXECUTOR_AUTH_TOKEN", "")
        if not auth_token:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_AUTH_TOKEN must be set or passed by --auth-token")
        evidence_auth_token = os.getenv("ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN", "")
        if not evidence_auth_token:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_EVIDENCE_AUTH_TOKEN must be set")
        discord_auth_token = os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN", "")
        if not discord_auth_token:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN must not be empty")
        discord_allowed_user_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_USER_IDS", "1568655444321243136"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_USER_IDS",
        )
        discord_allowed_guild_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_GUILD_IDS", "1568656073898987651"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_GUILD_IDS",
        )
        discord_allowed_channel_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_CHANNEL_IDS", "1570598910173646890"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_CHANNEL_IDS",
        )
        discord_intent_ttl_minutes = int(os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_INTENT_TTL_MINUTES", "15"))
        if discord_intent_ttl_minutes <= 0 or discord_intent_ttl_minutes > 240:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_DISCORD_INTENT_TTL_MINUTES must be between 1 and 240")
        discord_approval_ttl_minutes = int(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_APPROVAL_TTL_MINUTES", "60")
        )
        if discord_approval_ttl_minutes <= 0 or discord_approval_ttl_minutes > 4320:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_DISCORD_APPROVAL_TTL_MINUTES must be between 1 and 4320")
        return cls(
            socket_path=socket_path,
            state_dir=state_dir,
            state_db_path=state_db_path,
            policy_file=policy_file,
            workspaces_root=workspaces_root,
            workspace_metadata_root=workspace_metadata_root,
            auth_token=auth_token,
            evidence_auth_token=evidence_auth_token,
            discord_auth_token=discord_auth_token,
            discord_allowed_user_ids=discord_allowed_user_ids,
            discord_allowed_guild_ids=discord_allowed_guild_ids,
            discord_allowed_channel_ids=discord_allowed_channel_ids,
            discord_intent_ttl_minutes=discord_intent_ttl_minutes,
            discord_approval_ttl_minutes=discord_approval_ttl_minutes,
            allowed_peer_uid=args.allowed_peer_uid,
        )

    @classmethod
    def from_cli_args(cls, args: argparse.Namespace) -> "ExecutorConfig":
        root = Path("/home/mdv/mainbrain")
        state_dir = Path(
            getattr(args, "state_dir", None)
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_STATE_DIR",
                str(Path.home() / ".local/state/mainbrain/engineer-release-executor"),
            )
        ).resolve()
        state_db_path = Path(
            getattr(args, "state_db_path", None)
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_STATE_DB",
                str(state_dir / "state.db"),
            )
        ).resolve()
        policy_file = Path(
            getattr(args, "policy_file", None)
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_POLICY_FILE",
                str(root / "apps/engineer_release_executor/config/trusted_policy.json"),
            )
        ).resolve()
        workspaces_root = Path(
            getattr(args, "workspaces_root", None)
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_WORKSPACES_ROOT",
                str(root / "data/engineer-code-mcp/workspaces"),
            )
        ).resolve()
        workspace_metadata_root = Path(
            getattr(args, "workspace_meta_root", None)
            or os.getenv(
                "ENGINEER_RELEASE_EXECUTOR_WORKSPACE_META_ROOT",
                str(workspaces_root / "_engineer_meta"),
            )
        ).resolve()
        discord_allowed_user_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_USER_IDS", "1568655444321243136"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_USER_IDS",
        )
        discord_allowed_guild_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_GUILD_IDS", "1568656073898987651"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_GUILD_IDS",
        )
        discord_allowed_channel_ids = _parse_id_set(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_CHANNEL_IDS", "1570598910173646890"),
            field_name="ENGINEER_RELEASE_EXECUTOR_DISCORD_ALLOWED_CHANNEL_IDS",
        )
        discord_intent_ttl_minutes = int(os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_INTENT_TTL_MINUTES", "15"))
        if discord_intent_ttl_minutes <= 0 or discord_intent_ttl_minutes > 240:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_DISCORD_INTENT_TTL_MINUTES must be between 1 and 240")
        discord_approval_ttl_minutes = int(
            os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_APPROVAL_TTL_MINUTES", "60")
        )
        if discord_approval_ttl_minutes <= 0 or discord_approval_ttl_minutes > 4320:
            raise SystemExit("ENGINEER_RELEASE_EXECUTOR_DISCORD_APPROVAL_TTL_MINUTES must be between 1 and 4320")
        return cls(
            socket_path=Path("/tmp/engineer-release-executor-unused.sock"),
            state_dir=state_dir,
            state_db_path=state_db_path,
            policy_file=policy_file,
            workspaces_root=workspaces_root,
            workspace_metadata_root=workspace_metadata_root,
            auth_token="",
            evidence_auth_token="",
            discord_auth_token=os.getenv("ENGINEER_RELEASE_EXECUTOR_DISCORD_AUTH_TOKEN", ""),
            discord_allowed_user_ids=discord_allowed_user_ids,
            discord_allowed_guild_ids=discord_allowed_guild_ids,
            discord_allowed_channel_ids=discord_allowed_channel_ids,
            discord_intent_ttl_minutes=discord_intent_ttl_minutes,
            discord_approval_ttl_minutes=discord_approval_ttl_minutes,
            allowed_peer_uid=1000,
        )


class ReleaseStateStore:
    def __init__(self, config: ExecutorConfig):
        self._config = config
        self._config.state_dir.mkdir(parents=True, exist_ok=True)
        os.chmod(self._config.state_dir, 0o700)
        if not self._config.policy_file.exists():
            raise ValueError(f"trusted policy file does not exist: {self._config.policy_file}")
        self._policy = TrustedPolicy.load(self._config.policy_file)
        self._initialize_schema()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self._config.state_db_path, timeout=30)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    def _run_git(
        self,
        cwd: Path,
        args: list[str],
        *,
        allowed_exit_codes: set[int] | None = None,
        allow_file_transport: bool = False,
    ) -> str:
        exit_codes = allowed_exit_codes or {0}
        command = ["git", *TRUSTED_GIT_ARGS]
        if allow_file_transport:
            command.extend(["-c", "protocol.file.allow=always"])
        command.extend(args)
        proc = subprocess.run(
            command,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            check=False,
            env=_trusted_git_env(),
        )
        if proc.returncode not in exit_codes:
            detail = (proc.stderr or proc.stdout or "git command failed").strip()
            raise ValueError(detail)
        return (proc.stdout or "").strip()

    def _remote_ref(self, branch: str) -> str:
        return f"refs/heads/{branch}"

    def _read_remote_head(self, workspace: Path, remote_path: str, branch: str) -> str:
        remote_ref = self._remote_ref(branch)
        output = self._run_git(
            workspace,
            ["ls-remote", "--heads", "--refs", remote_path, remote_ref],
            allow_file_transport=True,
        )
        if not output:
            raise ValueError(f"remote branch '{branch}' does not exist on approved remote")
        line = output.splitlines()[0].strip()
        fields = line.split()
        if len(fields) < 1 or not re.fullmatch(SHA1_PATTERN, fields[0]):
            raise ValueError("failed to resolve remote HEAD")
        return fields[0]

    def _fetch_remote_branch_for_verification(self, workspace: Path, remote_path: str, branch: str) -> None:
        remote_ref = self._remote_ref(branch)
        verification_ref = f"refs/engineer-release/remote/{branch}"
        self._run_git(
            workspace,
            [
                "fetch",
                "--no-tags",
                "--no-recurse-submodules",
                remote_path,
                f"{remote_ref}:{verification_ref}",
            ],
            allow_file_transport=True,
        )

    def _is_ancestor(self, workspace: Path, ancestor_sha: str, descendant_sha: str) -> bool:
        proc = subprocess.run(
            ["git", *TRUSTED_GIT_ARGS, "merge-base", "--is-ancestor", ancestor_sha, descendant_sha],
            cwd=str(workspace),
            capture_output=True,
            text=True,
            check=False,
            env=_trusted_git_env(),
        )
        if proc.returncode == 0:
            return True
        if proc.returncode == 1:
            return False
        detail = (proc.stderr or proc.stdout or "git merge-base failed").strip()
        raise ValueError(detail)

    def _service_deployment_key(self, validated: dict[str, Any]) -> str:
        target = validated["deployment_target"]
        return f"{validated['repository_id']}::{validated['deployment_profile_id']}::{target['service_id']}"

    def _deployment_runtime_dir(self, validated: dict[str, Any]) -> Path:
        target = validated["deployment_target"]
        project = target["compose_project"]
        runtime_dir = (self._config.state_dir / "deployments" / project).resolve()
        runtime_dir.mkdir(parents=True, exist_ok=True)
        return runtime_dir

    def _snapshot_commit(self, workspace: Path, runtime_dir: Path, commit_sha: str) -> Path:
        snapshot_dir = (runtime_dir / "snapshots" / commit_sha).resolve()
        try:
            snapshot_dir.relative_to(runtime_dir)
        except ValueError as exc:
            raise ValueError("snapshot path escaped deployment runtime root") from exc
        if snapshot_dir.exists():
            return snapshot_dir
        snapshot_dir.mkdir(parents=True, exist_ok=True)
        archive_path = (runtime_dir / f"{commit_sha}.{uuid.uuid4().hex}.tar").resolve()
        self._run_git(
            workspace,
            ["archive", "--format=tar", commit_sha, "-o", str(archive_path)],
        )
        try:
            subprocess.run(
                ["tar", "-xf", str(archive_path), "-C", str(snapshot_dir)],
                check=True,
                capture_output=True,
                text=True,
            )
        except subprocess.CalledProcessError as exc:
            shutil.rmtree(snapshot_dir, ignore_errors=True)
            detail = (exc.stderr or exc.stdout or "failed to extract commit snapshot").strip()
            raise ValueError(detail) from exc
        finally:
            archive_path.unlink(missing_ok=True)
        return snapshot_dir

    def _run_compose(self, validated: dict[str, Any], env_file: Path, args: list[str]) -> str:
        target = validated["deployment_target"]
        compose_file = Path(target["compose_file"]).resolve()
        command = [
            "docker",
            "compose",
            "--project-name",
            target["compose_project"],
            "--file",
            str(compose_file),
            "--env-file",
            str(env_file),
            *args,
        ]
        proc = subprocess.run(command, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "docker compose command failed").strip()
            raise ValueError(detail)
        return (proc.stdout or "").strip()

    def _check_url_json(self, url: str, timeout: float) -> dict[str, Any]:
        try:
            with urllib.request.urlopen(url, timeout=timeout) as response:
                body = response.read().decode("utf-8")
        except urllib.error.URLError as exc:
            raise ValueError(f"request failed for {url}: {exc}") from exc
        try:
            payload = json.loads(body)
        except json.JSONDecodeError as exc:
            raise ValueError(f"response from {url} was not valid JSON") from exc
        if not isinstance(payload, dict):
            raise ValueError(f"response from {url} was not a JSON object")
        return payload

    def _verify_deployment_health(self, validated: dict[str, Any], expected_commit_sha: str) -> None:
        target = validated["deployment_target"]
        timeout_seconds = int(target["health_timeout_seconds"])
        interval_seconds = float(target["health_interval_seconds"])
        deadline = time.time() + timeout_seconds
        health_url = str(target["healthcheck_url"])
        version_url = str(target["version_url"])
        last_error = "health check not attempted"
        while time.time() < deadline:
            try:
                health_payload = self._check_url_json(health_url, timeout=2.0)
                if str(health_payload.get("status", "")).lower() != "ok":
                    raise ValueError("health endpoint did not return status=ok")
                version_payload = self._check_url_json(version_url, timeout=2.0)
                deployed_commit_sha = str(version_payload.get("commit_sha", "")).strip()
                if deployed_commit_sha != expected_commit_sha:
                    raise ValueError("version endpoint commit_sha mismatch")
                return
            except Exception as exc:
                last_error = str(exc)
                time.sleep(interval_seconds)
        raise ValueError(f"deployment health verification failed: {last_error}")

    def _marker_exists(self, snapshot_root: Path, marker_relative: str) -> bool:
        if not marker_relative:
            return False
        marker_path = (snapshot_root / marker_relative).resolve()
        try:
            marker_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError("deployment marker path escaped snapshot root") from exc
        return marker_path.exists()

    def _deploy_commit(self, validated: dict[str, Any], workspace: Path, commit_sha: str) -> Path:
        runtime_dir = self._deployment_runtime_dir(validated)
        snapshot_root = self._snapshot_commit(workspace, runtime_dir, commit_sha)
        source_subpath = str(validated["deployment_target"]["source_subpath"])
        source_path = (snapshot_root / source_subpath).resolve()
        try:
            source_path.relative_to(snapshot_root)
        except ValueError as exc:
            raise ValueError("deployment source path escaped snapshot root") from exc
        if not source_path.is_dir():
            raise ValueError("deployment source path is missing from approved commit snapshot")
        env_file = (runtime_dir / "runtime.env").resolve()
        env_file.write_text(
            (
                f"SOURCE_SNAPSHOT_PATH={source_path}\n"
                f"RELEASE_COMMIT_SHA={commit_sha}\n"
            ),
            encoding="utf-8",
        )
        self._run_compose(
            validated,
            env_file,
            [
                "up",
                "-d",
                "--force-recreate",
                "--remove-orphans",
                validated["deployment_target"]["compose_service"],
            ],
        )
        return snapshot_root

    def _get_deployment_state(self, conn: sqlite3.Connection, service_key: str) -> dict[str, Any]:
        row = conn.execute("SELECT * FROM service_deployments WHERE service_id = ?", (service_key,)).fetchone()
        if row is None:
            return {
                "service_id": service_key,
                "repository_id": "",
                "deployment_profile_id": "",
                "current_commit_sha": None,
                "previous_commit_sha": None,
                "last_execution_id": None,
                "last_stage": "",
                "reconcile_required": False,
            }
        return {
            "service_id": row["service_id"],
            "repository_id": row["repository_id"],
            "deployment_profile_id": row["deployment_profile_id"],
            "current_commit_sha": row["current_commit_sha"],
            "previous_commit_sha": row["previous_commit_sha"],
            "last_execution_id": row["last_execution_id"],
            "last_stage": row["last_stage"],
            "reconcile_required": bool(row["reconcile_required"]),
        }

    def _upsert_deployment_state(
        self,
        conn: sqlite3.Connection,
        *,
        service_id: str,
        repository_id: str,
        deployment_profile_id: str,
        current_commit_sha: str | None,
        previous_commit_sha: str | None,
        last_execution_id: str,
        last_stage: str,
        reconcile_required: bool,
    ) -> None:
        conn.execute(
            """
            INSERT INTO service_deployments (
                service_id,
                repository_id,
                deployment_profile_id,
                current_commit_sha,
                previous_commit_sha,
                last_execution_id,
                last_stage,
                reconcile_required,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(service_id) DO UPDATE SET
                repository_id = excluded.repository_id,
                deployment_profile_id = excluded.deployment_profile_id,
                current_commit_sha = excluded.current_commit_sha,
                previous_commit_sha = excluded.previous_commit_sha,
                last_execution_id = excluded.last_execution_id,
                last_stage = excluded.last_stage,
                reconcile_required = excluded.reconcile_required,
                updated_at = excluded.updated_at
            """,
            (
                service_id,
                repository_id,
                deployment_profile_id,
                current_commit_sha,
                previous_commit_sha,
                last_execution_id,
                last_stage,
                1 if reconcile_required else 0,
                _utc_now(),
            ),
        )

    def _assert_no_reconciliation_required(self, validated: dict[str, Any]) -> None:
        service_key = self._service_deployment_key(validated)
        with self._connect() as conn:
            state = self._get_deployment_state(conn, service_key)
        if state["reconcile_required"]:
            raise ValueError("deployment reconciliation is required before executing another release")

    def _ensure_column(self, conn: sqlite3.Connection, table: str, column: str, ddl: str) -> None:
        rows = conn.execute(f"PRAGMA table_info({table})").fetchall()
        known = {row["name"] for row in rows}
        if column in known:
            return
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}")

    def _initialize_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS approvals (
                    approval_id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    integration_workspace_id TEXT NOT NULL DEFAULT '',
                    integration_commit_sha TEXT NOT NULL,
                    remote_name TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    expected_remote_head_sha TEXT NOT NULL,
                    deployment_profile_id TEXT NOT NULL,
                    allowed_services_json TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('approved', 'consumed', 'revoked', 'expired')),
                    created_at TEXT NOT NULL,
                    created_by TEXT NOT NULL,
                    consumed_at TEXT,
                    consumed_execution_id TEXT
                );

                CREATE TABLE IF NOT EXISTS release_executions (
                    execution_id TEXT PRIMARY KEY,
                    approval_id TEXT NOT NULL UNIQUE REFERENCES approvals(approval_id) ON DELETE RESTRICT,
                    repository_id TEXT NOT NULL,
                    integration_workspace_id TEXT NOT NULL DEFAULT '',
                    integration_commit_sha TEXT NOT NULL,
                    remote_name TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    state TEXT NOT NULL CHECK (state IN ('locked', 'verifying', 'pushing', 'deploying', 'health_checking', 'completed', 'failed', 'rolled_back', 'rollback_failed', 'rejected')),
                    expected_remote_head_sha TEXT NOT NULL DEFAULT '',
                    previous_remote_head_sha TEXT,
                    resulting_remote_head_sha TEXT,
                    push_result TEXT NOT NULL DEFAULT 'not_started',
                    deployment_result TEXT NOT NULL DEFAULT 'not_started',
                    rollback_result TEXT NOT NULL DEFAULT 'not_needed',
                    deployed_commit_sha TEXT,
                    rolled_back_to_commit_sha TEXT,
                    created_at TEXT NOT NULL,
                    started_at TEXT,
                    completed_at TEXT,
                    failure_code TEXT,
                    failure_message TEXT
                );

                CREATE TABLE IF NOT EXISTS execution_locks (
                    lock_key TEXT PRIMARY KEY,
                    execution_id TEXT NOT NULL REFERENCES release_executions(execution_id) ON DELETE RESTRICT,
                    acquired_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS trusted_test_evidence (
                    evidence_id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    integration_workspace_id TEXT NOT NULL DEFAULT '',
                    integration_commit_sha TEXT NOT NULL,
                    check_id TEXT NOT NULL,
                    check_config_version TEXT NOT NULL DEFAULT '',
                    execution_id TEXT NOT NULL DEFAULT '',
                    exit_code INTEGER,
                    timed_out INTEGER NOT NULL DEFAULT 0,
                    source_controller TEXT NOT NULL,
                    source_run_id TEXT NOT NULL,
                    evidence_kind TEXT NOT NULL DEFAULT 'fixture',
                    result_state TEXT NOT NULL CHECK (result_state IN ('passed', 'failed', 'error')),
                    observed_at TEXT NOT NULL,
                    evidence_digest_sha256 TEXT NOT NULL,
                    evidence_payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(source_controller, source_run_id)
                );

                CREATE TABLE IF NOT EXISTS service_deployments (
                    service_id TEXT PRIMARY KEY,
                    repository_id TEXT NOT NULL,
                    deployment_profile_id TEXT NOT NULL,
                    current_commit_sha TEXT,
                    previous_commit_sha TEXT,
                    last_execution_id TEXT,
                    last_stage TEXT NOT NULL DEFAULT '',
                    reconcile_required INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS discord_approval_intents (
                    intent_id TEXT PRIMARY KEY,
                    request_interaction_id TEXT NOT NULL UNIQUE,
                    confirm_interaction_id TEXT UNIQUE,
                    state TEXT NOT NULL CHECK (state IN ('pending', 'confirmed', 'expired', 'revoked')),
                    discord_user_id TEXT NOT NULL,
                    discord_guild_id TEXT NOT NULL,
                    discord_channel_id TEXT NOT NULL,
                    approval_id TEXT,
                    repository_id TEXT NOT NULL,
                    integration_workspace_id TEXT NOT NULL,
                    integration_commit_sha TEXT NOT NULL,
                    remote_name TEXT NOT NULL,
                    target_branch TEXT NOT NULL,
                    expected_remote_head_sha TEXT NOT NULL,
                    deployment_profile_id TEXT NOT NULL,
                    allowed_services_json TEXT NOT NULL,
                    required_checks_json TEXT NOT NULL,
                    intent_expires_at TEXT NOT NULL,
                    approval_expires_at TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    confirmed_at TEXT,
                    FOREIGN KEY (approval_id) REFERENCES approvals(approval_id) ON DELETE RESTRICT
                );
                """
            )

            self._ensure_column(conn, "approvals", "integration_workspace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "release_executions", "integration_workspace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "release_executions", "expected_remote_head_sha", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "release_executions", "previous_remote_head_sha", "TEXT")
            self._ensure_column(conn, "release_executions", "resulting_remote_head_sha", "TEXT")
            self._ensure_column(conn, "release_executions", "push_result", "TEXT NOT NULL DEFAULT 'not_started'")
            self._ensure_column(conn, "release_executions", "deployment_result", "TEXT NOT NULL DEFAULT 'not_started'")
            self._ensure_column(conn, "release_executions", "rollback_result", "TEXT NOT NULL DEFAULT 'not_needed'")
            self._ensure_column(conn, "release_executions", "deployed_commit_sha", "TEXT")
            self._ensure_column(conn, "release_executions", "rolled_back_to_commit_sha", "TEXT")
            self._ensure_column(conn, "trusted_test_evidence", "integration_workspace_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "trusted_test_evidence", "check_config_version", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "trusted_test_evidence", "execution_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(conn, "trusted_test_evidence", "exit_code", "INTEGER")
            self._ensure_column(conn, "trusted_test_evidence", "timed_out", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "trusted_test_evidence", "evidence_kind", "TEXT NOT NULL DEFAULT 'fixture'")

    def _metadata_path(self, workspace_id: str) -> Path:
        return (self._config.workspace_metadata_root / f"{workspace_id}.json").resolve()

    def _workspace_path(self, managed_project_id: str, workspace_id: str) -> Path:
        path = (self._config.workspaces_root / managed_project_id / workspace_id).resolve()
        try:
            path.relative_to(self._config.workspaces_root)
        except ValueError as exc:
            raise ValueError("workspace path escapes managed storage") from exc
        return path

    def _get_integration_workspace_details(self, workspace_id: str) -> dict[str, Any]:
        _validate_pattern(workspace_id, WORKSPACE_ID_PATTERN, "integration_workspace_id")
        meta_path = self._metadata_path(workspace_id)
        if not meta_path.exists():
            raise ValueError(f"workspace metadata for '{workspace_id}' was not found")
        metadata = json.loads(meta_path.read_text(encoding="utf-8"))
        if metadata.get("workspace_type") != "integration":
            raise ValueError("workspace metadata does not represent an integration workspace")
        project_id = metadata.get("project_id")
        if not isinstance(project_id, str) or not project_id:
            raise ValueError("integration workspace metadata missing project_id")
        integration_commit_sha = metadata.get("integration_commit_sha")
        if not isinstance(integration_commit_sha, str) or not re.fullmatch(SHA1_PATTERN, integration_commit_sha):
            raise ValueError("integration workspace metadata missing valid integration_commit_sha")
        target_branch = metadata.get("target_branch")
        if not isinstance(target_branch, str) or not re.fullmatch(BRANCH_PATTERN, target_branch):
            raise ValueError("integration workspace metadata missing valid target_branch")
        target_head_at_merge = metadata.get("target_head_at_merge")
        if not isinstance(target_head_at_merge, str) or not re.fullmatch(SHA1_PATTERN, target_head_at_merge):
            raise ValueError("integration workspace metadata missing valid target_head_at_merge")
        workspace_path = self._workspace_path(project_id, workspace_id)
        if not workspace_path.exists() or workspace_path.is_symlink():
            raise ValueError("integration workspace path is missing or invalid")
        head_commit = self._run_git(workspace_path, ["rev-parse", "HEAD"])
        if not re.fullmatch(SHA1_PATTERN, head_commit):
            raise ValueError("integration workspace HEAD is not a valid commit SHA")
        if head_commit != integration_commit_sha:
            raise ValueError("integration workspace HEAD does not match metadata integration_commit_sha")
        return {
            "workspace_id": workspace_id,
            "project_id": project_id,
            "integration_commit_sha": integration_commit_sha,
            "head_commit_sha": head_commit,
            "target_branch": target_branch,
            "target_head_at_merge": target_head_at_merge,
            "workspace_path": str(workspace_path),
        }

    def _release_details_for_workspace(self, workspace_id: str) -> dict[str, Any]:
        workspace = self._get_integration_workspace_details(workspace_id)
        repository = self._policy.repository_for_managed_project(workspace["project_id"])
        remote_names = sorted(repository.allowed_remotes)
        if len(remote_names) != 1:
            raise ValueError(
                f"repository '{repository.repository_id}' must declare exactly one trusted remote for Discord approvals"
            )
        profile_ids = sorted(repository.deployment_profiles.keys())
        if len(profile_ids) != 1:
            raise ValueError(
                f"repository '{repository.repository_id}' must declare exactly one deployment profile for Discord approvals"
            )
        release_details = {
            "repository_id": repository.repository_id,
            "integration_workspace_id": workspace["workspace_id"],
            "integration_commit_sha": workspace["integration_commit_sha"],
            "remote_name": remote_names[0],
            "target_branch": workspace["target_branch"],
            "expected_remote_head_sha": workspace["target_head_at_merge"],
            "deployment_profile_id": profile_ids[0],
            "allowed_services": sorted(repository.deployment_profiles[profile_ids[0]].allowed_services),
        }
        return self.validate_release_details(release_details)

    def _required_check_statuses(
        self,
        conn: sqlite3.Connection,
        *,
        release_details: dict[str, Any],
    ) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        repository = self._policy.repository(release_details["repository_id"])
        profile = repository.deployment_profiles[release_details["deployment_profile_id"]]
        for check in profile.required_check_profiles:
            row = conn.execute(
                """
                SELECT evidence_id,
                       execution_id,
                       source_controller,
                       source_run_id,
                       result_state,
                       exit_code,
                       timed_out,
                       observed_at,
                       check_id,
                       check_config_version
                FROM trusted_test_evidence
                WHERE repository_id = ?
                  AND integration_workspace_id = ?
                  AND integration_commit_sha = ?
                  AND check_id = ?
                  AND check_config_version = ?
                  AND evidence_kind = 'actual_runner'
                ORDER BY observed_at DESC, created_at DESC
                LIMIT 1
                """,
                (
                    release_details["repository_id"],
                    release_details["integration_workspace_id"],
                    release_details["integration_commit_sha"],
                    check.check_id,
                    check.check_config_version,
                ),
            ).fetchone()
            if row is None:
                rows.append(
                    {
                        "check_id": check.check_id,
                        "check_config_version": check.check_config_version,
                        "result_state": "missing",
                        "passed": False,
                    }
                )
                continue
            rows.append(
                {
                    "check_id": row["check_id"],
                    "check_config_version": row["check_config_version"],
                    "result_state": row["result_state"],
                    "passed": row["result_state"] == "passed",
                    "evidence_id": row["evidence_id"],
                    "execution_id": row["execution_id"],
                    "source_controller": row["source_controller"],
                    "source_run_id": row["source_run_id"],
                    "exit_code": row["exit_code"],
                    "timed_out": bool(row["timed_out"]),
                    "observed_at": row["observed_at"],
                }
            )
        return rows

    def _assert_allowed_discord_actor(self, actor: dict[str, str]) -> None:
        if actor["discord_user_id"] not in self._config.discord_allowed_user_ids:
            raise ValueError("discord user is not authorized to approve releases")
        if actor["discord_guild_id"] not in self._config.discord_allowed_guild_ids:
            raise ValueError("discord guild is not authorized for release approvals")
        if actor["discord_channel_id"] not in self._config.discord_allowed_channel_ids:
            raise ValueError("discord channel is not authorized for release approvals")

    def _release_access_urls(self, release_details: dict[str, Any]) -> dict[str, Any]:
        target = release_details["deployment_target"]
        parsed = urllib.parse.urlparse(str(target["application_base_url"]))
        return {
            "application_url": str(target["application_base_url"]).rstrip("/"),
            "health_url": str(target["healthcheck_url"]),
            "version_url": str(target["version_url"]),
            "host": parsed.hostname or "",
            "host_port": parsed.port,
            "container_port": int(target["container_port"]),
        }

    def validate_release_details(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized = _validate_release_details_payload(payload)
        policy_scope = self._policy.resolve_release_scope(
            repository_id=normalized["repository_id"],
            remote_name=normalized["remote_name"],
            target_branch=normalized["target_branch"],
            deployment_profile_id=normalized["deployment_profile_id"],
            allowed_services=normalized["allowed_services"],
        )
        workspace = self._get_integration_workspace_details(normalized["integration_workspace_id"])
        if workspace["project_id"] != policy_scope["managed_project_id"]:
            raise ValueError("integration workspace project does not match trusted policy mapping")
        if workspace["integration_commit_sha"] != normalized["integration_commit_sha"]:
            raise ValueError("integration workspace commit does not match requested integration_commit_sha")
        deployment_service_id = policy_scope["deployment_target"]["service_id"]
        if policy_scope["allowed_services"] != [deployment_service_id]:
            raise ValueError("release request must authorize exactly the trusted deployment target service")
        return {
            "repository_id": normalized["repository_id"],
            "integration_workspace_id": normalized["integration_workspace_id"],
            "integration_commit_sha": normalized["integration_commit_sha"],
            "remote_name": normalized["remote_name"],
            "remote_path": policy_scope["remote_path"],
            "target_branch": normalized["target_branch"],
            "expected_remote_head_sha": normalized["expected_remote_head_sha"],
            "deployment_profile_id": normalized["deployment_profile_id"],
            "allowed_services": policy_scope["allowed_services"],
            "deployment_target": policy_scope["deployment_target"],
            "required_check_profiles": policy_scope["required_check_profiles"],
            "managed_project_id": policy_scope["managed_project_id"],
            "workspace_path": workspace["workspace_path"],
        }

    def _row_to_approval(self, row: sqlite3.Row) -> dict[str, Any]:
        return {
            "approval_id": row["approval_id"],
            "repository_id": row["repository_id"],
            "integration_workspace_id": row["integration_workspace_id"],
            "integration_commit_sha": row["integration_commit_sha"],
            "remote_name": row["remote_name"],
            "target_branch": row["target_branch"],
            "expected_remote_head_sha": row["expected_remote_head_sha"],
            "deployment_profile_id": row["deployment_profile_id"],
            "allowed_services": sorted(json.loads(row["allowed_services_json"])),
            "expires_at": row["expires_at"],
            "state": row["state"],
            "created_at": row["created_at"],
            "created_by": row["created_by"],
            "consumed_at": row["consumed_at"],
            "consumed_execution_id": row["consumed_execution_id"],
        }

    def _build_approval_row(
        self,
        *,
        approval_id: str,
        release_details: dict[str, Any],
        created_by: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        expires_utc = expires_at.astimezone(timezone.utc)
        if expires_utc <= now:
            raise ValueError("expires_at must be in the future")
        return {
            "approval_id": approval_id,
            "repository_id": release_details["repository_id"],
            "integration_workspace_id": release_details["integration_workspace_id"],
            "integration_commit_sha": release_details["integration_commit_sha"],
            "remote_name": release_details["remote_name"],
            "target_branch": release_details["target_branch"],
            "expected_remote_head_sha": release_details["expected_remote_head_sha"],
            "deployment_profile_id": release_details["deployment_profile_id"],
            "allowed_services_json": json.dumps(release_details["allowed_services"]),
            "expires_at": _normalize_utc(expires_utc),
            "state": "approved",
            "created_at": _normalize_utc(now),
            "created_by": created_by,
            "consumed_at": None,
            "consumed_execution_id": None,
        }

    def create_approval(
        self,
        *,
        approval_id: str | None,
        release_details: dict[str, Any],
        created_by: str,
        expires_at: datetime,
    ) -> dict[str, Any]:
        normalized = self.validate_release_details(release_details)
        resolved_approval_id = approval_id or _new_approval_id()
        _validate_pattern(resolved_approval_id, APPROVAL_ID_PATTERN, "approval_id")
        _validate_pattern(created_by, r"[A-Za-z0-9._-]{1,120}", "created_by")
        row = self._build_approval_row(
            approval_id=resolved_approval_id,
            release_details=normalized,
            created_by=created_by,
            expires_at=expires_at,
        )
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO approvals (
                        approval_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        remote_name,
                        target_branch,
                        expected_remote_head_sha,
                        deployment_profile_id,
                        allowed_services_json,
                        expires_at,
                        state,
                        created_at,
                        created_by,
                        consumed_at,
                        consumed_execution_id
                    ) VALUES (
                        :approval_id,
                        :repository_id,
                        :integration_workspace_id,
                        :integration_commit_sha,
                        :remote_name,
                        :target_branch,
                        :expected_remote_head_sha,
                        :deployment_profile_id,
                        :allowed_services_json,
                        :expires_at,
                        :state,
                        :created_at,
                        :created_by,
                        :consumed_at,
                        :consumed_execution_id
                    )
                    """,
                    row,
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError(f"approval_id '{resolved_approval_id}' already exists") from exc
        return self.get_approval(resolved_approval_id, include_missing_error=False)

    def list_approvals(self, *, state: str | None = None, limit: int = 100) -> dict[str, Any]:
        if state is not None and state not in APPROVAL_STATES:
            raise ValueError("state filter must be one of approved, consumed, revoked, expired")
        if limit <= 0 or limit > MAX_APPROVAL_LIST_LIMIT:
            raise ValueError(f"limit must be between 1 and {MAX_APPROVAL_LIST_LIMIT}")
        with self._connect() as conn:
            if state:
                rows = conn.execute(
                    """
                    SELECT * FROM approvals
                    WHERE state = ?
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (state, limit),
                ).fetchall()
            else:
                rows = conn.execute(
                    """
                    SELECT * FROM approvals
                    ORDER BY created_at DESC
                    LIMIT ?
                    """,
                    (limit,),
                ).fetchall()
        return {
            "count": len(rows),
            "approvals": [self._row_to_approval(row) for row in rows],
        }

    def get_approval(self, approval_id: str, *, include_missing_error: bool = True) -> dict[str, Any]:
        _validate_pattern(approval_id, APPROVAL_ID_PATTERN, "approval_id")
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
        if row is None:
            if include_missing_error:
                raise ValueError(f"approval_id '{approval_id}' was not found")
            return {}
        return self._row_to_approval(row)

    def revoke_approval(self, approval_id: str) -> dict[str, Any]:
        _validate_pattern(approval_id, APPROVAL_ID_PATTERN, "approval_id")
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError(f"approval_id '{approval_id}' was not found")
            current_state = row["state"]
            if current_state == "consumed":
                conn.rollback()
                raise ValueError("consumed approvals cannot be revoked")
            if current_state == "revoked":
                conn.rollback()
                raise ValueError("approval is already revoked")
            if current_state == "expired":
                conn.rollback()
                raise ValueError("expired approvals cannot be revoked")
            conn.execute(
                "UPDATE approvals SET state = 'revoked', consumed_at = ?, consumed_execution_id = NULL WHERE approval_id = ?",
                (now, approval_id),
            )
            conn.commit()
        return self.get_approval(approval_id)

    def discord_prepare_approval(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = _validate_discord_prepare_payload(payload)
        self._assert_allowed_discord_actor(request)
        release_details = self._release_details_for_workspace(request["integration_workspace_id"])
        approval_expires_at = datetime.now(timezone.utc) + timedelta(
            minutes=self._config.discord_approval_ttl_minutes
        )
        intent_expires_at = datetime.now(timezone.utc) + timedelta(minutes=self._config.discord_intent_ttl_minutes)
        required_checks = release_details["required_check_profiles"]
        intent_id = _new_discord_intent_id()
        now = _utc_now()
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            statuses = self._required_check_statuses(conn, release_details=release_details)
            missing = [item for item in statuses if not item["passed"]]
            if missing:
                conn.rollback()
                raise ValueError(
                    "required passing trusted runner evidence is missing for check profile(s): "
                    f"{[{ 'check_id': item['check_id'], 'check_config_version': item['check_config_version'] } for item in missing]}"
                )
            try:
                conn.execute(
                    """
                    INSERT INTO discord_approval_intents (
                        intent_id,
                        request_interaction_id,
                        confirm_interaction_id,
                        state,
                        discord_user_id,
                        discord_guild_id,
                        discord_channel_id,
                        approval_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        remote_name,
                        target_branch,
                        expected_remote_head_sha,
                        deployment_profile_id,
                        allowed_services_json,
                        required_checks_json,
                        intent_expires_at,
                        approval_expires_at,
                        created_at,
                        confirmed_at
                    ) VALUES (?, ?, NULL, 'pending', ?, ?, ?, NULL, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    """,
                    (
                        intent_id,
                        request["interaction_id"],
                        request["discord_user_id"],
                        request["discord_guild_id"],
                        request["discord_channel_id"],
                        release_details["repository_id"],
                        release_details["integration_workspace_id"],
                        release_details["integration_commit_sha"],
                        release_details["remote_name"],
                        release_details["target_branch"],
                        release_details["expected_remote_head_sha"],
                        release_details["deployment_profile_id"],
                        json.dumps(release_details["allowed_services"]),
                        json.dumps(required_checks),
                        _normalize_utc(intent_expires_at),
                        _normalize_utc(approval_expires_at),
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                if "request_interaction_id" in str(exc):
                    raise ValueError("interaction_id was already used for a release approval intent") from exc
                raise
            conn.commit()
        return {
            "ok": True,
            "intent_id": intent_id,
            "intent_expires_at": _normalize_utc(intent_expires_at),
            "approval_expires_at": _normalize_utc(approval_expires_at),
            "release_details": {
                "repository_id": release_details["repository_id"],
                "integration_workspace_id": release_details["integration_workspace_id"],
                "integration_commit_sha": release_details["integration_commit_sha"],
                "remote_name": release_details["remote_name"],
                "target_branch": release_details["target_branch"],
                "expected_remote_head_sha": release_details["expected_remote_head_sha"],
                "deployment_profile_id": release_details["deployment_profile_id"],
                "allowed_services": release_details["allowed_services"],
            },
            "trusted_test_results": statuses,
        }

    def discord_confirm_approval(self, payload: dict[str, Any]) -> dict[str, Any]:
        request = _validate_discord_confirm_payload(payload)
        self._assert_allowed_discord_actor(request)
        now_dt = datetime.now(timezone.utc)
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM discord_approval_intents WHERE intent_id = ?",
                (request["intent_id"],),
            ).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError("unknown approval intent_id")
            if row["state"] == "confirmed":
                if (
                    row["confirm_interaction_id"] == request["interaction_id"]
                    and row["discord_user_id"] == request["discord_user_id"]
                ):
                    approval_id = str(row["approval_id"] or "")
                    conn.commit()
                    approval = self.get_approval(approval_id)
                    return {
                        "ok": True,
                        "intent_id": request["intent_id"],
                        "approval": approval,
                        "idempotent_replay": True,
                    }
                conn.rollback()
                raise ValueError("approval intent was already confirmed")
            if row["state"] != "pending":
                conn.rollback()
                raise ValueError(f"approval intent state '{row['state']}' does not allow confirmation")
            if row["discord_user_id"] != request["discord_user_id"]:
                conn.rollback()
                raise ValueError("approval intent belongs to a different Discord user")
            if row["discord_guild_id"] != request["discord_guild_id"]:
                conn.rollback()
                raise ValueError("approval intent guild mismatch")
            if row["discord_channel_id"] != request["discord_channel_id"]:
                conn.rollback()
                raise ValueError("approval intent channel mismatch")

            intent_expires_at = _parse_utc(row["intent_expires_at"])
            if intent_expires_at <= now_dt:
                conn.execute(
                    "UPDATE discord_approval_intents SET state = 'expired' WHERE intent_id = ?",
                    (request["intent_id"],),
                )
                conn.commit()
                raise ValueError("approval intent expired before confirmation")

            current = self._release_details_for_workspace(str(row["integration_workspace_id"]))
            expected_release_fields = (
                "repository_id",
                "integration_workspace_id",
                "integration_commit_sha",
                "remote_name",
                "target_branch",
                "expected_remote_head_sha",
                "deployment_profile_id",
            )
            for field_name in expected_release_fields:
                if str(row[field_name]) != str(current[field_name]):
                    conn.rollback()
                    raise ValueError(f"release details changed after preview; stale intent for field '{field_name}'")
            stored_allowed_services = sorted(json.loads(row["allowed_services_json"]))
            if stored_allowed_services != sorted(current["allowed_services"]):
                conn.rollback()
                raise ValueError("release details changed after preview; stale intent for field 'allowed_services'")

            statuses = self._required_check_statuses(conn, release_details=current)
            missing = [item for item in statuses if not item["passed"]]
            if missing:
                conn.rollback()
                raise ValueError(
                    "required passing trusted runner evidence is missing for check profile(s): "
                    f"{[{ 'check_id': item['check_id'], 'check_config_version': item['check_config_version'] } for item in missing]}"
                )

            approval_expires_at = _parse_utc(row["approval_expires_at"])
            if approval_expires_at <= now_dt:
                conn.execute(
                    "UPDATE discord_approval_intents SET state = 'expired' WHERE intent_id = ?",
                    (request["intent_id"],),
                )
                conn.commit()
                raise ValueError("approval intent expired before approval could be created")

            approval_id = _new_approval_id()
            created_by = f"discord-user-{request['discord_user_id']}"
            approval_row = self._build_approval_row(
                approval_id=approval_id,
                release_details=current,
                created_by=created_by,
                expires_at=approval_expires_at,
            )
            try:
                conn.execute(
                    """
                    INSERT INTO approvals (
                        approval_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        remote_name,
                        target_branch,
                        expected_remote_head_sha,
                        deployment_profile_id,
                        allowed_services_json,
                        expires_at,
                        state,
                        created_at,
                        created_by,
                        consumed_at,
                        consumed_execution_id
                    ) VALUES (
                        :approval_id,
                        :repository_id,
                        :integration_workspace_id,
                        :integration_commit_sha,
                        :remote_name,
                        :target_branch,
                        :expected_remote_head_sha,
                        :deployment_profile_id,
                        :allowed_services_json,
                        :expires_at,
                        :state,
                        :created_at,
                        :created_by,
                        :consumed_at,
                        :consumed_execution_id
                    )
                    """,
                    approval_row,
                )
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                raise ValueError("failed to persist approval record") from exc

            conn.execute(
                """
                UPDATE discord_approval_intents
                SET state = 'confirmed',
                    approval_id = ?,
                    confirm_interaction_id = ?,
                    confirmed_at = ?
                WHERE intent_id = ?
                """,
                (approval_id, request["interaction_id"], _utc_now(), request["intent_id"]),
            )
            conn.commit()
        approval = self.get_approval(approval_id)
        return {
            "ok": True,
            "intent_id": request["intent_id"],
            "approval": approval,
            "trusted_test_results": statuses,
        }

    def record_trusted_test_fixture(
        self,
        *,
        repository_id: str,
        integration_workspace_id: str,
        integration_commit_sha: str,
        check_id: str,
        fixture_run_id: str,
        result_state: str = "passed",
        source_controller: str = "trusted-fixture-6b2",
        evidence_payload: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        _validate_pattern(repository_id, REPO_ID_PATTERN, "repository_id")
        _validate_pattern(integration_workspace_id, WORKSPACE_ID_PATTERN, "integration_workspace_id")
        _validate_pattern(integration_commit_sha, SHA1_PATTERN, "integration_commit_sha")
        _validate_pattern(check_id, CHECK_ID_PATTERN, "check_id")
        _validate_pattern(source_controller, CONTROLLER_PATTERN, "source_controller")
        _validate_pattern(fixture_run_id, RUN_ID_PATTERN, "fixture_run_id")
        if result_state not in EVIDENCE_STATES:
            raise ValueError("result_state must be one of passed, failed, error")

        payload = evidence_payload or {
            "fixture": True,
            "checkpoint": "6B2",
            "check_id": check_id,
            "repository_id": repository_id,
            "integration_workspace_id": integration_workspace_id,
            "integration_commit_sha": integration_commit_sha,
        }
        payload_json = json.dumps(payload, sort_keys=True)
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        evidence_id = f"evidence-{uuid.uuid4().hex[:16]}"
        now = _utc_now()

        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO trusted_test_evidence (
                    evidence_id,
                    repository_id,
                    integration_workspace_id,
                    integration_commit_sha,
                    check_id,
                    check_config_version,
                    execution_id,
                    exit_code,
                    timed_out,
                    source_controller,
                    source_run_id,
                    evidence_kind,
                    result_state,
                    observed_at,
                    evidence_digest_sha256,
                    evidence_payload_json,
                    created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    evidence_id,
                    repository_id,
                    integration_workspace_id,
                    integration_commit_sha,
                    check_id,
                    "fixture",
                    fixture_run_id,
                    None,
                    0,
                    source_controller,
                    fixture_run_id,
                    "fixture",
                    result_state,
                    now,
                    digest,
                    payload_json,
                    now,
                ),
            )
        return {
            "evidence_id": evidence_id,
            "repository_id": repository_id,
            "integration_workspace_id": integration_workspace_id,
            "integration_commit_sha": integration_commit_sha,
            "check_id": check_id,
            "source_controller": source_controller,
            "source_run_id": fixture_run_id,
            "evidence_kind": "fixture",
            "check_config_version": "fixture",
            "execution_id": fixture_run_id,
            "exit_code": None,
            "timed_out": False,
            "result_state": result_state,
            "observed_at": now,
            "evidence_digest_sha256": digest,
        }

    def record_runner_test_evidence(self, payload: dict[str, Any]) -> dict[str, Any]:
        repository_id = payload.get("repository_id", "")
        integration_workspace_id = payload.get("integration_workspace_id", "")
        integration_commit_sha = payload.get("integration_commit_sha", "")
        check_id = payload.get("check_id", "")
        check_config_version = payload.get("check_config_version", "")
        execution_id = payload.get("execution_id", "")
        source_controller = payload.get("source_controller", "")
        source_run_id = payload.get("source_run_id", "")
        observed_at = payload.get("observed_at", "")
        result_state = payload.get("result_state", "")
        exit_code = payload.get("exit_code")
        timed_out = payload.get("timed_out")
        evidence_payload = payload.get("evidence_payload", {})

        _validate_pattern(repository_id, REPO_ID_PATTERN, "repository_id")
        _validate_pattern(integration_workspace_id, WORKSPACE_ID_PATTERN, "integration_workspace_id")
        _validate_pattern(integration_commit_sha, SHA1_PATTERN, "integration_commit_sha")
        _validate_pattern(check_id, CHECK_ID_PATTERN, "check_id")
        _validate_pattern(check_config_version, CONFIG_VERSION_PATTERN, "check_config_version")
        _validate_pattern(execution_id, RUN_ID_PATTERN, "execution_id")
        _validate_pattern(source_controller, CONTROLLER_PATTERN, "source_controller")
        _validate_pattern(source_run_id, RUN_ID_PATTERN, "source_run_id")
        _parse_utc(observed_at)
        if result_state not in EVIDENCE_STATES:
            raise ValueError("result_state must be one of passed, failed, error")
        if not isinstance(exit_code, int):
            raise ValueError("exit_code must be an integer")
        if not isinstance(timed_out, bool):
            raise ValueError("timed_out must be a boolean")
        if not isinstance(evidence_payload, dict):
            raise ValueError("evidence_payload must be an object")

        workspace = self._get_integration_workspace_details(integration_workspace_id)
        if workspace["integration_commit_sha"] != integration_commit_sha:
            raise ValueError("integration workspace commit does not match integration_commit_sha")
        repo_policy = self._policy.repository(repository_id)
        if repo_policy.managed_project_id != workspace["project_id"]:
            raise ValueError("repository policy mapping does not match integration workspace project")

        payload_json = json.dumps(evidence_payload, sort_keys=True)
        digest = hashlib.sha256(payload_json.encode("utf-8")).hexdigest()
        evidence_id = f"evidence-{uuid.uuid4().hex[:16]}"
        now = _utc_now()
        with self._connect() as conn:
            try:
                conn.execute(
                    """
                    INSERT INTO trusted_test_evidence (
                        evidence_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        check_id,
                        check_config_version,
                        execution_id,
                        exit_code,
                        timed_out,
                        source_controller,
                        source_run_id,
                        evidence_kind,
                        result_state,
                        observed_at,
                        evidence_digest_sha256,
                        evidence_payload_json,
                        created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        evidence_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        check_id,
                        check_config_version,
                        execution_id,
                        exit_code,
                        1 if timed_out else 0,
                        source_controller,
                        source_run_id,
                        "actual_runner",
                        result_state,
                        observed_at,
                        digest,
                        payload_json,
                        now,
                    ),
                )
            except sqlite3.IntegrityError as exc:
                raise ValueError("duplicate runner source_run_id for source_controller") from exc
        return {
            "ok": True,
            "evidence_id": evidence_id,
            "repository_id": repository_id,
            "integration_workspace_id": integration_workspace_id,
            "integration_commit_sha": integration_commit_sha,
            "check_id": check_id,
            "check_config_version": check_config_version,
            "execution_id": execution_id,
            "source_controller": source_controller,
            "source_run_id": source_run_id,
            "result_state": result_state,
            "exit_code": exit_code,
            "timed_out": timed_out,
            "observed_at": observed_at,
            "evidence_kind": "actual_runner",
            "evidence_digest_sha256": digest,
        }

    def _required_check_profiles_for_approval(self, approval: dict[str, Any]) -> list[CheckProfilePolicy]:
        repo = self._policy.repository(approval["repository_id"])
        profile = repo.deployment_profiles.get(approval["deployment_profile_id"])
        if profile is None:
            raise ValueError(
                f"deployment profile '{approval['deployment_profile_id']}' is not allowed for repository '{approval['repository_id']}'"
            )
        return list(profile.required_check_profiles)

    def _has_required_actual_runner_evidence(
        self,
        conn: sqlite3.Connection,
        *,
        approval: dict[str, Any],
    ) -> tuple[bool, list[dict[str, str]]]:
        missing: list[dict[str, str]] = []
        for check_profile in self._required_check_profiles_for_approval(approval):
            row = conn.execute(
                """
                SELECT result_state
                FROM trusted_test_evidence
                WHERE repository_id = ?
                  AND integration_workspace_id = ?
                  AND integration_commit_sha = ?
                  AND check_id = ?
                  AND check_config_version = ?
                  AND evidence_kind = 'actual_runner'
                ORDER BY observed_at DESC, created_at DESC
                LIMIT 1
                """,
                (
                    approval["repository_id"],
                    approval["integration_workspace_id"],
                    approval["integration_commit_sha"],
                    check_profile.check_id,
                    check_profile.check_config_version,
                ),
            ).fetchone()
            if row is None or row["result_state"] != "passed":
                missing.append(
                    {
                        "check_id": check_profile.check_id,
                        "check_config_version": check_profile.check_config_version,
                    }
                )
        return (len(missing) == 0, missing)

    def authorize_release_preview(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = _validate_authorize_release_preview_payload(payload)
        now = datetime.now(timezone.utc)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (preview["approval_id"],)).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError("unknown approval_id")

            approval = self._row_to_approval(row)
            state = approval["state"]
            expires_at = _parse_utc(approval["expires_at"])
            if state == "approved" and expires_at <= now:
                conn.execute("UPDATE approvals SET state = 'expired' WHERE approval_id = ?", (approval["approval_id"],))
                state = "expired"
            if state != "approved":
                conn.rollback()
                raise ValueError(f"approval state '{state}' does not allow release authorization")

            workspace = self._get_integration_workspace_details(preview["integration_workspace_id"])
            if approval["integration_workspace_id"] != workspace["workspace_id"]:
                conn.rollback()
                raise ValueError("approval mismatch for field 'integration_workspace_id'")
            if approval["integration_commit_sha"] != workspace["integration_commit_sha"]:
                conn.rollback()
                raise ValueError("approval mismatch for field 'integration_commit_sha'")
            if approval["target_branch"] != workspace["target_branch"]:
                conn.rollback()
                raise ValueError("approval mismatch for field 'target_branch'")
            if approval["expected_remote_head_sha"] != workspace["target_head_at_merge"]:
                conn.rollback()
                raise ValueError("approval mismatch for field 'expected_remote_head_sha'")

            repository_policy = self._policy.repository(approval["repository_id"])
            if repository_policy.managed_project_id != workspace["project_id"]:
                conn.rollback()
                raise ValueError("approval repository policy does not match workspace project")

            self._policy.resolve_release_scope(
                repository_id=approval["repository_id"],
                remote_name=approval["remote_name"],
                target_branch=approval["target_branch"],
                deployment_profile_id=approval["deployment_profile_id"],
                allowed_services=approval["allowed_services"],
            )
            has_evidence, missing_profiles = self._has_required_actual_runner_evidence(
                conn,
                approval=approval,
            )
            if not has_evidence:
                conn.rollback()
                raise ValueError(
                    "required passing trusted runner evidence is missing for check profile(s): "
                    f"{missing_profiles}"
                )

            conn.commit()

        return {
            "ok": True,
            "approval_id": approval["approval_id"],
            "authorization_state": "AUTHORIZED_READY",
            "execution_enabled": True,
            "repository_id": approval["repository_id"],
            "integration_workspace_id": approval["integration_workspace_id"],
            "integration_commit_sha": approval["integration_commit_sha"],
            "remote_name": approval["remote_name"],
            "target_branch": approval["target_branch"],
            "expected_remote_head_sha": approval["expected_remote_head_sha"],
            "deployment_profile_id": approval["deployment_profile_id"],
            "allowed_services": approval["allowed_services"],
            "notes": [
                "Approval binding and trusted evidence validated successfully.",
                "Release execution is enabled through execute_release.",
            ],
        }

    def authorize_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        normalized_payload = _validate_authorize_release_payload(payload)
        validated = self.validate_release_details(normalized_payload)
        approval_id = normalized_payload["approval_id"]
        now = datetime.now(timezone.utc)
        now_text = _normalize_utc(now)

        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM approvals WHERE approval_id = ?", (approval_id,)).fetchone()
            if row is None:
                conn.rollback()
                raise ValueError("unknown approval_id")

            approval = self._row_to_approval(row)
            state = approval["state"]
            expires_at = _parse_utc(approval["expires_at"])
            if state == "approved" and expires_at <= now:
                conn.execute("UPDATE approvals SET state = 'expired' WHERE approval_id = ?", (approval_id,))
                state = "expired"
            if state != "approved":
                conn.rollback()
                raise ValueError(f"approval state '{state}' does not allow release authorization")

            compare_fields = [
                "repository_id",
                "integration_workspace_id",
                "integration_commit_sha",
                "remote_name",
                "target_branch",
                "expected_remote_head_sha",
                "deployment_profile_id",
            ]
            for field in compare_fields:
                if approval[field] != validated[field]:
                    conn.rollback()
                    raise ValueError(f"approval mismatch for field '{field}'")
            if sorted(approval["allowed_services"]) != sorted(validated["allowed_services"]):
                conn.rollback()
                raise ValueError("approval mismatch for field 'allowed_services'")

            has_evidence, missing_profiles = self._has_required_actual_runner_evidence(
                conn,
                approval=approval,
            )
            if not has_evidence:
                conn.rollback()
                raise ValueError(
                    "required passing trusted runner evidence is missing for check profile(s): "
                    f"{missing_profiles}"
                )

            execution_id = _new_execution_id()
            lock_key = _release_lock_key(
                validated["repository_id"],
                validated["remote_name"],
                validated["target_branch"],
            )
            try:
                conn.execute(
                    """
                    INSERT INTO release_executions (
                        execution_id,
                        approval_id,
                        repository_id,
                        integration_workspace_id,
                        integration_commit_sha,
                        remote_name,
                        target_branch,
                        expected_remote_head_sha,
                        state,
                        created_at,
                        started_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'locked', ?, ?)
                    """,
                    (
                        execution_id,
                        approval_id,
                        validated["repository_id"],
                        validated["integration_workspace_id"],
                        validated["integration_commit_sha"],
                        validated["remote_name"],
                        validated["target_branch"],
                        validated["expected_remote_head_sha"],
                        now_text,
                        now_text,
                    ),
                )
                conn.execute(
                    """
                    INSERT INTO execution_locks (lock_key, execution_id, acquired_at)
                    VALUES (?, ?, ?)
                    """,
                    (lock_key, execution_id, now_text),
                )
                update = conn.execute(
                    """
                    UPDATE approvals
                    SET state = 'consumed',
                        consumed_at = ?,
                        consumed_execution_id = ?
                    WHERE approval_id = ?
                      AND state = 'approved'
                    """,
                    (now_text, execution_id, approval_id),
                )
                if update.rowcount != 1:
                    raise ValueError("approval was not available for consumption")
            except sqlite3.IntegrityError as exc:
                conn.rollback()
                if "execution_locks.lock_key" in str(exc):
                    raise ValueError("release lock already exists for repository/remote/branch") from exc
                if "release_executions.approval_id" in str(exc):
                    raise ValueError("approval was already consumed") from exc
                raise ValueError("failed to reserve approval atomically") from exc

            conn.commit()

        return {
            "ok": True,
            "approval_id": approval_id,
            "execution_id": execution_id,
            "authorization_state": "reserved",
            "repository_id": validated["repository_id"],
            "integration_workspace_id": validated["integration_workspace_id"],
            "integration_commit_sha": validated["integration_commit_sha"],
            "remote_name": validated["remote_name"],
            "target_branch": validated["target_branch"],
            "deployment_profile_id": validated["deployment_profile_id"],
            "allowed_services": validated["allowed_services"],
            "lock_key": _release_lock_key(
                validated["repository_id"],
                validated["remote_name"],
                validated["target_branch"],
            ),
            "reserved_at": now_text,
            "notes": [
                "Approval is consumed at reservation time and is intentionally not reusable.",
                "This action reserves only; use execute_release to run the trusted push workflow.",
            ],
        }

    def _set_execution_state(self, execution_id: str, state: str) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE release_executions
                SET state = ?
                WHERE execution_id = ?
                """,
                (state, execution_id),
            )
            conn.commit()

    def _finalize_execution(
        self,
        *,
        execution_id: str,
        state: str,
        push_result: str,
        deployment_result: str,
        rollback_result: str,
        previous_remote_head_sha: str | None,
        resulting_remote_head_sha: str | None,
        deployed_commit_sha: str | None,
        rolled_back_to_commit_sha: str | None,
        failure_code: str | None,
        failure_message: str | None,
    ) -> None:
        with self._connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            conn.execute(
                """
                UPDATE release_executions
                SET state = ?,
                    push_result = ?,
                    deployment_result = ?,
                    rollback_result = ?,
                    previous_remote_head_sha = ?,
                    resulting_remote_head_sha = ?,
                    deployed_commit_sha = ?,
                    rolled_back_to_commit_sha = ?,
                    failure_code = ?,
                    failure_message = ?,
                    completed_at = ?
                WHERE execution_id = ?
                """,
                (
                    state,
                    push_result,
                    deployment_result,
                    rollback_result,
                    previous_remote_head_sha,
                    resulting_remote_head_sha,
                    deployed_commit_sha,
                    rolled_back_to_commit_sha,
                    failure_code,
                    failure_message,
                    _utc_now(),
                    execution_id,
                ),
            )
            conn.execute("DELETE FROM execution_locks WHERE execution_id = ?", (execution_id,))
            conn.commit()

    def execute_release(self, payload: dict[str, Any]) -> dict[str, Any]:
        preview = _validate_authorize_release_preview_payload(payload)
        approval_id = preview["approval_id"]
        integration_workspace_id = preview["integration_workspace_id"]

        try:
            approval = self.get_approval(approval_id)
            authorize_payload = {
                "approval_id": approval["approval_id"],
                "repository_id": approval["repository_id"],
                "integration_workspace_id": approval["integration_workspace_id"],
                "integration_commit_sha": approval["integration_commit_sha"],
                "remote_name": approval["remote_name"],
                "target_branch": approval["target_branch"],
                "expected_remote_head_sha": approval["expected_remote_head_sha"],
                "deployment_profile_id": approval["deployment_profile_id"],
                "allowed_services": approval["allowed_services"],
            }
            if authorize_payload["integration_workspace_id"] != integration_workspace_id:
                raise ValueError("approval mismatch for field 'integration_workspace_id'")
            validated = self.validate_release_details(authorize_payload)
            self._assert_no_reconciliation_required(validated)
            reservation = self.authorize_release(authorize_payload)
        except Exception as exc:
            return {
                "ok": False,
                "release_status": "AUTHORIZATION_REJECTED",
                "deployment_status": "NOT_ATTEMPTED",
                "push_status": "NOT_ATTEMPTED",
                "approval_id": approval_id,
                "integration_workspace_id": integration_workspace_id,
                "error": str(exc),
            }

        execution_id = reservation["execution_id"]
        workspace_path = Path(validated["workspace_path"])
        remote_path = validated["remote_path"]
        target_branch = validated["target_branch"]
        integration_commit_sha = validated["integration_commit_sha"]
        expected_remote_head_sha = validated["expected_remote_head_sha"]
        deployment_target = validated["deployment_target"]
        service_access = self._release_access_urls(validated)
        service_id = deployment_target["service_id"]
        service_key = self._service_deployment_key(validated)
        previous_remote_head_sha: str | None = None
        resulting_remote_head_sha: str | None = None
        previous_good_commit_sha: str | None = None
        stage = "verifying"

        try:
            self._set_execution_state(execution_id, "verifying")
            previous_remote_head_sha = self._read_remote_head(workspace_path, remote_path, target_branch)
            if previous_remote_head_sha != expected_remote_head_sha:
                self._finalize_execution(
                    execution_id=execution_id,
                    state="rejected",
                    push_result="not_attempted",
                    deployment_result="not_started",
                    rollback_result="not_needed",
                    previous_remote_head_sha=previous_remote_head_sha,
                    resulting_remote_head_sha=previous_remote_head_sha,
                    deployed_commit_sha=None,
                    rolled_back_to_commit_sha=None,
                    failure_code="remote_head_moved",
                    failure_message="remote branch head does not match approval expected_remote_head_sha",
                )
                return {
                    "ok": False,
                    "release_status": "AUTHORIZATION_REJECTED",
                    "deployment_status": "NOT_ATTEMPTED",
                    "push_status": "NOT_ATTEMPTED",
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "repository_id": validated["repository_id"],
                    "integration_workspace_id": validated["integration_workspace_id"],
                    "integration_commit_sha": integration_commit_sha,
                    "remote_name": validated["remote_name"],
                    "remote_path": remote_path,
                    "target_branch": target_branch,
                    "previous_remote_head_sha": previous_remote_head_sha,
                    "resulting_remote_head_sha": previous_remote_head_sha,
                    "service_access": service_access,
                    "error": "remote branch moved since approval",
                }
            self._fetch_remote_branch_for_verification(workspace_path, remote_path, target_branch)
            if not self._is_ancestor(workspace_path, previous_remote_head_sha, integration_commit_sha):
                self._finalize_execution(
                    execution_id=execution_id,
                    state="rejected",
                    push_result="not_attempted",
                    deployment_result="not_started",
                    rollback_result="not_needed",
                    previous_remote_head_sha=previous_remote_head_sha,
                    resulting_remote_head_sha=previous_remote_head_sha,
                    deployed_commit_sha=None,
                    rolled_back_to_commit_sha=None,
                    failure_code="non_fast_forward",
                    failure_message="approved commit is not a fast-forward descendant of remote branch head",
                )
                return {
                    "ok": False,
                    "release_status": "AUTHORIZATION_REJECTED",
                    "deployment_status": "NOT_ATTEMPTED",
                    "push_status": "NOT_ATTEMPTED",
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "repository_id": validated["repository_id"],
                    "integration_workspace_id": validated["integration_workspace_id"],
                    "integration_commit_sha": integration_commit_sha,
                    "remote_name": validated["remote_name"],
                    "remote_path": remote_path,
                    "target_branch": target_branch,
                    "previous_remote_head_sha": previous_remote_head_sha,
                    "resulting_remote_head_sha": previous_remote_head_sha,
                    "service_access": service_access,
                    "error": "approved commit is not a fast-forward descendant",
                }

            self._set_execution_state(execution_id, "pushing")
            stage = "pushing"
            self._run_git(
                workspace_path,
                [
                    "push",
                    "--porcelain",
                    remote_path,
                    f"{integration_commit_sha}:{self._remote_ref(target_branch)}",
                ],
                allow_file_transport=True,
            )
            resulting_remote_head_sha = self._read_remote_head(workspace_path, remote_path, target_branch)
            if resulting_remote_head_sha != integration_commit_sha:
                self._finalize_execution(
                    execution_id=execution_id,
                    state="failed",
                    push_result="failed",
                    deployment_result="not_started",
                    rollback_result="not_needed",
                    previous_remote_head_sha=previous_remote_head_sha,
                    resulting_remote_head_sha=resulting_remote_head_sha,
                    deployed_commit_sha=None,
                    rolled_back_to_commit_sha=None,
                    failure_code="post_push_remote_mismatch",
                    failure_message="remote branch did not resolve to approved commit after push",
                )
                return {
                    "ok": False,
                    "release_status": "PUSH_FAILED",
                    "deployment_status": "NOT_ATTEMPTED",
                    "push_status": "FAILED",
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "repository_id": validated["repository_id"],
                    "integration_workspace_id": validated["integration_workspace_id"],
                    "integration_commit_sha": integration_commit_sha,
                    "remote_name": validated["remote_name"],
                    "remote_path": remote_path,
                    "target_branch": target_branch,
                    "previous_remote_head_sha": previous_remote_head_sha,
                    "resulting_remote_head_sha": resulting_remote_head_sha,
                    "service_access": service_access,
                    "error": "remote branch verification failed after push",
                }

            self._set_execution_state(execution_id, "deploying")
            stage = "deploying"
            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                deployment_state = self._get_deployment_state(conn, service_key)
                previous_good_commit_sha = deployment_state["current_commit_sha"]
                self._upsert_deployment_state(
                    conn,
                    service_id=service_key,
                    repository_id=validated["repository_id"],
                    deployment_profile_id=validated["deployment_profile_id"],
                    current_commit_sha=deployment_state["current_commit_sha"],
                    previous_commit_sha=deployment_state["previous_commit_sha"],
                    last_execution_id=execution_id,
                    last_stage="deploying",
                    reconcile_required=True,
                )
                conn.commit()

            target_snapshot = self._deploy_commit(validated, workspace_path, integration_commit_sha)
            if self._marker_exists(target_snapshot, deployment_target["deploy_failure_marker"]):
                raise ValueError("controlled deployment failure marker triggered")

            self._set_execution_state(execution_id, "health_checking")
            stage = "health_checking"
            self._verify_deployment_health(validated, integration_commit_sha)

            with self._connect() as conn:
                conn.execute("BEGIN IMMEDIATE")
                self._upsert_deployment_state(
                    conn,
                    service_id=service_key,
                    repository_id=validated["repository_id"],
                    deployment_profile_id=validated["deployment_profile_id"],
                    current_commit_sha=integration_commit_sha,
                    previous_commit_sha=previous_good_commit_sha,
                    last_execution_id=execution_id,
                    last_stage="healthy",
                    reconcile_required=False,
                )
                conn.commit()

            self._finalize_execution(
                execution_id=execution_id,
                state="completed",
                push_result="succeeded",
                deployment_result="succeeded",
                rollback_result="not_needed",
                previous_remote_head_sha=previous_remote_head_sha,
                resulting_remote_head_sha=resulting_remote_head_sha,
                deployed_commit_sha=integration_commit_sha,
                rolled_back_to_commit_sha=None,
                failure_code=None,
                failure_message=None,
            )
            return {
                "ok": True,
                "release_status": "DEPLOYMENT_SUCCEEDED",
                "deployment_status": "SUCCEEDED",
                "push_status": "SUCCEEDED",
                "approval_id": approval_id,
                "execution_id": execution_id,
                "repository_id": validated["repository_id"],
                "integration_workspace_id": validated["integration_workspace_id"],
                "integration_commit_sha": integration_commit_sha,
                "deployed_commit_sha": integration_commit_sha,
                "deployed_service_id": service_id,
                "remote_name": validated["remote_name"],
                "remote_path": remote_path,
                "target_branch": target_branch,
                "previous_remote_head_sha": previous_remote_head_sha,
                "resulting_remote_head_sha": resulting_remote_head_sha,
                "service_access": service_access,
                "notes": [
                    "Approved commit pushed to trusted sandbox remote.",
                    "Sandbox deployment and health verification succeeded.",
                ],
            }
        except Exception as exc:
            try:
                resulting_remote_head_sha = self._read_remote_head(workspace_path, remote_path, target_branch)
            except Exception:
                resulting_remote_head_sha = None
            if stage in {"verifying", "pushing"}:
                self._finalize_execution(
                    execution_id=execution_id,
                    state="failed",
                    push_result="failed",
                    deployment_result="not_started",
                    rollback_result="not_needed",
                    previous_remote_head_sha=previous_remote_head_sha,
                    resulting_remote_head_sha=resulting_remote_head_sha,
                    deployed_commit_sha=None,
                    rolled_back_to_commit_sha=None,
                    failure_code="push_error",
                    failure_message=str(exc),
                )
                return {
                    "ok": False,
                    "release_status": "PUSH_FAILED",
                    "deployment_status": "NOT_ATTEMPTED",
                    "push_status": "FAILED",
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "repository_id": validated["repository_id"],
                    "integration_workspace_id": validated["integration_workspace_id"],
                    "integration_commit_sha": integration_commit_sha,
                    "remote_name": validated["remote_name"],
                    "remote_path": remote_path,
                    "target_branch": target_branch,
                    "previous_remote_head_sha": previous_remote_head_sha,
                    "resulting_remote_head_sha": resulting_remote_head_sha,
                    "service_access": service_access,
                    "error": str(exc),
                }
            rollback_error: str | None = None
            rollback_commit_sha: str | None = None
            try:
                if previous_good_commit_sha:
                    self._set_execution_state(execution_id, "rolled_back")
                    target_snapshot = self._snapshot_commit(workspace_path, self._deployment_runtime_dir(validated), integration_commit_sha)
                    if self._marker_exists(target_snapshot, deployment_target["rollback_failure_marker"]):
                        raise ValueError("controlled rollback failure marker triggered")
                    self._deploy_commit(validated, workspace_path, previous_good_commit_sha)
                    self._set_execution_state(execution_id, "health_checking")
                    self._verify_deployment_health(validated, previous_good_commit_sha)
                    rollback_commit_sha = previous_good_commit_sha
                    with self._connect() as conn:
                        conn.execute("BEGIN IMMEDIATE")
                        self._upsert_deployment_state(
                            conn,
                            service_id=service_key,
                            repository_id=validated["repository_id"],
                            deployment_profile_id=validated["deployment_profile_id"],
                            current_commit_sha=previous_good_commit_sha,
                            previous_commit_sha=None,
                            last_execution_id=execution_id,
                            last_stage="rolled_back_healthy",
                            reconcile_required=False,
                        )
                        conn.commit()
                else:
                    rollback_error = "no previously known-good deployment was recorded for rollback"
            except Exception as rollback_exc:
                rollback_error = str(rollback_exc)
                with self._connect() as conn:
                    conn.execute("BEGIN IMMEDIATE")
                    self._upsert_deployment_state(
                        conn,
                        service_id=service_key,
                        repository_id=validated["repository_id"],
                        deployment_profile_id=validated["deployment_profile_id"],
                        current_commit_sha=previous_good_commit_sha,
                        previous_commit_sha=None,
                        last_execution_id=execution_id,
                        last_stage="rollback_failed",
                        reconcile_required=True,
                    )
                    conn.commit()

            if rollback_error is None:
                self._finalize_execution(
                    execution_id=execution_id,
                    state="rolled_back",
                    push_result="succeeded" if resulting_remote_head_sha == integration_commit_sha else "failed",
                    deployment_result="failed",
                    rollback_result="succeeded",
                    previous_remote_head_sha=previous_remote_head_sha,
                    resulting_remote_head_sha=resulting_remote_head_sha,
                    deployed_commit_sha=integration_commit_sha,
                    rolled_back_to_commit_sha=rollback_commit_sha,
                    failure_code="deployment_failed_rolled_back",
                    failure_message=str(exc),
                )
                return {
                    "ok": False,
                    "release_status": "DEPLOYMENT_FAILED_ROLLED_BACK",
                    "deployment_status": "FAILED_ROLLED_BACK",
                    "push_status": "SUCCEEDED" if resulting_remote_head_sha == integration_commit_sha else "FAILED",
                    "approval_id": approval_id,
                    "execution_id": execution_id,
                    "repository_id": validated["repository_id"],
                    "integration_workspace_id": validated["integration_workspace_id"],
                    "integration_commit_sha": integration_commit_sha,
                    "deployed_commit_sha": integration_commit_sha,
                    "rolled_back_to_commit_sha": rollback_commit_sha,
                    "deployed_service_id": service_id,
                    "remote_name": validated["remote_name"],
                    "remote_path": remote_path,
                    "target_branch": target_branch,
                    "previous_remote_head_sha": previous_remote_head_sha,
                    "resulting_remote_head_sha": resulting_remote_head_sha,
                    "service_access": service_access,
                    "error": str(exc),
                    "rollback_error": None,
                }

            self._set_execution_state(execution_id, "rollback_failed")
            self._finalize_execution(
                execution_id=execution_id,
                state="rollback_failed",
                push_result="succeeded" if resulting_remote_head_sha == integration_commit_sha else "failed",
                deployment_result="failed",
                rollback_result="failed",
                previous_remote_head_sha=previous_remote_head_sha,
                resulting_remote_head_sha=resulting_remote_head_sha,
                deployed_commit_sha=integration_commit_sha,
                rolled_back_to_commit_sha=rollback_commit_sha,
                failure_code="deployment_failed_rollback_failed",
                failure_message=f"{exc} | rollback: {rollback_error}",
            )
            return {
                "ok": False,
                "release_status": "DEPLOYMENT_FAILED_ROLLBACK_FAILED",
                "deployment_status": "FAILED_ROLLBACK_FAILED",
                "push_status": "SUCCEEDED" if resulting_remote_head_sha == integration_commit_sha else "FAILED",
                "approval_id": approval_id,
                "execution_id": execution_id,
                "repository_id": validated["repository_id"],
                "integration_workspace_id": validated["integration_workspace_id"],
                "integration_commit_sha": integration_commit_sha,
                "deployed_commit_sha": integration_commit_sha,
                "deployed_service_id": service_id,
                "rolled_back_to_commit_sha": rollback_commit_sha,
                "remote_name": validated["remote_name"],
                "remote_path": remote_path,
                "target_branch": target_branch,
                "previous_remote_head_sha": previous_remote_head_sha,
                "resulting_remote_head_sha": resulting_remote_head_sha,
                "service_access": service_access,
                "error": str(exc),
                "rollback_error": rollback_error,
            }

    def get_contract(self) -> dict[str, Any]:
        return {
            "approval_record_schema": APPROVAL_RECORD_SCHEMA,
            "release_state_machine": {
                "approval_states": list(APPROVAL_STATES),
                "execution_states": list(RELEASE_STATES),
                "allowed_path": [
                    "locked",
                    "verifying",
                    "pushing",
                    "deploying",
                    "health_checking",
                    "completed",
                ],
                "failure_paths": [
                    "locked -> rejected",
                    "verifying -> failed",
                    "pushing -> failed",
                    "deploying -> failed",
                    "health_checking -> failed -> rolled_back|rollback_failed",
                ],
            },
            "request_schemas": {
                "envelope": {
                    "required": ["auth_token", "action", "payload"],
                    "payload_type": "object",
                    "additional_properties": False,
                },
                "actions": {
                    "ping": {"request_payload": {"required": [], "additional_properties": False}},
                    "describe_contract": {"request_payload": {"required": [], "additional_properties": False}},
                    "validate_execute_release_request": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["validate_execute_release_request"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "normalized_request": "object",
                            "derived_lock_key": "string",
                        },
                    },
                    "authorize_release_preview": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["authorize_release_preview"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "authorization_state": "AUTHORIZED_READY",
                            "execution_enabled": True,
                        },
                    },
                    "authorize_release": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["authorize_release"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "approval_id": "string",
                            "execution_id": "string",
                            "authorization_state": "reserved",
                        },
                    },
                    "execute_release": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["execute_release"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "release_status": "AUTHORIZATION_REJECTED|PUSH_FAILED|DEPLOYMENT_SUCCEEDED|DEPLOYMENT_FAILED_ROLLED_BACK|DEPLOYMENT_FAILED_ROLLBACK_FAILED",
                            "deployment_status": "NOT_ATTEMPTED|SUCCEEDED|FAILED_ROLLED_BACK|FAILED_ROLLBACK_FAILED",
                            "push_status": "NOT_ATTEMPTED|SUCCEEDED|FAILED",
                            "approval_id": "string",
                            "execution_id": "string|optional",
                            "service_access": {
                                "application_url": "http://127.0.0.1:<host-port>",
                                "container_port": "integer",
                                "host_port": "integer",
                            },
                        },
                    },
                    "record_test_evidence": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["record_test_evidence"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "evidence_id": "string",
                            "evidence_kind": "actual_runner",
                        },
                    },
                    "discord_prepare_approval": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["discord_prepare_approval"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "intent_id": "intent-<token>",
                            "intent_expires_at": "rfc3339_utc",
                            "approval_expires_at": "rfc3339_utc",
                            "release_details": "object",
                            "trusted_test_results": "array",
                        },
                    },
                    "discord_confirm_approval": {
                        "request_payload": {
                            "required": sorted(REQUEST_SCHEMAS["discord_confirm_approval"]["required"]),
                            "additional_properties": False,
                        },
                        "response": {
                            "ok": "boolean",
                            "intent_id": "intent-<token>",
                            "approval": "approval record",
                            "trusted_test_results": "array",
                        },
                    },
                },
            },
            "atomic_consumption_and_locking": {
                "algorithm": [
                    "BEGIN IMMEDIATE transaction",
                    "Load approval row under write lock",
                    "Reject unknown/revoked/expired/consumed approvals",
                    "Reject any mismatch between request and bound approval details",
                    "Verify trusted passed test evidence from private table",
                    "Insert release_executions row in locked state",
                    "Insert execution_locks row with UNIQUE(lock_key)",
                    "Consume approval (state=consumed, consumed_execution_id set)",
                    "COMMIT; otherwise rollback",
                ],
                "duplicate_release_prevention": [
                    "approvals.approval_id is unique",
                    "release_executions.approval_id has UNIQUE constraint",
                    "execution_locks.lock_key is unique for repository+remote+branch",
                ],
            },
            "trusted_test_evidence_store": {
                "table": "trusted_test_evidence",
                "independence": "Stored in private executor DB; not read from Engineer workspace metadata",
                "required_match_fields": [
                    "repository_id",
                    "integration_workspace_id",
                    "integration_commit_sha",
                    "check_id",
                    "check_config_version",
                    "evidence_kind=actual_runner",
                    "latest result_state=passed",
                ],
                "fixture_note": "Checkpoint 6B2 may use explicitly tagged fixture evidence via host-only tooling.",
                "release_eligible_evidence_kind": "actual_runner",
            },
            "release_execution_status": {
                "execution_enabled": True,
                "checkpoint": "6C",
                "note": "Executor performs approval-gated sandbox push/deploy/health verification with automatic rollback.",
            },
            "discord_release_approval": {
                "enabled": True,
                "single_use_approval": True,
                "identity_source": "trusted Discord interaction metadata only",
                "required_identity": {
                    "discord_user_ids": sorted(self._config.discord_allowed_user_ids),
                    "discord_guild_ids": sorted(self._config.discord_allowed_guild_ids),
                    "discord_channel_ids": sorted(self._config.discord_allowed_channel_ids),
                },
                "intent_ttl_minutes": self._config.discord_intent_ttl_minutes,
                "approval_ttl_minutes": self._config.discord_approval_ttl_minutes,
            },
            "trusted_git_execution_environment": {
                "env": TRUSTED_GIT_ENV,
                "git_args": TRUSTED_GIT_ARGS,
                "requirements": [
                    "Disable system/global Git config inheritance",
                    "Disable hooks via core.hooksPath=/dev/null",
                    "Disable interactive prompts",
                    "Do not accept command, path, or refspec input outside strict schemas",
                ],
            },
            "private_state_storage": {
                "state_dir": str(self._config.state_dir),
                "state_db_path": str(self._config.state_db_path),
                "policy_file": str(self._config.policy_file),
                "socket_path": str(self._config.socket_path),
            },
            "generated_at": _utc_now(),
        }


def _peer_uid(conn: socket.socket) -> int | None:
    if not hasattr(socket, "SO_PEERCRED"):
        return None
    creds = conn.getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, struct.calcsize("3i"))
    _, uid, _ = struct.unpack("3i", creds)
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
    parsed = json.loads(line.decode("utf-8"))
    if not isinstance(parsed, dict):
        raise ValueError("request must be a JSON object")
    return parsed


def _validate_envelope(
    request: dict[str, Any],
    *,
    auth_token: str,
    evidence_auth_token: str,
    discord_auth_token: str,
) -> tuple[str, dict[str, Any]]:
    allowed_keys = {"auth_token", "action", "payload"}
    unknown = set(request.keys()) - allowed_keys
    if unknown:
        raise ValueError(f"unsupported request fields: {sorted(unknown)}")

    action = request.get("action", "")
    if not isinstance(action, str) or action not in REQUEST_SCHEMAS:
        raise ValueError("unknown action")

    token = request.get("auth_token", "")
    if not isinstance(token, str):
        raise ValueError("authentication failed")
    if action == "record_test_evidence":
        expected_token = evidence_auth_token
    elif action in {"discord_prepare_approval", "discord_confirm_approval"}:
        expected_token = discord_auth_token
    else:
        expected_token = auth_token
    if not expected_token or not secrets.compare_digest(token, expected_token):
        raise ValueError("authentication failed")

    payload = request.get("payload", {})
    if not isinstance(payload, dict):
        raise ValueError("payload must be an object")

    schema = REQUEST_SCHEMAS[action]
    required = schema["required"]
    optional = schema["optional"]
    unknown_payload = set(payload.keys()) - (required | optional)
    if unknown_payload:
        raise ValueError(f"unsupported payload fields: {sorted(unknown_payload)}")
    missing = sorted([field for field in required if field not in payload])
    if missing:
        raise ValueError(f"missing required payload fields: {missing}")
    return action, payload


def _handle_request(request: dict[str, Any], auth_token: str, store: ReleaseStateStore) -> dict[str, Any]:
    action, payload = _validate_envelope(
        request,
        auth_token=auth_token,
        evidence_auth_token=store._config.evidence_auth_token,
        discord_auth_token=store._config.discord_auth_token,
    )
    if action == "ping":
        return {
            "ok": True,
            "action": "ping",
            "service": "engineer-release-executor",
            "time_utc": _utc_now(),
        }
    if action == "describe_contract":
        return {
            "ok": True,
            "action": "describe_contract",
            "contract": store.get_contract(),
        }
    if action == "validate_execute_release_request":
        normalized = _validate_authorize_release_payload(payload)
        validated = store.validate_release_details(normalized)
        return {
            "ok": True,
            "action": "validate_execute_release_request",
            "normalized_request": {
                "approval_id": normalized["approval_id"],
                **validated,
            },
            "derived_lock_key": _release_lock_key(
                validated["repository_id"],
                validated["remote_name"],
                validated["target_branch"],
            ),
        }
    if action == "authorize_release_preview":
        return store.authorize_release_preview(payload)
    if action == "execute_release":
        return store.execute_release(payload)
    if action == "record_test_evidence":
        return store.record_runner_test_evidence(payload)
    if action == "discord_prepare_approval":
        return store.discord_prepare_approval(payload)
    if action == "discord_confirm_approval":
        return store.discord_confirm_approval(payload)
    return store.authorize_release(payload)


def serve(config: ExecutorConfig) -> None:
    store = ReleaseStateStore(config)
    config.socket_path.parent.mkdir(parents=True, exist_ok=True)
    if config.socket_path.exists():
        config.socket_path.unlink()

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(str(config.socket_path))
        os.chmod(config.socket_path, 0o660)
        server.listen(8)
        while True:
            conn, _ = server.accept()
            with conn:
                try:
                    uid = _peer_uid(conn)
                    if uid is not None and uid != config.allowed_peer_uid:
                        raise ValueError("peer UID is not allowed")
                    request = _read_request(conn)
                    response = _handle_request(request, auth_token=config.auth_token, store=store)
                except Exception as exc:
                    response = {"ok": False, "error": str(exc)}
                try:
                    conn.sendall((json.dumps(response) + "\n").encode("utf-8"))
                except BrokenPipeError:
                    continue
    finally:
        server.close()
        if config.socket_path.exists():
            config.socket_path.unlink()


def parse_expires_at(expires_in_minutes: int, expires_at: str | None) -> datetime:
    if expires_at is not None:
        return _parse_utc(expires_at)
    if expires_in_minutes <= 0 or expires_in_minutes > 60 * 24 * 30:
        raise ValueError("expires_in_minutes must be between 1 and 43200")
    return datetime.now(timezone.utc) + timedelta(minutes=expires_in_minutes)


def main() -> None:
    parser = argparse.ArgumentParser(description="Trusted host-side release executor.")
    parser.add_argument(
        "mode",
        choices=["serve"],
        help="Run mode",
    )
    parser.add_argument(
        "--socket-path",
        default=None,
        help="Unix socket path for API server",
    )
    parser.add_argument(
        "--auth-token",
        default=None,
        help="Shared auth token for API requests",
    )
    parser.add_argument(
        "--allowed-peer-uid",
        type=int,
        default=1000,
        help="Allowed Unix peer UID for incoming socket clients",
    )
    args = parser.parse_args()
    config = ExecutorConfig.from_server_args(args)
    serve(config)


if __name__ == "__main__":
    main()
