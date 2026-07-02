# pycargoebuild
# (c) 2022-2024 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import logging
import tarfile
import typing
from pathlib import Path, PurePosixPath
from urllib.parse import urlparse

import pytest

from pycargoebuild.__main__ import main
from pycargoebuild.fetch import fetch_files_using_wget, verify_files


class Package(typing.NamedTuple):
    url: str
    checksum: str
    directories: list[str]
    expected_filename: str | None = None
    crate_license: bool = True
    has_crates_without_license: bool = False
    uses_license_file: bool = False
    uses_licenseref: bool = False
    uses_plus_fallback: bool = False
    use_features: bool = False


PACKAGES = {
    "alass-2.0.0.ebuild": Package(
        url="https://github.com/kaegi/alass/archive/refs/tags/v2.0.0.tar.gz",
        checksum="ce88f92c7a427b623edcabb1b64e80be"
                 "70cca2777f3da4b96702820a6cdf1e26",
        directories=["alass-2.0.0/alass-cli",
                     "alass-2.0.0/alass-core"],
        expected_filename="alass-cli-2.0.0.ebuild"),
    "attest-0.1.0.ebuild": Package(
        url="https://github.com/signalapp/libsignal/archive/v0.38.0.tar.gz",
        checksum="2e31240d41fc31105b3ee9d8c2e0492e"
                 "d0b93bbe62c1003c13fc9de463da60f6",
        directories=["libsignal-0.38.0/rust/attest"],
        uses_license_file=True),
    "bindgen-0.63.0.ebuild": Package(
        url="https://github.com/rust-lang/rust-bindgen/archive/"
            "refs/tags/v0.63.0.tar.gz",
        checksum="9fdfea04da35b9f602967426e4a5893e"
                 "4efb453bceb0d7954efb1b3c88caaf33",
        directories=["rust-bindgen-0.63.0/bindgen"],
        uses_license_file=True),
    "blake3-0.3.3.ebuild": Package(
        url="https://files.pythonhosted.org/packages/7e/88/"
            "271fc900d7e8f091601c01412f3eafb62c62a9ce98091a24a822b4c392c1/"
            "blake3-0.3.3.tar.gz",
        checksum="0a78908b6299fd21dd46eb00fa4592b2"
                 "59ee419d586d545a3b86e1f2e4d0ee6d",
        directories=["blake3-0.3.3"],
        use_features=True),
    "cryptography-38.0.3.ebuild": Package(
        url="https://files.pythonhosted.org/packages/13/dd/"
            "a9608b7aebe5d2dc0c98a4b2090a6b815628efa46cc1c046b89d8cd25f4c/"
            "cryptography-38.0.3.tar.gz",
        checksum="bfbe6ee19615b07a98b1d2287d6a6073"
                 "f734735b49ee45b11324d85efc4d5cbd",
        directories=["cryptography-38.0.3/src/rust"],
        expected_filename="cryptography-rust-0.1.0.ebuild",
        use_features=True),
    "fractal-5.0.0.ebuild": Package(
        url="https://gitlab.gnome.org/GNOME/fractal/-/archive/5/"
            "fractal-5.tar.gz",
        checksum="649fbf06810fb3636098cf576773daa3"
                 "065879794bb1e1984c6cd1bd2509d045",
        directories=["fractal-5"],
        uses_license_file=True,
        uses_plus_fallback=True),
    "lemmy_server-0.18.0.ebuild": Package(
        url="https://github.com/LemmyNet/lemmy/archive/0.18.0.tar.gz",
        checksum="dff7ce501cade3aed2427268d48a27ea"
                 "646159b3e6293db6ff0b78ef46ecba0d",
        directories=["lemmy-0.18.0"],
        uses_license_file=True,
        use_features=True),
    "mdbook-linkcheck-0.7.7.ebuild": Package(
        url="https://github.com/Michael-F-Bryan/mdbook-linkcheck/archive/"
            "v0.7.7.tar.gz",
        checksum="3194243acf12383bd328a9440ab1ae30"
                 "4e9ba244d3bd7f85f1c23b0745c4847a",
        directories=["mdbook-linkcheck-0.7.7"]),
    "milkshake-terminal-0.0.0.ebuild": Package(
        url="https://github.com/mizz1e/milkshake-terminal/archive/"
            "v0.0.1.tar.gz",
        checksum="1230635f2e1f707276f33a9e30e91334"
                 "fcff3df7c0e4d4486596e9c9102776d6",
        directories=["milkshake-terminal-0.0.1"]),
    "qiskit-terra-0.22.3.ebuild": Package(
        url="https://files.pythonhosted.org/packages/98/11/"
            "afb20dd5af0fcf9d5ca57e4cfb2b0b3b1e73fa9dcd39ece82389b77f428a/"
            "qiskit-terra-0.22.3.tar.gz",
        checksum="4dfd246177883c6d1908ff532e384e9a"
                 "e063ceb61236833ad656e2da9953a387",
        directories=["qiskit-terra-0.22.3"]),
    "ruffle_core-0.1.0.ebuild": Package(
        url="https://github.com/ruffle-rs/ruffle/archive/"
            "nightly-2023-06-24.tar.gz",
        checksum="8a47502bcbccae064d45dedde739b2ab"
                 "3f6ccf97fb9feb5e3898d6e11302db87",
        directories=[
            f"ruffle-nightly-2023-06-24/{x}"
            for x
            in ["core", "core/build_playerglobal", "core/macros",
                "desktop", "exporter", "render", "render/canvas",
                "render/naga-agal", "render/naga-pixelbender",
                "render/webgl", "render/wgpu", "scanner", "swf",
                "tests", "tests/input-format", "video",
                "video/software", "web", "web/common",
                "web/packages/extension/safari", "wstr"]
        ],
        has_crates_without_license=True),
    "rustworkx-0.12.1.ebuild": Package(
        url="https://files.pythonhosted.org/packages/17/e6/"
            "924967efd523c0bfed2868b62c334a3339f21fba0ac4b447089731312159/"
            "rustworkx-0.12.1.tar.gz",
        checksum="13a19a2f64dff086b3bffffb294c4630"
                 "100ecbc13634b4995d9d36a481ae130e",
        directories=["rustworkx-0.12.1"]),
    "rustic-rs-0.5.0.ebuild": Package(
        url="https://github.com/rustic-rs/rustic/archive/v0.5.0.tar.gz",
        checksum="cd3cdc17c3165b1533498f713e1c834d"
                 "0d65a80670f65597cc19c508ce15e957",
        directories=["rustic-0.5.0"],
        uses_license_file=True,
        uses_plus_fallback=True),
    "rustls-0.20.7.ebuild": Package(
        url="https://static.crates.io/crates/rustls/0.20.7/download",
        checksum="539a2bfe908f471bfa933876bd1eb6a1"
                 "9cf2176d375f82ef7f99530a40e48c2c",
        directories=["rustls-0.20.7"],
        uses_license_file=True),
    "setuptools-rust-1.5.2.ebuild": Package(
        url="https://files.pythonhosted.org/packages/99/db/"
            "e4ecb483ffa194d632ed44bda32cb740e564789fed7e56c2be8e2a0e2aa6/"
            "setuptools-rust-1.5.2.tar.gz",
        checksum="d8daccb14dc0eae1b6b6eb3ecef79675"
                 "bd37b4065369f79c35393dd5c55652c7",
        directories=[f"setuptools-rust-1.5.2/examples/{x}"
                     for x in ["hello-world",
                               "hello-world-script",
                               "html-py-ever",
                               "namespace_package",
                               "rust_with_cffi",
                               ]],
        expected_filename="hello-world-0.1.0.ebuild",
        crate_license=False),
    "watchfiles-0.18.1.ebuild": Package(
        url="https://files.pythonhosted.org/packages/5e/6a/"
            "2760278f309655cc7305392b0bb664738104202bf5d50396eb138258c5ca/"
            "watchfiles-0.18.1.tar.gz",
        checksum="4ec0134a5e31797eb3c6c624dbe9354f"
                 "2a8ee9c720e0b46fc5b7bab472b7c6d4",
        directories=["watchfiles-0.18.1"],
        expected_filename="watchfiles_rust_notify-0.18.1.ebuild"),
    "synapse-0.1.0.ebuild": Package(
        url="https://files.pythonhosted.org/packages/2b/a0/"
            "fda30d4ec70be0ce89db13c121a1ea72127f91b0b2d6ef6a2f27a1bb61f3/"
            "matrix_synapse-1.72.0.tar.gz",
        checksum="52fd58ffd0865793eb96f4c959c971eb"
                 "e724881863ab0dafca445baf89d21714",
        directories=["matrix_synapse-1.72.0/rust"]),
    "news_flash_gtk-0.0.0.ebuild": Package(
        url="https://gitlab.com/news-flash/news_flash_gtk/-/archive/"
            "v.3.3.4/news_flash_gtk-v.3.3.4.tar.gz",
        checksum="f408f4c2d1e1507008ef583868b84827"
                 "08d13269b86b8e22d2ba73da9c93a0ae",
        directories=["news_flash_gtk-v.3.3.4"],
        has_crates_without_license=True,
        uses_license_file=True,
        use_features=True),
    "fish-shell-4.8.0.ebuild": Package(
        url="https://github.com/fish-shell/fish-shell/archive/"
            "refs/tags/4.8.0.tar.gz",
        checksum="c27e91e3812608d70654cd0640670438"
                 "60f39d9e3fa1171e3af326c852f3e209",
        directories=["fish-shell-4.8.0/crates/fluent-extraction"],
        expected_filename="fish-fluent-extraction-0.0.0.ebuild"),
}


def normalize_ebuild(path: Path) -> str:
    """Strip the dynamic ebuild header for comparison"""
    return "".join(path.read_text(encoding="utf-8").partition("EAPI=")[1:])


@pytest.mark.parametrize("ebuild", PACKAGES)
def test_integration(tmp_path, capfd, caplog, ebuild):
    caplog.set_level(logging.WARNING)

    pkg_info = PACKAGES[ebuild]

    test_dir = Path(__file__).parent
    dist_dir = test_dir / "dist"
    dist_dir.mkdir(exist_ok=True)
    archive_name = PurePosixPath(urlparse(pkg_info.url).path).name
    dist_file = dist_dir / archive_name

    fetch_files_using_wget([(pkg_info.url, dist_file)])
    verify_files([(dist_file, pkg_info.checksum)])
    with tarfile.open(dist_file, "r") as tarf:
        for directory in pkg_info.directories:
            member_toml = tarf.getmember(f"{directory}/Cargo.toml")
            assert member_toml is not None
            tarf.extract(member_toml, tmp_path, set_attrs=False)
            for current in (PurePosixPath(directory) / "Cargo.lock").parents:
                try:
                    member_lock = tarf.getmember(f"{current}/Cargo.lock")
                except KeyError:
                    continue
                else:
                    member_workspace = tarf.getmember(f"{current}/Cargo.toml")
                break
            assert member_lock is not None
            assert member_workspace is not None
            tarf.extract(member_lock, tmp_path, set_attrs=False)
            tarf.extract(member_workspace, tmp_path, set_attrs=False)

    args = ["-d", str(dist_dir),
            "-l", str(test_dir / "license-mapping.conf"),
            "-o", str(tmp_path / "{name}-{version}.ebuild"),
            "--no-config"]
    if not pkg_info.crate_license:
        args.append("-L")
    if pkg_info.use_features:
        args.append("-e")
    args += [str(tmp_path / directory) for directory in pkg_info.directories]

    assert main("test", *args) == 0
    stdout, _ = capfd.readouterr()
    expected = tmp_path / (pkg_info.expected_filename or ebuild)
    assert stdout == str(expected) + "\n"
    assert normalize_ebuild(expected) == normalize_ebuild(test_dir / ebuild)

    records = set(caplog.records)
    if pkg_info.has_crates_without_license:
        # we should get a warning about license-file use
        no_license_warnings = [
            rec for rec in records
            if "does not specify a license" in rec.message]
        assert len(no_license_warnings) > 0
        records.difference_update(no_license_warnings)
    if pkg_info.uses_license_file:
        # we should get a warning about license-file use
        license_file_warnings = [
            rec for rec in records if "uses license-file" in rec.message]
        assert len(license_file_warnings) > 0
        records.difference_update(license_file_warnings)
    if pkg_info.uses_licenseref:
        # we should get a warning about LicenseRef-* use
        licenseref_warnings = [
            rec for rec in records if "User defined license" in rec.message]
        assert len(licenseref_warnings) > 0
        records.difference_update(licenseref_warnings)
    if pkg_info.uses_plus_fallback:
        # we should get a warning about foo+ fallback to foo
        license_file_warnings = [
            rec for rec in records if "No explicit entry for license"
            in rec.message]
        assert len(license_file_warnings) > 0
        records.difference_update(license_file_warnings)
    if len(pkg_info.directories) > 1:
        # we should get a warning about multiple directories
        multiple_dir_warnings = [
            rec for rec in records if "Multiple directories" in rec.message]
        assert len(multiple_dir_warnings) > 0
        records.difference_update(multiple_dir_warnings)
    assert len(records) == 0
