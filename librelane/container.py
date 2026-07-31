# Copyright 2023 Efabless Corporation
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

## This file is internal to LibreLane and is not part of the API.
from loguru import logger

import os
import re
import uuid
import shlex
import pathlib
import subprocess
from importlib.resources import files
from typing import NoReturn, Optional, Union
from collections.abc import Sequence

import httpx
import semver

from librelane.common import mkdirp
from librelane.env_info import ContainerInfo, OSInfo


def permission_args(osinfo: OSInfo) -> list[str]:
    if (
        osinfo.kernel == "Linux"
        and isinstance(osinfo.container_info, ContainerInfo)
        and osinfo.container_info.engine == "docker"
        and not osinfo.container_info.rootless
    ):
        uid = os.getuid()
        gid = os.getgid()

        return ["--user", f"{uid}:{gid}"]

    return []


def gui_args(osinfo: OSInfo) -> list[str]:
    args = []
    if osinfo.kernel == "Linux":
        if os.environ.get("DISPLAY") is None:
            logger.warning(
                "DISPLAY environment variable not set. GUI features will not be available."
            )
        else:
            args += [
                "-e",
                f"DISPLAY={os.environ.get('DISPLAY')}",
            ]
            if pathlib.Path("/tmp/.X11-unix").is_dir():
                args += ["-v", "/tmp/.X11-unix:/tmp/.X11-unix"]
            xauthority = pathlib.Path.home() / ".Xauthority"
            if xauthority.is_file():
                args += ["-v", f"{xauthority}:/.Xauthority"]
            args += [
                "--network",
                "host",
                "--security-opt",
                "seccomp=unconfined",
            ]
    return args


def image_exists(ce_path: str, image: str) -> bool:
    images = (
        subprocess.check_output([ce_path, "images", image])
        .decode("utf8")
        .rstrip()
        .split("\n")[1:]
    )
    return len(images) >= 1


def remote_manifest_exists(image: str) -> bool:
    registry = "docker.io"
    image_elements = image.split("/", maxsplit=1)
    if len(image_elements) > 1:
        registry = image_elements[0]
        image = image_elements[1]
    elements = image.split(":")
    repo = elements[0]
    tag = "latest"
    if len(elements) > 1:
        tag = elements[1]

    url = None
    if registry == "docker.io":
        url = f"https://registry.hub.docker.com/v2/repositories/{repo}/tags/{tag}"
    elif registry == "ghcr.io":
        url = f"https://ghcr.io/v2/{repo}/manifests/{tag}"
    else:
        logger.error(f"Unknown registry '{registry}'.")
        return False

    try:
        httpx.Client(follow_redirects=True).get(
            url, headers={"Accept": "application/json"}
        )
    except httpx.NetworkError:
        logger.error("Couldn't connect to the internet to pull container images.")
        return False
    except httpx.HTTPStatusError as e:
        logger.error(
            f"The image {image} was not found. This may be because the CI for this image is running- in which case, please try again later. (error: {e})"
        )
        return False
    return True


def ensure_image(ce_path: str, image: str) -> bool:
    if image_exists(ce_path, image):
        return True

    try:
        subprocess.check_call([ce_path, "pull", image])
    except subprocess.CalledProcessError:
        logger.error(f"Failed to pull image '{image}' from the container registries.")
        return False

    return True


dos_path_sep = re.compile(r"\\")


def sanitize_path(path: Union[str, os.PathLike]) -> tuple[str, str]:
    """
    Returns
    -------
    tuple[str, str]
        A tuple of:

        - The host path, processed ``abspath``
        - The target path, on UNIX-like operating systems it's identical to the
          host path, but on Windows, the path is translated to a valid UNIX path
          as follows:
          - Backslashes are converted into forward slashes
          - The drive letter (e.g. C:) is converted to a root directory (e.g. /c)
    """
    abspath = os.fspath(pathlib.Path(path).resolve())
    mountable_path = abspath
    if os.path.sep == "\\":
        mountable_path = f"/{abspath[0]}" + dos_path_sep.sub("/", abspath)[2:]
    return (abspath, mountable_path)


def container_version_error(input: str, against: str) -> Optional[str]:
    if input == "UNKNOWN":
        return (
            "Could not determine version for %s. You may encounter unexpected issues."
        )
    if semver.compare(input, against) < 0:
        return f"Your %s version ({input}) is out of date. You may encounter unexpected issues."
    return None


def ubuntu_version_at_least(current: str, minimum: str) -> bool:
    if current == "UNKNOWN":
        return False
    return tuple(map(int, current.split("."))) >= tuple(map(int, minimum.split(".")))


def run_in_container(
    image: str,
    args: Sequence[str],
    pdk_root: Optional[str] = None,
    pdk: Optional[str] = None,
    scl: Optional[str] = None,
    other_mounts: Optional[Sequence[str]] = None,
    tty: bool = False,
) -> NoReturn:
    # If imported at the top level, would interfere with Conda where Volare
    # would not be installed.
    import ciel

    osinfo = OSInfo.get()
    if not osinfo.supported:
        logger.warning(
            f"Unsupported host operating system '{osinfo.kernel}'. You may encounter unexpected issues."
        )

    if not isinstance(osinfo.container_info, ContainerInfo):
        raise FileNotFoundError("No compatible container engine found.")

    ce_path = osinfo.container_info.path
    assert ce_path is not None

    engine_name = osinfo.container_info.engine.lower()
    if engine_name == "docker":
        if error := container_version_error(osinfo.container_info.version, "25.0.5"):
            logger.warning(error % engine_name)
    elif engine_name == "podman":
        if osinfo.distro.lower() == "ubuntu" and not ubuntu_version_at_least(
            osinfo.distro_version, "24.04"
        ):
            logger.warning(
                "Versions of Podman for Ubuntu before Ubuntu 24.04 are generally pretty buggy. We recommend using Docker instead if possible."
            )
        elif error := container_version_error(osinfo.container_info.version, "4.1.0"):
            logger.warning(error % engine_name)
    else:
        logger.warning(
            f"Unsupported container engine referenced by '{osinfo.container_info.path}'. You may encounter unexpected issues."
        )

    if not ensure_image(ce_path, image):
        raise ValueError(f"Failed to use image '{image}'.")

    terminal_args = ["-i"]
    if tty:
        terminal_args.append("-t")

    mount_args = []
    from_home, to_home = sanitize_path(pathlib.Path.home())

    mount_args += ["-v", f"{from_home}:{to_home}"]

    from_pdk, to_pdk = sanitize_path(ciel.get_ciel_home(pdk_root))

    try:
        mkdirp(from_pdk)
    except FileExistsError:
        raise ValueError(f"Invalid PDK root: '{from_pdk}' is a file")

    mount_args += [
        "-v",
        f"{from_pdk}:{to_pdk}",
        "-e",
        f"PDK_ROOT={to_pdk}",
    ]

    if pdk is not None:
        mount_args += ["-e", f"PDK={pdk}"]

    if scl is not None:
        mount_args += [
            "-e",
            f"STD_CELL_LIBRARY={scl}",
        ]

    from_cwd, to_cwd = sanitize_path(pathlib.Path.cwd())
    if not from_cwd.startswith(from_home):
        mount_args += ["-v", f"{from_cwd}:{to_cwd}"]
    mount_args += ["-w", to_cwd]

    if other_mounts is not None:
        for mount in other_mounts:
            if pathlib.Path(mount).is_dir():
                mount_from, mount_to = sanitize_path(mount)
                mount_args += ["-v", f"{mount_from}:{mount_to}"]
                mkdirp(mount_from)
            else:
                mount_args += ["-v", f"{mount}"]

    container_id = str(uuid.uuid4())

    if os.getenv("_MOUNT_HOST_LIBRELANE") == "1":
        # librelane always ships unpacked, so files() is a real filesystem path.
        # typeshed only promises Traversable, which has no __fspath__.
        host_librelane_pythonpath = pathlib.Path(
            files("librelane")  # type: ignore[arg-type]
        ).parent
        mount_args += ["-v", f"{host_librelane_pythonpath}:/host_librelane"]

    cmd = (
        [
            ce_path,
            "run",
            "--rm",
            "--name",
            container_id,
        ]
        + terminal_args
        + permission_args(osinfo)
        + mount_args
        + gui_args(osinfo)
        + [image]
        + list(args)
    )

    logger.info("Running containerized command:")
    print(shlex.join(cmd))

    os.execlp(ce_path, *cmd)
