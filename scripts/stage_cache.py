#!/usr/bin/env python3
"""Content-addressed, hash-validated cache for deterministic pipeline stages."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from dataclasses import asdict, dataclass, is_dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


CACHE_SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CacheHit:
    key: str
    artifact: Path
    metadata: dict[str, Any]


@dataclass(frozen=True)
class PruneResult:
    entries_removed: int
    bytes_removed: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: Any) -> Any:
    if is_dataclass(value):
        return _normalize(asdict(value))
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, dict):
        return {str(key): _normalize(item) for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))}
    if isinstance(value, (list, tuple)):
        return [_normalize(item) for item in value]
    if isinstance(value, set):
        return sorted(_normalize(item) for item in value)
    return value


def build_cache_key(
    source_hashes: Any,
    segments: Any,
    profile: Any,
    options: Any,
    tool_version: str,
) -> str:
    payload = {
        "source_hashes": _normalize(source_hashes),
        "segments": _normalize(segments),
        "profile": _normalize(profile),
        "options": _normalize(options),
        "tool_version": tool_version,
    }
    encoded = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def hash_path(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _directory_size(path: Path) -> int:
    return sum(item.stat().st_size for item in path.rglob("*") if item.is_file())


class StageCache:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    def entry_dir(self, key: str) -> Path:
        if not key or any(part in key for part in ("/", "\\", "..")):
            raise ValueError("invalid cache key")
        return self.root / key

    def lookup(self, key: str) -> CacheHit | None:
        entry = self.entry_dir(key)
        metadata_path = entry / "metadata.json"
        if not metadata_path.is_file():
            return None
        try:
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            artifact = entry / metadata["artifact_name"]
        except (OSError, KeyError, json.JSONDecodeError):
            return None
        if metadata.get("schema_version") != CACHE_SCHEMA_VERSION or metadata.get("key") != key:
            return None
        if metadata.get("validation_status") != "pass" or not artifact.is_file():
            return None
        if hash_path(artifact) != metadata.get("sha256"):
            return None
        metadata["accessed_at"] = _now()
        temp_path = metadata_path.with_suffix(".json.tmp")
        temp_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        os.replace(temp_path, metadata_path)
        return CacheHit(key=key, artifact=artifact, metadata=metadata)

    def store(
        self,
        key: str,
        artifact: Path,
        *,
        validation_status: str,
        metadata: dict[str, Any] | None = None,
    ) -> CacheHit:
        if not artifact.is_file():
            raise FileNotFoundError(artifact)
        entry = self.entry_dir(key)
        temp = Path(tempfile.mkdtemp(prefix=f".{key[:12]}-", dir=self.root))
        try:
            artifact_name = f"artifact{artifact.suffix.lower()}"
            cached_artifact = temp / artifact_name
            shutil.copy2(artifact, cached_artifact)
            now = _now()
            payload = {
                **(metadata or {}),
                "schema_version": CACHE_SCHEMA_VERSION,
                "key": key,
                "artifact_name": artifact_name,
                "sha256": hash_path(cached_artifact),
                "validation_status": validation_status,
                "created_at": now,
                "accessed_at": now,
            }
            (temp / "metadata.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            if entry.exists():
                shutil.rmtree(entry)
            os.replace(temp, entry)
        finally:
            if temp.exists():
                shutil.rmtree(temp)
        hit = self.lookup(key)
        if hit is None:
            raise RuntimeError("stored cache entry failed validation")
        return hit

    def materialize(self, hit: CacheHit, destination: Path) -> Path:
        destination.parent.mkdir(parents=True, exist_ok=True)
        temp_path = destination.with_suffix(destination.suffix + ".tmp")
        shutil.copy2(hit.artifact, temp_path)
        os.replace(temp_path, destination)
        return destination

    def prune(self, referenced_keys: Iterable[str]) -> PruneResult:
        referenced = set(referenced_keys)
        entries_removed = 0
        bytes_removed = 0
        for entry in self.root.iterdir():
            if not entry.is_dir() or entry.name.startswith(".") or entry.name in referenced:
                continue
            bytes_removed += _directory_size(entry)
            shutil.rmtree(entry)
            entries_removed += 1
        return PruneResult(entries_removed=entries_removed, bytes_removed=bytes_removed)
