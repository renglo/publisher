#!/usr/bin/env python3
"""Studio package publisher CDK app.

Reads studio-config.json and synthesizes one stack: <studio>-publisher.

The template is environment-agnostic (AWS::AccountId / AWS::Region). Choose the
studio AWS account and region at deploy time.

    cd publisher/cdk
    cp studio-config.example.json studio-config.json
    python3.12 -m venv ../venv && source ../venv/bin/activate
    pip install -r requirements.txt
    cdk synth
    cdk deploy <studio>-publisher [--parameters CreateGitHubOIDC=true]
"""

from __future__ import annotations

import json
from pathlib import Path

import aws_cdk as cdk

from stacks.registry import PublisherStack

_ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = _ROOT / "studio-config.json"
if not _CONFIG_PATH.is_file():
    _example = _ROOT / "studio-config.example.json"
    raise FileNotFoundError(
        f"studio-config.json not found at {_CONFIG_PATH}\n"
        f"Copy the example: cp {_example} {_CONFIG_PATH}"
    )

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)


def _require(key: str) -> str:
    v = str(_cfg.get(key, "") or "").strip()
    if not v:
        raise ValueError(f"studio-config.json: required key '{key}' is missing or empty")
    return v


def _string_list(key: str) -> list[str]:
    raw = _cfg.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"studio-config.json: '{key}' must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


studio_name = _require("studio_name")
github_org = _require("github_org")
github_publish_repos = _string_list("github_publish_repos") or ["*"]
reader_aws_accounts = _string_list("reader_aws_accounts")
python_repository = str(_cfg.get("python_repository") or "python-store").strip()
npm_repository = str(_cfg.get("npm_repository") or "npm-store").strip()

app = cdk.App()
PublisherStack(
    app,
    f"{studio_name}-publisher",
    studio_name=studio_name,
    github_org=github_org,
    github_publish_repos=github_publish_repos,
    reader_aws_accounts=reader_aws_accounts,
    python_repository=python_repository,
    npm_repository=npm_repository,
)
app.synth()
