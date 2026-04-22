# Quant Project Operating Rules

## Purpose and Scope

- This file is the single source of truth for every Codex session and every spawned agent working inside this project.
- These rules apply to direct work in the root workspace and all nested project content, including `cherry_quant_wikidocs/`.
- Custom specialist prompts live in `agents/` and are used as a prompt library together with `spawn_agent(agent_type="worker")`.
- If custom subagent spawning is unavailable in Codex, enable it once in `~/.codex/config.toml` with:

```toml
[features]
multi_agent = true
```

## Subagent Registry

| Agent | Prompt File | Primary Use |
| --- | --- | --- |
| `quant-trading-expert` | `agents/quant-trading-expert.md` | Quant strategy, factors, backtests, risk, portfolio logic |
| `stock-chart-analyst` | `agents/stock-chart-analyst.md` | Candles, indicators, chart patterns, visual chart review |
| `senior-backend-engineer-python` | `agents/senior-backend-engineer-python.md` | Python APIs, data pipelines, batch jobs, backtest engines |
| `senior-frontend-engineer` | `agents/senior-frontend-engineer.md` | Dashboards, UI state, interactions, frontend architecture |
| `ui-ux-designer` | `agents/ui-ux-designer.md` | Information architecture, flows, layout, visual direction |
| `paranoid-staff-engineer-reviewer` | `agents/paranoid-staff-engineer-reviewer.md` | Risk-focused technical review after implementation |
| `qa-engineer` | `agents/qa-engineer.md` | Regression validation, scenario coverage, release readiness |

## Subagent Selection Protocol

1. If the user does not name an agent, select the most appropriate subagent before doing substantial work.
2. State the selected agent in the first substantive response, for example: `Selected agent: senior-backend-engineer-python`.
3. Use the routing rules below for first choice:
   - Quant strategy, factors, backtests, risk, portfolio construction: `quant-trading-expert`
   - Candles, patterns, indicators, chart interpretation, visual chart review: `stock-chart-analyst`
   - Python APIs, data pipelines, batch, backtest engines, infrastructure logic: `senior-backend-engineer-python`
   - Web UI, dashboards, interaction design in code, state management: `senior-frontend-engineer`
   - Information architecture, user flows, screen structure, visual direction: `ui-ux-designer`
   - Large or risky completed change review: `paranoid-staff-engineer-reviewer`
   - User-impact validation or regression checks: `qa-engineer`
4. Use mixed-task chaining in this order unless the task clearly needs a different sequence:
   - Domain specialist first
   - Implementing engineer second
   - Reviewer third for large or risky changes
   - QA last for user-impact validation
5. Custom specialist prompts must be dispatched with `spawn_agent(agent_type="worker")`.
6. `explorer` is allowed only for read-only discovery and must not replace a specialist agent when domain judgment or implementation ownership is required.

## Common Workflow

1. Explore before editing. Read the current code, docs, config, and constraints before proposing or making changes.
2. Ask the user only when exploration cannot resolve a meaningful product, implementation, or risk decision.
3. If the current directory is not a Git repository, run `git init` before the first tracked change.
4. For Python work, standardize the environment and execution flow with `uv`.
5. Make the smallest coherent change that fully satisfies the request.
6. Run relevant checks after changes. Prefer the narrowest useful validation first, then expand if risk warrants it.
7. Trigger the review and QA gates below when the change crosses their thresholds.
8. Commit every logical unit of completed work immediately after validation.
9. Report what changed, how it was validated, and what was intentionally left unverified.

## UV Rules

- These rules are mandatory for all Python execution, package management, scripts, tests, and tooling in this project.
- If `pyproject.toml` does not exist and Python work is required, bootstrap with `uv init`.
- Add dependencies with `uv add`.
- Materialize or refresh the environment with `uv sync`.
- Run Python entry points, scripts, tests, and linters with `uv run ...`.
- Do not use bare `python`, `pip`, `pytest`, or ad hoc virtualenv management for project Python tasks.
- Frontend-only work may use the native ecosystem toolchain, but any Python helper involved in that work still uses `uv`.

## Git and Commit Rules

- If the workspace is not already under Git, initialize it with `git init` before the first tracked change.
- Commit after each logical unit, not only at the end of a long session.
- Stage only files relevant to the change being committed.
- Commit messages must use `type(scope): summary`.
- Preferred commit types are `feat`, `fix`, `docs`, `refactor`, `test`, and `chore`.
- Do not amend, reset, rebase, force-push, or discard existing user work unless the user explicitly requests it.
- Do not revert unrelated changes you did not make.

## Review and QA Gates

### Mandatory Reviewer Gate

Use `paranoid-staff-engineer-reviewer` before finalizing when any of the following is true:

- The change spans multiple files or introduces new architecture
- Trading logic, factor logic, execution logic, or risk logic changed
- Data models, schemas, storage contracts, or API contracts changed
- Security, auth, permissions, or performance-sensitive logic changed
- The implementation feels correct but has non-trivial downside if wrong

### Mandatory QA Gate

Use `qa-engineer` before finalizing when any of the following is true:

- User-facing behavior changed
- UI layout, flows, or copy changed
- Regression risk is material
- A new endpoint, report, export, or calculation affects downstream users
- The user explicitly asks for test coverage, validation, or release readiness

## Prohibited Actions

- Do not overwrite or discard user changes without explicit permission.
- Do not use destructive Git commands such as `git reset --hard` or `git checkout --` unless explicitly requested.
- Do not bypass `uv` for Python work.
- Do not skip validation and still claim the work is verified.
- Do not present specialist confidence in areas outside the chosen agent's ownership; hand off instead.
- Do not use `explorer` as a substitute for a named specialist when real judgment is required.

## Reporting Rules

Every substantial completion update must include:

- The selected agent or agent chain
- A short change summary
- Commands or checks that were run
- Validation scope
- What was not run or not verified
- Open risks, if any

User-facing responses should be in Korean unless the user requests another language. Code identifiers, commands, filenames, and commit messages should stay in English unless the repository already requires another convention.

## Validation Scenarios

### Routing Smoke Tests

- `Design a factor rotation strategy for KOSPI sectors with monthly rebalancing.` -> `quant-trading-expert`
- `Review this RSI and MACD chart setup and explain the invalidation levels.` -> `stock-chart-analyst`
- `Implement a Python batch job that recalculates factor scores every night.` -> `senior-backend-engineer-python`
- `Build a dashboard page that compares drawdown and turnover interactively.` -> `senior-frontend-engineer`
- `Restructure the onboarding flow for a retail quant dashboard.` -> `ui-ux-designer`
- `Review the completed order-routing refactor for hidden risks.` -> `paranoid-staff-engineer-reviewer`
- `Validate whether the new rebalance screen introduces regressions.` -> `qa-engineer`

### Mixed-Task Chain Examples

- `Design and implement a factor backtest API, then review it.` -> `quant-trading-expert` -> `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer`
- `Redesign a signal dashboard and ship the UI safely.` -> `ui-ux-designer` -> `senior-frontend-engineer` -> `qa-engineer`

### Operational Scenario Checks

- No Git repository exists -> initialize with `git init` before the first tracked change
- No `pyproject.toml` exists and Python work is requested -> bootstrap with `uv init`
- Python code changes -> run via `uv run ...`, validate, then commit
- UI changes -> use the frontend/designer chain as needed, validate, then commit
- Large structural changes -> require reviewer gate before final commit
