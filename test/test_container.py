import os
from pathlib import Path


def test_sanitize_path_accepts_pathlib(tmp_path):
    from librelane.container import sanitize_path

    nested = tmp_path / "nested" / ".." / "design"
    host, container = sanitize_path(nested)

    assert host == os.fspath((tmp_path / "design").resolve())
    if os.path.sep == "/":
        assert container == host


def test_gui_args_uses_pathlib_home(monkeypatch, tmp_path):
    from librelane.container import gui_args
    from librelane.env_info import OSInfo

    xauthority = tmp_path / ".Xauthority"
    xauthority.write_text("")
    monkeypatch.setattr(Path, "home", classmethod(lambda cls: tmp_path))
    monkeypatch.setenv("DISPLAY", ":0")

    os_info = OSInfo()
    os_info.kernel = "Linux"
    args = gui_args(os_info)

    assert f"{xauthority}:/.Xauthority" in args
