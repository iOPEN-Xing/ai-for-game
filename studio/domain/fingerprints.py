"""Stable content addresses used by skills, evidence and recorded model inputs."""

import hashlib
import json


def digest(value):
    content = (
        value
        if isinstance(value, str)
        else json.dumps(
            value,
            sort_keys=True,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
    )
    return hashlib.sha256(content.encode()).hexdigest()
