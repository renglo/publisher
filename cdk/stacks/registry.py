"""Studio package registry: CodeArtifact + GitHub OIDC publish role.

One stack per studio AWS account. Product repos (renglo-lib, extensions, …)
are not parameterized here — they publish by assuming the OIDC role.
"""

from __future__ import annotations

import json
import re

from aws_cdk import CfnCondition, CfnOutput, CfnParameter, Fn, Stack
from aws_cdk import aws_codeartifact as codeartifact
from aws_cdk import aws_iam as iam
from aws_cdk import aws_ssm as ssm
from constructs import Construct

GITHUB_OIDC_PROVIDER_ARN_SUFFIX = "token.actions.githubusercontent.com"
GITHUB_OIDC_URL = "https://token.actions.githubusercontent.com"
GITHUB_OIDC_THUMBPRINT = "6938fd4d98bab03faadb97b34396831e3780aea1"
GITHUB_OIDC_CLIENT_ID = "sts.amazonaws.com"

PUBLISHER_CONFIG_PARAM = "/publisher/config"
PYTHON_REPO_DEFAULT = "python-store"
NPM_REPO_DEFAULT = "npm-store"


def sanitize_domain_name(studio_name: str) -> str:
    raw = studio_name.strip().lower().replace("_", "-")
    cleaned = re.sub(r"[^a-z0-9-]", "", raw)
    if not cleaned:
        raise ValueError("studio_name must contain letters or digits")
    if cleaned[0].isdigit():
        cleaned = f"pkg-{cleaned}"
    return cleaned[:50]


def _domain_arn(region: str, account: str, domain: str) -> str:
    return f"arn:aws:codeartifact:{region}:{account}:domain/{domain}"


def _repo_arn(region: str, account: str, domain: str, repo: str) -> str:
    return f"arn:aws:codeartifact:{region}:{account}:repository/{domain}/{repo}"


def _package_arn(region: str, account: str, domain: str, repo: str) -> str:
    return f"arn:aws:codeartifact:{region}:{account}:package/{domain}/{repo}/*/*"


def _oidc_subs(github_org: str, github_publish_repos: list[str]) -> list[str] | str:
    repos = [r.strip() for r in github_publish_repos if str(r).strip()]
    if not repos or repos == ["*"]:
        return f"repo:{github_org}/*:*"
    if len(repos) == 1:
        return f"repo:{github_org}/{repos[0]}:*"
    return [f"repo:{github_org}/{name}:*" for name in repos]


class PublisherStack(Stack):
    def __init__(
        self,
        scope: Construct,
        construct_id: str,
        *,
        studio_name: str,
        github_org: str,
        github_publish_repos: list[str] | None = None,
        reader_aws_accounts: list[str] | None = None,
        python_repository: str = PYTHON_REPO_DEFAULT,
        npm_repository: str = NPM_REPO_DEFAULT,
        **kwargs,
    ) -> None:
        super().__init__(
            scope,
            construct_id,
            description=f"Studio package publisher ({studio_name})",
            **kwargs,
        )
        aws_account = self.account
        aws_region = self.region
        domain_name = sanitize_domain_name(studio_name)
        python_repository = (python_repository or PYTHON_REPO_DEFAULT).strip() or PYTHON_REPO_DEFAULT
        npm_repository = (npm_repository or NPM_REPO_DEFAULT).strip() or NPM_REPO_DEFAULT
        readers = [a.strip() for a in (reader_aws_accounts or []) if str(a).strip()]
        publish_repos = list(github_publish_repos or ["*"])

        create_oidc = CfnParameter(
            self,
            "CreateGitHubOIDC",
            type="String",
            default="false",
            allowed_values=["true", "false"],
            description=(
                "Create the GitHub Actions OIDC provider in this account. "
                "Set to true only if token.actions.githubusercontent.com is not already registered."
            ),
        )
        create_oidc_condition = CfnCondition(
            self,
            "CreateGitHubOIDCCondition",
            expression=Fn.condition_equals(create_oidc.value_as_string, "true"),
        )

        domain_policy = _domain_policy(aws_account, readers)
        domain = codeartifact.CfnDomain(
            self,
            "PackageDomain",
            domain_name=domain_name,
            permissions_policy_document=domain_policy,
        )

        repo_policy = _repository_policy(readers)
        repo_kwargs: dict = {
            "domain_name": domain_name,
            "external_connections": ["public:pypi"],
        }
        if repo_policy is not None:
            repo_kwargs["permissions_policy_document"] = repo_policy

        python_repo = codeartifact.CfnRepository(
            self,
            "PythonStore",
            repository_name=python_repository,
            description=f"{studio_name} Python packages",
            **repo_kwargs,
        )
        python_repo.add_resource_dependency(domain)

        npm_kwargs = {
            "domain_name": domain_name,
            "external_connections": ["public:npmjs"],
        }
        if repo_policy is not None:
            npm_kwargs["permissions_policy_document"] = repo_policy
        npm_repo = codeartifact.CfnRepository(
            self,
            "NpmStore",
            repository_name=npm_repository,
            description=f"{studio_name} npm packages",
            **npm_kwargs,
        )
        npm_repo.add_resource_dependency(domain)

        oidc_provider_arn = (
            f"arn:aws:iam::{aws_account}:oidc-provider/{GITHUB_OIDC_PROVIDER_ARN_SUFFIX}"
        )
        if create_oidc_condition is not None:
            oidc_provider_resource = iam.CfnOIDCProvider(
                self,
                "GitHubOidcProviderResource",
                url=GITHUB_OIDC_URL,
                client_id_list=[GITHUB_OIDC_CLIENT_ID],
                thumbprint_list=[GITHUB_OIDC_THUMBPRINT],
            )
            oidc_provider_resource.cfn_options.condition = create_oidc_condition
        oidc_provider = iam.OpenIdConnectProvider.from_open_id_connect_provider_arn(
            self,
            "GitHubOidcProvider",
            open_id_connect_provider_arn=oidc_provider_arn,
        )

        domain_arn = _domain_arn(aws_region, aws_account, domain_name)
        repos = [
            _repo_arn(aws_region, aws_account, domain_name, python_repository),
            _repo_arn(aws_region, aws_account, domain_name, npm_repository),
        ]
        packages = [
            _package_arn(aws_region, aws_account, domain_name, python_repository),
            _package_arn(aws_region, aws_account, domain_name, npm_repository),
        ]
        config_param_arn = (
            f"arn:aws:ssm:{aws_region}:{aws_account}:parameter{PUBLISHER_CONFIG_PARAM}"
        )

        publish_role = iam.Role(
            self,
            "OidcPublishRole",
            role_name=f"GitHubActionsPublishRole-{studio_name}",
            assumed_by=iam.WebIdentityPrincipal(
                oidc_provider.open_id_connect_provider_arn,
                conditions={
                    "StringEquals": {
                        "token.actions.githubusercontent.com:aud": "sts.amazonaws.com"
                    },
                    "StringLike": {
                        "token.actions.githubusercontent.com:sub": _oidc_subs(
                            github_org, publish_repos
                        )
                    },
                },
            ),
            inline_policies={
                f"PublishToCodeArtifact-{studio_name}": iam.PolicyDocument(
                    statements=[
                        iam.PolicyStatement(
                            sid="CodeArtifactDomain",
                            actions=[
                                "codeartifact:GetAuthorizationToken",
                                "codeartifact:DescribeDomain",
                            ],
                            resources=[domain_arn],
                        ),
                        iam.PolicyStatement(
                            sid="CodeArtifactBearerToken",
                            actions=["sts:GetServiceBearerToken"],
                            resources=["*"],
                            conditions={
                                "StringEquals": {
                                    "sts:AWSServiceName": "codeartifact.amazonaws.com"
                                }
                            },
                        ),
                        iam.PolicyStatement(
                            sid="CodeArtifactPublish",
                            actions=[
                                "codeartifact:GetRepositoryEndpoint",
                                "codeartifact:ReadFromRepository",
                                "codeartifact:DescribeRepository",
                                "codeartifact:ListPackages",
                                "codeartifact:ListPackageVersions",
                                "codeartifact:DescribePackageVersion",
                                "codeartifact:GetPackageVersionReadme",
                                "codeartifact:GetPackageVersionAsset",
                                "codeartifact:PublishPackageVersion",
                                "codeartifact:PutPackageMetadata",
                                "codeartifact:PutPackageOriginConfiguration",
                            ],
                            resources=[*repos, *packages],
                        ),
                        iam.PolicyStatement(
                            sid="ReadPublisherConfig",
                            actions=["ssm:GetParameter"],
                            resources=[config_param_arn],
                        ),
                    ]
                )
            },
            description=f"GitHub Actions publishes {studio_name} packages to CodeArtifact",
        )

        config = {
            "studio_name": studio_name,
            "github_org": github_org,
            "domain": domain_name,
            "python_repository": python_repository,
            "npm_repository": npm_repository,
            "config_parameter": PUBLISHER_CONFIG_PARAM,
        }
        ssm.CfnParameter(
            self,
            "PublisherConfig",
            name=PUBLISHER_CONFIG_PARAM,
            type="String",
            tier="Standard",
            value=json.dumps(config, separators=(",", ":")),
            description="Studio CodeArtifact endpoints for GitHub publish workflows",
        )

        CfnOutput(self, "StudioName", value=studio_name)
        CfnOutput(self, "CodeArtifactDomainName", value=domain_name)
        CfnOutput(self, "CodeArtifactDomainOwner", value=aws_account)
        CfnOutput(self, "CodeArtifactPythonRepository", value=python_repository)
        CfnOutput(self, "CodeArtifactNpmRepository", value=npm_repository)
        CfnOutput(self, "OidcPublishRoleArn", value=publish_role.role_arn)
        CfnOutput(self, "PublisherConfigParameter", value=PUBLISHER_CONFIG_PARAM)
        CfnOutput(self, "GithubOrg", value=github_org)


def _domain_policy(account: str, readers: list[str]) -> dict:
    statements: list[dict] = [
        {
            "Sid": "StudioAccountDomain",
            "Effect": "Allow",
            "Principal": {"AWS": f"arn:aws:iam::{account}:root"},
            "Action": [
                "codeartifact:CreateRepository",
                "codeartifact:DescribeDomain",
                "codeartifact:GetAuthorizationToken",
                "codeartifact:GetDomainPermissionsPolicy",
                "codeartifact:ListRepositoriesInDomain",
            ],
            "Resource": "*",
        }
    ]
    if readers:
        statements.append(
            {
                "Sid": "ReaderGetAuthorizationToken",
                "Effect": "Allow",
                "Principal": {"AWS": [f"arn:aws:iam::{r}:root" for r in readers]},
                "Action": ["codeartifact:GetAuthorizationToken", "codeartifact:DescribeDomain"],
                "Resource": "*",
            }
        )
    return {"Version": "2012-10-17", "Statement": statements}


def _repository_policy(readers: list[str]) -> dict | None:
    if not readers:
        return None
    return {
        "Version": "2012-10-17",
        "Statement": [
            {
                "Sid": "ReaderPull",
                "Effect": "Allow",
                "Principal": {"AWS": [f"arn:aws:iam::{r}:root" for r in readers]},
                "Action": [
                    "codeartifact:DescribePackageVersion",
                    "codeartifact:DescribeRepository",
                    "codeartifact:GetPackageVersionReadme",
                    "codeartifact:GetRepositoryEndpoint",
                    "codeartifact:ListPackageVersions",
                    "codeartifact:ListPackages",
                    "codeartifact:ReadFromRepository",
                    "codeartifact:GetPackageVersionAsset",
                    "codeartifact:ListPackageVersionAssets",
                    "codeartifact:ListPackageVersionDependencies",
                ],
                "Resource": "*",
            }
        ],
    }
