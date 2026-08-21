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

| Piece | Registry | Example name |
|-------|----------|----------------|
| Python package (handlers, APIs, blueprints shipped in the wheel) | CodeArtifact `python-store` (optional public PyPI later) | `acme-mail` |
| UI package (console screens, widgets) | CodeArtifact `npm-store` (optional public npmjs later) | `@acme/mail` |

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

| | Publisher (this repo) | Project / customer |
|---|-----------------------|--------------------|
| AWS account | Yours | Theirs (or another of yours) |
| Job | Host packages; accept publishes from your GitHub org | Run the product; `pip` / `npm` install |
| Stack | `<publisher-name>-publisher` | Their app infrastructure (Lambdas, databases, …) |
| GitHub | Product repos (`mail`, `scheduler`, …) | Releases / deploy repo |

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

| Resource | Name / path |
|----------|-------------|
| CloudFormation stack | `<publisher-name>-publisher` |
| CodeArtifact domain | sanitized publisher name (letters, digits, hyphens) |
| Repositories | `python-store` (upstream public PyPI), `npm-store` (upstream public npmjs) |
| IAM role | `GitHubActionsPublishRole-<publisher-name>` |
| SSM | `/publisher/config` — domain and repo names so workflows stay generic |

`reader_aws_accounts` adds a CodeArtifact **resource policy** so those accounts may call `GetAuthorizationToken` and `ReadFromRepository`. Each reader account still needs **its own** IAM (`codeartifact:GetAuthorizationToken`, `sts:GetServiceBearerToken`, `ReadFromRepository`). That policy lives on the project side, not in this stack.

---

## Deploy

Use the **publisher** AWS account and region (the account that will *own* the packages). Account and region are chosen at deploy time, not baked into product repos.

```bash
cd publisher/cdk
cp publisher-config.example.json publisher-config.json
# set publisher_name, github_org, github_publish_repos, reader_aws_accounts

python3.12 -m venv ../venv
source ../venv/bin/activate
pip install -r requirements.txt

cdk synth
cdk deploy <publisher-name>-publisher --app "python app.py"
```

Add `--parameters CreateGitHubOIDC=true` only if this account does not already have the GitHub Actions OIDC provider (`token.actions.githubusercontent.com`). If another stack already created it, leave the default `false`.

Copy stack output `OidcPublishRoleArn`.

---

## Connect GitHub (each product repo)

Product repositories should not know customer names, env names, or CodeArtifact domain strings. They only need **one** Actions variable (org-level is enough for every repo under this publisher):

| Variable | Value |
|----------|--------|
| `AWS_PUBLISH_ROLE_ARN` | `OidcPublishRoleArn` from `<publisher-name>-publisher` |

Optional: `AWS_REGION` (default `us-east-1`, must match this stack), `PACKAGE_DIR` if the package is not at the repo root (`package` or `ui`), `PUBLISH_PUBLIC=true` plus secrets `PYPI_API_TOKEN` / `NPM_TOKEN`.

Copy [workflows/publish-python.yml](workflows/publish-python.yml) to `.github/workflows/publish.yml` in each Python repo. Copy [workflows/publish-npm.yml](workflows/publish-npm.yml) for UI packages.

The job assumes the publisher role, reads `/publisher/config`, builds, and uploads. After you bump `version` in `pyproject.toml` / `package.json` and commit:

```bash
git tag v1.4.0
git push origin v1.4.0
```

The tag starts publish. The **package version** is whatever is in the manifest, not the tag string — keep them aligned.

---

## Public PyPI / npmjs

CodeArtifact is always the publisher registry (private or shared with listed accounts). If a package is open source, set `PUBLISH_PUBLIC=true` and the matching token so the same tag can also land on the public index. Keep proprietary packages off public indexes.
