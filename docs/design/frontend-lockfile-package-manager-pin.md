# Frontend Lockfile Package Manager Pin

> Why `web/frontend` pins no package-manager version, and the npm 11.6.2
> optional-peer defect that made the pin actively harmful.

## Summary

`web/frontend/package.json` carried `"packageManager": "npm@11.6.2"`. That
version has a defect in its optional-peer-dependency handling which corrupts
the lockfile during incremental updates. Dependabot honored the pin; CI did
not. The two disagreed, and every Dependabot pull request touching
`web/frontend` failed CI. The pin has been removed.

## Symptom

Sixteen open Dependabot pull requests against `web/frontend` failed the
`build-and-test` check, all with the same error:

```
npm error code EUSAGE
npm error `npm ci` can only install packages when your package.json and
          package-lock.json are in sync.
npm error Missing: webpack@5.109.0 from lock file
npm error Invalid: lock file's es-module-lexer@2.0.0 does not satisfy 2.3.1
```

Dependabot pull requests against `web/admin-dash` and `web/tester` passed. The
failures were confined to a single directory, and the affected pull requests
modified only `package-lock.json` — deleting roughly 149 lines while leaving
`package.json` untouched.

## Root cause

The `web/frontend` lockfile contains 47 entries marked both `optional` and
`peer`. These are the webpack tree, reachable as an optional peer of
`@angular/build`. Nothing installs them — `npm ls webpack` reports empty — but
npm records them, and `npm ci` verifies they are present.

npm 11.6.2 prunes those entries. Regenerating the same `package.json` across
npm releases shows the defect is specific to that version:

| npm version | webpack in lock | optional-peer entries |
|---|---|---|
| 10.9.2 | yes | 46 |
| 11.0.0 | yes | 46 |
| **11.6.2** | yes | **4** |
| 11.13.0 | yes | 46 |

The incremental path — what Dependabot actually does — is more destructive than
a fresh resolve. Applying a single-dependency bump to the committed lockfile
with npm 11.6.2 drops the count from 47 to 0 and removes the webpack tree
entirely:

```
47 optional-peer entries
  -> npm@11.6.2 install <dep> --package-lock-only
  -> 0 optional-peer entries, webpack absent
```

That reproduces the Dependabot diff exactly.

`web/admin-dash` and `web/tester` have zero optional-peer entries, so the same
npm leaves their lockfiles intact. This is why only one directory failed.

## Why the two disagreed

Dependabot reads `packageManager` and regenerates the lockfile with npm 11.6.2.

CI does not. `.github/workflows/ci.yml` uses `actions/setup-node` with
`node-version: '24'` and never enables corepack, so it runs whatever npm ships
with Node 24 — a release without the defect. CI then finds the pruned entries
missing and fails `npm ci`.

The pin had no other effect on this repository. No workflow, `Dockerfile`,
`Makefile`, or compose file reads it. Its only observable consequence was to
hand Dependabot a defective npm.

## Resolution

The `packageManager` field was removed from `web/frontend/package.json`.
Dependabot and CI now both resolve with current npm and agree on the result.

The committed lockfile was already npm-canonical — regenerating it with current
npm produces a byte-identical file — so no lockfile change was required. The
corruption was introduced by Dependabot, not present in the repository.

With the pin removed, the identical incremental bump that previously destroyed
the lockfile preserves all 47 entries and `npm ci` exits 0.

## Alternatives considered

**Pin to a known-good npm and enable corepack in CI.** Preserves toolchain
determinism across contributors, at the cost of a workflow change and a version
choice — and it reintroduces the same failure mode whenever the pinned version
develops a defect. Rejected as part of this fix; see Open question.

**Regenerate the lockfile on each affected branch.** Rejected. It treats the
symptom, leaves the defect in place, and every future Dependabot pull request
against `web/frontend` would need the same manual repair.

## Open question

CI ignoring `packageManager` is a latent inconsistency independent of this
defect. A pin that only one consumer honors can drift again. Either adopt
corepack in CI so the pin is authoritative everywhere, or record that this
repository deliberately does not pin package-manager versions.
