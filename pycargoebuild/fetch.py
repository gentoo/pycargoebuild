# pycargoebuild
# (c) 2022-2024 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import hashlib
import subprocess
import sys
import tempfile
import typing
from pathlib import Path

from pycargoebuild import __version__
from pycargoebuild.cargo import Crate, FileCrate


class ChecksumMismatchError(RuntimeError):
    def __init__(self,
                 path: Path,
                 current: str,
                 expected: str,
                 ) -> None:
        super().__init__(f"Checksum mismatch for {path}\n"
                         f" current: {current}\n"
                         f"expected: {expected}")
        self.path = path
        self.current = current
        self.expected = expected


def fetch_crates_using_aria2(crates: typing.Iterable[Crate], *, distdir: Path
                             ) -> None:
    """
    Fetch specified crates into distdir using aria2c(1)
    """

    distdir.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w+") as file_list_f:
        by_filename = {crate.filename: crate for crate in crates}
        for filename, crate in by_filename.items():
            if not (distdir / filename).exists():
                file_list_f.write(
                    f"{crate.download_url}\n\tout={crate.filename}\n")

        if file_list_f.tell() == 0:
            # no crates to fetch
            return

        file_list_f.flush()

        subprocess.check_call(
            ["aria2c",
                "-U", f"pycargoebuild/{__version__} (https://github.com/gentoo/pycargoebuild)",
                "-d", str(distdir),
                "-i", file_list_f.name],
            stdout=sys.stderr)


def fetch_files_using_wget(files: typing.Iterable[typing.Tuple[str, Path]]
                           ) -> None:
    """
    Fetch specified URLs to the specified filenames using wget(1)
    """

    for url, path in files:
        if not path.exists():
            subprocess.check_call(
                ["wget",
                    "-U", f"pycargoebuild/{__version__} (https://github.com/gentoo/pycargoebuild)",
                    "-O", str(path), url],
                stdout=sys.stderr)


def fetch_crates_using_wget(crates: typing.Iterable[Crate], *, distdir: Path
                            ) -> None:
    """
    Fetch specified crates into distdir using wget(1)
    """

    distdir.mkdir(parents=True, exist_ok=True)
    fetch_files_using_wget(
        (crate.download_url, distdir / crate.filename) for crate in crates)


def verify_files(files: typing.Iterable[typing.Tuple[Path, str]]) -> None:
    """
    Verify checksums of specified files
    """

    buffer = bytearray(128 * 1024)
    mv = memoryview(buffer)
    for path, checksum in files:
        with open(path, "rb", buffering=0) as f:
            hasher = hashlib.sha256()
            while True:
                rd = f.readinto(mv)
                if rd == 0:
                    break
                hasher.update(mv[:rd])
            if hasher.hexdigest() != checksum:
                raise ChecksumMismatchError(path, hasher.hexdigest(), checksum)


def verify_crates(crates: typing.Iterable[Crate], *, distdir: Path) -> None:
    """
    Verify checksums of crates fetched into distdir
    """

    verify_files((distdir / crate.filename, crate.checksum)
                 for crate in crates
                 if isinstance(crate, FileCrate))
