# Git strategy

This repository uses GitHub Flow on a single long-lived branch, `main`. Releases are tags on `main`. Plugin contracts are versioned separately from the application version.

## Branches

| Branch | Role |
| --- | --- |
| `main` | Always releasable. Protected. |
| `feat/<short-name>` | A new plugin, endpoint, or workflow |
| `fix/<short-name>` | A bug fix |
| `docs/<short-name>` | Documentation only |
| `plugin/<provider>` | A payment or commerce adapter |

Create the branch from the current `main`. Delete it after the pull request merges.

There are no long-lived `develop` or release branches. A hotfix is a `fix/` branch from `main`, merged back to `main`, then tagged as a patch release.

```mermaid
gitGraph
  commit id: "v0.1.0"
  branch feat/adyen-plugin
  commit id: "adapter"
  checkout main
  merge feat/adyen-plugin id: "squash"
  commit id: "v0.2.0" tag: "v0.2.0"
```

## Protection on main

Maintainers turn these on in the host settings:

- Pull request required before merge.
- The CI workflow must pass.
- Linear history. Squash merge is the default.
- Force pushes are disabled.
- Secret scanning and push protection are enabled where the host provides them.

A maintainer may bypass a failing check only to revert a broken merge, and says so in the pull request.

## Commits

Use [Conventional Commits](https://www.conventionalcommits.org/).

| Type | When |
| --- | --- |
| `feat` | Shopper-visible or merchant-visible behavior |
| `fix` | A broken behavior |
| `docs` | Docs only |
| `test` | Tests only |
| `refactor` | Behavior stays the same |
| `chore` | Tooling, CI, or dependencies |

The subject is imperative and specific: `fix: deny public capture of unsettled payments`.

The squash commit on `main` is the message that appears in history. Write that message in the pull request title.

`feat` and `fix` entries are copied into `CHANGELOG.md` before a release.

## Pull requests

A pull request explains:

- why the change is needed
- which plugin or signal it affects
- how it was tested

The template checklist covers secrets, tool access, and docs. Plugin changes include a mocked provider test.

Review looks for the safety checklist in `CONTRIBUTING.md` before style nits. One approving review is enough while the maintainer set is small. The author does not approve their own pull request when another maintainer is available.

## Versioning

Application releases use semantic versioning, tagged `vX.Y.Z` on `main`.

| Bump | Examples |
| --- | --- |
| Patch | A safe bug fix, docs, or a stricter default |
| Minor | A new plugin or an optional field |
| Major | A breaking change to the Python API, the HTTP API, or the byo-v1 contract |

The byo-v1 payment contract is part of the public API. Breaking it requires a new contract name, such as `byo-v2`, and a major version. Additive fields are a minor version. Adapters must ignore fields they do not use.

Deprecations last at least one minor release. The changelog names the replacement and the release that will remove the old behavior.

## Releases

1. `main` is green.
2. Update `CHANGELOG.md` and the version in `pyproject.toml` and `src/ecommerce_agent/version.py`.
3. Merge that release pull request.
4. Tag `vX.Y.Z` on the merge commit and push the tag.
5. Publish the GitHub release from the tag notes in the changelog.

Do not tag a branch that is not `main`.

## What never enters git

- `.env` and real provider keys
- shopper exports, card numbers, and webhook payloads from a live store
- the demo server token, if you replaced the sample value with a real one

`.env.example` lists variable names only. Sample values in that file are placeholders.

If a secret is pushed, rotate it at the provider first. History rewriting on `main` is a last resort, needs every maintainer's agreement, and is a force push, so it is announced before it happens. Rotation is still required because clones may already have the old commit.

## Forks

External contributors fork the repository, push the feature branch to their fork, and open a pull request. Maintainer commits stay on branches in this repository. Nobody pushes directly to `main`.
