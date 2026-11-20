import asyncio
import os
import shutil
from contextlib import AbstractContextManager
from pathlib import Path
from typing import BinaryIO, Protocol


class FileStore(Protocol):
    """Storage for uploaded files, addressed by keys like `owner/document/version.pdf`."""

    async def put(self, key: str, source: Path) -> None:
        """Move `source` into the store under `key`, replacing any existing file."""
        ...

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        """Open the stored file for binary reading."""
        ...

    async def delete_prefix(self, prefix: str) -> None:
        """Remove everything stored under `prefix`; a missing prefix is not an error."""
        ...


class LocalFileStore:
    """A `FileStore` on a local directory.

    Args:
        root: Directory that holds the files. `put` moves files with an atomic rename, so
            sources must be on the same filesystem as `root`.
    """

    def __init__(self, root: Path) -> None:
        self._root: Path = root

    def resolve(self, key: str) -> Path:
        """Map a key to its path under the root.

        Raises:
            ValueError: If the key is empty or absolute, contains a backslash or NUL character,
                has an empty, `.` or `..` path segment, or would not stay strictly below the root.
        """
        segments: list[str] = key.split("/")
        if (
            not key
            or "\\" in key
            or "\0" in key
            or any(segment in ("", ".") or ".." in segment for segment in segments)
        ):
            raise ValueError(f"Unsafe file key: {key!r}")
        path: Path = self._root / key
        resolved_root: Path = self._root.resolve()
        resolved: Path = path.resolve()
        if resolved == resolved_root or not resolved.is_relative_to(resolved_root):
            raise ValueError(f"Unsafe file key: {key!r}")
        return path

    async def put(self, key: str, source: Path) -> None:
        destination: Path = self.resolve(key)
        await asyncio.to_thread(self._move, source, destination)

    @staticmethod
    def _move(source: Path, destination: Path) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, destination)

    def open(self, key: str) -> AbstractContextManager[BinaryIO]:
        return self.resolve(key).open("rb")

    async def delete_prefix(self, prefix: str) -> None:
        """Remove the directory or file at `prefix`, which may end in one `/`.

        Raises:
            ValueError: If the prefix is unsafe or names the root itself.
        """
        target: Path = self.resolve(prefix.removesuffix("/"))
        await asyncio.to_thread(self._remove, target)

    @staticmethod
    def _remove(target: Path) -> None:
        if target.is_dir():
            shutil.rmtree(target, ignore_errors=True)
        else:
            target.unlink(missing_ok=True)
