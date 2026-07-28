from importlib.resources import files
import zipfile


def test_packaged_resource_access():
    from librelane.resources import package_path

    package_root = files("librelane")
    assert package_root.is_dir()
    assert package_root.name == "librelane"
    assert package_path().is_dir()

    pdk_hashes = package_root.joinpath("pdk_hashes.yaml")
    assert pdk_hashes.is_file()
    assert "sky130" in pdk_hashes.read_text(encoding="utf8")

    script_root = files("librelane").joinpath("scripts")
    assert script_root.is_dir()
    assert script_root.joinpath("base.sdc").is_file()

    example = package_root.joinpath("examples", "spm", "config.yaml")
    assert example.is_file()
    assert "DESIGN_NAME" in example.read_text(encoding="utf8")


def test_non_filesystem_package_is_materialized(tmp_path, monkeypatch):
    import librelane.resources as resources

    archive_path = tmp_path / "resources.zip"
    with zipfile.ZipFile(archive_path, "w") as archive:
        archive.writestr("librelane/__init__.py", "")
        archive.writestr("librelane/scripts/tool.tcl", "puts ok\n")

    with zipfile.ZipFile(archive_path) as archive:
        package = zipfile.Path(archive, "librelane/")
        monkeypatch.setattr(resources, "files", lambda _: package)
        monkeypatch.setattr(resources, "_package_root", None)
        monkeypatch.setattr(resources, "_materialized_dir", None)

        package_path = resources.package_path()
        script_path = package_path / "scripts" / "tool.tcl"

        assert package_path.is_dir()
        assert script_path.read_text() == "puts ok\n"
