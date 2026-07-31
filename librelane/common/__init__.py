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
"""
Common Utilities Module
-----------------------

A number of common utility functions and classes used throughout the codebase.
"""

import os

from librelane.common.tcl import TclUtils
from librelane.common.metrics import parse_metric_modifiers, aggregate_metrics
from librelane.common import metrics
from librelane.common.generic_dict import (
    GenericDictEncoder,
    GenericDict,
    GenericImmutableDict,
    copy_recursive,
)
from librelane.common.misc import (
    idem,
    get_pdk_hash,
    slugify,
    protected,
    final,
    mkdirp,
    format_size,
    format_elapsed_time,
    Filter,
    recreate_tree,
    get_latest_file,
    process_list_file,
    count_occurences,
    _get_process_limit,
)
from librelane.common.types import (
    is_number,
    is_real_number,
    is_string,
    is_string_like,
    Number,
    Path,
    AnyPath,
    ScopedFile,
    DUMMY_PATH,
    is_path_annotation,
    rel_if_child,
    unwrap_annotated,
    validate_path,
)
from librelane.common.toolbox import Toolbox
from librelane.common.fingerprint import Fingerprinter
from librelane.common.drc import DRC, Violation, BoundingBox
from librelane.common.tpe import get_tpe, set_tpe, ContextPropagatingThreadPoolExecutor
