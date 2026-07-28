#!/usr/bin/env python3

import argparse
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def git(*args: str) -> str:
    return subprocess.check_output(["git", *args], cwd=ROOT, text=True).strip()


def export_env(key: str, value: str) -> None:
    github_env = os.getenv("GITHUB_ENV")
    if os.getenv("GITHUB_ACTIONS") == "true" and github_env:
        with open(github_env, "a", encoding="utf8") as env_file:
            env_file.write(f"{key}={value}\n")
    else:
        os.environ[key] = value
        print(f"Setting ENV[{key}] to {value}...")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Determine whether the current revision should be published."
    )
    parser.parse_args()

    repository = os.getenv("GITHUB_REPOSITORY")
    repo_url = (
        f"https://github.com/{repository}.git"
        if repository
        else git("remote", "get-url", "origin")
    )
    branch = os.getenv("GITHUB_REF_NAME") or git("branch", "--show-current")
    event = os.getenv("GITHUB_EVENT_NAME", "workflow_dispatch")
    publishing_branch = branch in {"main", "dev"} or branch.startswith("version")

    new_tag = "NO_NEW_TAG"
    publish = False
    if event == "push" and publishing_branch:
        version = subprocess.check_output(
            ["python3", "./librelane/__version__.py"], cwd=ROOT, text=True
        ).strip()
        remote_tags = git("ls-remote", "--tags", repo_url)
        tags = {
            line.split()[1].removeprefix("refs/tags/").removesuffix("^{}")
            for line in remote_tags.splitlines()
            if line.strip()
        }
        if version not in tags:
            new_tag = version
            publish = True

    export_env("REPO_URL", repo_url)
    export_env("BRANCH_NAME", branch)
    export_env("NEW_TAG", new_tag)
    export_env("PUBLISHING_BRANCH", "1" if publishing_branch else "0")
    export_env("PUBLISH", "1" if publish else "0")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
