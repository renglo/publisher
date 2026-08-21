#!/usr/bin/env python3
"""Package publisher CDK app.

Reads publisher-config.json and synthesizes one stack: <publisher-name>-publisher.

The template is environment-agnostic (AWS::AccountId / AWS::Region). Choose the
publisher AWS account and region at deploy time.

    cd publisher/cdk
    cp publisher-config.example.json publisher-config.json
    python3.12 -m venv ../venv && source ../venv/bin/activate
    pip install -r requirements.txt
    export AWS_PROFILE=<your-publisher-profile>
    cdk synth --profile "$AWS_PROFILE"
    cdk deploy <publisher-name>-publisher --profile "$AWS_PROFILE"
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path

import aws_cdk as cdk

from stacks.registry import PublisherStack


def _require_explicit_profile() -> str:
    """Refuse the default credential chain so this never lands in the wrong account."""
    profile = (
        os.environ.get("AWS_PROFILE") or os.environ.get("AWS_DEFAULT_PROFILE") or ""
    ).strip()
    if not profile or profile == "default":
        raise SystemExit(
            "Refusing to synth/deploy without an explicit AWS profile "
            "(AWS_PROFILE is missing or set to 'default').\n"
            "  export AWS_PROFILE=<your-publisher-profile>\n"
            "  aws sts get-caller-identity --profile \"$AWS_PROFILE\"\n"
            "  cdk deploy <publisher-name>-publisher --profile \"$AWS_PROFILE\"\n"
            "List profiles: aws configure list-profiles"
        )
    print(f"Using AWS profile: {profile}", file=sys.stderr)
    return profile


_require_explicit_profile()

_ROOT = Path(__file__).resolve().parent
_CONFIG_PATH = _ROOT / "publisher-config.json"
if not _CONFIG_PATH.is_file():
    _example = _ROOT / "publisher-config.example.json"
    raise FileNotFoundError(
        f"publisher-config.json not found at {_CONFIG_PATH}\n"
        f"Copy the example: cp {_example} {_CONFIG_PATH}"
    )

with open(_CONFIG_PATH, encoding="utf-8") as _f:
    _cfg = json.load(_f)


def _require(key: str) -> str:
    v = str(_cfg.get(key, "") or "").strip()
    if not v:
        raise ValueError(f"publisher-config.json: required key '{key}' is missing or empty")
    return v


def _string_list(key: str) -> list[str]:
    raw = _cfg.get(key, [])
    if raw is None:
        return []
    if not isinstance(raw, list):
        raise ValueError(f"publisher-config.json: '{key}' must be a list")
    return [str(item).strip() for item in raw if str(item).strip()]


publisher_name = _require("publisher_name")
github_org = _require("github_org")
github_publish_repos = _string_list("github_publish_repos") or ["*"]
reader_aws_accounts = _string_list("reader_aws_accounts")
python_repository = str(_cfg.get("python_repository") or "python-store").strip()
npm_repository = str(_cfg.get("npm_repository") or "npm-store").strip()

app = cdk.App()
PublisherStack(
    app,
    f"{publisher_name}-publisher",
    publisher_name=publisher_name,
    github_org=github_org,
    github_publish_repos=github_publish_repos,
    reader_aws_accounts=reader_aws_accounts,
    python_repository=python_repository,
    npm_repository=npm_repository,
)
app.synth()
