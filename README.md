# Package publisher

This repo is the starting point for anyone who **builds extensions** (and related tools) and wants other projects to **install them as versioned packages** — not by cloning your source.

It deploys one AWS stack: a private **Python + npm registry** for you as a **publisher**, plus a GitHub login so a `v1.2.0` tag on a product repo publishes that version automatically.

---

## The problem

An extension is a product: backend code, often a UI, sometimes other artifacts. Teams used to consume it by **cloning a git repo at a pinned commit**. That falls apart as soon as:

- The repo is private and the consumer’s CI token cannot read it
- Several publishers each ship their own extensions (each in a different GitHub org)
- You want semver, rollback, and “install `mail==1.4.0`” instead of a SHA
- The people who **write** the extension should not hard-code who **runs** it, or in which customer AWS account

Cloning git is a fine way to *develop*. It is a poor way to *distribute*.

This stack gives the publisher a registry the rest of the world (or only selected AWS accounts) can `pip` / `npm` from. Your product repos stay ordinary libraries. Customer apps stay ordinary installers.

---

## What you are publishing

Think of an extension the way you think of a plugin for an editor or a payment SDK: one product, one version, installable in many apps.

A typical extension repo holds:


| Piece                                                            | Registry                                                 | Example name |
| ---------------------------------------------------------------- | -------------------------------------------------------- | ------------ |
| Python package (handlers, APIs, blueprints shipped in the wheel) | CodeArtifact `python-store` (optional public PyPI later) | `acme-mail`  |
| UI package (console screens, widgets)                            | CodeArtifact `npm-store` (optional public npmjs later)   | `@acme/mail` |


You may also publish **platform libraries** the same way (a shared core used by many extensions). Same pipeline: tag → package → registry.

You do **not** publish a running application. Consumers install your packages into *their* app, the same way they install `requests` or `lodash`.

---

## How a project uses your extensions

A project (a company running the platform, an internal app, another publisher’s demo) never needs push access to your git history. They need:

1. Permission to **read** your registry (same AWS account, or their account listed in `reader_aws_accounts`)
2. A bill of materials: “use `acme-mail==1.4.0` and `@acme/mail==1.4.0`”

Then their CI does the boring thing:

```bash
aws codeartifact login --tool pip \
  --domain acme \
  --domain-owner <your-publisher-aws-account> \
  --repository python-store

pip install "acme-mail==1.4.0"
```

Same idea for npm. When they want 1.5.0, they bump the pin — they do not re-clone your repo.

**One project, many publishers** is normal. Northwind might install `acme-mail` from Acme’s registry and `contoso-search` from Contoso’s, and still publish `northwind-payroll` to *their own* registry for internal-only use. Consume and publish are separate stacks: this one is publish (plus the lock on who may pull).

---

## Two roles (do not mix them)


|             | Publisher (this repo)                                | Project / customer                               |
| ----------- | ---------------------------------------------------- | ------------------------------------------------ |
| AWS account | Yours                                                | Theirs (or another of yours)                     |
| Job         | Host packages; accept publishes from your GitHub org | Run the product; `pip` / `npm` install           |
| Stack       | `<publisher-name>-publisher`                         | Their app infrastructure (Lambdas, databases, …) |
| GitHub      | Product repos (`mail`, `scheduler`, …)               | Releases / deploy repo                           |


A company can wear **both hats**. They deploy this stack for extensions they own, and they add *other* publishers’ AWS accounts as readers (or the reverse: other publishers add *them* as readers).

```text
  GitHub: acme/mail
       │  git tag v1.4.0
       ▼
  Acme AWS — this stack
  CodeArtifact domain "acme"
       │  pip install acme-mail==1.4.0
       ▼
  Any allowed project AWS account
```

---

## What the stack creates


| Resource             | Name / path                                                                |
| -------------------- | -------------------------------------------------------------------------- |
| CloudFormation stack | `<publisher-name>-publisher`                                               |
| CodeArtifact domain  | sanitized publisher name (letters, digits, hyphens)                        |
| Repositories         | `python-store` (upstream public PyPI), `npm-store` (upstream public npmjs) |
| IAM role             | `GitHubActionsPublishRole-<publisher-name>`                                |
| SSM                  | `/publisher/<publisher-name>/config` — domain and repo names for workflows |


`reader_aws_accounts` adds a CodeArtifact **resource policy** so those accounts may call `GetAuthorizationToken` and `ReadFromRepository`. Each reader account still needs **its own** IAM (`codeartifact:GetAuthorizationToken`, `sts:GetServiceBearerToken`, `ReadFromRepository`). On the tenant/launcher side that is `package_registry.domain_owners` (list of foreign publisher AWS accounts; same-account read is always granted). BOM `deploy_targets.yml` lists login targets under `registries:` (omit for internal-only).

**Multiple publishers in one AWS account:** Supported. Each `publisher_name` gets its own stack, CodeArtifact domain, IAM role, and SSM path. Deploy with a different `publisher-config.json` per publisher (or swap config between deploys). Only the GitHub OIDC provider is shared — set `CreateGitHubOIDC=false` on the second and later deploys.

---

## Configure `publisher-config.json`

CDK reads this file when you synth or deploy. Fill it in **before** the first deploy. A later change only takes effect after you redeploy.

```bash
cd publisher/cdk
cp publisher-config.example.json publisher-config.json
```


| Field                                    | What to set                                                                                                                                                                                                 |
| ---------------------------------------- | ----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| `publisher_name`                         | Short name for this publisher. Stack name is `<publisher_name>-publisher`; the CodeArtifact domain is a sanitized form of this name.                                                                        |
| `github_org`                             | GitHub org that owns the product repos.                                                                                                                                                                     |
| `github_publish_repos`                   | Repo **short names** that may assume the publish role (e.g. `renglo-lib`, `data`, `stanley-wl`). List every repo you already know will publish. Avoid `["*"]` unless you want **any** repo in the org. The stack trusts both classic (`repo:org/name`) and GitHub's immutable (`repo:org@id/name@id`) OIDC subjects — repos created after 15 Jul 2026 use the latter. |
| `reader_aws_accounts`                    | AWS account IDs allowed to `pip` / `npm` install from this registry. Empty = same-account readers only. Each reader account still needs its own IAM (see above).                                            |
| `python_repository` / `npm_repository`   | Usually leave as `python-store` / `npm-store`.                                                                                                                                                              |


Account and region are **not** in this file. Templates use `AWS::AccountId` / `AWS::Region`. Choose them at deploy time with your AWS profile.

**Adding a repo later:** append its short name to `github_publish_repos` and redeploy. Then do [Step 2](#step-2--configure-each-product-repository) for that repo (workflow file + Actions variables).

---

## Deploy

Use the **publisher** AWS account and region (the account that will *own* the packages).

```bash
cd publisher/cdk
python3.12 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt --index-url https://pypi.org/simple

export AWS_PROFILE=<aws-profile>
export AWS_REGION=<aws-region>
aws sts get-caller-identity --profile "$AWS_PROFILE"

cdk synth --profile "$AWS_PROFILE"
cdk deploy <publisher-name>-publisher --app "python app.py" --profile "$AWS_PROFILE"
```

This `pip install` only downloads the CDK libraries used to deploy the stack. It does not publish anything. Product packages still go to CodeArtifact (`python-store` / `npm-store`) via the GitHub workflows below — not to public PyPI unless a repo sets `PUBLISH_PUBLIC`. `--index-url https://pypi.org/simple` is here so a leftover `aws codeartifact login --tool pip` (expired token in `~/.config/pip/pip.conf`) does not 401 this bootstrap step.

`app.py` exits if `AWS_PROFILE` is unset or `default`. Pass `--profile` (CDK forwards it as `AWS_PROFILE`) or export the variable. Profile names are machine-local — they do not belong in `publisher-config.json`.

Add `--parameters CreateGitHubOIDC=true` only if this account does not already have the GitHub Actions OIDC provider (`token.actions.githubusercontent.com`). If another stack already created it, leave the default `false`.

---

## Connect GitHub and publish packages

Publishing is configured **per product repository**. Credentials and registry pointers live in that repo's GitHub Actions settings — not at org level — so random repos in the org cannot inherit publish access.

**Two gates must both allow the repo:**

1. **AWS** — repo name listed in `github_publish_repos` in `publisher-config.json` (OIDC trust on the publish role). Set this before deploy; if you add a name later, redeploy.
2. **GitHub** — that repo has the workflow file and repository variables set below.

Product repos never hard-code CodeArtifact domain names or customer env names.

### Step 1 — Find your AWS region

Publish workflows must call AWS in the **same region where you deployed** `<publisher-name>-publisher`. You will paste this value into **each** product repo in Step 2.

**Where to get it:**


| Source                 | How                                                                            |
| ---------------------- | ------------------------------------------------------------------------------ |
| Your deploy shell      | The `AWS_REGION` (or `--region`) you used with `cdk deploy`                    |
| AWS CLI profile        | `aws configure get region --profile <aws-profile>`                             |
| CloudFormation console | **CloudFormation → Stacks → `<publisher-name>-publisher` → Overview → Region** |


```bash
export AWS_PROFILE=<aws-profile>
aws configure get region --profile "$AWS_PROFILE"
```

Example result: `us-east-1`. Write it down — you need it for every repo you connect.

---

### Step 2 — Configure each product repository

Repeat this block **for every repo** that should publish (e.g. `renglo-lib`, `renglo-api`, `data`, `schd`). Skip repos that will never publish.

The repo must already appear in `github_publish_repos`. If you are adding a repo after the first deploy, add its name there and redeploy first.

#### 2a. Get the shared stack outputs (once)

Run these once; the same three values go into **each** product repo you connect:

```bash
export AWS_PROFILE=<aws-profile>
export AWS_REGION=<aws-region>          # from Step 1
export STACK=<publisher-name>-publisher

aws cloudformation describe-stacks \
  --stack-name "$STACK" \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION" \
  --query 'Stacks[0].Outputs[?OutputKey==`OidcPublishRoleArn` || OutputKey==`PublisherName`].[OutputKey,OutputValue]' \
  --output table
```

Copy `OidcPublishRoleArn` and `PublisherName`. Workflows read `/publisher/<PublisherName>/config` in SSM (you do not set that path). 

#### 2b. Set repository variables

In GitHub: **that repo → Settings → Secrets and variables → Actions → Variables → New repository variable**


| Variable               | Value                        | Notes                                          |
| ---------------------- | ---------------------------- | ---------------------------------------------- |
| `AWS_PUBLISH_ROLE_ARN` | `OidcPublishRoleArn` from 2a | Same ARN in every connected repo               |
| `PUBLISHER_NAME`       | `PublisherName` from 2a      | e.g. `renglo` → SSM `/publisher/renglo/config` |
| `AWS_REGION`           | Region from Step 1           | Must match deploy region                       |


Do not set any other Actions variables for the usual repos (`renglo-lib`, `renglo-api`, `data`, `schd`, …).

#### 2c. Add the workflow file

Pick **one row** for the repo:


| Repo type                         | Layout                                      | Workflow to copy                                         | Destination                     |
| --------------------------------- | ------------------------------------------- | -------------------------------------------------------- | ------------------------------- |
| Python only                       | `pyproject.toml` at root                    | [publish-python.yml](workflows/publish-python.yml)       | `.github/workflows/publish.yml` |
| npm only                          | `package.json` at root                      | [publish-npm.yml](workflows/publish-npm.yml)             | `.github/workflows/publish.yml` |
| **Extension (Python and/or npm)** | `package/` and/or `ui/`                     | [publish-extension.yml](workflows/publish-extension.yml) | `.github/workflows/publish.yml` |


**Extension repos (`data`, `schd`, `claw`, …):** one workflow file covers Python-only, npm-only, and both. [publish-extension.yml](workflows/publish-extension.yml) detects `package/pyproject.toml` and `ui/package.json` and skips the missing job. A tag publishes whichever artifacts exist. You only set the three variables above.

If the Python or npm tree is not at the repo root (and this is not an extension), see [Annex: `PACKAGE_DIR](#annex-package_dir)`.

Repo-root `blueprints/*.json` stay where they are. The publish job copies them into `package/<import>/blueprints/` before `python -m build package` so the wheel includes the current tag. Do not move the git folder. Local helper: [scripts/stage_extension_blueprints.py](scripts/stage_extension_blueprints.py).

After a tag is on CodeArtifact, pin it in the tenant BOM. Step-by-step (extension files vs BOM JSON): [docs/package-registry-extension-cutover.md](docs/package-registry-extension-cutover.md).

On release, bump `**version` in every tree that exists** (`package/pyproject.toml` and/or `ui/package.json`) to the same semver before tagging.

Commit and push the workflow file to the repo's default branch.

---

### Step 3 — Optional: also publish to public PyPI / npmjs

By default, tags publish **only to CodeArtifact**. Set these on **that repo only** if you want a public index too:


| Setting          | Where             | Value                   |
| ---------------- | ----------------- | ----------------------- |
| `PUBLISH_PUBLIC` | Repo **variable** | `true`                  |
| `PYPI_API_TOKEN` | Repo **secret**   | PyPI API token (Python) |
| `NPM_TOKEN`      | Repo **secret**   | npm token (UI)          |


**Warnings:**

- `**PUBLISH_PUBLIC` makes the package public** on PyPI/npmjs — anyone can install it without CodeArtifact credentials.
- **Public package ≠ public GitHub repo**, but open-source packages usually live in public repos. Do not enable for proprietary code.
- **Public release is effectively irreversible.** Bump version and publish a fix; do not rely on unpublish.
- Proprietary extensions (e.g. `props`) should never set `PUBLISH_PUBLIC`.

---

### Step 4 — Release a version (order matters)

A git tag triggers the publish workflow. The **version consumers install** comes from the manifest (`pyproject.toml` or `package.json`), **not** from the tag string. Keep them aligned.

**What “bump the version” means:** increment the semver in the manifest before you release — e.g. `1.0.0` → `1.0.1` (patch), `1.1.0` (minor), or `2.0.0` (major).

You are probably not sitting on `main`. That is fine — do the version bump on the branch that actually has the code. Then, **before you tag**, get that same code onto `main`. The publish job builds whatever commit the tag points at.

**1. Bump the version on the branch that has the code**

Python — set `version` in `pyproject.toml`:

```toml
[project]
name = "renglo-data"
version = "1.0.1"
```

Extension repos — bump **both** `package/pyproject.toml` and `ui/package.json` to the same version.

npm-only — edit `version` in `ui/package.json` (or root `package.json`):

```json
"version": "1.0.1"
```

```bash
git add pyproject.toml          # or package/pyproject.toml, ui/package.json, etc.
git commit -m "Release 1.0.1"
```

**2. Merge that branch into `main`, then tag `main`**

```bash
git checkout main
git pull origin main
git merge your-branch           # the branch that has the code you want to release
git push origin main

git tag v1.0.1
git push origin v1.0.1
```

The tag push starts **Publish to publisher registry** in GitHub Actions. The workflow builds the package and uploads `1.0.1` to CodeArtifact.

**3. Confirm the version is on the registry**

First, the Actions run must succeed: repo → **Actions** → the run for tag `v1.0.1`.

Then check CodeArtifact itself (publisher AWS account, same region as the stack). Replace names and version with what you just published:

```bash
export AWS_PROFILE=<aws-profile>
export AWS_REGION=<aws-region>
export PUBLISHER_NAME=renglo          # stack output PublisherName
ACCOUNT=$(aws sts get-caller-identity --query Account --output text --profile "$AWS_PROFILE")

# Python (renglo-lib, renglo-api, renglo-data, …)
aws codeartifact list-package-versions \
  --domain "$PUBLISHER_NAME" \
  --domain-owner "$ACCOUNT" \
  --repository python-store \
  --format pypi \
  --package renglo-data \
  --query 'versions[?version==`1.0.1`].version' \
  --output text \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"

# npm (@renglo/data → namespace renglo, package data)
aws codeartifact list-package-versions \
  --domain "$PUBLISHER_NAME" \
  --domain-owner "$ACCOUNT" \
  --repository npm-store \
  --format npm \
  --namespace renglo \
  --package data \
  --query 'versions[?version==`1.0.1`].version' \
  --output text \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
```

Each command should print `1.0.1`. Empty output means that version is not in the store — do not pin it in a BOM yet.

Optional consumer check (clean venv / empty npm cache):

```bash
aws codeartifact login --tool pip \
  --domain "$PUBLISHER_NAME" \
  --domain-owner "$ACCOUNT" \
  --repository python-store \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
pip install "renglo-data==1.0.1"

aws codeartifact login --tool npm \
  --domain "$PUBLISHER_NAME" \
  --domain-owner "$ACCOUNT" \
  --repository npm-store \
  --profile "$AWS_PROFILE" \
  --region "$AWS_REGION"
npm view @renglo/data@1.0.1 version
```

**Common mistakes:**


| Mistake                                                                 | Result                                                                         |
| ----------------------------------------------------------------------- | ------------------------------------------------------------------------------ |
| Tag before bumping the manifest                                         | Old version gets republished                                                   |
| Tag `v1.0.2` but manifest says `1.0.1`                                  | Confusing releases; consumers see `1.0.1` on the index                         |
| Bump version but forget to commit before tagging                        | Tag points at a commit that still has the old version                          |
| Tag `main` without merging your branch into it                          | Whatever was already on `main` is published; your branch is left behind        |
| `git push origin main` while on another branch                          | Git says `Everything up-to-date`; `main` does not move                         |
| Tag and `git push origin vX.Y.Z` before that commit is on remote `main` | GitHub: *“This commit does not belong to any branch”*; the tag still publishes |


Do not add a BOM pin until step 3 printed the version.

---

## Annex: `PACKAGE_DIR`

You do **not** set `PACKAGE_DIR` on `renglo-lib`, `renglo-api`, or any extension.

- **lib / api:** [publish-python.yml](workflows/publish-python.yml) defaults to `.` (`pyproject.toml` at the repo root).
- **extensions:** [publish-extension.yml](workflows/publish-extension.yml) never reads `PACKAGE_DIR`. It publishes `package/` and/or `ui/` when those trees exist.

Set it only when you copy `publish-python.yml` or `publish-npm.yml` into a **single-artifact** repo whose manifest is **not** at the root:


| When using                                    | Set `PACKAGE_DIR` to | Example                               |
| --------------------------------------------- | -------------------- | ------------------------------------- |
| `publish-python.yml`, Python under `package/` | `package`            | Python-only repo with no `ui/`        |
| `publish-npm.yml`, npm under `ui/`            | `ui`                 | Standalone UI repo with no `package/` |


If that repo also has the other tree, use `publish-extension.yml` instead of `PACKAGE_DIR`.

Wrong `PACKAGE_DIR` makes the build fail or publish the wrong tree. Leave it unset unless you are in one of the rows above.