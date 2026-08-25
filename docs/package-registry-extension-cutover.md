# Take an extension off git clone

Operator playbook for Phase 2 of the [package registry migration](package-registry-migration.md). Two different jobs: **extension repo** vs **tenant BOM**. Do **not** move `blueprints/`. The git layout stays as it is.

Start with **`data`**. Repeat the same steps for every other extension.

The team copy of this page lives at [ops/docs/package-registry-extension-cutover.md](../../docs/package-registry-extension-cutover.md). Keep them in sync.

---

## 1. In each extension repo (code)

These packaging files must be on `main` before you tag. They do **not** invent a new folder layout.

| File | What it must do | Why |
| --- | --- | --- |
| `.github/workflows/publish-extension.yml` | Before `python -m build package`, copy `blueprints/*.json` into `package/<import>/blueprints/` | The published wheel contains the current JSON |
| `package/pyproject.toml` | `[tool.setuptools.package-data]` includes `blueprints/*.json` | setuptools actually puts those files in the wheel |
| `data` only: `package/setup.py` + `.gitignore` | `setup.py` does the same copy locally; staged `package/data/blueprints/` is gitignored | Reference implementation |

**Do not change**

- `blueprints/` at the repo root (source of truth)
- `package/` Python handlers
- `ui/` layout

**Repos that already have this in the Stanley workspace:**  
`data`, `schd`, `pes`, `props`, `breakdown`, `claw`, `dumbo`, `gmail`, `whatsapp`, `lgx`

**Still to apply in its own repo:** `gro` (same three edits).

`renglo-lib` is **not** an extension. Code-first blueprint resolve lives there; publish a new `renglo-lib` before a deploy can use wheel-first `/_blueprint`.

---

## 2. In each extension repo (publish)

**A. One-time GitHub repo variables** (if not already set)

- `AWS_PUBLISH_ROLE_ARN`
- `PUBLISHER_NAME` (e.g. `renglo`)
- `AWS_REGION`

See [../README.md](../README.md).

**B. Publish a version that includes the new workflow**

1. Merge the file changes above onto `main`.
2. Set the **same** semver in both:
   - `package/pyproject.toml` → `version = "1.0.0"` (or the next unused version)
   - `ui/package.json` → `"version": "1.0.0"`
3. Commit, push `main`.
4. Tag and push that exact version:

```bash
git tag v1.0.0
git push origin v1.0.0
```

5. Confirm Actions uploaded to CodeArtifact:
   - Python: `renglo-data==1.0.0`
   - npm: `@renglo/data@1.0.0`

Do **not** add a BOM pin until that upload succeeded.

---

## 3. In the BOM repo

Live deploy is `deploy_targets.yml` → `bom:`. A pin that is not on the publisher store will break CI.

**To take `data` off git clone:**

1. Copy the current BOM:

```bash
cp bom/v0.1.0.json bom/v0.2.0.json
```

2. In the new file, set `"version"` and **add pins**. Leave the `repos` row; the pin wins and CI will not clone that repo.

```json
{
  "version": "v0.2.0",
  "python": {
    "renglo-lib": "1.0.0",
    "renglo-api": "1.0.0",
    "renglo-data": "1.0.0"
  },
  "npm": {
    "@renglo/data": "1.0.0"
  },
  "repos": {
    "renglo/data": { "commit": "…", "branch": "main" },
    "renglo/schd": { "commit": "…", "branch": "main" }
  }
}
```

Use the **published** versions, not a version you hope exists.

3. Point CI at it:

```yaml
# deploy_targets.yml
release: 0.2.0
```

4. Commit and push the BOM repo `main`.

**What you do not put in the BOM for an extension**

- A new path or blueprint location
- A new repo (it is already listed)
- A pin for an unpublished package

### Name mapping

| Git repo | Python pin | npm pin |
| --- | --- | --- |
| `renglo/data` | `renglo-data` | `@renglo/data` |
| `renglo/schd` | `renglo-schd` | `@renglo/schd` |
| `renglo/pes` | `renglo-pes` | `@renglo/pes` |
| `renglo/<name>` | `renglo-<name>` | `@renglo/<name>` |

`blalab/props` is the exception: the package name is `renglo-props`, but the git key is `blalab/props`. Pin it only after skip-clone maps that org.

---

## Order

```text
1. Merge extension file changes  (data first)
2. Publish tag                   (data first)
3. Confirm CodeArtifact has the version
4. New bom/vX.Y.Z.json      add python + npm pins
5. deploy_targets.yml            release: X.Y.Z
6. Repeat 1–5 for the next extension
```

Until step 4, deploy still **clones** that extension. After the pin, backend `pip install`s it and console `npm install`s it. `checkout_bom.py` goes away only when **every** extension (and console) has a pin.

You do not change `blueprints/` in any extension. You merge the packaging/workflow diffs, publish a tag, then add two version strings to the BOM JSON.
