# Copyright 2026 LibreLane Contributors
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Stable filesystem paths for packaged executable resources."""

import atexit
import os
import pathlib
import tempfile
import threading
from importlib.resources import files


_lock = threading.Lock()
_package_root: pathlib.Path | None = None
_materialized_dir: tempfile.TemporaryDirectory[str] | None = None


def _copy_tree(source, target: pathlib.Path) -> None:
    target.mkdir(parents=True, exist_ok=True)
    for child in source.iterdir():
        destination = target / child.name
        if child.is_dir():
            _copy_tree(child, destination)
        elif child.is_file():
            destination.write_bytes(child.read_bytes())


def _cleanup() -> None:
    if _materialized_dir is not None:
        _materialized_dir.cleanup()


atexit.register(_cleanup)


def package_path() -> pathlib.Path:
    """
    Returns the package as a stable filesystem path.

    Filesystem-backed installations are returned directly. Packages loaded
    through another importer are materialized once for the process lifetime.
    """
    global _materialized_dir, _package_root

    if _package_root is not None:
        return _package_root

    with _lock:
        if _package_root is not None:
            return _package_root

        package = files("librelane")
        if isinstance(package, os.PathLike):
            _package_root = pathlib.Path(package)
            return _package_root

        _materialized_dir = tempfile.TemporaryDirectory(prefix="librelane-resources-")
        _package_root = pathlib.Path(_materialized_dir.name) / "librelane"
        _copy_tree(package, _package_root)
        return _package_root
