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
"""The ``librelane metrics`` subcommand group."""

import os
import sys
import json
import gzip
import tarfile
import tempfile
from io import BytesIO
from pathlib import Path
from decimal import Decimal
from typing import Annotated
from collections.abc import Sequence

import httpx
import typer

from librelane.common.metrics.util import MetricDiff, TableVerbosity
from librelane.common.misc import Filter, get_httpx_session, mkdirp
from librelane.cli._app import make_group

default_filter_set = [
    "design__*__area",
    "design__max_*",
    "design__lvs_error__count",
    "antenna__violating*",
    "clock__*",
    "ir__*",
    "power__*",
    "timing__*_vio__*",
    "timing*wns*",
    "timing*tns*",
    "*error*",
    "!*__iter:*",
]

# passing_filter_set = [
#     "design__*__area",
#     "route__wirelength__max",
#     "design__instance__utilization",
#     "antenna__violating*",
#     "timing__*__ws",
#     "clock__skew__*",
#     "ir__*",
#     "power__*",
#     "!*__iter:*",
# ]


cli = make_group(help="Compare metrics.json files produced by LibreLane runs.")


def parse_table_verbosity(value: str) -> TableVerbosity:
    try:
        try:
            return TableVerbosity(int(value))
        except ValueError:
            return TableVerbosity[value.upper()]
    except (KeyError, ValueError) as error:
        choices = ", ".join(
            f"{verbosity.name} ({verbosity.value})" for verbosity in TableVerbosity
        )
        raise typer.BadParameter(f"choose one of: {choices}") from error


FilterOption = Annotated[
    list[str] | None,
    typer.Option(
        "-f",
        "--filter",
        help="A list of wildcards to filter by. Wildcards prefixed with ! exclude rather than include and take priority. 'DEFAULT' is replaced by a set of default wildcards.",
    ),
]
TableVerbosityOption = Annotated[
    TableVerbosity,
    typer.Option(
        "--table-verbosity",
        parser=parse_table_verbosity,
        metavar="NONE|CRITICAL|WORSE|CHANGED|ALL",
        show_default="ALL",
        help=TableVerbosity.__doc__,
    ),
]
TableOutOption = Annotated[
    Path | None,
    typer.Option(
        "--table-out",
        file_okay=True,
        dir_okay=False,
        writable=True,
        help="The place to write the table to.",
    ),
]
SignificantFiguresOption = Annotated[
    int,
    typer.Option(
        "--significant-figures",
        min=1,
        help="Number of significant figures.",
    ),
]


def normalize_filters(filter_wildcards: list[str] | None) -> list[str]:
    return filter_wildcards or ["DEFAULT"]


@cli.command()
def compare(
    metric_files: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            file_okay=True,
            dir_okay=False,
            help="Exactly two metrics.json files to compare.",
        ),
    ],
    table_verbosity: TableVerbosityOption = TableVerbosity.ALL,
    filter_wildcards: FilterOption = None,
    table_out: TableOutOption = None,
    significant_figures: SignificantFiguresOption = 4,
) -> None:
    """
    Creates a small summary of the differences between two ``metrics.json`` files.
    """
    if len(metric_files) != 2:
        raise typer.BadParameter("exactly two metric files are required")
    if table_verbosity is TableVerbosity.NONE:
        typer.echo("Table is empty.", err=True)
        return

    a_path, b_path = metric_files
    with a_path.open(encoding="utf8") as a_file:
        a = json.load(a_file, parse_float=Decimal)
    with b_path.open(encoding="utf8") as b_file:
        b = json.load(b_file, parse_float=Decimal)

    final_filters = []
    for wildcard in normalize_filters(filter_wildcards):
        if wildcard == "DEFAULT":
            final_filters += default_filter_set
        else:
            final_filters.append(wildcard)

    diff = MetricDiff.from_metrics(
        a, b, significant_figures, filter=Filter(final_filters)
    )

    md_str = diff.render_md(sort_by=("corner", ""), table_verbosity=table_verbosity)

    table_file = sys.stdout
    if table_out is None:
        print(md_str)
    else:
        with table_out.open("w", encoding="utf8") as table_file:
            print(md_str, file=table_file)

    # When we upgrade to rich 13 (when NixOS 23.11 comes out,
    # it has a proper markdown table renderer, but until then, this will have to do)


def _compare_metric_folders(
    filter_wildcards: Sequence[str],
    table_verbosity: TableVerbosity,
    path_a: str,
    path_b: str,
    significant_figures: int,
) -> tuple[str, str]:  # (summary, table)
    a: set[tuple[str, str, str]] = set()
    b: set[tuple[str, str, str]] = set()

    def add_designs(in_dir: str, to_set: set[tuple[str, str, str]]):
        for file in os.listdir(in_dir):
            basename = os.path.basename(file)
            if not basename.endswith(".metrics.json"):
                continue
            basename = basename[: -len(".metrics.json")]

            # We have to rsplit, since ihp-sg13g2 contains a "-"
            parts = basename.rsplit("-", maxsplit=2)
            if len(parts) != 3:
                raise ValueError(
                    f"Invalid filename {basename}: not in the format {{pdk}}-{{scl}}-{{design_name}}"
                )
            pdk, scl, design = parts
            to_set.add((pdk, scl, design))

    add_designs(path_a, a)
    add_designs(path_b, b)

    not_in_a = b - a
    not_in_b = a - b
    common = a.intersection(b)
    difference_report = ""
    for tup in not_in_a:
        pdk, scl, design = tup
        difference_report += f"* Results for a new test, `{'/'.join(tup)}`, detected.\n"
    for tup in not_in_b:
        pdk, scl, design = tup
        difference_report += (
            f"* ‼️ Results for `{'/'.join(tup)}` appear to be missing!\n"
        )

    final_filters = []
    for wildcard in filter_wildcards:
        if wildcard == "DEFAULT":
            final_filters += default_filter_set
        else:
            final_filters.append(wildcard)

    filter = Filter(final_filters)
    critical_change_report = ""
    tables = ""
    total_critical = 0
    for pdk, scl, design in sorted(common):
        metrics_a = json.load(
            open(
                os.path.join(path_a, f"{pdk}-{scl}-{design}.metrics.json"),
                encoding="utf8",
            ),
            parse_float=Decimal,
        )

        metrics_b = json.load(
            open(
                os.path.join(path_b, f"{pdk}-{scl}-{design}.metrics.json"),
                encoding="utf8",
            ),
            parse_float=Decimal,
        )

        diff = MetricDiff.from_metrics(
            metrics_a,
            metrics_b,
            significant_figures,
            filter=filter,
        )

        stats = diff.stats()

        total_critical += stats.critical
        if stats.critical > 0:
            critical_change_report += f"  * `{pdk}/{scl}/{design}` \n"
        if table_verbosity is not TableVerbosity.NONE:
            rendered = diff.render_md(("corner", ""), table_verbosity)
            if rendered.strip() != "":
                tables += f"<details><summary><code>{pdk}/{scl}/{design}</code></summary>\n{rendered}\n</details>\n\n"

    if total_critical == 0:
        critical_change_report = (
            "* No changes to critical metrics were detected in analyzed designs.\n"
            + critical_change_report
        )
    else:
        critical_change_report = (
            "* **Changes to critical metrics were detected in the following designs:**\n"
            + critical_change_report
        )

    report = ""
    report += difference_report
    report += critical_change_report

    return report, tables.strip()


@cli.command("compare-multiple")
def compare_multiple(
    metric_folders: Annotated[
        list[Path],
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="Exactly two directories containing metrics files.",
        ),
    ],
    table_verbosity: TableVerbosityOption = TableVerbosity.ALL,
    filter_wildcards: FilterOption = None,
    table_out: TableOutOption = None,
    significant_figures: SignificantFiguresOption = 4,
) -> None:
    """
    Creates a small summary/report of the differences between two folders with
    metrics files.

    The metrics files must be named in the format ``{pdk}-{scl}-{design}.metrics.json``.
    All other files are ignored.
    """
    if len(metric_folders) != 2:
        raise typer.BadParameter("exactly two metric folders are required")
    path_a, path_b = (str(path) for path in metric_folders)
    summary, tables = _compare_metric_folders(
        normalize_filters(filter_wildcards),
        table_verbosity,
        path_a,
        path_b,
        significant_figures,
    )
    print(summary)
    if table_out is None:
        print(tables)
    else:
        with table_out.open("w", encoding="utf8") as table_file:
            print(tables, file=table_file)


@cli.command("compare-remote", hidden=True)
def compare_remote(
    metric_folder: Annotated[
        Path,
        typer.Argument(
            exists=True,
            file_okay=False,
            dir_okay=True,
            help="A directory containing metrics files.",
        ),
    ],
    repo: Annotated[
        str, typer.Option("--repo", "-r", help="The GitHub repository.")
    ] = "librelane/librelane",
    metric_repo: Annotated[
        str,
        typer.Option(
            "--metric-repo",
            "-m",
            help="The repository storing metrics for --repo.",
        ),
    ] = "librelane/librelane-metrics",
    branch: Annotated[
        str, typer.Option("--branch", "-b", help="The branch to compare to.")
    ] = "main",
    commit: Annotated[
        str | None,
        typer.Option(
            "--commit",
            "-c",
            help="The commit whose metrics should be fetched.",
        ),
    ] = None,
    token: Annotated[
        str | None,
        typer.Option(
            "--token",
            "-t",
            envvar="GITHUB_TOKEN",
            help="A GitHub API token used to avoid rate limits.",
        ),
    ] = None,
    table_verbosity: TableVerbosityOption = TableVerbosity.ALL,
    filter_wildcards: FilterOption = None,
    table_out: TableOutOption = None,
    significant_figures: SignificantFiguresOption = 4,
) -> None:
    """
    Creates a small summary/report of the differences between a folder and
    a set of metrics stored in --metric-repo. Requires Internet access and
    access to GitHub.

    The metrics files must be named in the format ``{pdk}-{scl}-{design}.metrics.json``.
    All other files are ignored.
    """
    session = get_httpx_session(token)

    if commit is None:
        try:
            result = session.get(
                f"https://api.github.com/repos/{repo}/branches/{branch}"
            )
        except httpx.HTTPStatusError as e:
            if e.response is not None and e.response.status_code == 404:
                print(f"'{branch}' branch of repo {repo} not found.", file=sys.stderr)
            else:
                print(
                    f"failed to get info from github API: {e.response.status_code}",
                    file=sys.stderr,
                )
            sys.exit(-1)
        result.raise_for_status()
        commit = str(result.json()["commit"]["sha"])
    url = f"https://github.com/{metric_repo}/tarball/commit-{commit}"

    try:
        with tempfile.TemporaryDirectory(prefix="librelane_metrics_tmpdir_") as d:
            bio_gz = BytesIO()
            with session.stream("GET", url) as r:
                r.raise_for_status()
                for chunk in r.iter_bytes(chunk_size=8192):
                    bio_gz.write(chunk)
            bio_gz.seek(0)
            with (
                gzip.GzipFile(fileobj=bio_gz) as bio,
                tarfile.TarFile(fileobj=bio, mode="r") as tf,
            ):
                for file in tf:
                    if file.isdir():
                        continue
                    stripped = os.path.sep.join(file.name.split(os.path.sep)[1:])
                    final_path = os.path.join(d, stripped)
                    final_dir = os.path.dirname(final_path)
                    mkdirp(final_dir)
                    io = tf.extractfile(file)
                    if io is None:
                        print(
                            f"Failed to unpack file in tarball: {file.name}.",
                            file=sys.stderr,
                        )
                    else:
                        with open(final_path, "wb") as f:
                            f.write(io.read())

            summary, tables = _compare_metric_folders(
                normalize_filters(filter_wildcards),
                table_verbosity,
                d,
                str(metric_folder),
                significant_figures,
            )
            print(summary)
            table_file = sys.stdout
            if table_out is not None:
                table_file = open(table_out, "w", encoding="utf8")
            print(tables, file=table_file)
    except httpx.HTTPStatusError as e:
        if e.response is not None and e.response.status_code == 404:
            print(f"Metrics not found for commit: {commit}.", file=sys.stderr)
        else:
            if e.response is not None:
                print(
                    f"Failed to obtain metrics for {commit} remotely: {e.response}.",
                    file=sys.stderr,
                )
            else:
                print(
                    f"Failed to request metrics for {commit} from server: {e}.",
                    file=sys.stderr,
                )
        sys.exit(-1)


if __name__ == "__main__":
    cli()
