# pycargoebuild
# (c) 2022-2026 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import configparser
import logging
import typing

import license_expression

MAPPING: dict[str, str] = {}


class UnmatchedLicense(RuntimeError):
    """License does not match anything in the mapping"""

    def __init__(self,
                 license_key: str,
                 crate: str | None = None,
                 ) -> None:
        super().__init__()
        self.license_key = license_key
        self.crate = crate


def load_license_mapping(f: typing.IO[str]) -> None:
    """Read license mapping from the specified file"""
    conf = configparser.ConfigParser(comment_prefixes=("#",),
                                     delimiters=("=",),
                                     empty_lines_in_values=False,
                                     interpolation=None)
    conf.read_file(f)
    MAPPING.update((k.lower(), v) for k, v in conf.items("spdx-to-ebuild"))


def symbol_to_ebuild(license_symbol: license_expression.LicenseSymbol |
                                     license_expression.LicenseWithExceptionSymbol
                     ) -> str:
    full_key = str(license_symbol).lower()
    full_match = MAPPING.get(full_key)
    no_plus = MAPPING.get(full_key.replace("+", ""))

    # we permit matching LicenseRef- to mapping but do not throw an error
    # if it's not there
    if no_plus is None and full_key.startswith("licenseref-"):
        logging.warning(
            f"User defined license found: {str(license_symbol)!r}, mapping "
            "not possible.")
        return ""

    if full_match is not None:
        return full_match

    # if we do not have an exact match, check if it is a "+" expression
    # and try a match without the "+" symbol
    if no_plus is not None:
        logging.warning(
            f"No explicit entry for license {license_symbol} found, "
            f"assuming {str(license_symbol).replace('+', '')}.")
        return no_plus

    raise UnmatchedLicense(str(license_symbol))


def spdx_to_ebuild(spdx: license_expression.Renderable) -> str:
    """
    Convert SPDX license expression to ebuild license string.
    """
    def sub(x: license_expression.Renderable, in_or: bool
            ) -> typing.Generator[str, None, None]:
        if isinstance(x, license_expression.AND):
            if in_or:
                yield "("
            for y in x.args:
                yield from sub(y, in_or=False)
            if in_or:
                yield ")"
        elif isinstance(x, license_expression.OR):
            if not in_or:
                yield "|| ("
            for y in x.args:
                yield from sub(y, in_or=True)
            if not in_or:
                yield ")"
        elif isinstance(x, (license_expression.LicenseSymbol,
                            license_expression.LicenseWithExceptionSymbol)):
            def is_pure_or(symbols: typing.Iterable[str]) -> bool:
                """
                Test whether symbols is a pure any-of clause "|| ( ... )"
                """

                it = iter(symbols)
                # it must start with a "|| ("
                if next(it) != "||":
                    return False
                if next(it) != "(":
                    return False
                level = 1
                for x in it:
                    if x == ")":
                        level -= 1
                    elif level == 0:
                        # if we have anything past top-level ")", we have
                        # an AND-expression
                        return False
                    elif x == "(":
                        level += 1
                return True

            mapped = symbol_to_ebuild(x).split()
            if len(mapped) > 1 and in_or:
                if is_pure_or(mapped):
                    # avoid nesting || ( || ( ... ) )
                    yield from mapped[2:-1]
                else:
                    # if we are inside || ( ... ), we need explicit ( ... )
                    # for AND-groups
                    yield "("
                    yield from mapped
                    yield ")"
            else:
                # single replacement item can always go inline,
                # as well as AND_groups inside an AND group
                yield from mapped
        else:
            assert False, f"Unknown type {type(x)}"

    return " ".join(sub(spdx, in_or=False))
