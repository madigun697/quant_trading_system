# Custom Subagents

This directory contains the project's custom specialist prompt library.

## Dispatch Pattern

1. Choose the specialist prompt that best matches the task.
2. Read the prompt file.
3. Wrap the prompt contents in an instruction block.
4. Spawn a `worker` agent with that wrapped prompt.
5. Keep `AGENTS.md` as the higher-priority source of truth if any prompt detail conflicts.

## Recommended Message Frame

```text
Your task is to perform the following. Follow the instructions below exactly.

<agent-instructions>
[paste the selected prompt file here]
</agent-instructions>

Project root AGENTS.md is authoritative for workflow, git, uv, validation,
and reporting rules. Execute this now and return only the requested output.
```

## Example Spawn Pattern

```text
spawn_agent(
  agent_type="worker",
  message="[wrapped prompt from agents/senior-backend-engineer-python.md]"
)
```

## Suggested Chains

- Quant research -> implementation -> review:
  `quant-trading-expert` -> `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer`
- Chart-heavy UI feature:
  `stock-chart-analyst` -> `ui-ux-designer` -> `senior-frontend-engineer` -> `qa-engineer`
- Backend feature with user-facing impact:
  `senior-backend-engineer-python` -> `paranoid-staff-engineer-reviewer` -> `qa-engineer`

## Ownership Reminder

- Specialists own judgment inside their stated domain.
- They should hand off when the next step moves outside that domain.
- `explorer` remains available for read-only discovery, but it does not replace specialist ownership.
