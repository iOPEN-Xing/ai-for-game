"""Build the public chapter games with the studio's normal release compiler."""

import hashlib
import json
import os
import tempfile

from studio.application.tools.cartridge import compile_bundle, player_data
from studio.infra import art_files
from studio.settings import ROOT, WEB

SAMPLES = {"tidal-beacon": "sample-game.json", "mountain-post": "sample-post.json"}


def build(slug):
    project = ROOT / "examples" / slug
    design = json.loads((project / "design.json").read_text(encoding="utf-8"))
    docs = {key: design[key] for key in ("levels", "gdd", "art")}
    for key, filename in (
        ("game_code", "game.js"),
        ("level_code", "level-generator.js"),
    ):
        docs[key] = {"source": (project / filename).read_text(encoding="utf-8")}
    # Exporting this sample must never create a draft or assets in a team's live studio.
    previous = os.environ.get("STUDIO_DATA_DIR")
    with tempfile.TemporaryDirectory(prefix="studio-playable-sample-") as folder:
        os.environ["STUDIO_DATA_DIR"] = folder
        try:
            for entity, name in design.get("illustrations", {}).items():
                image = (WEB / name).read_bytes()
                digest = hashlib.sha256(image).hexdigest()
                art_files.folder().mkdir(exist_ok=True)
                (art_files.folder() / (digest + ".png")).write_bytes(image)
                docs["art"].setdefault("rendered", {})[entity] = {
                    "sha256": digest,
                    "model": "gpt-image-2",
                }
            bundle, proof = compile_bundle({"seed": design["seed"]}, docs)
            payload = player_data(bundle)
        finally:
            if previous is None:
                del os.environ["STUDIO_DATA_DIR"]
            else:
                os.environ["STUDIO_DATA_DIR"] = previous
    payload["origin"] = {
        "model": "glm-5.4",
        "authorship": design["authorship"],
        "version": design["version"],
        "seed": design["seed"],
        "bundle": bundle,
        "verified_levels": proof["levels"],
    }
    return payload


if __name__ == "__main__":
    for slug, filename in SAMPLES.items():
        sample = build(slug)
        (WEB / filename).write_text(
            json.dumps(sample, ensure_ascii=False, separators=(",", ":")) + "\n",
            encoding="utf-8",
        )
        print(
            f"{sample['title']} · {sample['count']} 关 · {sample['origin']['bundle']}"
        )
