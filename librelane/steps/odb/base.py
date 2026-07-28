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
from loguru import logger

from importlib.resources import files
import os
import re
import json
from math import inf
from decimal import Decimal
from abc import abstractmethod

from ...common import Path, aggregate_metrics
from ...state import DesignFormat, State

from ..openroad import OpenROADStep
from ..openroad_alerts import OpenROADAlert, OpenROADOutputProcessor
from ..step import (
    DefaultOutputProcessor,
    MetricsUpdate,
    Step,
    StepError,
    StepException,
    ViewsUpdate,
)

inf_rx = re.compile(r"\b(-?)inf\b")


class OdbpyStep(Step):
    inputs = [DesignFormat.ODB]
    outputs = [DesignFormat.ODB, DesignFormat.DEF]

    output_processors = [OpenROADOutputProcessor, DefaultOutputProcessor]

    alerts: list[OpenROADAlert] | None = None

    @classmethod
    def get_openroad_path(Self) -> str:
        return OpenROADStep.get_openroad_path()

    def on_alert(self, alert: OpenROADAlert) -> OpenROADAlert:
        if alert.code in [
            "ORD-0039",  # .openroad ignored with -python
            "ODB-0220",  # LEF thing obsolete
        ]:
            return alert
        if alert.cls == "error":
            logger.bind(step=self.id, key=alert.code).error(str(alert))
        elif alert.cls == "warning":
            logger.bind(step=self.id, key=alert.code).warning(str(alert))
        return alert

    def run(self, state_in: State, **kwargs) -> tuple[ViewsUpdate, MetricsUpdate]:
        self.alerts = None

        kwargs, env = self.extract_env(kwargs)

        automatic_outputs = set(self.outputs).intersection(
            [DesignFormat.ODB, DesignFormat.DEF]
        )

        views_updates: ViewsUpdate = {}
        command = self.get_command()
        for output in automatic_outputs:
            filename = f"{self.config.DESIGN_NAME}.{output.extension}"
            file_path = os.path.join(self.step_dir, filename)
            command.append(f"--output-{output.id}")
            command.append(file_path)
            views_updates[output] = Path(file_path)

        command += [
            str(state_in[DesignFormat.ODB]),
        ]

        env["PYTHONPATH"] = ":".join(
            (
                env.get("PYTHONPATH", ""),
                str(files("librelane").joinpath("scripts", "odbpy")),
            )
        )
        check = False
        if "check" in kwargs:
            check = kwargs.pop("check")

        subprocess_result = self.run_subprocess(
            command,
            env=env,
            check=check,
            **kwargs,
        )
        generated_metrics = subprocess_result["generated_metrics"]

        # 1. Parse warnings and errors
        self.alerts = subprocess_result.get("openroad_alerts") or []
        if subprocess_result["returncode"] != 0:
            error_strings = [
                str(alert) for alert in self.alerts if alert.cls == "error"
            ]
            if len(error_strings):
                error_string = "\n".join(error_strings)
                raise StepError(
                    f"{self.id} failed with the following errors:\n{error_string}"
                )
            else:
                step_exception_message = f"{self.id} failed with an unexpected error."
                log_path = self.get_log_path()
                if os.path.isfile(log_path):
                    step_exception_message += f" Please check {repr(os.path.relpath(log_path))} and unless you wrote the step yourself, file an issue.\n"
                    with open(log_path, "r", encoding="utf8") as f:
                        last_n_lines = f.readlines()[-10:]
                        step_exception_message += f"Last {len(last_n_lines)} lines:\n"
                        for line in last_n_lines:
                            step_exception_message += "\t" + line
                else:
                    step_exception_message += f" Please check the logs in {repr(self.step_dir)} and unless you wrote the step yourself, file an issue."
                raise StepException(step_exception_message)
        # 2. Metrics
        metrics_path = os.path.join(self.step_dir, "or_metrics_out.json")
        if os.path.exists(metrics_path):
            or_metrics_out = json.loads(open(metrics_path).read(), parse_float=Decimal)
            for key, value in or_metrics_out.items():
                if value == "Infinity":
                    or_metrics_out[key] = inf
                elif value == "-Infinity":
                    or_metrics_out[key] = -inf
            generated_metrics.update(or_metrics_out)

        metric_updates_with_aggregates = aggregate_metrics(generated_metrics)

        return views_updates, metric_updates_with_aggregates

    def get_command(self) -> list[str]:
        metrics_path = os.path.join(self.step_dir, "or_metrics_out.json")

        tech_lefs = self.toolbox.filter_views(self.config, self.config.TECH_LEFS)
        if len(tech_lefs) != 1:
            raise StepException(
                "Misconfigured SCL: 'TECH_LEFS' must return exactly one Tech LEF for its default timing corner."
            )

        lefs = ["--input-lef", str(tech_lefs[0])]
        for lef in self.config.CELL_LEFS:
            lefs.append("--input-lef")
            lefs.append(str(lef))
        if extra_lefs := self.config.EXTRA_LEFS:
            for lef in extra_lefs:
                lefs.append("--input-lef")
                lefs.append(str(lef))
        if pad_lefs := self.config.PAD_LEFS:
            for lef in pad_lefs:
                lefs.append("--input-lef")
                lefs.append(str(lef))
        if (design_lef := self.state_in.result().get(DesignFormat.LEF)) and (
            DesignFormat.LEF in self.inputs
        ):
            lefs.append("--design-lef")
            lefs.append(str(design_lef))
        return (
            [
                self.get_openroad_path(),
                "-exit",
                "-no_splash",
                "-metrics",
                str(metrics_path),
                "-python",
                self.get_script_path(),
            ]
            + self.get_subcommand()
            + lefs
        )

    @abstractmethod
    def get_script_path(self) -> str:
        pass

    def get_subcommand(self) -> list[str]:
        return []
