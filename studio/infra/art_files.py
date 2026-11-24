"""Immutable generated PNG storage and atomic image-cache writes."""

import hashlib
import os
import re
import tempfile
from pathlib import Path

from studio.settings import data_dir


def folder():
    return data_dir() / "generated-art"


def png_bytes(record):
    digest = record["sha256"]
    if not re.fullmatch("[a-f0-9]{64}", digest):
        raise ValueError("无效的图像摘要")
    image = (folder() / (digest + ".png")).read_bytes()
    if hashlib.sha256(image).hexdigest() != digest:
        raise ValueError("图像内容与生成记录不符")
    return image


def atomic(path, data):
    with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as tmp:
        name = Path(tmp.name)
        try:
            tmp.write(data)
            tmp.flush()
            os.replace(name, path)
        finally:
            name.unlink(missing_ok=True)
