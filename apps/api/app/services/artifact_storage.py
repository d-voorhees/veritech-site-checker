"""Artifact storage abstraction.

The MVP stores screenshots and HTML report exports on a local filesystem
path (`ARTIFACT_STORAGE_LOCAL_PATH`). This interface is the seam that lets a future
S3/R2-compatible backend replace local storage without touching collectors,
the rules engine, or report generation — callers only ever see
`ArtifactStorage.save` / `.read` / `.url_for`.
"""

import abc
from pathlib import Path

from app.config import get_settings


class ArtifactStorage(abc.ABC):
    @abc.abstractmethod
    def save(self, relative_path: str, content: bytes) -> str:
        """Persist content and return a storage reference (path or key)."""

    @abc.abstractmethod
    def read(self, reference: str) -> bytes:
        """Read back content by storage reference."""

    @abc.abstractmethod
    def exists(self, reference: str) -> bool:
        ...


class LocalArtifactStorage(ArtifactStorage):
    def __init__(self, base_path: str) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)

    def _resolve(self, relative_path: str) -> Path:
        # Prevent path traversal outside the artifact root.
        candidate = (self.base_path / relative_path).resolve()
        if not str(candidate).startswith(str(self.base_path.resolve())):
            raise ValueError("Invalid artifact path")
        return candidate

    def save(self, relative_path: str, content: bytes) -> str:
        target = self._resolve(relative_path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
        return relative_path

    def read(self, reference: str) -> bytes:
        return self._resolve(reference).read_bytes()

    def exists(self, reference: str) -> bool:
        try:
            return self._resolve(reference).exists()
        except ValueError:
            return False


_storage_instance: ArtifactStorage | None = None


def get_artifact_storage() -> ArtifactStorage:
    global _storage_instance
    if _storage_instance is not None:
        return _storage_instance

    settings = get_settings()
    if settings.artifact_storage_backend == "local":
        _storage_instance = LocalArtifactStorage(settings.artifact_storage_local_path)
    else:
        raise NotImplementedError(
            f"Artifact storage backend {settings.artifact_storage_backend!r} is not implemented. "
            "Implement an ArtifactStorage subclass (e.g. S3ArtifactStorage) and wire it here."
        )
    return _storage_instance
