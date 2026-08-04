"""Canonical quota-bucket identifiers shared by hosted authority paths."""

from __future__ import annotations

import re

QUOTA_BUCKET_PATTERN = r"^[a-z][a-z0-9_]{0,63}$"
_QUOTA_BUCKET = re.compile(QUOTA_BUCKET_PATTERN)


def is_canonical_quota_bucket(value: object) -> bool:
    """Return whether *value* is an exact bounded ASCII quota identifier."""

    return type(value) is str and _QUOTA_BUCKET.fullmatch(value) is not None


__all__ = ["QUOTA_BUCKET_PATTERN", "is_canonical_quota_bucket"]
