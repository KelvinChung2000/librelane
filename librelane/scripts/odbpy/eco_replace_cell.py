#!/usr/bin/env python3
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
import re
import sys

from reader import click_odb, click
import grt as GRT


def matching_instances(reader, rule):
    """
    The instances a replacement rule applies to: those whose name the rule's
    regular expression matches and, if the rule names a current cell, those
    that are instances of it.
    """
    matcher = re.compile(rule["instance"])
    current_cell = rule.get("current_cell")
    result = []
    for instance in reader.block.getInsts():
        if matcher.search(instance.getName()) is None:
            continue
        if current_cell is not None and instance.getMaster().getName() != current_cell:
            continue
        result.append(instance)
    return result


@click.command()
@click_odb
def cli(reader):
    grt = reader.design.getGlobalRouter()
    dpl = reader.design.getOpendp()

    replaced = []
    for rule in reader.config["REPLACE_ECO_CELLS"] or []:
        replacement = reader.db.findMaster(rule["replace_with"])
        if replacement is None:
            print(
                f"[ERROR] Replacement cell '{rule['replace_with']}' not found.",
                file=sys.stderr,
            )
            exit(-1)

        instances = matching_instances(reader, rule)
        if len(instances) == 0:
            print(
                f"[ERROR] No instance matches '{rule['instance']}'"
                + (
                    f" with cell '{rule['current_cell']}'."
                    if rule.get("current_cell") is not None
                    else "."
                ),
                file=sys.stderr,
            )
            exit(-1)

        for instance in instances:
            previous = instance.getMaster().getName()
            if not instance.swapMaster(replacement):
                print(
                    f"[ERROR] Could not replace '{previous}' with"
                    + f" '{rule['replace_with']}' for instance"
                    + f" '{instance.getName()}': the two cells are not"
                    + " interchangeable.",
                    file=sys.stderr,
                )
                exit(-1)
            print(
                f"Replaced '{previous}' with '{rule['replace_with']}' for instance"
                + f" '{instance.getName()}'."
            )
            replaced.append(instance)

    # The replacements are what detailed placement is allowed to move: a cell of
    # a different size overlaps its neighbours until it is legalized.
    replaced_names = {instance.getName() for instance in replaced}
    locked = []
    for instance in reader.block.getInsts():
        if instance.getName() in replaced_names:
            continue
        if instance.getPlacementStatus() != "LOCKED":
            locked.append((instance, instance.getPlacementStatus()))
            instance.setPlacementStatus("LOCKED")

    reader._grt_setup(grt)
    grt_inc = GRT.IncrementalGRoute(grt, reader.block)

    for instance in replaced:
        for iterm in instance.getITerms():
            if net := iterm.getNet():
                grt.addDirtyNet(net)

    site = reader.rows[0].getSite()
    max_disp_x = int(
        reader.design.micronToDBU(reader.config["PL_MAX_DISPLACEMENT_X"])
        / site.getWidth()
    )
    max_disp_y = int(
        reader.design.micronToDBU(reader.config["PL_MAX_DISPLACEMENT_Y"])
        / site.getHeight()
    )
    dpl.detailedPlacement(max_disp_x, max_disp_y)

    grt_inc.updateRoutes(True)

    for instance, previous_status in locked:
        instance.setPlacementStatus(previous_status)


if __name__ == "__main__":
    cli()
