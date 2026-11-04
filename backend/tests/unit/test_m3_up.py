import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts import m3_up  # noqa: E402


class FakeProcess:
    def poll(self):
        return None


def test_supervisor_can_start_frontend_from_its_package_directory(monkeypatch, tmp_path):
    observed = {}

    def fake_popen(command, **kwargs):
        observed.update({"command": command, **kwargs})
        return FakeProcess()

    frontend = tmp_path / "frontend"
    frontend.mkdir()
    monkeypatch.setattr(m3_up, "LOG_DIR", tmp_path / "logs")
    monkeypatch.setattr(m3_up.subprocess, "Popen", fake_popen)

    supervisor = m3_up.Supervisor()
    supervisor.start("frontend", ["npm", "run", "dev"], {}, cwd=frontend)

    assert observed["command"] == ["npm", "run", "dev"]
    assert observed["cwd"] == frontend


def test_default_unit_config_is_the_main_xingtu_config():
    # The old local-main config has no juxing binding; using it by default silently disables
    # Juxing collection even though the API flag is on.
    assert m3_up.DEFAULT_UNIT_CONFIG.name == "local-dev-mac-02.json"
    assert "local-main" not in m3_up.DEFAULT_UNIT_CONFIG.parts


def test_collection_workers_are_optional_for_stack_lifetime():
    names = m3_up.optional_collection_workers(["unit-local-mac-03-juxing"])
    assert "collection-worker" in names
    assert "collection-worker-unit-local-mac-03-juxing" in names
    assert "api" not in names
    assert "intake-worker" not in names
