"""Strict canonical JSON binding for hosted tool arguments."""

from __future__ import annotations

import hashlib
import json
import math
from typing import TypeAlias

JsonScalar: TypeAlias = None | bool | int | float | str
JsonValue: TypeAlias = JsonScalar | list["JsonValue"] | dict[str, "JsonValue"]


class CanonicalArgumentsError(ValueError):
    """Arguments cannot be represented by the exact approval-binding format."""


def _validate(value: object, *, depth: int = 0) -> None:
    if depth > 100:
        raise CanonicalArgumentsError("tool arguments exceed the nesting limit")
    if value is None or type(value) in {bool, int, str}:
        return
    if type(value) is float:
        if not math.isfinite(value):
            raise CanonicalArgumentsError("tool arguments contain a non-finite number")
        return
    if type(value) is list:
        for item in value:
            _validate(item, depth=depth + 1)
        return
    if type(value) is dict:
        for key, item in value.items():
            if type(key) is not str or not key:
                raise CanonicalArgumentsError(
                    "tool argument object keys must be non-empty strings"
                )
            _validate(item, depth=depth + 1)
        return
    raise CanonicalArgumentsError("tool arguments must use exact JSON value types")


def canonical_argument_bytes(arguments: object) -> bytes:
    """Return one whitespace-free, sorted-key UTF-8 JSON representation."""
    if type(arguments) is not dict:
        raise CanonicalArgumentsError("tool arguments must be an exact JSON object")
    _validate(arguments)
    try:
        canonical = json.dumps(
            arguments,
            ensure_ascii=False,
            allow_nan=False,
            check_circular=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return canonical.encode("utf-8")
    except (
        TypeError,
        ValueError,
        UnicodeEncodeError,
        RecursionError,
        OverflowError,
    ) as error:
        raise CanonicalArgumentsError(
            "tool arguments cannot be canonicalized"
        ) from error


def canonical_argument_hash(arguments: object) -> bytes:
    """Return the 32-byte approval and audit binding for sanitized arguments."""
    return hashlib.sha256(canonical_argument_bytes(arguments)).digest()


__all__ = [
    "CanonicalArgumentsError",
    "canonical_argument_bytes",
    "canonical_argument_hash",
]
