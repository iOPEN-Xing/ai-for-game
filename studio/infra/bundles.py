"""Immutable game packages, archives and cacheable player payloads."""

import base64
import io
import json
import re
import zipfile
from functools import lru_cache

from studio.infra.store import encode
from studio.settings import data_dir


def folder(key):
    if not key or not re.fullmatch(r"[a-f0-9]{64}", key):
        raise ValueError("缺少构建")
    return data_dir() / "builds" / key


def player_data(key):
    return read_player_assets(folder(key))


@lru_cache(maxsize=8)
def public_payload(root):
    return encode(read_player_assets(root)).encode("utf-8")


def read_player_assets(root):
    out = json.loads((root / "manifest.json").read_bytes())
    out["source"] = (root / "remoteEntry.js").read_text()
    out["sprite"] = (
        "data:image/png;base64,"
        + base64.b64encode((root / "sprite.png").read_bytes()).decode()
    )
    out["sprites"] = {
        name: "data:image/png;base64,"
        + base64.b64encode((root / item["file"]).read_bytes()).decode()
        for name, item in out["assets"].get("sprites", {}).items()
    }
    out["sounds"] = {
        k: "data:audio/wav;base64,"
        + base64.b64encode((root / name).read_bytes()).decode()
        for k, name in out["assets"]["audio"].items()
    }
    return out


def bundle_zip(key):
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for path in sorted(folder(key).iterdir()):
            z.write(path, path.name)
    return out.getvalue()
