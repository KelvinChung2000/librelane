from importlib.resources import files


def test_packaged_resource_access():
    package_root = files("librelane")
    assert package_root.is_dir()
    assert package_root.name == "librelane"

    pdk_hashes = package_root.joinpath("pdk_hashes.yaml")
    assert pdk_hashes.is_file()
    assert "sky130" in pdk_hashes.read_text(encoding="utf8")

    script_root = package_root.joinpath("scripts")
    assert script_root.is_dir()
    assert script_root.joinpath("base.sdc").is_file()

    example = package_root.joinpath("examples", "spm", "config.yaml")
    assert example.is_file()
    assert "DESIGN_NAME" in example.read_text(encoding="utf8")
