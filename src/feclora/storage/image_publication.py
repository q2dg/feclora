"""Safe manifest-last publication of immutable image sets.

The staging directory must be a private child of the repository. Directory
file descriptors pin both directories while publishing and rolling back.
Rollback removes a final name only while it still identifies this attempt's
staged inode; it never unlinks a concurrent replacement.
"""
from __future__ import annotations

import os
import stat
from collections.abc import Sequence


class ImagePublicationError(RuntimeError):
    """An image set could not be safely published."""


def publish_image_set(
    repository: str | os.PathLike[str],
    stage: str | os.PathLike[str],
    names: Sequence[str],
) -> None:
    """Publish payload/signature names in order and the manifest last."""
    if not names or len(set(names)) != len(names):
        raise ImagePublicationError("publication names must be non-empty and unique")
    for name in names:
        if (not isinstance(name, str) or not name or name in {".", ".."}
                or "/" in name or "\\" in name or "\x00" in name):
            raise ImagePublicationError("publication contains an unsafe filename")

    repo_path = os.fspath(repository)
    stage_path = os.fspath(stage)
    repo_fd = stage_fd = None
    linked: list[tuple[str, int, int]] = []
    committed = False
    try:
        repo_info = os.lstat(repo_path)
        stage_info = os.lstat(stage_path)
        if not stat.S_ISDIR(repo_info.st_mode) or not stat.S_ISDIR(stage_info.st_mode):
            raise ImagePublicationError("repository and staging paths must be real directories")
        flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
        repo_fd = os.open(repo_path, flags)
        stage_fd = os.open(stage_path, flags)
        opened_repo = os.fstat(repo_fd)
        opened_stage = os.fstat(stage_fd)
        stage_parent = os.stat("..", dir_fd=stage_fd, follow_symlinks=False)
        if ((opened_repo.st_dev, opened_repo.st_ino) != (repo_info.st_dev, repo_info.st_ino)
                or (opened_stage.st_dev, opened_stage.st_ino) != (stage_info.st_dev, stage_info.st_ino)
                or (stage_parent.st_dev, stage_parent.st_ino) != (opened_repo.st_dev, opened_repo.st_ino)):
            raise ImagePublicationError("repository or staging directory changed during publication setup")

        for name in names:
            source = os.stat(name, dir_fd=stage_fd, follow_symlinks=False)
            if not stat.S_ISREG(source.st_mode):
                raise ImagePublicationError(f"staged image component is not a regular file: {name}")
            os.link(name, name, src_dir_fd=stage_fd, dst_dir_fd=repo_fd, follow_symlinks=False)
            linked.append((name, source.st_dev, source.st_ino))
        os.fsync(repo_fd)
        committed = True
    except FileExistsError:
        raise
    except ImagePublicationError:
        raise
    except OSError as exc:
        raise ImagePublicationError(f"image-set publication failed: {exc}") from exc
    finally:
        if not committed and repo_fd is not None:
            for name, device, inode in reversed(linked):
                try:
                    current = os.stat(name, dir_fd=repo_fd, follow_symlinks=False)
                    if (current.st_dev, current.st_ino) == (device, inode):
                        os.unlink(name, dir_fd=repo_fd)
                except FileNotFoundError:
                    pass
                except OSError:
                    # Preserve the primary publication error; never guess at
                    # ownership of a name that can no longer be inspected.
                    pass
            try:
                os.fsync(repo_fd)
            except OSError:
                pass
        if stage_fd is not None:
            os.close(stage_fd)
        if repo_fd is not None:
            os.close(repo_fd)
