# Retro — SmartScanner

Run a development retrospective. The retro-agent will audit the current workflow, check CLAUDE.md accuracy, identify gaps in the skill/command/agent coverage, and scan for project health signals.

It writes a structured proposal to `docs/RETRO.md` — nothing is changed automatically. You review the findings and decide what to act on.

Use this:
- After finishing a phase
- When something keeps going wrong and you want to find the pattern
- Periodically to keep the workflow sharp

```
Use the Agent tool with subagent_type="retro-agent"
```
