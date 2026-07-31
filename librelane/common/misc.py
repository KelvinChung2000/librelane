# Copyright 2025 LibreLane Contributors
#
# Adapted from OpenLane
#
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
from loguru import logger

import io
import os
import re
import gzip
import yaml
import typing
import pathlib
import fnmatch
import unicodedata
from importlib.resources import files
from importlib.resources.abc import Traversable
from typing import (
    IO,
    Any,
    SupportsFloat,
    TypeVar,
)
from collections.abc import Generator, Iterable

import httpx

from librelane.__version__ import __version__
from librelane.common.types import AnyPath, Path

T = TypeVar("T")


def idem(obj: T, *args, **kwargs) -> T:
    """
    Returns
    -------
    T
        the parameter ``obj`` unchanged. Useful for some lambdas.
    """
    return obj


def get_pdk_hash(pdk_variant) -> str:
    """
    Gets the PDK version hash confirmed compatible with this version of LibreLane.
    """

    pdk_hashes = yaml.safe_load(
        files("librelane").joinpath("pdk_hashes.yaml").read_text(encoding="utf8")
    )
    for pdk_family in pdk_hashes:
        if pdk_family in pdk_variant:
            return pdk_hashes[pdk_family]

    logger.error(
        f"Could not find a PDK family for '{pdk_variant}'. Please specify a PDK manually with '--manual-pdk'."
    )
    exit(1)


# The following code snippet has been adapted under the following license:
#
# Copyright (c) Django Software Foundation and individual contributors.
# All rights reserved.

# Redistribution and use in source and binary forms, with or without modification,
# are permitted provided that the following conditions are met:

#     1. Redistributions of source code must retain the above copyright notice,
#        this list of conditions and the following disclaimer.

#     2. Redistributions in binary form must reproduce the above copyright
#        notice, this list of conditions and the following disclaimer in the
#        documentation and/or other materials provided with the distribution.

#     3. Neither the name of Django nor the names of its contributors may be used
#        to endorse or promote products derived from this software without
#        specific prior written permission.


# THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS" AND
# ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE IMPLIED
# WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
# DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT OWNER OR CONTRIBUTORS BE LIABLE FOR
# ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL DAMAGES
# (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR SERVICES;
# LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER CAUSED AND ON
# ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY, OR TORT
# (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE OF THIS
# SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
def slugify(value: str, lower: bool = False) -> str:
    """
    Adapted from Django slugify. In practice it works more like a kebabify…

    Parameters
    ----------
    value : str
        Input string

    Returns
    -------
    str
        The input string converted to lower case, with all characters
        except alphanumerics, underscores and hyphens removed, and spaces and\
        dots converted into hyphens.

        Leading and trailing whitespace is stripped.
    """
    if lower:
        value = value.lower()
    value = (
        unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    )
    value = re.sub(r"[^\w\s\-\.]", "", value).strip().lower()
    return re.sub(r"[\s\.]+", "-", value)


def protected(method):
    """A decorator to indicate protected methods.

    It dynamically adds a statement to the effect in the docstring as well
    as setting an attribute, ``protected``, to ``True``, but has no other effects.

    Parameters
    ----------
    f
        Method to mark as protected
    """
    if method.__doc__ is None:
        method.__doc__ = ""
    method.__doc__ = "**protected**\n" + method.__doc__

    setattr(method, "protected", True)
    return method


final = typing.final
final.__doc__ = """A decorator to indicate final methods and final classes.

    Use this decorator to indicate to type checkers that the decorated
    method cannot be overridden, and decorated class cannot be subclassed.
    For example:


    .. code-block:: python

       class Base:
           @final
           def done(self) -> None:
               ...
       class Sub(Base):
           def done(self) -> None:  # Error reported by type checker
                 ...

       @final
       class Leaf:
           ...
       class Other(Leaf):  # Error reported by type checker
           ...

    There is no runtime checking of these properties.
"""


def mkdirp(path: str | os.PathLike):
    """
    Attempts to create a directory and all of its parents.

    Does not fail if the directory already exists, however, it does fail
    if it is unable to create any of the components and/or if the path
    already exists as a file.

    Parameters
    ----------
    path : str | os.PathLike
        A filesystem path for the directory
    """
    return pathlib.Path(path).mkdir(parents=True, exist_ok=True)


def format_size(byte_count: int) -> str:
    units = [
        "B",
        "KiB",
        "MiB",
        "GiB",
        "TiB",
        "PiB",
        "EiB",
        # TODO: update LibreLane when zebibytes are a thing
    ]

    tracker = 0
    so_far = byte_count
    while (so_far // 1024) > 0 and tracker < (len(units) - 1):
        tracker += 1
        so_far //= 1024

    return f"{so_far}{units[tracker]}"


def format_elapsed_time(elapsed_seconds: SupportsFloat) -> str:
    """
    Parameters
    ----------
    elapsed_seconds : SupportsFloat
        Total time elapsed in seconds

    Returns
    -------
    str
        A string in the format ``{hours}:{minutes}:{seconds}:{milliseconds}``
    """
    elapsed_seconds = float(elapsed_seconds)

    hours = int(elapsed_seconds // 3600)
    leftover = elapsed_seconds % 3600

    minutes = int(leftover // 60)
    leftover = leftover % 60

    seconds = int(leftover // 1)
    milliseconds = int((leftover % 1) * 1000)

    return f"{hours:02}:{minutes:02}:{seconds:02}.{milliseconds:03}"


class Filter(object):
    """
    Encapsulates commonly used wildcard-based filtering functions into an object.

    Parameters
    ----------
    filters : Iterable[str]
        A list of a wildcards supporting the
        `fnmatch spec <https://docs.python.org/3.10/library/fnmatch.html>`_.

        The wildcards will be split into an "allow" and "deny" list based on whether
        the filter is prefixed with a ``!``.
    """

    def __init__(self, filters: Iterable[str]):
        self.allow = []
        self.deny = []
        for filter in filters:
            if filter.startswith("!"):
                self.deny.append(filter[1:])
            else:
                self.allow.append(filter)

    def get_matching_wildcards(self, input: str) -> Generator[str, Any, None]:
        """
        Parameters
        ----------
        input : str
            An input to match wildcards against.

        Returns
        -------
        Generator[str, Any, None]
            An iterable object for *all* wildcards in the allow list
            accepting ``input``, and *all* wildcards in the deny list rejecting
            ``input``.
        """
        for wildcard in self.allow:
            if fnmatch.fnmatch(input, wildcard):
                yield wildcard
        for wildcard in self.deny:
            if not fnmatch.fnmatch(input, wildcard):
                yield wildcard

    def match(self, input: str) -> bool:
        """
        Parameters
        ----------
        input : str
            An input string to either accept or reject

        Returns
        -------
        bool
            A boolean indicating whether the input:
            * Has matched at least one wildcard in the allow list
            * Has matched exactly 0 inputs in the deny list
        """
        allowed = False
        for wildcard in self.allow:
            if fnmatch.fnmatch(input, wildcard):
                allowed = True
                break
        for wildcard in self.deny:
            if fnmatch.fnmatch(input, wildcard):
                allowed = False
                break
        return allowed

    def filter(
        self,
        inputs: Iterable[str],
    ) -> Generator[str, Any, None]:
        """
        Parameters
        ----------
        inputs : Iterable[str]
            A series of inputs to filter according to the wildcards.

        Returns
        -------
        Generator[str, Any, None]
            An iterable object of any values in ``inputs`` that:
            * Have matched at least one wildcard in the allow list
            * Have matched exactly 0 inputs in the deny list
        """
        for input in inputs:
            if self.match(input):
                yield input


def recreate_tree(
    source: AnyPath | Traversable,
    target: AnyPath,
):
    """
    This function attempts to recreate a file tree from a source path in another
    target path.

    Permissions are not copied over. Symlinks and hardlinks are followed.

    Directories are not recreated unless they contain files as (grand)children.

    If the source and target are the same, the function returns early and does
    nothing.

    Parameters
    ----------
    source : AnyPath | Traversable
        The source file tree to replicate
    target : AnyPath
        The target path to recreate the file tree within
    """
    target_path = pathlib.Path(target).resolve()
    if isinstance(source, Traversable) and not isinstance(source, os.PathLike):
        target_path.mkdir(parents=True, exist_ok=True)
        for child in source.iterdir():
            child_target = target_path / child.name
            if child.is_dir():
                recreate_tree(child, child_target)
            elif child.is_file():
                child_target.parent.mkdir(parents=True, exist_ok=True)
                child_target.write_bytes(child.read_bytes())
        return

    source_path = pathlib.Path(source).resolve()
    if target_path.exists() and source_path.samefile(target_path):
        return
    for resolved in source_path.rglob("*"):
        if not resolved.is_file():
            continue
        resolved_target = target_path / resolved.relative_to(source_path)
        resolved_target.parent.mkdir(parents=True, exist_ok=True)
        resolved_target.write_bytes(resolved.read_bytes())


def get_latest_file(in_path: str | os.PathLike, filename: str) -> Path | None:
    """
    Parameters
    ----------
    in_path : str | os.PathLike
        A directory to search in
    filename : str
        The final filename

    Returns
    -------
    Path | None
        The latest file matching the parameters, by modification time
    """
    candidates = pathlib.Path(in_path).rglob(filename)
    latest = max(
        candidates, key=lambda candidate: candidate.stat().st_mtime, default=None
    )
    return Path(latest) if latest is not None else None


def get_httpx_session(token: str | None = None) -> httpx.Client:
    """
    Creates an ``httpx`` session client that follows redirects and has the
    User-Agent header set to ``librelane/{__version__}``.

    Parameters
    ----------
    token : str | None
        If this parameter is non-None and not empty, another header,
        Authorization: Bearer {token}, is included.

    Returns
    -------
    httpx.Client
        The created client
    """
    session = httpx.Client(follow_redirects=True)
    headers_raw = {"User-Agent": f"librelane/{__version__}"}
    if token is not None and token.strip() != "":
        headers_raw["Authorization"] = f"Bearer {token}"
    session.headers = httpx.Headers(headers_raw)
    return session


def process_list_file(from_file: AnyPath) -> list[str]:
    """
    Convenience function to process text files in a ``.gitignore``-style format,
    i.e., those where the lines may be:

    * A list element
    * A comment prefixed with ``#``
    * Blank

    Parameters
    ----------
    from_file : AnyPath
        The input text file.

    Returns
    -------
    list[str]
        A list of the strings listed in the file, ignoring lines
        prefixed with a ``#`` and empty lines.
    """
    excluded_cells = []
    list_str = open(str(from_file), encoding="utf8").read()
    for line in list_str.splitlines():
        line = line.strip()
        if line == "":
            continue
        if line[0] == "#":
            continue
        excluded_cells.append(line)
    return excluded_cells


def _get_process_limit() -> int:
    return int(os.getenv("_OPENLANE_MAX_CORES", os.cpu_count() or 1))


def gzopen(filename: AnyPath, mode="rt") -> IO[Any]:
    """
    This function (tries to?) emulate the gzopen from the Linux Standard Base,
    specifically this part:

    If path refers to an uncompressed file, and mode refers to a read mode,
    gzopen() shall attempt to open the file and return a gzFile object suitable
    for reading directly from the file without any decompression.

    gzip.open does not have this behavior.

    Parameters
    ----------
    filename : AnyPath
        The full path to the uncompressed or gzipped file.
    mode
        "r", "rb", "w", "wb", "x", "xb", "a" or "ab" for
        binary mode, or "rt", "wt", "xt" or "at" for text mode.

    Returns
    -------
    IO[Any]
        An I/O wrapper that may very slightly based on the mode.
    """
    try:
        g = gzip.open(filename, mode=mode)
        # Incredibly, it won't actually try to figure out if it's a gzipped
        # file until you try to read from it.
        if "r" in mode:
            g.read(1)
            g.seek(0)
        return g
    except gzip.BadGzipFile:
        g.close()
        return open(filename, mode=mode)


def count_occurences(fp: io.TextIOWrapper, pattern: str = "") -> int:
    """
    Counts the occurences of a certain string in a stream, line-by-line, without
    necessarily loading the entire file into memory.

    Equivalent to: ``grep -c 'pattern' <file>`` (but without regex support).

    Parameters
    ----------
    fp : io.TextIOWrapper
        the text stream
    pattern : str
        the substring to search for. if set to "", it will simply
        count the lines in the file.

    Returns
    -------
    int
        the number of matching lines
    """
    return sum(pattern in line for line in fp)
