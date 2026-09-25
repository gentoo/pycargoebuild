# pycargoebuild
# (c) 2022-2026 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import argparse
import datetime
import enum
import io
import json
import logging
import lzma
import os.path
import stat
import subprocess
import sys
import tarfile
import tempfile
import typing
from pathlib import Path, PurePosixPath

if sys.version_info >= (3, 15):
    import tomllib
else:
    import tomli as tomllib

from pycargoebuild.cargo import (
    Crate,
    FileCrate,
    WorkspaceCargoTomlError,
    get_crates,
    get_package_metadata,
)
from pycargoebuild.ebuild import get_ebuild, update_ebuild
from pycargoebuild.fetch import (
    ChecksumMismatchError,
    fetch_crates_using_aria2,
    fetch_crates_using_wget,
    verify_crates,
)
from pycargoebuild.license import (
    MAPPING,
    UnmatchedLicense,
    load_license_mapping,
)

FETCHERS = ("aria2", "wget")


class WorkspaceData(typing.NamedTuple):
    crates: frozenset[Crate]
    workspace_metadata: dict


class Mode(enum.Enum):
    WRITE_CRATE_TARBALL = enum.auto()
    USE_CRATE_TARBALL = enum.auto()
    FILL_CRATES = enum.auto()


def main(prog_name: str, *argv: str) -> int:
    argp = argparse.ArgumentParser(prog=os.path.basename(prog_name))

    # mode
    mode_g_outer = argp.add_argument_group("mode")
    mode_g = mode_g_outer.add_mutually_exclusive_group()
    mode_g.add_argument("-w", "--write-crate-tarball",
                        dest="mode",
                        action="store_const",
                        const=Mode.WRITE_CRATE_TARBALL,
                        help="Pack fetched crates into a tarball and do not "
                             "fill CRATES variable")
    mode_g.add_argument("-u", "--use-crate-tarball",
                        dest="mode",
                        action="store_const",
                        const=Mode.USE_CRATE_TARBALL,
                        help="Assume crate tarball exists and do not fill "
                             "CRATES variable")
    mode_g.add_argument("-C", "--fill-crates",
                        dest="mode",
                        action="store_const",
                        const=Mode.FILL_CRATES,
                        help="Fill the CRATES variable directly")

    # option flags
    opt_g = argp.add_argument_group("common flags")
    opt_g.add_argument("-e", "--features",
                       action="store_true",
                       help="Add USE flags for Cargo features")
    opt_g.add_argument("-f", "--force",
                       action="store_true",
                       help="Force overwriting the output file")
    opt_g.add_argument("-i", "--input", "--inplace",
                       type=Path,
                       metavar="INPUT",
                       help="Update the CRATES and LICENSE variables "
                            "in the specified ebuild instead of creating "
                            "one from scratch")
    opt_g.add_argument("-L", "--no-license",
                       action="store_true",
                       help="Do not include LICENSEs (e.g. when crates are "
                            "only used at build time)")
    opt_g.add_argument("-M", "--no-manifest",
                       action="store_true",
                       help="Do not call `pkgdev manifest` (called only if "
                            "Manifest exists)")
    opt_g.add_argument("-o", "--output",
                       help="Ebuild file to write (default: INPUT if --input "
                            "is specified, {name}-{version}.ebuild otherwise)")

    cfg_g = argp.add_argument_group("configuration flags")
    cfg_g.add_argument("-d", "--distdir",
                       type=Path,
                       help="Directory to store downloaded crates in "
                            "(default: get from Portage)")
    cfg_g.add_argument("-F", "--fetcher",
                       choices=("auto",) + FETCHERS,
                       default="auto",
                       help="Fetcher to use")
    cfg_g.add_argument("-l", "--license-mapping",
                       type=Path,
                       help="Path to license-mapping.conf file (default: "
                            "get from Portage)")
    cfg_g.add_argument("--no-config",
                      action="store_true",
                      help="Inhibit loading configuration files")

    ct_opt_g = argp.add_argument_group("crate tarball options")
    ct_opt_g.add_argument("-c", "--crate-tarball",
                          action="store_true",
                          help="Pack fetched crates into a tarball rather "
                               "than adding them to the CRATES variable "
                               "(deprecated, use --write-crate-tarball or "
                               "--use-crate-tarball)")
    ct_opt_g.add_argument("--crate-tarball-path",
                          default="{distdir}/{name}-{version}-crates.tar.xz",
                          help="Path to write crate tarball to (default: "
                               "{distdir}/{name}-{version}-crates.tar.xz)")
    ct_opt_g.add_argument("--crate-tarball-prefix",
                          default="cargo_home/gentoo",
                          help="Prefix prepended for all paths in the crate "
                               "tarball (default: cargo_home/gentoo)")
    ct_opt_g.add_argument("--no-write-crate-tarball",
                          action="store_true",
                          help="Do not create the crate tarball, just write "
                               "the ebuild assuming it exists (deprecated, "
                               "use --use-crate-tarball instead)")
    argp.add_argument("directory",
                      type=Path,
                      default=[Path(".")],
                      nargs="*",
                      help="Directory containing Cargo.* files (default: .)")
    args = argp.parse_args(argv)

    if args.mode is None:
        if not args.crate_tarball:
            args.mode = Mode.FILL_CRATES
            repl = "-C or --fill-crates"
        elif args.no_write_crate_tarball:
            args.mode = Mode.USE_CRATE_TARBALL
            repl = "-u or --use-crate-tarball"
        else:
            args.mode = Mode.WRITE_CRATE_TARBALL
            repl = "-w or --write-crate-tarball"
        logging.warning(
            "The mode argument will be required in the future. Please pass "
            f"{repl} for the mode implied by current flags."
        )

    config_toml = {}
    if not args.no_config:
        config_dirs = os.environ.get("XDG_CONFIG_DIRS", "/etc/xdg").split(":")
        config_dirs.insert(0, os.environ.get("XDG_CONFIG_HOME", "~/.config"))
        for x in config_dirs:
            config_path = Path(os.path.expanduser(x)) / "pycargoebuild.toml"
            try:
                with open(config_path, "rb") as f:
                    config_toml = tomllib.load(f)
            except (FileNotFoundError, NotADirectoryError):
                pass
            except tomllib.TOMLDecodeError as e:
                raise RuntimeError(
                    f"Error parsing configuration file {config_path}") from e
            else:
                logging.info(f"Using configuration file {config_path}")
                break

    # load defaults from config file
    config_toml_paths = config_toml.get("paths", {})
    if args.distdir is None:
        default_distdir = config_toml_paths.get("distdir")
        if default_distdir is not None:
            args.distdir = Path(default_distdir)
    if args.license_mapping is None:
        # may still be None
        args.license_mapping = config_toml_paths.get("license-mapping")

    if args.distdir is None or args.license_mapping is None:
        from portage import create_trees
        trees = create_trees()
        tree = trees[max(trees)]
        if args.distdir is None:
            args.distdir = Path(tree["porttree"].settings["DISTDIR"])
        if args.license_mapping is None:
            repo = Path(tree["porttree"].dbapi.repositories["gentoo"].location)
            args.license_mapping = repo / "metadata/license-mapping.conf"

    with open(args.license_mapping, "r", encoding="utf-8") as f:
        load_license_mapping(f)
    MAPPING.update(
        (k.lower(), v) for k, v
        in config_toml.get("license-mapping", {}).items())

    def iterate_parents(directory: Path) -> typing.Generator[Path, None, None]:
        root = directory.absolute().root
        yield directory
        while not directory.samefile(root):
            directory /= ".."
            yield directory

    def get_workspace_root(start_directory: Path) -> WorkspaceData:
        err: Exception | None = None
        for directory in iterate_parents(start_directory):
            try:
                with open(directory / "Cargo.lock", "rb") as cargo_lock:
                    try:
                        with open(directory / "Cargo.toml",
                                  "rb") as cargo_toml:
                            workspace_toml = (
                                tomllib.load(cargo_toml).get("workspace", {})
                                                        .get("package", {}))
                    except FileNotFoundError:
                        workspace_toml = {}

                    return WorkspaceData(
                        crates=frozenset(get_crates(cargo_lock)),
                        workspace_metadata=workspace_toml)
            except FileNotFoundError as e:
                if err is None:
                    err = e
        raise RuntimeError(
            "Cargo.lock not found in any of the parent directories") from err

    def try_fetcher(name: str,
                    func: typing.Callable[..., None],
                    crates: typing.Iterable[Crate],
                    ) -> bool:
        if args.fetcher == "auto":
            try:
                func(crates, distdir=args.distdir)
            except FileNotFoundError:
                return False
        elif args.fetcher == name:
            func(crates, distdir=args.distdir)
        else:
            return False
        return True

    def fetch_crates(crates: typing.Iterable[Crate]) -> None:
        if (not try_fetcher("aria2", fetch_crates_using_aria2, crates) and
                not try_fetcher("wget", fetch_crates_using_wget, crates)):
            if args.fetcher == "auto":
                raise RuntimeError(
                    "No supported fetcher found (out of "
                    f"{', '.join(FETCHERS)})")
            assert False, f"Unexpected args.fetcher={args.fetcher}"

    def repack_crates(tar_out: tarfile.TarFile,
                      crates: set[Crate],
                      ) -> None:
        prefix = args.crate_tarball_prefix
        start_time = datetime.datetime.now(tz=datetime.timezone.utc)
        interval = datetime.timedelta(seconds=10)
        next_ping = start_time + interval
        for crate_no, crate in enumerate(sorted(crates,
                                                key=lambda x: x.filename)):
            now = datetime.datetime.now(tz=datetime.timezone.utc)
            if now > next_ping:
                logging.info(
                    f"Processed {crate_no} out of {len(crates)} crates")
                next_ping = now + interval
            if isinstance(crate, FileCrate):
                with tarfile.open(args.distdir / crate.filename,
                                  "r:gz") as tar_in:
                    crate_dir = crate.get_package_directory(args.distdir)
                    for tar_info in tar_in:
                        orig_name = PurePosixPath(tar_info.path)
                        assert orig_name.is_relative_to(crate_dir)
                        member_file = tar_in.extractfile(tar_info)
                        assert member_file is not None
                        with member_file:
                            new_tar_info = tar_info.replace(
                                name=f"{prefix}/{orig_name}")
                            tar_out.addfile(new_tar_info, member_file)

                    checksum_data = json.dumps(
                        {
                            "package": crate.checksum,
                            "files": {},
                        })
                    checksum_info = tarfile.TarInfo()
                    checksum_info.name = (
                        f"{prefix}/{crate_dir}/.cargo-checksum.json")
                    checksum_info.size = len(checksum_data)
                    checksum_info.mode = 0o644
                    tar_out.addfile(checksum_info,
                                    io.BytesIO(checksum_data.encode()))
        end_time = datetime.datetime.now(tz=datetime.timezone.utc)
        logging.info(f"Time elapsed during repacking: {end_time - start_time}")

    crates: set[Crate] = set()
    pkg_metas = []
    for directory in args.directory:
        try:
            f = open(directory / "Cargo.toml", "rb")
        except FileNotFoundError:
            logging.error(f"'Cargo.toml' not found in {str(directory)!r}")
            logging.info(
                "Please pass the path to a directory containing 'Cargo.toml' "
                "as an argument.")
            return 1
        with f:
            workspace = get_workspace_root(directory)
            crates.update(workspace.crates)
            try:
                pkg_metas.append(
                    get_package_metadata(f, workspace.workspace_metadata))
            except WorkspaceCargoTomlError as e:
                logging.error("The specified directory is a workspace root: "
                              f"{str(directory)!r}")
                logging.info(
                    "Please run pycargoebuild in one of its members: "
                    f"{' '.join(e.members)}")
                return 1
    pkg_meta = pkg_metas[0]

    if args.no_license:
        pkg_meta = pkg_meta.with_replaced_license(None)
    elif len(args.directory) > 1:
        # Combine licenses of multiple packages
        combined_license = " AND ".join(f"( {pkg.license} )"
                                        for pkg in pkg_metas
                                        if pkg.license is not None)
        pkg_meta = pkg_meta.with_replaced_license(
            combined_license or None)

    if args.input is not None and args.output is None:
        # default to overwriting the input file
        outfile = args.input
    else:
        # This warning is only relevant when constructing a new ebuild,
        # as otherwise we do not update other metadata.
        if len(args.directory) > 1:
            logging.warning(
                "Multiple directories passed, all metadata except for LICENSE "
                f"will be taken from the first package, {pkg_meta.name}")
        if args.output is None:
            args.output = "{name}-{version}.ebuild"
        outfile = Path(args.output.format(name=pkg_meta.name,
                                          version=pkg_meta.version))
        if not args.force and outfile.exists():
            logging.error(f"{outfile} exists already, pass -f to overwrite it")
            return 1

    fetch_crates(crates)
    try:
        verify_crates(crates, distdir=args.distdir)
    except ChecksumMismatchError as e:
        logging.error(f"Checksum mismatch for {str(e.path)!r}")
        logging.info(f"   Found checksum (SHA256): {e.current!r}")
        logging.info(f"Expected checksum (SHA256): {e.expected!r}")
        logging.info("Remove the file to try downloading again.")
        return 1

    umask = os.umask(0)
    os.umask(umask)

    if args.mode != Mode.FILL_CRATES:
        crate_tarball = Path(
            args.crate_tarball_path.format(name=pkg_meta.name,
                                           version=pkg_meta.version,
                                           distdir=args.distdir))
        if args.mode == Mode.USE_CRATE_TARBALL:
            logging.info("Skipping creating crate tarball")
        else:
            assert args.mode == Mode.WRITE_CRATE_TARBALL
            if not args.force and crate_tarball.exists():
                logging.error(f"{crate_tarball} exists already, pass -f to "
                              "overwrite it")
                return 1
            with tempfile.NamedTemporaryFile(mode="wb",
                                             dir=args.distdir,
                                             delete=False
                                             ) as cratef:
                try:
                    # preset: https://github.com/astral-sh/ty/issues/4595
                    with tarfile.open(fileobj=cratef,
                                      mode="w:xz",
                                      format=tarfile.GNU_FORMAT,
                                      encoding="UTF-8",
                                      preset=9 | lzma.PRESET_EXTREME,  # type: ignore
                                      ) as tar_out:
                        os.fchmod(cratef.fileno(), 0o666 & ~umask)
                        logging.info("Repacking crates ...")
                        repack_crates(tar_out, crates)
                except BaseException:
                    Path(cratef.name).unlink()
                    raise
            Path(cratef.name).rename(crate_tarball)
            logging.info(f"Crate tarball written to {crate_tarball}")

            # do not regenerate Manifest, crate tarball needs to be uploaded
            # first
            args.no_manifest = True

    try:
        if args.input is not None:
            ebuild = update_ebuild(
                args.input.read_text(encoding="utf-8"),
                pkg_meta,
                crates,
                distdir=args.distdir,
                crate_license=not args.no_license,
                crate_tarball=(crate_tarball if args.mode != Mode.FILL_CRATES
                               else None),
                license_overrides=config_toml.get("license-overrides", {}),
                )
            logging.warning(
                "The in-place mode updates CRATES, GIT_CRATES and crate "
                "LICENSE+= variables only, other metadata is left unchanged")
        else:
            ebuild = get_ebuild(
                pkg_meta,
                crates,
                distdir=args.distdir,
                crate_license=not args.no_license,
                crate_tarball=(crate_tarball if args.mode != Mode.FILL_CRATES
                               else None),
                license_overrides=config_toml.get("license-overrides", {}),
                use_features=args.features,
                )
    except UnmatchedLicense as e:
        logging.error(
            f"The license {e.license_key!r} did not match any entry in "
            f"{args.license_mapping.name!r}")
        if e.crate is not None:
            logging.info(f"Crate file: {e.crate!r}")
        logging.info(
            "1. If that is a valid SPDX-2.0 license identifier, then please "
            "add it to the license mapping file.  However, please make sure "
            "to:\n"
            "a. avoid adding duplicate licenses (multiple SPDX-2.0 "
            "identifiers can map to the same Gentoo license),\n"
            "b. add new licenses to appropriate license-groups.\n"
            "\n"
            "2. If that is not a valid SPDX-2.0 license identiiers, please "
            "file a bug upstream.  For the time being, you can use a local "
            "license mapping file (--license-mapping) or per-crate "
            "license-overrides in config (see README).")
        return 1

    with tempfile.NamedTemporaryFile(mode="w",
                                     encoding="utf-8",
                                     dir=outfile.parent,
                                     delete=False) as outf:
        try:
            if args.input is not None:
                st = args.input.stat()
                os.chown(outf.fileno(), st.st_uid, st.st_gid)
                os.chmod(outf.fileno(), stat.S_IMODE(st.st_mode))
            else:
                os.fchmod(outf.fileno(), 0o666 & ~umask)
            outf.write(ebuild)
        except BaseException:
            Path(outf.name).unlink()
            raise
    Path(outf.name).rename(outfile)

    if not args.no_manifest and (outfile.parent / "Manifest").exists():
        try:
            subprocess.call(["pkgdev", "manifest"], cwd=outfile.parent)
        except FileNotFoundError:
            logging.warning("pkgdev not found, Manifest will not be updated")

    print(f"{outfile}")
    return 0


def entry_point() -> None:
    try:
        from rich.logging import RichHandler
    except ImportError:
        logging.basicConfig(
            format="[{levelname:>7}] {message}",
            level=logging.INFO,
            style="{")
    else:
        logging.basicConfig(
            format="{message}",
            level=logging.INFO,
            style="{",
            handlers=[RichHandler(show_time=False, show_path=False)])

    sys.exit(main(*sys.argv))


if __name__ == "__main__":
    entry_point()
