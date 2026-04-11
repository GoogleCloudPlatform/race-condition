# Tutorial: Implementing and Registering Skills in ADK Agents

This tutorial explains how to add "Skills" to agents built using the Google
Assistant Developer Kit (ADK).

## What is a Skill?

In the ADK framework, a **Skill** is a structured collection of:

1. **Instructions**: Detailed guidance on how the agent should behave or use
   specific tools.
2. **References**: Supplementary documentation (e.g., Markdown files) that the
   agent can read.
3. **Assets**: Additional text-based resources or data files.

Skills differ from "Tools" (Python functions) by providing contextual knowledge
and descriptive behavior rather than just functional capabilities.

## 1. Directory Structure (Standard Pattern)

While ADK is flexible, a common pattern is to place skill resources in a
`skill/` directory within your agent's package.

```text
my_agent_package/
├── agent.py
├── agent.json
└── skill/
    ├── SKILL.md          <-- Main instructions and metadata
    ├── references/       <-- Optional (additional .md files)
    └── assets/           <-- Optional (other text-based resources)
```

## 2. Defining the Skill Content (SKILL.md)

A skill typically starts with metadata (Frontmatter) followed by the instruction
body.

### Example `SKILL.md`

```markdown
---
name: specialized-negotiator
description: |
  Provides high-level strategies for complex negotiation simulations.
---

# Negotiator Skill

You are an expert negotiator. When interacting with other agents, you should:

1. Identify the core needs of the counterparty.
2. Use the `propose_trade` tool only when a win-win scenario is identified.
3. Maintain a professional and collaborative tone.

## Advanced Guidelines

- Prioritize long-term relationship value over immediate gains.
- If a deadlock is reached, suggest a temporary recess.
```

## 3. Loading and Registering Skills

This project uses auto-discovery via the `load_agent_skills()` helper in
`agents.utils`. You do **not** need to manually construct `Skill` objects.

### How Auto-Discovery Works

`load_agent_skills(agent_dir)` scans two directories and merges results:

1. **Shared skills** in `agents/skills/` (available to all agents).
2. **Local skills** in `{agent_dir}/skills/` (agent-specific).

If a local skill has the same name as a shared skill, the local version wins.
Tools from both directories are always combined.

### Usage in an Agent

```python
import pathlib
from agents.utils import load_agent_skills
from google.adk.agents import LlmAgent

# Auto-discover skills and tools from the agent's skills/ directory
_skills, skill_tools = load_agent_skills(str(pathlib.Path(__file__).parent))

def get_agent():
    return LlmAgent(
        name="my_agent",
        tools=[*skill_tools],
        # ... other config ...
    )
```

### Adding a Tool to a Skill

If a skill directory contains a `tools.py` file, all public functions in it are
automatically collected as tools. If the module defines `__all__`, that list is
used verbatim.

```text
agents/my_agent/skills/
└── negotiator/
    ├── SKILL.md       <-- Instructions (auto-loaded)
    ├── tools.py       <-- Public functions become agent tools
    └── references/    <-- Optional supplementary docs
```

## 4. Best Practices

- **Atomic Skills**: Keep skills focused on a single domain or behavior pattern.
- **Clear Descriptions**: The `description` in frontmatter helps the LLM decide
  when to utilize the skill.
- **Use References for Verbosity**: Use `references/` for long documents to
  avoid cluttering the primary instructions.
- **Return Dictionaries**: Any tools associated with a skill **MUST** return a
  `dict` for compatibility with ADK serialization and the A2A protocol.
