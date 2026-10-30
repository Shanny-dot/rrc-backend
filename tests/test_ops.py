"""Security phase 3: health check for uptime monitoring and the storage backup script."""
import importlib
import json
import os
import sys


def test_database_health_check(env, monkeypatch):
    c = env["c"]
    assert c.get("/health/db").json() == {"status": "ok"}
    # Database unreachable: 503 so the uptime check fails, and no internal details
    monkeypatch.setattr(env["db"], "table", lambda name: (_ for _ in ()).throw(RuntimeError("connection refused")))
    r = c.get("/health/db")
    assert r.status_code == 503 and r.json() == {"status": "database unreachable"}


def test_storage_backup_walks_folders_and_saves_every_file(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_KEY", "service-key")
    sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(__file__)), "ops"))
    backup = importlib.import_module("backup_storage")
    tree = {"reward-images": {"": [{"name": "rewards", "id": None}, {"name": "logo.png", "id": "1"}],
                              "rewards/": [{"name": "a b.jpg", "id": "2"}]}}
    calls = []

    def fake_call(method, path, body=None):
        calls.append((method, path))
        if path == "bucket":
            return json.dumps([{"id": "reward-images"}]).encode()
        if path.startswith("object/list/"):
            return json.dumps(tree["reward-images"][body["prefix"]]).encode()
        return f"bytes of {path}".encode()

    monkeypatch.setattr(backup, "call", fake_call)
    backup.main(str(tmp_path))
    assert (tmp_path / "reward-images" / "logo.png").read_bytes() == b"bytes of object/reward-images/logo.png"
    assert (tmp_path / "reward-images" / "rewards" / "a b.jpg").exists()
    assert ("GET", "object/reward-images/rewards/a%20b.jpg") in calls


def test_workflows_are_valid_yaml():
    import pytest
    yaml = pytest.importorskip("yaml")
    root = os.path.join(os.path.dirname(os.path.dirname(__file__)), ".github", "workflows")
    for name in ("nightly-backup.yml", "uptime-check.yml"):
        with open(os.path.join(root, name), encoding="utf-8") as f:
            wf = yaml.safe_load(f)
        assert wf["jobs"] and (wf.get("on") or wf.get(True))
