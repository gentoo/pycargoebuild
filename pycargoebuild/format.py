# pycargoebuild
# (c) 2022-2026 Michał Górny <mgorny@gentoo.org>
# SPDX-License-Identifier: GPL-2.0-or-later

from __future__ import annotations

import typing
from textwrap import TextWrapper


class CompoundGroup(typing.NamedTuple):
    prefix: list[str]
    values: list[str | CompoundGroup]
    suffix: list[str]


class Line(typing.NamedTuple):
    indent: int
    tokens: list[str]


def format_license_var(value: str, *, prefix: str, line_width: int = 72
                       ) -> str:
    """
    Pretty-format and wrap value for use in LICENSE

    prefix specifies the expected variable prefix (e.g. 'LICENSE="'), that
    is used to determine the line wrapping.  Neither prefix nor the '"' suffix
    are included in the return value.
    """

    suffix = '"'

    # 1. tokenize into series of license tokens and compound groups
    def tokenize_into(current_group: CompoundGroup,
                      token_it: typing.Iterator[str],
                      ) -> CompoundGroup:
        try:
            while True:
                token = next(token_it)
                if token in ("||", "("):
                    prefix = [token]
                    if token == "||":
                        prefix.append(next(token_it))
                        if prefix[-1] != "(":
                            raise ValueError("|| not followed by (")
                    current_group.values.append(
                        tokenize_into(CompoundGroup(prefix, [], []), token_it))
                elif token == ")":
                    current_group.suffix.append(token)
                    return current_group
                else:
                    current_group.values.append(token)
        except StopIteration as exception:
            if current_group.prefix and not current_group.suffix:
                raise ValueError("Unterminated license group") from exception
        return current_group

    tokens = iter(value.split())
    ast = tokenize_into(CompoundGroup([], [], []), tokens)

    # 2. if we're dealing with something trivial, see if we can fit it as-is
    # on one line
    flat_list = all(isinstance(x, str) for x in ast.values)
    one_flat_group = (
        not flat_list and len(ast.values) == 1 and
        all(isinstance(x, str) for x in ast.values[0].values))  # type: ignore
    if flat_list or one_flat_group:
        expected_length = len(prefix) + len(value) + len(suffix)
        if expected_length <= line_width:
            return value

    # 3. pretty-format the AST into a list of lines
    def format_into(lines: list[Line],
                    indent: int,
                    compound_group: CompoundGroup
                    ) -> list[Line]:
        value_it = iter(compound_group.values)
        value_span = []
        while True:
            try:
                value = next(value_it)
            except StopIteration:
                value = None

            if isinstance(value, str):
                value_span.append(value)
            else:
                # flush the current value_span
                if value_span:
                    lines.append(Line(indent, value_span))
                    value_span = []
                # return if we reached the end of the list
                if value is None:
                    return lines
                # compound group
                # again, if it's flat and short, let's inline it
                if all(isinstance(x, str) for x in value.values):
                    # mypy can't figure the all() clause above out
                    sub_values: list[str] = (
                        value.prefix + value.values +
                        value.suffix)  # type: ignore
                    test_line = indent * "    " + " ".join(sub_values)
                    if len(test_line) <= line_width:
                        lines.append(Line(indent, sub_values))
                        continue
                # otherwise, append it multi-line
                lines.append(Line(indent, value.prefix))
                format_into(lines, indent + 1, value)
                lines.append(Line(indent, value.suffix))

    lines = format_into([], 1, ast)

    # 4. combine lines into string, adding indentation and wrapping
    # as necessary
    value = "\n"
    wrapper = TextWrapper(expand_tabs=False,
                          replace_whitespace=False,
                          drop_whitespace=True,
                          break_long_words=False,
                          break_on_hyphens=False)
    for line in lines:
        wrapper.width = line_width - line.indent * 4
        for wrapped_line in wrapper.wrap(" ".join(line.tokens)):
            value += line.indent * "\t" + f"{wrapped_line}\n"

    return value
