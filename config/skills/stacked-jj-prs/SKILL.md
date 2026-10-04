---
name: stacked-jj-prs
description: Use when a user asks to prepare a multi-commit Jujutsu change as stacked diff PRs or ordered topic commits from an explicit jj revset. Triggers include "jj revset", "stacked diff PRs", and "topic commits". Not for a single bookmark request.
---

# Prepare stacked Jujutsu PRs

Help prepare a proposed single-topic commit stack from user-selected Jujutsu changes. Work across repositories without assuming a branch model, default base, or application. Do not push or open PRs automatically.

## Inspect selection and safety

1. Check `command -v jj`. If unavailable, stop and ask how to proceed.
2. Require an explicit user revset. Do not choose or assume a default. Pass the exact revset as one safely quoted argv value (for example, `jj log -r "$revset" --stat`). Do not use `eval`, concatenate it into a shell command, or write a placeholder revset in single quotes.
3. Inspect `jj status`, selected graph and stats, each selected commit diff, `jj op log`, all relevant local and remote bookmarks and targets, and immutable revisions. Use graph ancestry to identify the actual base and unique selected tip; do not infer `@` is the tip or use a local bookmark as proof a revision is unpublished. Check remote/tracked state and affected descendants/bookmarks.
4. Require one contiguous base-to-tip path. Stop and ask if selection has multiple tips, merges, unrelated branches, or an unclear base, unless the user explicitly defines a safe path through the selection. Stop if publication/immutability or rewrite safety is unclear. Never rewrite published or immutable revisions. Include any descendants and bookmark movements affected by proposed operations; do not move or overwrite existing bookmarks without separate explicit authorization.
5. Inspect working-copy changes and preserve them. Stop if an operation risks overwriting them. Include docs and other preserved changes in proposed topic boundaries; do not silently drop or misassign them.

## Plan and approval

Before any history rewrite or bookmark creation, present a concrete plan and wait for explicit approval of that plan. Include selected commit IDs, actual base and unique tip, topic boundaries/order and before/after content, preserved files, publication/immutability status, affected descendants and bookmarks, rewrite operations, unique bookmark names and nonempty target commits, relevant tests, and tree validation. State that first PR base is the actual chosen base and each later PR base is the preceding topic bookmark.

Prefer one nonempty commit and bookmark per cohesive review topic. Combine adjacent changes to the same topic when safe; avoid duplicate same-topic PRs or preserving obsolete intermediate commits solely because they already exist. Keep separate topics when dependencies or review boundaries justify them.

Approval given before the concrete plan is not sufficient. If selection, operation, topic boundaries, tree changes, bookmark targets, or scope changes after approval, present the revised plan and ask again. Require separate explicit authorization before moving an existing bookmark or changing tree content. Never push or open PRs without separate authorization.

## Execute safely

- Rewrite only safe local unpublished revisions. Check remote bookmarks and tracked state; a local bookmark does not establish that a revision is unpublished. Do not rewrite published or immutable revisions.
- Use an appropriate operation such as split, squash, or rebase only as approved. Record original selected tip commit ID, its tree, and current operation ID. Account for every affected descendant and bookmark; stop and replan if any unapproved bookmark would move.
- Immediately before execution, recheck operation ID, selected and affected commit IDs, working-copy status, and bookmark targets. If anything changed, stop and replan; do not proceed on stale approval.
- Check suggested bookmark names for collisions. Create local bookmarks only on approved, nonempty topic commits. Never overwrite or move an existing bookmark without separate explicit authorization.
- Inspect conflicts, resulting graph, every topic diff, and bookmark targets. Stop on unexpected changes; resolve only within approved scope. Verify every topic diff is nonempty and every bookmark targets a nonempty topic commit.

## Validate and report

- Compare the tree of the recorded original selected tip commit with the tree of the final topic tip. They must match unless the user explicitly approved a tree-content change. Also confirm preserved files and working-copy changes remain intact.
- Run relevant tests for changed code; tests are unnecessary if only bookmarks changed. Report tests and skips.
- Rollback with `jj op restore` only after explaining what it may discard, inspecting later operations/work, and obtaining user consent. Do not restore blindly.
- Report ordered topics and local bookmark targets, actual base for first PR, predecessor bookmark as each later PR base, validation, and local next steps. Do not push or create PRs automatically.
