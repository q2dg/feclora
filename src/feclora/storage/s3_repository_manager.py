"""Root-managed definitions for S3-compatible object repositories.

S3 repositories are deliberately independent of filesystem mount definitions.
Only non-secret connection metadata and an encrypted credential identifier are
persisted; access keys are decrypted into process memory when an operation runs.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import stat
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Callable

from feclora.storage.s3_repository import S3ObjectRepository, S3RepositoryConfig, S3RepositoryError
from feclora.storage.systemd_credential_store import SystemdCredentialStore

REGISTRY = Path("/etc/feclora/s3-repositories.json")
_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


class S3RepositoryManagerError(RuntimeError):
    """A managed S3 repository operation failed safely."""


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("duplicate field")
        result[key] = value
    return result


class S3RepositoryManager:
    """Persist S3 endpoint metadata without persisting access-key material."""

    def __init__(self, *, registry: Path = REGISTRY,
                 credentials: SystemdCredentialStore | None = None,
                 effective_uid: Callable[[], int] = os.geteuid,
                 owner_uid: int = 0):
        self.registry = Path(registry)
        self.credentials = credentials or SystemdCredentialStore()
        self.effective_uid = effective_uid
        self.owner_uid = owner_uid

    def _root(self):
        if self.effective_uid() != 0:
            raise S3RepositoryManagerError("S3 repository management requires root")
        parent = self.registry.parent
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
        info = os.lstat(parent)
        if (not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid
                or info.st_mode & 0o022):
            raise S3RepositoryManagerError("S3 repository state directory is unsafe")

    @contextmanager
    def _lock(self):
        self._root()
        lock_path = self.registry.with_suffix(self.registry.suffix + ".lock")
        fd = os.open(lock_path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
        try:
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
                raise S3RepositoryManagerError("S3 registry lock is unsafe")
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            os.close(fd)

    def _load(self):
        self._root()
        try:
            info = os.lstat(self.registry)
        except FileNotFoundError:
            return {}
        if (not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid
                or info.st_mode & 0o077 or info.st_size > 256 * 1024):
            raise S3RepositoryManagerError("S3 repository registry is unsafe")
        fd = os.open(self.registry, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        try:
            opened = os.fstat(fd)
            if (not stat.S_ISREG(opened.st_mode) or opened.st_uid != self.owner_uid
                    or opened.st_mode & 0o077
                    or (opened.st_dev, opened.st_ino) != (info.st_dev, info.st_ino)):
                raise S3RepositoryManagerError("S3 registry changed during inspection")
            raw = os.read(fd, 256 * 1024 + 1)
        finally:
            os.close(fd)
        try:
            value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique)
        except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
            raise S3RepositoryManagerError("S3 repository registry is malformed") from exc
        if (not isinstance(value, dict) or set(value) != {"schema_version", "repositories"}
                or value["schema_version"] != 1 or isinstance(value["schema_version"], bool)
                or not isinstance(value["repositories"], dict) or len(value["repositories"]) > 128):
            raise S3RepositoryManagerError("S3 repository registry has an invalid schema")
        for identifier, item in value["repositories"].items():
            if (not isinstance(identifier, str) or not _ID.fullmatch(identifier)
                    or not isinstance(item, dict)
                    or set(item) != {"endpoint_url", "region", "bucket", "prefix", "credential_id", "read_only"}):
                raise S3RepositoryManagerError("S3 repository registry contains an invalid entry")
        return value["repositories"]

    def _save(self, entries):
        self._root()
        fd, temporary = tempfile.mkstemp(prefix=".s3-repositories-", dir=self.registry.parent)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump({"schema_version": 1, "repositories": entries}, stream,
                          sort_keys=True, separators=(",", ":"))
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.registry)
            dfd = os.open(self.registry.parent, os.O_RDONLY | getattr(os, "O_DIRECTORY", 0))
            try:
                os.fsync(dfd)
            finally:
                os.close(dfd)
        except Exception:
            try:
                os.unlink(temporary)
            except OSError:
                pass
            raise

    @staticmethod
    def _validate(identifier: str, definition: dict[str, Any]):
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise S3RepositoryManagerError("S3 repository ID is invalid")
        fields = {"endpoint_url", "region", "bucket", "prefix", "credential_id", "read_only"}
        if not isinstance(definition, dict) or set(definition) != fields:
            raise S3RepositoryManagerError("S3 repository definition has missing or unknown fields")
        if definition["endpoint_url"] is not None and (
            not isinstance(definition["endpoint_url"], str) or len(definition["endpoint_url"]) > 512
        ):
            raise S3RepositoryManagerError("endpoint_url must be null or an HTTPS URL")
        if not isinstance(definition["region"], str) or not definition["region"]:
            raise S3RepositoryManagerError("region is required")
        if not isinstance(definition["bucket"], str) or not definition["bucket"]:
            raise S3RepositoryManagerError("bucket is required")
        if not isinstance(definition["prefix"], str) or len(definition["prefix"]) > 512:
            raise S3RepositoryManagerError("prefix must be a string of at most 512 characters")
        if not isinstance(definition["credential_id"], str) or not _ID.fullmatch(definition["credential_id"]):
            raise S3RepositoryManagerError("credential_id is invalid")
        if not isinstance(definition["read_only"], bool):
            raise S3RepositoryManagerError("read_only must be boolean")
        # Validate all public fields through the same strict configuration model.
        try:
            S3RepositoryConfig(
                endpoint_url=definition["endpoint_url"], region=definition["region"],
                bucket=definition["bucket"], prefix=definition["prefix"],
                access_key_id="VALIDACCESSKEY", secret_access_key="placeholder-secret",
                read_only=definition["read_only"],
            )
        except S3RepositoryError as exc:
            raise S3RepositoryManagerError(str(exc)) from exc

    def list(self):
        return [{"id": identifier, **definition, "provider": "s3",
                 "credential_ref": f"feclora-{definition['credential_id']}-s3",
                 "credential_refs": [str(self.credentials._path(definition["credential_id"], "s3"))]}
                for identifier, definition in sorted(self._load().items())]

    def add(self, identifier, definition):
        self._validate(identifier, definition)
        try:
            self.credentials._validate_existing(
                self.credentials._path(definition["credential_id"], "s3")
            )
        except Exception as exc:
            raise S3RepositoryManagerError("selected encrypted S3 credential is unavailable") from exc
        with self._lock():
            entries = self._load()
            if identifier in entries:
                raise S3RepositoryManagerError("S3 repository ID already exists")
            entries[identifier] = dict(definition)
            self._save(entries)
        return {"id": identifier, "provider": "s3"}

    def update(self, identifier, definition):
        self._validate(identifier, definition)
        try:
            self.credentials._validate_existing(
                self.credentials._path(definition["credential_id"], "s3")
            )
        except Exception as exc:
            raise S3RepositoryManagerError("selected encrypted S3 credential is unavailable") from exc
        usage_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            with self._lock():
                entries = self._load()
                if identifier not in entries:
                    raise S3RepositoryManagerError("unknown S3 repository ID")
                entries[identifier] = dict(definition)
                self._save(entries)
        finally:
            os.close(usage_fd)
        return {"id": identifier, "provider": "s3", "updated": True}

    def _acquire_usage_lock(self, identifier: str, *, exclusive: bool) -> int:
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise S3RepositoryManagerError("S3 repository ID is invalid")
        self._root()
        lock_dir = self.registry.parent / "s3-repository-locks"
        lock_dir.mkdir(mode=0o700, exist_ok=True)
        info = os.lstat(lock_dir)
        if not stat.S_ISDIR(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
            raise S3RepositoryManagerError("S3 repository lock directory is unsafe")
        path = lock_dir / (identifier + ".lock")
        fd = -1
        try:
            fd = os.open(path, os.O_RDWR | os.O_CREAT | getattr(os, "O_NOFOLLOW", 0), 0o600)
            info = os.fstat(fd)
            if not stat.S_ISREG(info.st_mode) or info.st_uid != self.owner_uid or info.st_mode & 0o077:
                raise S3RepositoryManagerError("S3 repository usage lock is unsafe")
            fcntl.flock(fd, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            return fd
        except BlockingIOError as exc:
            if fd >= 0:
                os.close(fd)
            raise S3RepositoryManagerError("S3 repository is in use by an active deployment operation") from exc
        except Exception:
            if fd >= 0:
                os.close(fd)
            raise

    def acquire_usage_lock(self, identifier: str) -> int:
        usage_fd = self._acquire_usage_lock(identifier, exclusive=False)
        try:
            # Check existence while holding the lease so remove() cannot
            # delete the definition between validation and lock acquisition.
            if identifier not in self._load():
                raise S3RepositoryManagerError("unknown S3 repository ID")
            return usage_fd
        except Exception:
            os.close(usage_fd)
            raise

    def remove(self, identifier):
        if not isinstance(identifier, str) or not _ID.fullmatch(identifier):
            raise S3RepositoryManagerError("S3 repository ID is invalid")
        usage_fd = self._acquire_usage_lock(identifier, exclusive=True)
        try:
            with self._lock():
                entries = self._load()
                if identifier not in entries:
                    raise S3RepositoryManagerError("unknown S3 repository ID")
                del entries[identifier]
                self._save(entries)
        finally:
            os.close(usage_fd)
        return {"id": identifier, "removed": True}

    def credential_is_referenced(self, credential_id: str) -> bool:
        return any(item["credential_id"] == credential_id for item in self._load().values())

    def repository(self, identifier: str, *, progress=None) -> S3ObjectRepository:
        entries = self._load()
        try:
            definition = entries[identifier]
        except KeyError as exc:
            raise S3RepositoryManagerError("unknown S3 repository ID") from exc
        try:
            raw = self.credentials.read(definition["credential_id"], "s3")
            payload = json.loads(raw.decode("utf-8"))
            config = S3RepositoryConfig(
                endpoint_url=definition["endpoint_url"], region=definition["region"],
                bucket=definition["bucket"], prefix=definition["prefix"],
                access_key_id=payload["access_key_id"],
                secret_access_key=payload["secret_access_key"],
                read_only=definition["read_only"],
            )
            return S3ObjectRepository(config, progress=progress)
        except Exception as exc:
            raise S3RepositoryManagerError(f"cannot initialize S3 repository: {exc}") from exc

    def check(self, identifier: str):
        repository = self.repository(identifier)
        try:
            result = repository.check_connection()
        except Exception as exc:
            raise S3RepositoryManagerError(str(exc)) from exc
        return {"id": identifier, "provider": "s3", **result}
