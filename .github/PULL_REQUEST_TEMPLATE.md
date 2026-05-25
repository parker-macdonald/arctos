## Summary

<!-- 1-2 sentences. What does this PR do, and why? -->

## What changed

<!-- Bullet list of the meaningful changes. Group by area if it helps:
     Backend / Frontend / Schema / Docs / Tests / CI. -->

## Migration impact

<!-- Required if this PR changes the database schema, models, or alembic
     migrations. Delete this section if there's no schema impact.

     - Alembic revisions added: ###
     - Run `make db-backup && make db-migrate` before deploy.
     - Backfill needed?      Link the script.
     - Backwards compatible? If not, note what breaks and how to recover. -->

## Test plan

<!-- What did you exercise? What's still untested?
     Don't just check the boxes; say what you actually ran. -->

- [ ] `make test` passes locally
- [ ] Manual verification:
  -

## Linked issues

<!-- "Closes #X" only auto-closes when this PR is merged into `main`. PRs into
     `dev` need a manual close, so reference and close by hand if needed. -->

Closes #
Refs   #

## Screenshots / repro

<!-- For UI changes, include before/after. For API changes, a curl invocation
     or response sample is just as useful (see #181 for the format). -->

---

### Pre-review checklist

<!-- Strike through (~~item~~) anything that doesn't apply, rather than
     deleting, so reviewers can see you thought about it. -->

- [ ] Title prefixed with one of `[Feature]`, `[Bugfix]`, `[Refactor]`, `[Documentation]`.
- [ ] Branch name follows `category/name` (`feat/...`, `bugfix/...`, `refactor/...`).
- [ ] Targeting `dev`, not `main` (unless this is a release PR).
- [ ] `make lint` and `make format` are clean.
- [ ] Tests added or updated for the new behavior.
- [ ] If a new module was added under `app/`: corresponding `app/<area>/README.md` and `docs/api/*.rst` are updated (per `CLAUDE.md`).
- [ ] If developer workflow changes: `README.md`, `CONTRIBUTING.md`, or `TESTING.md` updated.
- [ ] No merge conflicts with the base branch.
