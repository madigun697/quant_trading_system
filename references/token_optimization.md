## AGENTS.md Optimization

### Keep AGENTS.md Small

Avoid:

* long architectural explanations
* duplicated README content
* unnecessary examples

Prefer:

* concise operational rules
* response contracts
* workflow constraints

### Recommended AGENTS.md Template

```
# Communication

- Be concise.
- Do not print raw logs unless asked.
- Summarize command results in 1-3 bullets.
- Only mention actionable errors.

# Workflow

- Prefer targeted file reads.
- Use rg before opening files.
- Avoid broad repository scans.
- Inspect only minimal failing output.

# Final Response

Respond only with:

- files changed
- tests run
- remaining issues
```

## State-Based Context Architecture

### Preferred Approach

Instead of replaying conversations:

```
{
  "task": "FastAPI auth fix",
  "stack": ["Python", "FastAPI", "Postgres"],
  "current_issue": "JWT validation failing",
  "constraints": [
    "must support refresh tokens"
  ]
}
```

### Benefits

* smaller token footprint
* higher reasoning clarity
* easier persistence
* better retrieval

## Terminal / Log Optimization

### Critical Insight

Logs are expensive when:

* echoed into responses
* reinserted into context
* repeatedly summarized

### Recommended Rules

```
- Never paste full logs.
- Report only:
  - command executed
  - pass/fail
  - first relevant error
```

### Preferred Commands

#### Avoid

```
npm test
```

#### Prefer

```
npm test > /tmp/test.log 2>&1
tail -n 80 /tmp/test.log
```
or:
```
pytest -q 2>&1 | tail -n 80
```

## Verbose Output Suppression

### Recommended Global Rules

```
# Response Style

- Be terse.
- No preambles.
- No status narration.
- No unnecessary explanations.
- No “I will now...” messages.
- Keep final response under 8 lines.
```

### Recommended Final Format
```
Changed:
- ...

Tests:
- ...

Notes:
- ...
```