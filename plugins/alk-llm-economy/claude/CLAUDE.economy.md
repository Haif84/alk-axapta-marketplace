## LLM economy (plugin alk-llm-economy)

Chat language: Russian. Save tokens wherever quality allows, and suggest how.
Why a rule exists: `~/.claude/docs/decisions/`. What hooks and scripts do:
`~/.claude/docs/scripts.md`. This file holds only the rules.

### Models and effort

Calibrated by measurements in `~/.claude/docs/costs.md`, not by benchmarks.

| Work | Model, effort |
|---|---|
| Default | Opus 5 `high` |
| Session filled by tool output: logs, tests, planned refactoring, recon, small tasks | Opus 5 |
| Decision-heavy, read-light: spec, plan, architecture, invariant | Fable 5.1 solo driver only, never as a subagent (2× per token, pays back in fewer turns) |
| One deep chain | Fable 5.1 `medium` solo; second opinion Opus 5 `high` |
| Recon, lookups | `low`/`medium` or Explore (Haiku) |
| Batch of independent edits | Executors Sonnet 5, every reviewer Opus 5 — always an explicit `model` on the `Agent` call (input is spec, plan and code, not the chat). Reviewer ≠ author. Our "most capable available model" is Opus 5: `docs/agent-prompts.md`. Executor fails review twice → task goes to Opus. |

- Model and effort are set before the first message and never switched
  mid-session (cache reset). `/model` and `/effort` persist to `settings.json`:
  after a session on another model, restore the default alongside `/remember`.
- Subagents only for two or more independent pieces.
- Context budget is 100k tokens (not a share of the 1M window), but the hook
  stays silent there: autocompact reaches that point on its own, and asking cost
  a turn on the full context. It blocks at 150k and again every 100k past it;
  the owner decides. Never shrink the work because of context.
- The way out at a threshold is `/compact` in the same session, not a new one:
  the summary is written by the model that saw everything, model and effort
  stay, the transcript stays in the same `.jsonl`. Only the owner types it; the
  agent commits the current piece and hands over the line:
  `/compact Сводка по шаблону handoff: State (сделано, коммиты, дерево), Next (нумерованные шаги), Context (решения владельца, файлы и строки, что не делать).`
  Neither `/compact` nor `/remember` is blocked. A new session is for a model
  or effort change and for the end of the day; then one Bash turn for
  `session-cost.js` and `handoff-from-transcript.js`, the Haiku subagent writes
  the handoff. Something from before the compaction → a digest by
  `handoff-from-transcript.js <uuid>` and grep in it, never the raw transcript.
- Pause over an hour → new session: the cache has expired. The hook blocks the
  first message once; resending passes.
- First turn of a session: `CronCreate` `13,43 * * * *`, recurring, prompt
  `keepalive: ответь точкой`. The ping reads the cache prefix, so an hour away
  from the keyboard costs $0.05 instead of a rewrite; `keepalive-gate` blocks
  the pings not worth paying for and asks the sixth to write the handoff
  (`docs/decisions/2026-09-18-keepalive-cron.md`).
- `AskUserQuestion` headers start with the time asked (`13:47 — merge?`):
  a question may hang for hours.
- A question that may wait hours goes as text at the end of the turn;
  `AskUserQuestion` only when the answer is needed to continue the same
  turn, then all forks batched (up to 4). A pending question is not idle:
  cron pings do not fire (`docs/decisions/2026-09-18-keepalive-cron.md`).
- Every fork in an answer is numbered question.point.subpoint (3, 3.5,
  3.5.6); the owner replies `3.5.6`, `356` or `3 5 6`, all read the same.
- A session may be closed at any moment: the handoff is built from the
  transcript by a Haiku subagent (`node ~/.claude/scripts/handoff-from-transcript.js`,
  prompt in `~/.claude/docs/agent-prompts.md`) into `.remember/remember.md`.
  If the previous session broke off, run it first thing. Never read a raw
  transcript into context.
- Edit `CLAUDE.md` and memory at session end: an edit rewrites the cache from
  the first message.
- Every `/remember` starts with a measurement: `node ~/.claude/scripts/session-cost.js --since <date>`
  from the project folder; one line goes to `~/.claude/llm-costs.md` (never to
  `~/.claude/docs/`: it is the plugin's folder in the marketplace clone). This
  write is pre-approved; an unrecorded measurement does not count.
- Alongside `/remember`, name the session by the work it did:
  `node ~/.claude/scripts/rename-session.js --session <id> --title "…" --self <id>`
  (`~/.claude/docs/scripts.md`). Untouched, the panel keeps the title made
  from the first prompt — «дальше» for every session started from a handoff.

### Skills by phase

Process skills are mandatory; reference skills are only sources of facts.

| Phase | Skill |
|---|---|
| New functionality or behaviour change | `superpowers:brainstorming` |
| Level L with a spec | `superpowers:writing-plans` |
| Before code | `superpowers:test-driven-development` |
| Before "done", commit, PR | `superpowers:verification-before-completion` |
| After implementation (M, L) | `/code-review` |

In doubt whether a skill applies, invoke it before answering — including
before clarifying questions.

A skill's own prompt templates are defaults, not rules: `superpowers` dispatches
`Subagent (general-purpose)` and reads "most capable available model" as the
priciest one on offer. The model table above wins over both — recon goes to
Explore, every review to Opus 5. Measured 2026-09-17: the plugin drove 41 % of a
day's usage, `writing-plans` alone 20 %.

Asked to skip a step → remind, in Russian: "By our agreement [step] comes first —
skip it?" and do as the owner decides.

`claude-api` is listed name-only, so invoke it deliberately: any question on
Anthropic models, prices, limits, API parameters or call debugging starts with
that skill, never from memory.

### Task levels

Declare the level in one line before work; in doubt, take the lower one.
Ceremony must not cost more than the edit.

| Level | Scope | Process |
|---|---|---|
| S | one place in code, the edit is clear | TDD, verification, commit. Solo, effort `medium`; no spec, plan or subagents |
| M | one chain across 2–5 files | design in chat, solo, effort `medium`, `/code-review medium` at the end |
| L | two or more independent pieces | full cycle below; spec and plan exist only here |

### Level L cycle

1. Spec in `docs/superpowers/specs/` → review by a separate model that checks
   it against the code → fixes, commit the second edition.
2. Plan in `docs/superpowers/plans/` → the same reviewer reviews spec + plan:
   plan code compiles, tests prove the claims.
3. Branch in the same tree; execution via subagent-driven-development with the
   prompt blocks from `~/.claude/docs/agent-prompts.md` (executor report, task
   reviewer, final branch reviewer). Verify review findings against the code
   yourself: some miss.
4. Accepted → local `merge --no-ff` into the main branch, `git branch -d`.
5. Summary in `docs/results-<date>.md` (template in `~/.claude/docs/templates/`):
   done by commits, owner decisions, measured vs inferred, open items.
   Leftovers → `docs/tech-debt.md`.
6. Cost measurement → `~/.claude/llm-costs.md`; `/remember`.

One session drives a batch. A second session in the same tree neither commits
nor edits batch files; a driver change is recorded in the SDD journal, which is
the source of truth — the old session's handoff and memory lie about whose
branch it is.

### Commits

- Commit after each logical piece without being asked. One commit = one task;
  never mix refactoring with a feature.
- `git push` only on an explicit word. A project deviation lives in its own
  CLAUDE.md.
- The branch is not discussed: L → own branch from main; S and M → straight to
  main. Never ask "which branch" or "merge?".
- Done and verified → `git merge --no-ff`, then `git branch -d`. A branch with
  no commits of its own is deleted at once. Conflict or red tests → stop and
  report, do not merge. `superpowers:finishing-a-development-branch` follows
  this rule and offers the owner no integration options.

### Context economy

- Name specific files and lines; do not read a whole file without need. The
  `read-gate` hook rejects `Read` over 350 lines without `offset`/`limit`:
  locate with `grep -n`, delegate a full overview to a subagent.
- Command output over 12k chars never enters context: it is saved to a file
  and the model gets the path. Fold big logs through `grep`/`awk` up front.
- Give subagents and reviewers explicit context: what was read, what was
  tried, which files and lines.
- Dead end → `/rewind` → "Summarize up to here", not `/compact`: the first
  reads the cached prefix, the second builds a new one. At a budget threshold
  there is no cached point to return to, so there `/compact` is the way.
- Fewer turns: independent tool calls in one turn; do not reread a file after
  editing; fold long output into a summary. A turn costs the whole context.
