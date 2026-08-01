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
"""
Content identity for the files a step depends on.

A step's configuration and input state name files by path. A path is not an
identity: editing ``src/design.v`` leaves every path in both structures byte for
byte the same, so a resume decision made on paths alone would reuse stale
synthesis output. This module answers the question paths cannot.
"""

import hashlib
import os
import stat
import threading

#: Read granularity. Large enough that a 30MB liberty file is a handful of
#: reads, small enough not to hold a GDS in memory.
_CHUNK_SIZE = 1 << 20


class Fingerprinter:
    """
    Answers what a path's contents are, memoizing on cheap metadata.

    One instance is created per flow run. The same PDK views appear in many
    steps' configurations, and the memo is what keeps them read once rather than
    once per step.

    The memo is keyed on size and modification time, but the identity it caches
    is always a content hash. Using size and mtime as the identity itself would
    be wrong in both directions: Nix store paths carry epoch-normalized mtimes,
    so a rebuild can leave mtime untouched while contents differ, and a bare
    ``touch`` would otherwise invalidate a whole run for no reason.
    """

    def __init__(self) -> None:
        self.__memo: dict[tuple[str, int, int], str] = {}
        self.__memo_lock = threading.Lock()

    def _read_digest(self, path: str) -> str:
        """
        Hashes a file's contents.

        Separate from :meth:`of_path` so tests can assert the memo prevented a
        read rather than infer it from timing.

        Parameters
        ----------
        path : str
            An absolute path to a regular file.

        Returns
        -------
        str
            A 128-bit BLAKE2b digest, hex encoded.
        """
        digest = hashlib.blake2b(digest_size=16)
        with open(path, "rb") as file:
            while chunk := file.read(_CHUNK_SIZE):
                digest.update(chunk)
        return digest.hexdigest()

    def of_path(self, path: str | os.PathLike[str]) -> str:
        """
        Parameters
        ----------
        path : str | os.PathLike[str]
            Any path, existing or not, file or directory.

        Returns
        -------
        str
            An identity string, one of:

            * ``file:<digest>`` for a regular file
            * ``dir:<abspath>`` for a directory, whose contents are deliberately
              not read
            * ``absent:<abspath>`` when nothing exists at the path

            An absent path yields an identity rather than raising, which is what
            turns a deleted view into an ordinary cache miss.
        """
        resolved = os.path.abspath(os.fspath(path))
        try:
            status = os.stat(resolved)
        except (FileNotFoundError, NotADirectoryError):
            return f"absent:{resolved}"

        if stat.S_ISDIR(status.st_mode):
            return f"dir:{resolved}"

        memo_key = (resolved, status.st_size, status.st_mtime_ns)
        with self.__memo_lock:
            if (cached := self.__memo.get(memo_key)) is not None:
                return cached

        # Deliberately outside the lock. One instance is shared by every job
        # of a run, and jobs run concurrently, so holding the lock across the
        # read would serialise the hashing of every distinct file in the flow
        # behind one thread -- removing exactly the parallelism the engine
        # exists to add, to save a cost that only appears when two jobs happen
        # to miss on the same file at the same moment. The identity is a pure
        # function of the key, so the loser of that race recomputes the same
        # string and stores it over an equal one.
        identity = f"file:{self._read_digest(resolved)}"
        with self.__memo_lock:
            self.__memo[memo_key] = identity
        return identity
