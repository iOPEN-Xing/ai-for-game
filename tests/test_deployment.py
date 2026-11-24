"""Deployment contract, old database migration, backup integrity and single-studio limits."""

import hashlib
import io
import json
import os
import sqlite3
import tempfile
import zlib
from pathlib import Path
from unittest.mock import patch

from fastapi.testclient import TestClient

import app as server
from studio.application.harness import worker
from studio.application.tools import cartridge, image_service
from studio.domain import limits
from studio.infra.backup import export_backup, restore_backup
from studio.infra.store import db, enqueue, init, need
from studio.settings import validate_runtime
from tests.support import IDEA, StudioCase


class DeploymentTests(StudioCase):
    def test_local_bypass_requires_local_peer_and_local_hostname(self):
        for peer, host in (
            ("192.0.2.5", "localhost"),
            ("127.0.0.1", "untrusted.example"),
        ):
            client = TestClient(
                server.app, base_url="http://" + host, client=(peer, 42000)
            )
            try:
                self.assertEqual(client.get("/api/studio").status_code, 401)
            finally:
                client.close()
        with (
            patch.dict(os.environ, {"STUDIO_DEPLOYED": "1"}),
            self.assertRaises(RuntimeError),
        ):
            validate_runtime()
        with patch.dict(os.environ, {"STUDIO_PUBLIC_URL": "https://games.example"}):
            self.assertEqual(
                self.get("studio")["public_origin"], "https://games.example"
            )
        with (
            patch.dict(
                os.environ, {"STUDIO_PUBLIC_URL": "https://user@wrong.example/path"}
            ),
            self.assertRaises(RuntimeError),
        ):
            validate_runtime()

    def test_deployed_limits_persist_and_requests_have_correlated_errors(self):
        with patch.dict(
            os.environ, {"STUDIO_DEPLOYED": "1", "STUDIO_ACCESS_KEY": "fixture"}
        ):
            self.assertEqual(self.client.get("/metrics").status_code, 401)
            self.assertEqual(self.client.get("/healthz").status_code, 200)
            for _ in range(10):
                self.assertEqual(
                    self.client.post("/api/login", json={"key": "invalid"}).status_code,
                    401,
                )
            init()
            res = self.client.post(
                "/api/login",
                json={"key": "fixture"},
                headers={"X-Request-Id": "test-limit"},
            )
            self.assertEqual(res.status_code, 429)
            self.assertGreater(int(res.headers["Retry-After"]), 0)
            self.assertEqual(res.headers["X-Request-Id"], res.json()["request_id"])
            self.assertEqual(res.json()["code"], "RATE_LIMITED")
        body = self.client.post("/api/games", json={**IDEA, "unknown": "hidden-value"})
        self.assertEqual(body.status_code, 422)
        self.assertNotIn("hidden-value", body.text)
        absent = self.client.get("/api/nonexistent")
        self.assertEqual(absent.status_code, 404)
        self.assertEqual(absent.json()["request_id"], absent.headers["X-Request-Id"])

    def test_legacy_baseline_migrates_idempotently(self):
        with (
            tempfile.TemporaryDirectory() as old,
            patch.dict(os.environ, {"STUDIO_DATA_DIR": old}),
        ):
            con = sqlite3.connect(Path(old) / "studio.sqlite3")
            try:
                baseline = (
                    Path(server.__file__).parent
                    / "studio/infra/migrations/baseline.sql"
                )
                con.executescript(baseline.read_text())
                con.execute(
                    "INSERT INTO games VALUES('old','旧项目','创意','win_rate','边界',NULL,9)"
                )
                con.commit()
            finally:
                con.close()
            init()
            init()
            with db() as con:
                self.assertEqual(
                    need(con, "SELECT title FROM games WHERE id='old'")["title"],
                    "旧项目",
                )
                self.assertIn(
                    "replay",
                    {r["name"] for r in con.execute("PRAGMA table_info(rounds)")},
                )
                self.assertEqual(
                    con.execute("SELECT count(*) FROM schema_migrations").fetchone()[0],
                    len(list(baseline.parent.glob("migrate_*.sql"))),
                )

    def test_snapshot_restores_published_build_art_and_a_replay(self):
        self.draft()
        self.publish()
        token = self.play()
        source = Path(self.tmp.name)

        with db() as con:
            published = need(con, "SELECT bundle FROM rounds WHERE id=?", token)[
                "bundle"
            ]
        png = (cartridge.folder(published) / "sprite.png").read_bytes()
        digest = hashlib.sha256(png).hexdigest()
        art = source / "generated-art"
        art.mkdir(exist_ok=True)
        image_service.atomic(art / (digest + ".png"), png)
        (art / ("0" * 64 + ".json")).write_text(json.dumps({"sha256": digest}))
        archive = io.BytesIO()
        export_backup(source, archive)
        with (
            tempfile.TemporaryDirectory() as temp,
            patch.dict(os.environ, {"STUDIO_DATA_DIR": temp}),
        ):
            root = Path(temp)
            restore_backup(root, io.BytesIO(archive.getvalue()))
            with self.assertRaisesRegex(ValueError, "空数据目录"):
                restore_backup(root, io.BytesIO(archive.getvalue()))
            init()
            with db() as con:
                row = need(con, "SELECT * FROM rounds WHERE id=?", token)
            inputs = json.loads(zlib.decompress(row["replay"]))
            replay = cartridge.replay(row["bundle"], row["level"], inputs)
            self.assertEqual(
                (replay["won"], replay["score"]), (bool(row["won"]), row["score"])
            )
            self.assertEqual(image_service.png_bytes({"sha256": digest}), png)

    def test_capacity_checks_preserve_idempotency_and_leave_active_work_untouched(self):
        with patch.object(limits, "GAMES_PER_STUDIO", 1):
            body = {**IDEA, "request_id": "repeat-this-request-2026"}
            first = self.post("games", body, 201)
            self.assertEqual(self.post("games", body, 201), first)
            rejected = self.post("games", IDEA, 429)
            self.assertEqual(rejected["code"], "QUOTA_EXCEEDED")
        with db(True) as con:
            enqueue(con, "analysis", "one", "discuss")
            enqueue(con, "analysis", "two", "discuss")
        self.assertEqual(worker.claim()["kind"], "production")
        self.assertEqual(worker.claim()["target"], "one")
        self.assertIsNone(worker.claim())

    def test_incomplete_archive_leaves_the_new_volume_empty(self):
        import tarfile

        archive = io.BytesIO()
        with tarfile.open(fileobj=archive, mode="w:gz") as tar:
            item = tarfile.TarInfo("checksums.json")
            body = b'{"studio.sqlite3":"missing"}'
            item.size = len(body)
            tar.addfile(item, io.BytesIO(body))
        with tempfile.TemporaryDirectory() as target:
            with self.assertRaisesRegex(ValueError, "清单校验失败"):
                restore_backup(Path(target), io.BytesIO(archive.getvalue()))
            self.assertEqual(list(Path(target).iterdir()), [])
