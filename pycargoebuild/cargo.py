# pycargoebuild
# (c) 2022-2024 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

import dataclasses
import enum
import functools
import sys
import tarfile
import typing
import urllib.parse
from pathlib import Path, PurePath

if sys.version_info >= (3, 11):
    import tomllib
else:
    import tomli as tomllib


CRATE_REGISTRY = "registry+https://github.com/rust-lang/crates.io-index"


@dataclasses.dataclass(frozen=True)
class Crate:
    name: str
    version: str

    @property
    def filename(self) -> str:
        return f"{self.name}-{self.version}.crate"

    def get_workspace_toml(self, distdir: Path) -> dict:
        return {}

    def get_package_directory(self, distdir: Path) -> PurePath:
        return PurePath(f"{self.name}-{self.version}")

    def get_root_directory(self, distdir: Path) -> PurePath | None:
        return self.get_package_directory(distdir)

    @property
    def download_url(self) -> str:
        raise NotImplementedError()


@dataclasses.dataclass(frozen=True)
class FileCrate(Crate):
    checksum: str

    @property
    def download_url(self) -> str:
        return (f"https://static.crates.io/crates/{self.name}/{self.version}/"
                "download")

    @property
    def crate_entry(self) -> str:
        return f"{self.name}@{self.version}"


class GitHost(enum.Enum):
    GITHUB = enum.auto()
    GITLAB = enum.auto()
    GITLAB_SELFHOSTED = enum.auto()
    GITEA = enum.auto()


@dataclasses.dataclass(frozen=True)
class GitCrate(Crate):
    repository: str
    commit: str

    def __post_init__(self) -> None:
        self.repo_host  # check for supported git hosts

    @functools.cached_property
    def repo_host(self) -> GitHost:
        if self.repository.startswith("https://github.com/"):
            return GitHost.GITHUB
        if self.repository.startswith("https://gitlab.com/"):
            return GitHost.GITLAB
        if self.repository.startswith("https://gitlab."):
            return GitHost.GITLAB_SELFHOSTED
        if self.repository.startswith("https://codeberg.org/"):
            return GitHost.GITEA
        raise RuntimeError("Unsupported git crate source: "
                           f"{self.repository}")

    @property
    def repo_name(self) -> str:
        return self.repository.rpartition("/")[2]

    @property
    def repo_ext(self) -> str:
        """Used by cargo.eclass to abbreviate crate URI"""
        match self.repo_host:
            case GitHost.GITHUB:
                return ".gh"
            case GitHost.GITLAB:
                return ".gl"
            case GitHost.GITLAB_SELFHOSTED:
                return ""
            case GitHost.GITEA:
                return ".gt"
            case _ as host:
                typing.assert_never(host)

    @property
    def download_url(self) -> str:
        match self.repo_host:
            case GitHost.GITHUB | GitHost.GITEA:
                return f"{self.repository}/archive/{self.commit}.tar.gz"
            case GitHost.GITLAB | GitHost.GITLAB_SELFHOSTED:
                return (f"{self.repository}/-/archive/{self.commit}/"
                        f"{self.repo_name}-{self.commit}.tar.gz")
            case _ as host:
                typing.assert_never(host)

    @property
    def filename(self) -> str:
        return f"{self.repo_name}-{self.commit}{self.repo_ext}.tar.gz"

    @functools.cache
    def get_workspace_toml(self, distdir: Path) -> dict:
        filename = self.filename
        root_dir = self.get_root_directory(distdir)
        if root_dir is None:
            return {}
        with tarfile.open(distdir / filename, "r:gz") as crate_tar:
            tarf = crate_tar.extractfile(str(root_dir / "Cargo.toml"))
            if tarf is None:
                raise RuntimeError(
                    f"{root_dir}/Cargo.toml not found in {filename}")
            with tarf:
                # tarfile.ExFileObject() is IO[bytes] while tomli/tomllib
                # expects BinaryIO -- but it actually is compatible
                # https://github.com/hukkin/tomli/issues/214
                return (tomllib.load(tarf).get("workspace", {})  # type: ignore
                                          .get("package", {}))

    @functools.cache
    def get_package_directory(self, distdir: Path) -> PurePath:
        workspace_toml = self.get_workspace_toml(distdir)
        # TODO: perhaps it'd be more correct to follow workspaces
        with tarfile.open(distdir / self.filename, "r:gz") as crate_tar:
            while (tar_info := crate_tar.next()) is not None:
                path = PurePath(tar_info.name)
                if path.name == "Cargo.toml":
                    f = crate_tar.extractfile(tar_info)
                    if f is None:
                        continue

                    # tarfile.ExFileObject() is IO[bytes] while tomli/tomllib
                    # expects BinaryIO -- but it actually is compatible
                    # https://github.com/hukkin/tomli/issues/214
                    try:
                        metadata = get_package_metadata(
                            f, workspace_toml)  # type: ignore
                    except WorkspaceCargoTomlError:
                        continue
                    if (metadata.name == self.name and
                            metadata.version == self.version):
                        return path.parent

        raise RuntimeError(f"Package {self.name} not found in crate "
                           f"{distdir / self.filename}")

    def get_git_crate_entry(self, distdir: Path) -> str:
        subdir = (str(self.get_package_directory(distdir))
                  .replace(self.commit, "%commit%"))
        match self.repo_host:
            case GitHost.GITHUB | GitHost.GITLAB:
                return f"{self.repository};{self.commit};{subdir}"
            case GitHost.GITEA:
                return f"{self.repository};{self.commit};{subdir};gitea"
            case GitHost.GITLAB_SELFHOSTED:
                crate_uri = self.download_url.replace(self.commit, "%commit%")
                return f"{crate_uri};{self.commit};{subdir}"
            case _ as host:
                typing.assert_never(host)

    @functools.cache
    def get_root_directory(self, distdir: Path) -> PurePath | None:
        """Get the directory containing Cargo.lock"""
        with tarfile.open(distdir / self.filename, "r:gz") as crate_tar:
            while (tar_info := crate_tar.next()) is not None:
                path = PurePath(tar_info.name)
                if path.name == "Cargo.lock":
                    return path.parent
                if path.name == "Cargo.toml":
                    tarf = crate_tar.extractfile(tar_info)
                    assert tarf is not None
                    with tarf:
                        if "workspace" in tomllib.load(tarf):  # type: ignore
                            return path.parent
        return None


class PackageMetadata(typing.NamedTuple):
    name: str
    version: str
    features: dict[str, bool] = {}
    license: str | None = None
    license_file: str | None = None
    description: str | None = None
    homepage: str | None = None

    def with_replaced_license(self, new_license: str | None
                              ) -> "PackageMetadata":
        return PackageMetadata(name=self.name,
                               version=self.version,
                               features=self.features,
                               license=new_license,
                               license_file=None,
                               description=self.description,
                               homepage=self.homepage)


class WorkspaceCargoTomlError(RuntimeError):
    """Cargo.toml belongs to a workspace root"""

    def __init__(self, members: list[str]) -> None:
        super().__init__()
        self.members = members


def cargo_to_spdx(license_str: str) -> str:
    """
    Convert deprecated Cargo license string to SPDX-2.0, if necessary.
    """
    return license_str.replace("/", " OR ")


def get_crates(f: typing.BinaryIO) -> typing.Generator[Crate, None, None]:
    """Read crate list from the open ``Cargo.lock`` file"""
    cargo_lock = tomllib.load(f)
    lock_version = cargo_lock.get("version", None)
    if lock_version not in (None, 3, 4):
        raise NotImplementedError(
            f"Cargo.lock version '{cargo_lock['version']} unsupported")

    for p in cargo_lock["package"]:
        # Skip all crates without "source", they should be local.
        if "source" not in p:
            continue

        try:
            if p["source"] == CRATE_REGISTRY:
                if lock_version is None:
                    checksum = cargo_lock["metadata"][
                        f"checksum {p['name']} {p['version']} "
                        f"({p['source']})"]
                else:
                    checksum = p["checksum"]
                yield FileCrate(name=p["name"],
                                version=p["version"],
                                checksum=checksum)
            elif p["source"].startswith("git+"):
                parsed_url = urllib.parse.urlsplit(p["source"])
                if not parsed_url.fragment:
                    raise RuntimeError(
                        "Git crate with no fragment identifier (i.e. commit "
                        f"identifier): {p['source']!r}")
                repo = parsed_url.path.strip("/").removesuffix(".git")
                if repo.count("/") != 1:
                    raise RuntimeError("Invalid GitHub/GitLab URL: "
                                       f"{p['source']}")
                yield GitCrate(
                    name=p["name"],
                    version=p["version"],
                    repository=f"https://{parsed_url.netloc}/{repo}",
                    commit=parsed_url.fragment)
            else:
                raise RuntimeError(f"Unsupported crate source: {p['source']}")
        except KeyError as e:
            raise RuntimeError("Incorrect/insufficient metadata for crate: "
                               f"{p!r}") from e


def get_meta_key(key: str, pkg_meta: dict,
                 workspace_pkg_meta: dict) -> str | None:
    """Get a key from package metadata respecting ``workspace: true``"""
    value = pkg_meta.get(key)

    if isinstance(value, str) or value is None:
        return value
    if isinstance(value, dict) and value.get("workspace") is True:
        return get_meta_key(key, workspace_pkg_meta, {})
    raise ValueError(f"Invalid metadata key value: {key!r}={value!r}")


def get_package_metadata(f: typing.BinaryIO,
                         workspace_pkg_meta: dict | None = None,
                         ) -> PackageMetadata:
    """Read package from the open ``Cargo.toml`` file"""
    if workspace_pkg_meta is None:
        workspace_pkg_meta = {}
    cargo_toml = tomllib.load(f)

    if "package" not in cargo_toml and "workspace" in cargo_toml:
        raise WorkspaceCargoTomlError(
            cargo_toml["workspace"]["members"])

    pkg_meta = cargo_toml["package"]
    _get_meta_key = functools.partial(get_meta_key,
                                      pkg_meta=pkg_meta,
                                      workspace_pkg_meta=workspace_pkg_meta)

    pkg_license = _get_meta_key("license")
    if pkg_license is not None:
        pkg_license = cargo_to_spdx(pkg_license)

    # missing version field is legal in rust >= 1.75 and defaults to 0.0.0:
    # https://doc.rust-lang.org/cargo/reference/manifest.html#the-version-field
    pkg_version = _get_meta_key("version")
    if pkg_version is None:
        pkg_version = "0.0.0"

    features = cargo_toml.get("features", {})
    default_features = features.pop("default", [])

    return PackageMetadata(
        name=pkg_meta["name"],
        version=pkg_version,
        license=pkg_license,
        features={name: name in default_features for name in features},
        license_file=_get_meta_key("license-file"),
        description=_get_meta_key("description"),
        homepage=_get_meta_key("homepage"))
