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
