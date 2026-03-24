# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""Blob storage protocol for syncing session databases to remote storage.

No concrete implementation yet — just the protocol.
Add ``S3BlobBackend`` or ``GCSBlobBackend`` when cloud deployment is needed.
"""

from __future__ import annotations
from pathlib import Path
from typing import Protocol, runtime_checkable


@runtime_checkable
class BlobBackend(Protocol):
    """Interface for uploading/downloading session .db files."""

    async def download(self, key: str, dest: Path) -> None: ...

    async def upload(self, src: Path, key: str) -> None: ...

    async def exists(self, key: str) -> bool: ...
