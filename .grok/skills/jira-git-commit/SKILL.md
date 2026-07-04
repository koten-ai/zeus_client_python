---
name: jira-git-commit
description: >
  Create JIRA-prefixed git commits with detailed change descriptions. On main,
  prompt whether to create a feat/{TICKET}-… or fix/{TICKET}-… branch from a
  JIRA URL (inferring type from the ticket), or commit on main with a ticket ID
  prefix. Commit title format: ZC-10 short description. Use when the user asks
  to commit, git commit, create a commit, save changes to git, or runs
  /jira-git-commit.
---

# JIRA Git Commit

Create well-structured commits with a JIRA ticket prefix and a detailed body
that explains what changed and why.

## Prerequisites

Before committing, always inspect the working tree:

```bash
git status
git diff
git diff --staged
```

If nothing is staged, stage the relevant files (`git add …`) or ask the user
which paths to include. Never commit unrelated or secret files (`.env`, keys).

## Commit message format

**Title (first line, ≤72 chars):**

```
{TICKET-ID} short description of the changes
```

Example: `ZC-10 document error handling in README`

**Body (required — detailed):**

- What changed (files/areas affected)
- Why (link to ticket goal when known)
- Notable decisions or trade-offs
- Testing done (or "not run" with reason)

Separate title and body with a blank line. Use complete sentences.

```
ZC-10 document error handling in README

Add an Error handling section covering fatal RuntimeErrors, structured JSON
error codes, and soft trace errors. Document likely causes and fixes for auth,
catalog sync, session drift, and LLM failures.

Testing: not run (docs-only change).
```

## Branch workflow when on `main`

Detect the current branch:

```bash
git branch --show-current
```

If the branch is `main` or `master`, **ask the user** (regular conversation,
one question at a time):

> You're on `main`. Do you want to create a feature/fix branch before
> committing?

### User wants a branch

1. Ask for the **JIRA ticket URL** (e.g.
   `https://yoursite.atlassian.net/browse/ZC-10`).

2. Extract the ticket key from the URL (`ZC-10`). If extraction fails, ask for
   the ticket ID directly.

3. Fetch issue metadata to determine type and summary:
   - **Preferred:** Atlassian MCP `getJiraIssue` with `issueIdOrKey` and
     `fields` including `issuetype` and `summary`. Resolve `cloudId` via
     `getAccessibleAtlassianResources` if needed.
   - **Fallback:** Ask the user for issue type (feature vs bug) and a one-line
     summary if MCP is unavailable.

4. Map issue type → branch prefix:

   | JIRA issue type (case-insensitive) | Branch prefix |
   |------------------------------------|---------------|
   | Bug, Defect, Incident, Issue       | `fix/`        |
   | Story, Feature, Task, Epic, Improvement, New Feature | `feat/` |
   | Unknown                            | Ask the user: feat or fix? |

5. Build the branch name:

   ```
   {prefix}{TICKET-ID}-{short-slug}
   ```

   - `short-slug`: lowercase kebab-case from ticket summary or change scope
   - Max ~40 chars for the slug; drop filler words (a, the, and, for)
   - ASCII letters, digits, hyphens only

   Examples:
   - `feat/ZC-10-document-error-handling`
   - `fix/ZC-42-session-create-timeout`

6. Create and switch:

   ```bash
   git checkout -b feat/ZC-10-document-error-handling
   ```

7. Use `{TICKET-ID}` from the ticket as the commit title prefix.

### User does not want a branch

Ask for the **JIRA ticket ID** to use as the commit prefix (e.g. `ZC-10`).
Proceed with the commit on `main` — warn briefly that committing directly to
`main` is discouraged if team policy prefers PRs.

## Branch workflow when NOT on `main`

1. Try to parse the ticket ID from the branch name (`feat/ZC-10-…` → `ZC-10`).
2. If no ticket is inferable, ask the user for the JIRA ticket ID.
3. Proceed to compose the commit message.

## Compose the message

1. Read staged diff and summarize changes accurately — do not invent changes.
2. Write the title: `{TICKET-ID} {imperative short description}`.
3. Write the detailed body (see format above).
4. Show the **full proposed commit message** to the user and ask for approval
   before running `git commit`.

## Execute the commit

After user approval:

```bash
git commit -m "$(cat <<'EOF'
ZC-10 short description

Detailed body paragraph one.

Detailed body paragraph two.
EOF
)"
```

On Windows PowerShell, use a here-string or `-m` for title plus `-m` for each
body paragraph instead of heredoc.

## Rules

- **Never** use `--no-verify` unless the user explicitly requests it.
- **Never** push unless the user explicitly asks.
- **Never** amend or force-push without explicit user consent.
- If the commit fails (hooks, conflicts), report the error and suggest a fix.
- Keep ticket IDs uppercase as in JIRA (`ZC-10`, not `zc-10`).

## Quick checklist

- [ ] Inspected `git status` and diff
- [ ] On `main` → asked about branch creation
- [ ] Branch created with correct `feat/` or `fix/` prefix (if requested)
- [ ] JIRA ticket ID confirmed
- [ ] Title: `{TICKET-ID} short description`
- [ ] Body: detailed what/why/testing
- [ ] User approved message before commit