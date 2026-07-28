import runpy
import sys
from types import SimpleNamespace
from unittest import mock

import pytest


SCRIPT = "librelane/scripts/klayout/open_design.py"


def fake_pya():
    layout_options = SimpleNamespace(
        keep_other_cells=False,
        lefdef_config=SimpleNamespace(
            macro_resolution_mode=0,
            read_lef_with_def=True,
            lef_files=[],
            map_file=None,
        ),
    )
    layout_view = mock.Mock()
    cell_view = mock.Mock()
    cell_view.view.return_value = layout_view
    main_window = mock.Mock()
    main_window.load_layout.return_value = cell_view
    application = mock.Mock()
    application.main_window.return_value = main_window
    technology = mock.Mock(load_layout_options=layout_options)
    technology.name = "test-tech"
    module = SimpleNamespace(
        Application=SimpleNamespace(instance=mock.Mock(return_value=application)),
        Technology=mock.Mock(return_value=technology),
    )
    return module, technology, layout_options, main_window, layout_view


def test_klayout_open_design_cli(monkeypatch):
    pya, technology, options, main_window, layout_view = fake_pya()
    monkeypatch.setitem(sys.modules, "pya", pya)
    monkeypatch.setenv(
        "KLAYOUT_ARGV",
        '-l "first macro.lef" --input-lef second.lef '
        '-T "tech file.lyt" -P layers.lyp -M layers.map "design file.def"',
    )

    runpy.run_path(SCRIPT, run_name="__main__")

    technology.load.assert_called_once_with("tech file.lyt")
    assert options.lefdef_config.lef_files == ["first macro.lef", "second.lef"]
    assert options.lefdef_config.map_file == "layers.map"
    main_window.load_layout.assert_called_once_with(
        "design file.def",
        options,
        "test-tech",
        False,
    )
    layout_view.load_layer_props.assert_called_once_with("layers.lyp")


def test_klayout_open_design_cli_requires_technology(monkeypatch):
    pya, *_ = fake_pya()
    monkeypatch.setitem(sys.modules, "pya", pya)
    monkeypatch.setenv("KLAYOUT_ARGV", "-P layers.lyp -M layers.map design.def")

    with pytest.raises(SystemExit) as exc_info:
        runpy.run_path(SCRIPT, run_name="__main__")

    assert exc_info.value.code == 2
