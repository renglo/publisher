# Package registry migration

Team reference for moving Renglo deploys from **git clone in CI** to **versioned packages** (AWS CodeArtifact now; public PyPI / npmjs for open-source core later).

**Status:** Phase 2 in progress (`data` is the reference extension)  
**Last updated:** 2026-08-23 (Phase 2: wheels include `blueprints/`; code-first resolve)  
**Owners:** Platform / BOM (`<tenant>-bom`, launcher, bootstrap)

---

## Why we are doing this

Today `<tenant>-bom` CI clones private GitHub repos at pinned commits (`checkout_bom.py`) and builds from source trees. That breaks when:

- Repos are private and the default `github.token` cannot read them
- Extensions live in another org (e.g. `blalab/props`)
- We want semver, rollback, and caching without managing dozens of repo tokens

**Target:** CI installs pinned versions from a registry (`pip install …`, `npm install …`). GitHub access is only needed to **publish** packages (on tag), not to **deploy**.

---



## Current vs target


| Today                                                        | Target                                                                      |
| ------------------------------------------------------------ | --------------------------------------------------------------------------- |
| `bom/vX.Y.Z.json` pins **git SHAs**                     | BOM pins **package versions**                                               |
| `checkout_bom.py` clones into `dev/`, `extensions/`      | `pip` / `npm` install from CodeArtifact                                     |
| Dockerfile runs `install_backend_packages.py` on local trees | `pip install renglo-lib==… renglo-api==… renglo-gmail==…`                   |
| Console workflow clones repos; Vite aliases `../extensions/` | `npm install @renglo/console @renglo/data …`; prod aliases → `node_modules` |
| Auth: GitHub PAT per org/repo                                | Auth: CodeArtifact token (one domain)                                       |


---



## Scope



### Platform Python packages


| Component             | PyPI name (target) | Current location | Notes                                                 |
| --------------------- | ------------------ | ---------------- | ----------------------------------------------------- |
| Core library          | `renglo-lib`       | `dev/renglo-lib` | Already a package (`pyproject.toml`)                  |
| API / Lambda app      | `renglo-api`       | `dev/renglo-api` | Already a package (`setup.py`); add `pyproject.toml`  |
|                       |                    |                  |                                                       |
| Local WebSocket relay | `renglo-wss`       | `dev/wss`        | Dev-only; optional package or `renglo-api[dev]` extra |




### Platform frontend


| Component     | npm name (target) | Current location | Notes                                                                                                    |
| ------------- | ----------------- | ---------------- | -------------------------------------------------------------------------------------------------------- |
| Console shell | `@renglo/console` | `console/`       | **Vite + React SPA** (not Next.js). Publish source; CI runs `npm run build` → static `dist/` for Amplify |




### Extensions (monorepo per extension — keep this design)

One Git repo per extension; Python + UI stay aligned on the **same git tag** (TensorFlow-style multi-package repo):

```text
extensions/<name>/
├── package/          → PyPI:  renglo-<name>
├── ui/               → npm:   @renglo/<name>
├── blueprints/       → third deliverable (same git tag; see below)
├── installer/        → ops scripts (not published)
└── (optional) root pyproject / npm workspace for local dev
```

**Open-source candidates (public PyPI + npmjs):** `renglo-lib`, `renglo-api`, `console`, `data`, `schd`, `pes`  
**Private / customer extensions:** CodeArtifact only (e.g. `props`)

Normalize names before public release (e.g. `gmail-mod` → `renglo-gmail`, bare `data` → `renglo-data`).

---



## Registry strategy



### Phase A — Publisher CodeArtifact (now)

- **Not** part of customer stack-a / stack-b. Registry lives in `ops/publisher` (`<publisher-name>-publisher`).
- One **domain per publisher** (e.g. `renglo`), not per customer env
- Two repositories: `python-store`, `npm-store` (upstream PyPI / npmjs)
- GitHub OIDC **publish** role in the publisher account; product repos set one org variable `AWS_PUBLISH_ROLE_ARN`
- Workflows read `/publisher/<publisher-name>/config` after assume-role (no customer env name in `renglo-lib`)
- Optional `reader_aws_accounts` so tenant accounts can `pip`/`npm` install
- Optional second hop to public PyPI / npmjs (`PUBLISH_PUBLIC`)



### Phase B — Dual publish (open core)

On release tag (e.g. `v1.2.0`):

1. Publish to CodeArtifact (always)
2. Publish to public PyPI / npmjs (repos marked open-source)

Proprietary extensions never publish to public indexes.

---



## Release bill of materials (v2 schema)

Evolve `bom/vX.Y.Z.json` from git SHAs to version pins. Example:

```json
{
  "version": "v0.1.0",
  "description": "Package-based deploy",
  "python": {
    "renglo-lib": "1.0.1",
    "renglo-api": "1.0.1",
    "renglo-data": "1.0.0",
    "renglo-gmail": "0.3.1"
  },
  "npm": {
    "@renglo/console": "0.1.0",
    "@renglo/data": "1.0.0",
    "@renglo/gmail": "0.3.1"
  }
}
```

During migration, support **both** `repos` (git) and `python` / `npm` (packages) until git clone is removed.

---



## Console distribution (npm)

We do **not** publish a “running app” to npm. We publish:

- `@renglo/console` — source + build scripts; CI installs it and extension UI packages, then `npm run build`
- Extension UIs as `@renglo/<extension>` dependencies

Production Vite config must resolve extensions from `node_modules/@renglo/…` when `VITE_DEV_MODE=false`. Local dev keeps `../extensions/…` (see `console/extensions.local.ts`, `EXTENSIONS_README.md` Method 3).

Amplify still deploys `console/dist/` (static files). No Next.js migration required.

---



## Blueprints (third deliverable)

An extension has **three first-class artifacts**, one git repo, one authority:

| Artifact | Authority | How you change it | Distribution today / target |
|----------|-----------|-------------------|-----------------------------|
| 1. Python package | Extension git (`renglo/dumbo` or fork `acme/dumbo`) | PRs, maintainer, tags | CodeArtifact → PyPI |
| 2. npm package | Same repo, same tag | Same | CodeArtifact → npmjs |
| 3. Blueprints | Same repo, same tag (`blueprints/*.json`) | Same | Current tag is copied into the Python wheel at publish/install |

Forking the repo publishes under a **different namespace** (PyPI name, `@scope`, blueprint `handle`). Repo **public vs private** is whether those blueprints are public or private. Do **not** use a separate `*-blueprints` git repo.

### Authority vs serving

- **Source of truth for history** is git (tags = published contract versions; do not rewrite tags).
- **Runtime must not clone GitHub.** Private repos made git-as-CDN fail for the same reason CI clone failed. Python and npm already avoid that via registries.
- **Serving is a projection** of git (wheel, Dynamo seed, dump, CDN, public API). The channel can change; the repo does not.

Blueprints differ from code packages: **documents pin old versions**, so in theory every published tag must remain fetchable. A venv/wheel only holds **one** package version, so “latest JSON in the wheel” is **not** a full archive.

### Agreed for now (pragmatic)

1. **Ship current-tag blueprint JSON in the Python wheel** (`package_data` / files under the importable package). Same private/public registry path as the rest of the wheel. No GitHub token at deploy.
2. **Seed tenant Dynamo** from those files (existing `extension_blueprints.py` flow). Dynamo is a **local cache / leftover versions / tenant-custom blueprints**, not the global library.
3. **Defer full history.** Walking every git tag (or publishing every tag to S3/CodeArtifact) can come later. Old documents whose version is not in the current wheel keep working only if Dynamo still has that row.
4. **Resolve in this order** (backend / BlueprintController / `/_blueprint`):
   1. **Installed packages** (code in the venv — including dependency extensions)
   2. **Tenant Dynamo**
   3. **Optional public URL / API** (open-source extensions only)

Cross-extension: if `renglo-b` depends on `renglo-a` and both are installed, B sees A’s **current** blueprints via (1) without copying JSON into B.

### Later (history without git clone at runtime)

On each tag, optionally also publish versioned JSON to CodeArtifact/S3 (`dumbo/dumbo_profiles/1.2.0.json`), or accumulate old files in the wheel (`blueprints/foo/1.2.0.json`). Consumers still never clone. Not required for the first registry milestone.

---



## Migration phases



### Phase 0 — Foundations

- [x] Publisher CDK (`ops/publisher`) — CodeArtifact domain + python/npm stores + GitHub OIDC publish role
- [x] Peel registry out of customer stack-a (tenant templates stay auth/storage/runtime only)
- [x] Standardize `renglo-api` on `pyproject.toml` (match `renglo-lib`)
- [x] Normalize extension PyPI/npm names (`renglo-*`, `@renglo/*`)
- [x] Per-repo **publish on tag** workflow (lib, api) — assume publisher role; read publisher SSM config

**Exit criteria:** `pip install renglo-lib==x renglo-api==x` from the **Renglo publisher** CodeArtifact in a clean venv.

Deploy `ops/publisher` once in the Renglo AWS account (`cdk deploy renglo-publisher`). For **each** product repo, set repository Actions variables (not org-wide):

| Variable | Stack output |
|----------|----------------|
| `AWS_PUBLISH_ROLE_ARN` | `OidcPublishRoleArn` |
| `PUBLISHER_NAME` | `PublisherName` (e.g. `renglo`) |
| `AWS_REGION` | Same region as deploy |
| `PACKAGE_DIR` | Single-artifact repos only: `.` (lib/api), `package`, or `ui`. Omit on `publish-extension.yml`. |

Also list each repo in `github_publish_repos` in `publisher-config.json`. Domain and repository names come from the publisher's SSM config, not from product repos.

Push a `v*` tag (or run **Publish Python to publisher registry**). Then in a clean venv:

```bash
aws codeartifact login --tool pip \
  --domain renglo \
  --domain-owner "$PUBLISHER_AWS_ACCOUNT" \
  --repository python-store
pip install "renglo-lib==1.0.0" "renglo-api==1.0.0"
```

See [ops/publisher/README.md](../publisher/README.md).

Distribution names after this phase (import packages unchanged):

| Dist name | Import |
|-----------|--------|
| `renglo-lib` / `renglo-api` | `renglo` / `renglo_api` |
| `renglo-data`, `renglo-schd`, `renglo-pes`, `renglo-props`, … | `data`, `schd`, `pes`, `props`, … |
| `@renglo/data`, `@renglo/schd`, `@renglo/breakdown`, … | console aliases |

The publish role trusts `repo:<github_org>/<repos>` from `publisher-config.json` (Renglo example: whole `renglo` org).

### Phase 1 — Core platform off git clone

- [x] Update `<tenant>-bom` Dockerfile: install `wheels/` from the BOM, then leftover local trees (`install_backend_packages.py`)
- [x] Introduce BOM JSON v2 (`python` / `npm` sections alongside `repos`)
- [x] Update `deploy.yml` / `deploy_console.yml`: CodeArtifact login; skip `checkout_bom.py` for pinned core Python
- [x] Console CI: `npm install` from BOM when `npm` pins exist; Vite uses `node_modules/@renglo/*` when the local `ui/` tree is absent

**Exit criteria:** Backend Lambda deploy succeeds with zero git clones for `renglo-lib` / `renglo-api`.

**Cutover (operational — not flipped yet):** see [ops/docs/package-registry-migration.md](../../docs/package-registry-migration.md).

### Phase 2 — Extensions on registry

- [x] Publish workflow stages repo-root `blueprints/` into the Python wheel (git layout unchanged)
- [x] `data` is the reference: `package_data` + setup.py stage; other extensions declare `package-data`
- [x] Backend image: leftover `extensions/*/package` installs stage sibling `blueprints/` into a temp copy
- [x] Blueprint resolve: **code (wheel) first**, then Dynamo, then optional `BLUEPRINT_PUBLIC_BASE_URL`
- [x] Seed Dynamo still uses Dynamo existence (not the code-first getter), current tag only
- [ ] Pin each extension in the BOM after it is published (`renglo-<ext>` / `@renglo/<ext>`); start with `data`
- [ ] External handlers-service still clones until it can `pip install` the same pins

**Exit criteria:** Full stack deploy from BOM only; no `checkout_bom.py`.

**Operator playbook (what to change in each extension vs the BOM):** [package-registry-extension-cutover.md](package-registry-extension-cutover.md).

**Do not invent pins.** After `renglo-data` (and `@renglo/data`) are on the publisher stores, add them to a new `bom/vX.Y.Z.json` `python` / `npm` section. The existing `repos.renglo/data` row can stay; the pin wins and CI will not clone it.

**Git layout does not change.** `blueprints/` stays at the extension root. Publish/install copy those JSON files into `package/<import>/blueprints/` so `find_blueprints_dir` works from site-packages.

### Phase 3 — Open source

- [ ] Public GitHub for core repos
- [ ] Dual-publish tags to PyPI + npmjs
- [ ] Document: open core from public indexes; private extensions from CodeArtifact
- [ ] Customer extensions remain private on CodeArtifact

---



## First milestone (recommended)

Smallest step that fixes private-repo CI pain for the backend:

1. CodeArtifact domain live
2. Publish `renglo-lib` + `renglo-api` on tag
3. One `<tenant>-bom` deploy using pip from CodeArtifact (extensions still git clone temporarily)

---



## What stays in git (not replaced by packages)


| In git                                | Published as package       |
| ------------------------------------- | -------------------------- |
| Source code                           | Yes                        |
| Blueprints (source)                   | Yes (in wheel or artifact) |
| `customer-config.json`, CDK, launcher | No — infra                 |
| `<tenant>-bom` BOM + workflows    | No — orchestration         |
| `env_config.py`, secrets              | No                         |


---



## Key decisions (record when made)


| Decision                            | Choice                                        | Date | Notes       |
| ----------------------------------- | --------------------------------------------- | ---- | ----------- |
| Extension PyPI/npm version coupling | Same semver on both for one tag               |      | Recommended |
| Console repo layout                 | Separate `renglo/console` → `@renglo/console` |      |             |
| Blueprint delivery                  | Current JSON in Python wheel; seed Dynamo; code-first resolve | 2026-08-20 | Full tag history deferred |
| Monorepo tooling per extension      | TBD: uv workspace / npm workspaces            |      |             |
| CodeArtifact domain name            | Per publisher via `ops/publisher` (`renglo`, …) | 2026-08-20 | Not in customer stack-a |


---



## Related docs and code


| Path                                                       | Role                                       |
| ---------------------------------------------------------- | ------------------------------------------ |
| `ops/<tenant>-bom/README.md`                           | Current BOM JSON + deploy flow         |
| `ops/<tenant>-bom/scripts/checkout_bom.py`         | Git clone (to be retired)                  |
| `ops/<tenant>-bom/scripts/install_backend_packages.py` | Local pip install (to be retired)          |
| `ops/<tenant>-bom/Dockerfile`                          | Lambda image build                         |
| `console/EXTENSIONS_README.md`                             | Extension UI; Method 3 = npm install       |
| `ops/publisher/README.md`                                  | CodeArtifact + OIDC publish                 |
| `ops/publisher/docs/package-registry-extension-cutover.md` | What to change in each extension vs the BOM |
| `ops/publisher/scripts/stage_extension_blueprints.py`      | Copy repo-root `blueprints/` into the wheel |
| `ops/bootstrap/README.md`                                  | Path A cloud deploy / CI contract          |


---



## FAQ

**Can we use private PyPI/npm registries?**  
Yes. CodeArtifact is the chosen private registry for now. Public PyPI and npmjs.com for open-source core later.

**Do we need Next.js for console?**  
No. Console is Vite + React. npm distributes the package; CI builds static assets.

**Why keep extensions in one repo instead of** `dumbo_python` **+** `dumbo_react`**?**  
Single tag keeps Python, UI, and blueprints on the same version. Three artifacts, one repo, one release.

**Are blueprints a fourth git repo?**  
No. They live in the extension repo (`blueprints/`). Git is authority; the wheel (and later mirrors) are how private/public distribution works without cloning at runtime.

**Does the wheel hold every historical blueprint version?**  
Not for now. Only the current tag. History remains in git tags; Dynamo may still hold older seeds. Full archive (S3/CodeArtifact per tag, or files accumulated in the wheel) is later.

**What about** `_files` **/ presigned S3 redirects?**  
Unrelated to this migration; lives in `renglo-lib` / `renglo-api` packages once published.

---



## Changelog


| Date       | Change                                                                         |
| ---------- | ------------------------------------------------------------------------------ |
| 2026-08-20 | Initial draft from platform discussion (git clone → CodeArtifact → public OSS) |
| 2026-08-20 | Blueprints: third deliverable in the same repo; wheel + Dynamo seed; code-first resolve; history deferred |
| 2026-08-23 | Phase 1: v2 BOM (`python` / `npm`), CodeArtifact pull in `stanley-bom`, Vite hybrid aliases |
| 2026-08-23 | Phase 2: stage repo-root `blueprints/` into the wheel; code-first resolve; `data` is the reference |
| 2026-08-23 | Operator playbook: `package-registry-extension-cutover.md` (extension files vs BOM pins) |


