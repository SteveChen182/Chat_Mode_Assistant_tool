# GNAI Toolkit Development Guidelines

This file contains persistent guidelines for developing the **SightingAssistantTool**, an Intel GNAI local toolkit. These guidelines are sourced from official GNAI documentation and should be consulted during all development activity on this repository.

> **Keep this file updated** whenever you discover new GNAI framework behavior, model changes, or best practices.

---

## 1. What is GNAI?

GNAI is Intel's internal GenAI platform powered by LLM models (OpenAI + Anthropic/Claude) enhanced by RAG (Retrieval-Augmented Generation). It supports agentic workflows via local toolkits, server MCP toolkits, GitHub Actions, profiles, and a marketplace.

**Interfaces:** Web UI, Microsoft Teams, VSCode Extension, Visual Studio Extension, Command Line (`gnai` CLI), **Claude Code** (`gnai-claude` CLI).

**Docs:** https://gpusw-docs.intel.com/services/gnai/

---

## 2. This Repository: SightingAssistantTool

This repo is a **GNAI local toolkit** — a collection of custom tools, assistants, and skills for GPU sighting (bug triage) analysis.

- **Toolkit name:** `sighting`
- **Config file:** `toolkit.yaml` (root)
- **Assistants:** `assistants/` directory (prefixed `sighting_*`)
- **Tools:** `tools/` directory (prefixed `sighting_*`)
- **Source code:** `src/` directory (Python scripts)
- **Skills:** `skills/` directory (local skills, e.g. `burnin_log_analyzer`)

---

## 3. Toolkit Directory Structure

```
toolkit.yaml                     ← Toolkit config (name, env, template, skills, tools)
assistants/
  sighting_assistant.yaml        ← Main assistant definition
tools/
  sighting_<tool_name>.yaml      ← Tool definitions
src/
  <tool_python_script>.py        ← Python implementations
skills/
  burnin_log_analyzer/
    SKILL.md                     ← Skill definition (agentskills.io standard)
scripts/
  burnin_log_parser.py           ← Parser scripts
```

---

## 4. Key GNAI Concepts

### 4.1 Tool
A custom function an assistant can invoke. Defined in `tools/<toolkit>_<name>.yaml`.
- **command tool** — runs a shell command/script, returns stdout/stderr.
- **agent tool** — invokes the LLM with a prompt, returns LLM output.

### 4.2 Assistant
An agent with a specific prompt + list of tools and sub-assistants. Defined in `assistants/<toolkit>_<name>.yaml`.
- Uses the LLM to decide which tool/sub-assistant to invoke.
- Can have `params[]` the LLM discovers from user input.
- Can invoke other assistants via `assistants[]`.

### 4.3 Skill
A pre-built agent capability following the [agentskills.io](https://agentskills.io/home) open standard. Defined by a `SKILL.md` file. When registered, skills automatically become assistants named `<toolkit_name>_<name_from_SKILL.md_frontmatter>`.
- The `name:` field in the SKILL.md YAML frontmatter determines the suffix — **not** the skill directory name.
- E.g., toolkit `sighting` + SKILL.md `name: burnin_log_analyzer_assistant` → loaded as `sighting_burnin_log_analyzer_assistant`.
- **Always verify** the actual loaded name by running with `-v` and checking the `Loaded assistant skill ...` debug line.
- Registered in `toolkit.yaml` under `skills:`.
- Can be local (`type: local`) or from GitHub (`type: github_repo`).
- **External skills from GitHub repos** (type: github_repo) may appear as `<toolkit>_skill_<name>` where `name` is the toolkit.yaml `skills[].name`. The exact name depends on the SKILL.md frontmatter `name:` field in the referenced repo.
- **Important:** YAML assistant files (`assistants/<name>.yaml`) are the **former** version of Skills. They are functionally equivalent to Skills, but it is encouraged to create new capabilities as `SKILL.md` files instead. Convert existing YAML assistants with: `gnai toolkits convert-to-skills <path-to-your-toolkit>`

### 4.4 Plugin
Extends the toolkit following the Claude Code plugin spec. Provides additional skills and agents. Registered in `toolkit.yaml` under `plugins:`.

### 4.5 Toolkit
A collection of tools, assistants, and skills. Defined by `toolkit.yaml` at the root.

### 4.6 Collection
A **collection** bundles related toolkits so users can install a set of skills through one alias. Browse available collections in the marketplace. Collections are defined in the GNAI marketplace registry — not in toolkit.yaml.
- Install a collection: `gnai toolkits register <collection-alias>`
- Collections enable one-command installs of multi-toolkit agentic flows.

---

## 5. toolkit.yaml Schema Reference

```yaml
version: 1
name: <toolkit_name>          # lowercase, 3–20 chars
description: <description>    # max 500 chars

env:
  - name: ENV_VAR_NAME        # uppercase, max 50 chars
    description: "..."        # max 1000 chars
    secret: true | false
    default: "value"          # optional
    run:
      get: "command to dynamically resolve value"   # optional

template:
  type: python | node | generic
  python:
    version: "3.11"
    manager: uv               # optional, for uv projects
    requirements:
      - requests
      - requests_kerberos
    requirements_file: requirements.txt   # alternative
    extra_paths: []
  # assets: download binaries/files at registration time
  assets:
    - name: my-binary
      flavors:
        - os: [linux]
          path: bin/my-binary-linux
        - os: [windows]
          path: bin/my-binary.exe

skills:
  - name: burnin_log_analyzer
    type: local
    local_path: skills/burnin_log_analyzer   # relative to toolkit dir

plugins:
  - name: my_plugin
    type: local | github_repo
    local_path: plugins/my_plugin
    skills: []   # optional filter: only include these skill names from the plugin

assistants:           # sub-assistants declared at toolkit level (if needed)
  - name: sighting_skill_burnin_log_analyzer

tools: []             # not in toolkit.yaml — tools live in tools/*.yaml

run:
  setup: "command to run on setup"

dependencies:
  - name: other_toolkit
    url: https://github.com/...

examples:
  - assistant: sighting_assistant
    prompt: "Analyze sighting HSD 18040537448"

contact: "your.name@intel.com"   # optional maintainer contact
```

**Important naming rules:**
- Toolkit name: lowercase, 3–20 chars
- All assistant/tool files MUST be prefixed with the toolkit name: `sighting_<name>.yaml`
- Tool names referenced in `assistants/*.yaml` must match the file name (without `.yaml`)

---

## 6. Assistant YAML Schema

```yaml
version: 1
description: "Short description for LLM routing (max 1000 chars)"
prompt: |
  Your detailed agent prompt here. Max 10000 chars.
model: claude-4-5-opus           # optional, see Section 8 for model list
params:
  - name: param_name
    type: string | integer | boolean
    description: "..."
    optional: true | false
    multiple: false
tools:
  - sighting_read_article
  - sighting_attachments
  - default_ask_user             # built-in tool
assistants:
  - name: sighting_skill_burnin_log_analyzer
    should_end: false            # optional
```

---

## 7. Tool YAML Schema

### Command Tool
```yaml
version: 1
description: "Short description (max 1000 chars)"
kind: command
params:
  - name: file_path
    type: str
    description: "Path to input file"
    optional: false
    multiple: false
env:
  - INTEL_USERNAME
  - INTEL_PASSWORD
run:
  command: $GNAI_TOOLKIT_ENTRYPOINT $GNAI_TOOLKIT_DIRECTORY/src/my_tool.py
  console_output: stdout         # stdout | stderr | both
  timeout: 300                   # seconds, optional
```

### Agent Tool
```yaml
version: 1
description: "Short description (max 1000 chars)"
kind: agent
params:
  - name: issues_file
    type: str
    description: "Path to JSON file with issues"
env:
  - INTEL_USERNAME
prompt: |
  Summarize the issues in:
  {{ readFileFromParam "issues_file" }}
model: gpt-4.1
output_file: $GNAI_TEMP_WORKSPACE/summary.txt   # optional: saves LLM output to file
run:
  pre: "command to run before LLM"             # optional
  post: "command to run after LLM"             # optional
  timeout: 600
structured_output:                             # optional
  method: json_schema
  schema:
    type: object
    properties: {}
  strict: true
```

---

## 8. Available Models

| Model | Provider | Notes |
|-------|----------|-------|
| `claude-4-5-sonnet` | Anthropic | Balanced model |
| `claude-4-6-sonnet` | Anthropic | Latest sonnet (default alias: `claude-sonnet`) |
| `claude-4-5-opus` | Anthropic | Most capable, most expensive |
| `claude-4-6-opus` | Anthropic | Latest opus |
| `claude-4-5-haiku` | Anthropic | Fast, cheap |
| `gpt-4.1` | OpenAI | Good for general tasks |
| `gpt-4o` | OpenAI | Vision capable |
| `gpt-5-mini` | OpenAI | Fast, economical |
| `gpt-5-nano` | OpenAI | Ultra-fast, ultra-cheap |
| `gpt-5.1` | OpenAI | Latest GPT-5 |
| `gpt-5.1-codex` | OpenAI | Code-focused |
| `gpt-5.1-codex-max` | OpenAI | Code-focused, max capacity |
| `gpt-5.2` | OpenAI | Advanced GPT-5 |
| `gpt-5.2-codex` | OpenAI | Code-focused v5.2 |
| `gpt-5.3-codex` | OpenAI | Code-focused v5.3 |
| `gpt-5.4` | OpenAI | Most advanced GPT |
| `gpt-5.4-mini` | OpenAI | Fast GPT-5.4 |
| `gpt-5.4-nano` | OpenAI | Ultra-fast GPT-5.4 |
| `o3` | OpenAI | Reasoning model |
| `o3-mini` | OpenAI | Fast reasoning model |
| `o4-mini` | OpenAI | Reasoning model |

- Thinking variants: append `-thinking` to claude sonnet/opus/haiku models (e.g., `claude-4-5-sonnet-thinking`, `claude-4-6-opus-thinking`)
- If no model specified in yaml, GNAI uses a platform default
- **Current model in `sighting_assistant.yaml`**: check `assistants/sighting_assistant.yaml`

---

## 9. Environment Variables

### Always Available (Built-in)
| Variable | Description |
|----------|-------------|
| `GNAI_TOOLKIT_DIRECTORY` | Absolute path to the toolkit repo/directory |
| `GNAI_TEMP_WORKSPACE` | Temporary directory for this chat session (cleaned up after) |
| `GNAI_TOOLKIT_ENTRYPOINT` | Python/Node entrypoint for the toolkit's virtual environment |

### Sighting Assistant Tool — GNAI_TEMP_WORKSPACE Layout

> For the full sighting assistant architecture including tool execution flow and data flow between tools, see [SIGHTING_ARCHITECTURE.md](SIGHTING_ARCHITECTURE.md).

GNAI creates a session-scoped temp directory at:
```
%LOCALAPPDATA%\Temp\gnai-chat\<session-uuid>\
```

Typical contents during a `sighting_assistant` run:

```
$GNAI_TEMP_WORKSPACE/                              ← session root, cleaned up after chat ends
├── hsd_info_file                                  ← output of sighting_read_article tool
├── attachment_info_file                           ← output of sighting_attachments tool
├── all_log_txt_trace_csv_files.json               ← index of all extracted log/txt/trace/csv files
├── all_etl_files.json                             ← index of direct ETLs + ETLs found inside extracted archives
├── messages.json                                  ← conversation message history (internal)
├── extracted_<attachment_id>/                     ← one dir per HSD attachment, named by ID
│   └── <zip_or_folder_name>/
│       └── <extracted file(s)>                    ← contents vary by attachment type
└── persistent_logs/                               ← individual log files extracted from ZIPs
  ├── <attachment_id>_<log_file_1.txt>           ← named <attachment_id>_<original_filename>
  └── <attachment_id>_<log_file_n.txt>
```

**Key points for tool authors:**
- `extracted_<attachment_id>/` — directory name is the HSD attachment ID, not the filename. Created by `sighting_attachments` / `check_attachments.py`.
- `all_etl_files.json` — the native ETL analyzer resolves `etl_target` from this index. ETLs extracted from archives are indexed here but remain physically inside `extracted_<attachment_id>/`.
- `persistent_logs/` — individual files unpacked from ZIPs and renamed with the HSD attachment ID prefix so multiple attachments don't collide.
- `hsd_info_file` / `attachment_info_file` — these are plain text output files written by tool scripts; their paths are passed as params between tools.
- `messages.json` — GNAI internal file; do NOT read or write this from tool scripts.
- The entire directory is deleted when the chat session ends — never store anything here that needs to survive across sessions.

### Sighting Assistant Tool — Persistent `SAT_<HSD_ID>_Output/` Layout

The toolkit also writes durable artifacts under the toolkit repository root via `get_sat_output_dir()`.

```
$GNAI_TOOLKIT_DIRECTORY/
└── SAT_<HSD_ID>_Output/
  ├── raw_attachments/                           ← original HSD downloads kept for re-use / re-extraction
  │   ├── <archive_or_direct_attachment>
  │   └── <split_archive_part>.7z.001
  ├── extracted_<attachment_id>/                 ← extracted archive contents kept outside %TEMP%
  │   └── <archive member tree>
  ├── PTAT_logs_plots/                           ← PTAT PNG plots generated by log_file_analyzer.py
  ├── GfxPnp_logs_plots/                         ← GfxPnp PNG plots generated by log_file_analyzer.py
  ├── DisplayDebugger_Output/                    ← DisplayDebugger text outputs
  ├── Sherlog_Output/                            ← Sherlog markdown outputs
  └── SAT_analysis_report.html                   ← final rendered HTML report artifact
```

**Persistence rules:**
- `SAT_<HSD_ID>_Output/` is **not** inside `GNAI_TEMP_WORKSPACE`; it is anchored to `GNAI_TOOLKIT_DIRECTORY`.
- `raw_attachments/` is intentionally persistent. `check_attachments.py` clears `hsd.attachments` after download so the HSDESAPI destructor does not delete these files.
- `extracted_<attachment_id>/` under `SAT_<HSD_ID>_Output/` is preferred for large/on-demand archive extraction to avoid `%TEMP%` disk-space exhaustion.
- Plots, Sherlog outputs, DisplayDebugger outputs, and the final HTML report are intended to survive after the chat session ends.

### Tool Parameters
- Each `params[].name` in a tool YAML → available as `GNAI_INPUT_<NAME_UPPERCASE>`
- E.g., `param name: file_path` → `GNAI_INPUT_FILE_PATH`
- For `multiple: true` params → value is a JSON list string, parse with `json.loads()`

### Custom Env Vars
- Declare in `toolkit.yaml` under `env:`
- Reference in tool YAML under `env:`
- GNAI will prompt the user if not configured
- Secrets are stored encrypted (`secret: true`)

---

## 10. Python Scripting Patterns

### Getting parameters in a Python tool:
```python
import os, json

# Simple parameter
file_path = os.environ['GNAI_INPUT_FILE_PATH']

# Multiple parameter (list)
emails = json.loads(os.environ.get('GNAI_INPUT_EMAILS', '[]'))

# Required env var
username = os.environ['INTEL_USERNAME']
password = os.environ['INTEL_PASSWORD']

# Built-in paths
toolkit_dir = os.environ['GNAI_TOOLKIT_DIRECTORY']
temp_workspace = os.environ['GNAI_TEMP_WORKSPACE']
```

### Writing output to a file (context window best practice):
```python
output_path = os.path.join(os.environ['GNAI_TEMP_WORKSPACE'], 'result.json')
with open(output_path, 'w', encoding='utf-8') as f:
    json.dump(result, f, indent=2)
print(f"Output written to {output_path}")   # only path goes into LLM context
```

### Running the script:
```yaml
run:
  command: $GNAI_TOOLKIT_ENTRYPOINT $GNAI_TOOLKIT_DIRECTORY/src/my_script.py
```

---

## 11. Best Practices

### Context Window Management
- **Do NOT** print large outputs (JSON blobs, full file contents) to stdout — they go into the LLM context window and consume tokens.
- **DO** write large outputs to `$GNAI_TEMP_WORKSPACE/<filename>` and print only the file path.
- Use `output_file:` in agent tools to auto-redirect LLM output to a file.
- For agent tools that process large files, use `{{ readFileFromParam "param_name" }}` in the prompt rather than passing content via environment variables.
- **sighting_gop_analyzer is conditional**
- Only invoke `sighting_gop_analyzer` when at least one `.log` or `.txt` filename contains a GOP indicator (`gop`, `uefi`, `preos`, `bios`, `intelgop`, `intelugop`, `intelpeim`, `boot`). STC system trace logs (e.g. `*_STC.log`) are NOT GOP logs and must not trigger the tool. If no GOP indicators are found, write "No GOP logs detected" in section 1.3.3 and skip the call entirely. This prevents wasted LLM cycles on non-GOP log files.
### Tool Description Quality
- The `description:` field is critical — the LLM uses it to decide when to invoke the tool.
- Be specific and include trigger keywords: "Use when...", "Call this when..."
- Bad: `"Gets articles"` → Good: `"Use when user provides an HSD ID to read article details from HSD-ES"`

### Prompt Writing
- Clearly define steps the assistant should follow (numbered list)
- Explicitly list which tools to call and in what order
- Use `default_ask_user` built-in tool when user input may be missing
- Always end prompts with explicit stop conditions: "NEVER STOP UNTIL ALL REQUIREMENTS ABOVE ARE MET"

### Naming Conventions
- All files must be prefixed with toolkit name: `sighting_tool_name.yaml`
- Parameter names: `snake_case`
- Environment variable names: `UPPER_SNAKE_CASE`

### Template: Always use Python
```yaml
template:
  type: python
  python:
    requirements:
      - requests
      - requests_kerberos
```
Python template is preferred: creates isolated venv, OS-agnostic, supports `$GNAI_TOOLKIT_ENTRYPOINT`.

---

## 12. Built-in Tools (System Tools)

These are GNAI platform tools available to any assistant — no `tools/*.yaml` needed.

**As of GNAI v1.153.8, these tools are renamed from `default_*` to `system_*`.** Using the old `default_*` names in the `tools:` list will produce a "not found in any loaded toolkit" warning and cause the tools to be **excluded** from the LLM's available tool set.

**Do NOT list system_* tools in the assistant `tools:` section** — they are auto-injected. Listing them (especially with old names) breaks them.

| Tool Name (v1.153.8+) | Old Name (pre-v1.153.8) | Description |
|----------------------|-------------------------|-------------|
| `system_ask_user` | `default_ask_user` | Ask the user a question and wait for input |
| `system_read_file` | `default_read_file` | Read contents of a local file |
| `system_write_file` | `default_write_file` | Write content to a local file |
| `system_list_directory` | `default_list_directory` | List files in a directory |
| `system_tree_directory` | `default_tree_directory` | Recursive directory listing |
| `system_create_directory` | `default_create_directory` | Create a directory |
| `system_delete_file` | `default_delete_file` | Delete a file |
| `system_move_file` | `default_move_file` | Move/rename a file |
| `system_copy_file` | `default_copy_file` | Copy a file |
| `system_get_file_info` | `default_get_file_info` | Get metadata about a file |
| `system_search_files` | `default_search_files` | Search for files by pattern |
| `system_shell_execute` | `default_shell_execute` | Execute a shell command |

---

## 13. Skills Reference

Skills follow the [agentskills.io](https://agentskills.io/home) open standard. A skill is a directory with a `SKILL.md` file describing the agent capability.

### Registering a Local Skill
```yaml
# toolkit.yaml
skills:
  - name: burnin_log_analyzer
    type: local
    local_path: skills/burnin_log_analyzer
```

### Invoking a Skill from an Assistant
Skills become assistants after registration, named `<toolkit_name>_<name_from_SKILL.md>`:
```yaml
# assistants/sighting_assistant.yaml
assistants:
  - name: sighting_burnin_log_analyzer_assistant   # SKILL.md frontmatter: name: burnin_log_analyzer_assistant
```

And in the prompt, instruct the LLM when to call it:
```
[Call sighting_burnin_log_analyzer_assistant and show its output here]
```

> **Tip:** Run `dt gnai ask "test" -v --assistant <assistant>` and look for `Loaded assistant skill ...` lines to confirm the exact name GNAI assigns to a skill.

### Skill Sub-Agent Capabilities vs Full GNAI Assistant (Verified Feb 2026, SGQE-21307)

**A SKILL.md sub-agent is NOT equivalent to a full GNAI assistant.** Verified by direct testing.

| Capability | Full GNAI Assistant | Skill Sub-Agent (SKILL.md) |
|---|---|---|
| Custom toolkit tools (e.g. `sighting_burnin_log_analyzer`) | ✅ Available via `tools:` list | ❌ Not available |
| `default_*` built-in tools | ✅ Yes | ✅ Yes (`default_read_file`, `default_tree_directory` confirmed working) |
| `default_shell_execute` PATH | ✅ Full system PATH | ❌ Stripped cmd.exe — `python`, `powershell`, `where` all "not recognized" |
| `GNAI_TEMP_WORKSPACE` in shell | ✅ Available to Python subprocesses | ❌ Not injected — `echo $env:GNAI_TEMP_WORKSPACE` returns literal; `echo %GNAI_TEMP_WORKSPACE%` returns "ECHO is off." |
| `$GNAI_TOOLKIT_ENTRYPOINT` | ✅ Available | ❌ Not available in skill shell context |
| `GNAI_INPUT_*` env vars | ✅ Set by runtime for tool scripts | ❌ Not injected into `default_shell_execute` |
| Spawn sub-agents | ✅ Via `assistants:` list | ❌ Cannot spawn further sub-agents |
| Receive parent context | N/A | ✅ Receives parent conversation context |

### Correct Architecture for Skills that Need Python Execution

**Do NOT** put Python invocation logic in `SKILL.md` — it will always fail.

**DO** follow this pattern:
1. Parent assistant (`sighting_assistant`) calls the Python tool directly via the toolkit tool YAML
2. Parent passes the structured output into the skill sub-agent's context
3. Skill sub-agent focuses purely on **LLM-based interpretation** of the pre-parsed data

```yaml
# In sighting_assistant.yaml prompt:
# Step 1: Call tool to run Python parser
#   → invoke sighting_burnin_log_analyzer tool with burnin_log_path
# Step 2: Pass parsed output to skill for interpretation
#   → invoke sighting_burnin_log_analyzer_assistant skill
```

---

## 14. MCP Server Integration

GNAI supports MCP (Model Context Protocol) servers via `stdio` mode. To wrap an MCP server:

1. Create `server_params.py` — defines how to start the server
2. Add `mcp:` section in `toolkit.yaml`

```yaml
mcp:
  client_params_command: $GNAI_TOOLKIT_ENTRYPOINT setup $GNAI_TOOLKIT_DIRECTORY/server_params.py
  assistant_prompt: "You are a XYZ assistant..."
  transport: stdio
```

**Distribution types:** PyPi package, GitHub repo (UV project), GitHub release binary, Node NPM package.

**Reference repos:**
- https://github.com/intel-innersource/applications.ai.gnai.toolkits.mcp-servers

---

## 15. GNAI Key Repositories

| Purpose | Repository |
|---------|-----------|
| Demo toolkit (reference implementation) | `intel-innersource/applications.ai.gnai.toolkits.demo` |
| MCP server toolkits | `intel-innersource/applications.ai.gnai.toolkits.mcp-servers` |
| GNAI API | `intel-innersource/applications.ai.gnai.api` |
| Toolkits base library | `intel-innersource/applications.ai.gnai.toolkits.base` |
| VSCode Extension | `intel-innersource/applications.ai.gnai.interfaces.vscode` |
| Claude Code GitHub Action | `intel-innersource/frameworks.actions.gnai.claude-code` |

**This toolkit:** `intel-sandbox/SightingAssistantTool`

---

## 16. Registering & Testing the Toolkit

```bash
# Initialize a new toolkit from template
gnai toolkits init --type python <path-to-my-toolkit>

# Validate the toolkit files
gnai toolkits validate <path-to-my-toolkit>

# Convert YAML assistants to SKILL.md skills format
gnai toolkits convert-to-skills <path-to-your-toolkit>

# Register from local path
gnai toolkits register /path/to/SightingAssistantTool

# Register from GitHub
gnai toolkits register intel-sandbox/SightingAssistantTool

# List registered toolkits and assistants
gnai toolkits list

# Serve toolkit as MCP server
gnai toolkits serve <path-to-my-toolkit>

# Start interactive chat session
gnai chat --assistant sighting_assistant

# Verbose mode (shows tool invocations)
gnai chat --assistant sighting_assistant -v

# Claude Code CLI (gnai-claude) — runs skills directly
gnai-claude --plugin-dir ./my-toolkit "/my-skill"
gnai-claude "/release-notes"
```

---

## 17. What to Update Here

When you discover something new, add it to the relevant section above:

- New GNAI features or schema changes → update Section 5/6/7
- New models available → update Section 8
- New built-in tools → update Section 12
- New GNAI patterns or behaviors observed → update Section 11
- New skills or plugins patterns → update Section 13/14
- New toolkit integration patterns (dependencies, subprocess, MCP) → update Section 19
- New bugs or workarounds found in GNAI framework → add to Section 20+
- New Git/DevOps patterns → update Section 18

---

## 18. Git & DevOps Guidelines

### Commit Message Format

Every commit message **must** follow this structure:

```
<type>(<scope>): <short description>

- <bullet detail 1>
- <bullet detail 2>

Related-To: <JIRA-ticket-ID>
```

**Rules:**
- `<type>`: `feat`, `fix`, `refactor`, `docs`, `chore`, `test`
- `<scope>`: optional, e.g. `burnin`, `skill`, `assistant`, `tool`
- Short description: imperative mood, max ~72 chars
- `Related-To:` field is **mandatory** on every commit — always the last line
- The JIRA ticket ID is provided by the user for the branch/PR being worked on — **always ask the user if not provided**

**Examples:**
```
feat(burnin): Add burnin log analyzer skill and tool

- Add SKILL.md with GPGPU error analysis instructions
- Add sighting_burnin_log_analyzer command tool
- Integrate with sighting_assistant workflow

Related-To: SGQE-21307
```
```
fix(tool): Correct GNAI tool YAML format and param naming

- Replace args: list with single run.command string
- Rename BURNIN_LOG_PATH param to snake_case burnin_log_path
- Fix skill sub-assistant reference name

Related-To: SGQE-21307
```

### Branch / PR Workflow

1. **One JIRA ticket per branch** — ask the user for the ticket ID at the start of work on a new branch
2. **All commits on a branch share the same `Related-To:` ticket** unless explicitly told otherwise
3. **Never use `git add -A`** — always use `git add -u <explicit file paths>` on only the exact files that were modified or deleted in that change. Never use bare `git add -u` (without paths) and never use `git add -A`. Only stage what you deliberately touched.
4. **Commit frequently** — one logical change per commit, not a dump of everything at once
5. **Before switching branches** — always commit or stash open changes with `git add -u`

### GNAI Development Loop

Follow this loop on every development session:

1. **Read `CLAUDE.md` first** — understand current guidelines before making any changes
2. **Make changes** — implement features, fixes, or improvements
3. **Validate against `CLAUDE.md`** — check naming, run format, param style, skill naming, etc.
4. **If GNAI behaves differently than documented** — update `CLAUDE.md` on `docs/gnai-guidelines` branch with the new observed behavior before merging
5. **Commit with explicit message + `Related-To:`** — never vague messages like "fix stuff" or "update"
6. **If something is missing from `CLAUDE.md`** — add it immediately; don't defer

### What Requires a CLAUDE.md Update

Update `CLAUDE.md` whenever you discover:
- A GNAI schema field that behaves differently than documented
- A new model added or removed from the platform
- A new built-in tool available
- A naming convention that differs from what's documented (e.g. skill assistant name format)
- A new bug or workaround specific to this toolkit's environment
- Any new GNAI feature (plugins, new template types, etc.)

---

## 19. Integrated External Toolkits

The SightingAssistantTool integrates with other GNAI toolkits to provide specialized analysis capabilities. These integrations are invoked via subprocess calls to `gnai ask` commands.

### 19.1 Sherlog Integration

**Repository:** `intel-innersource/drivers.gpu.core.sherlog-toolkit`  
**Purpose:** Analyze GDHM (GPU Debug Hardware Monitoring) dumps  
**Tool:** `sighting_sherlog_sync`  
**Invocation Pattern:**
```bash
gnai ask "Analyze GDHM dump ID {gdhm_id}" --assistant=sherlog_complex_analyzer
```

**Tracking Updates:**
- Monitor the sherlog repository README for changes to the invocation command or assistant name
- If sherlog changes its assistant name from `sherlog_complex_analyzer`, update `src/sherlog_subprocess.py`
- If sherlog changes its input format or parameters, update the GNAI command construction in `sherlog_subprocess.py`

**Current Implementation:** `tools/sighting_sherlog_sync.yaml` + `src/sherlog_subprocess.py`

### 19.2 DisplayDebugger Integration

**Repository:** `https://github.com/intel-sandbox/displaydebugger`  
**Purpose:** Analyze display driver logs (GOP UEFI logs and ETL OS driver logs) for display-related sightings  
**Tool:** `sighting_displaydebugger`  
**Invocation Patterns:**

**For GOP logs:**
```bash
gnai ask -v --log-file="{output_file}" --assistant=displaydebugger "analyze the display GOP log file '{local_log_path}' and check {analysis_focus} in this log"
```

**For ETL logs:**
```bash
gnai ask -v --log-file="{output_file}" --assistant=displaydebugger "analyze the display etl file '{local_log_path}' and check {analysis_focus} in this log"
```

`-v` is enabled in the subprocess wrapper for easier debugging. `--log-file` is required in this toolkit's subprocess pattern to persist output for post-processing.

**Prompt Construction:**
The DisplayDebugger prompt is built around the resolved local file path, not the HSD ID. `src/displaydebugger_subprocess.py` now prefers a concrete extracted file path first, then `raw_attachments/`, then other local matches, so the child `displaydebugger` assistant receives a usable on-disk file reference.

The `{analysis_focus}` string still comes from the **sighting_assistant** based on the HSD issue description and the user's interactive choice. The assistant analyzes the HSD content and maps it to specific focus areas such as:
- Display detection issues → `"display detection and initialization sequence"`
- Modeset failures → `"modeset and timing configuration"`
- Link training failures → `"link training and display connectivity"`
- Hotplug issues → `"hotplug detection and handling"`
- HDCP issues → `"HDCP authentication and key exchange"`
- Power issues → `"power state transitions and display power management"`
- EDID issues → `"EDID reading and display information"`
- Type-C issues → `"Type-C and Alt Mode configuration"`
- Panel issues → `"panel initialization and embedded display"`
- Output issues → `"display output and signal issues"`

**Design Rationale:**
The GNAI assistant has full context of the HSD (title, description, comments, attachments) and can make more sophisticated decisions about analysis focus than regex pattern matching in a Python script. This follows the GNAI pattern where the assistant orchestrates intelligent decisions and tools execute specific actions.

**Tracking Updates:**
- Monitor https://github.com/intel-sandbox/displaydebugger/blob/main/README.md section "How to use examples" for changes to invocation patterns
- Check for updates to the assistant name (currently `displaydebugger`)
- If displaydebugger changes its prompt format or parameters, update `src/displaydebugger_subprocess.py`
- Review displaydebugger CHANGELOG or commit history periodically for breaking changes

**Tool Parameters:**
- `hsd_id`: HSD ID being analyzed
- `log_files`: List of display log file paths (GOP or ETL)
- `analysis_focus`: Intelligent focus string constructed by the assistant and confirmed by the user in interactive mode (e.g., "display detection and initialization sequence")

**Log Type Detection:**
- GOP logs: Text files with `[InteluGOP]`, `[IntelGOP]`, or `[IntelPEIM]` prefixes in boot/UEFI logs
- ETL logs: Binary `.etl` files or `.7z`/`.zip` archives containing ETL traces

**Current Implementation:** `tools/sighting_displaydebugger.yaml` + `src/displaydebugger_subprocess.py`

**Output naming behavior:**
- DisplayDebugger outputs are written under `SAT_<HSD_ID>_Output/DisplayDebugger_Output/`
- Output filenames are based on a sanitized basename and become collision-safe with `_1`, `_2`, etc. suffixes when the same basename appears multiple times

**GDHM validation note:**
- `src/sherlog_subprocess.py` now accepts only strict 10-digit GDHM IDs. Do not relax this back to `>= 8` digits unless the upstream format changes.

### 19.3 Toolkit Integration Patterns: Dependencies vs Subprocess

**Verified:** February 2026 via [GNAI FAQ documentation](https://gpusw-docs.intel.com/services/gnai/faq/#can-i-use-tools-from-another-toolkit-into-my-toolkit)

GNAI provides two mechanisms for cross-toolkit integration, depending on what you need to invoke:

#### Official Dependencies Mechanism (For Individual Tools)

GNAI supports declaring toolkit dependencies in `toolkit.yaml` for **individual tools**:

```yaml
# toolkit.yaml
dependencies:
  - name: sherlog
    url: https://github.com/intel-innersource/drivers.gpu.core.sherlog-toolkit
  - name: displaydebugger
    url: https://github.com/intel-sandbox/displaydebugger
```

Then reference tools directly in your assistant's `tools:` list:

```yaml
# assistants/sighting_assistant.yaml
tools:
  - sighting_read_article
  - sighting_attachments
  - sherlog_some_tool           # tool from sherlog toolkit
  - displaydebugger_some_tool   # tool from displaydebugger toolkit
```

**How it works:**
- GNAI checks if dependency toolkits are registered when your toolkit is installed
- If missing, GNAI prompts the user with the command to install dependencies
- Once registered, your assistant can invoke individual tools from those toolkits directly
- The LLM orchestrates tool selection and invocation as part of your assistant's workflow

**Use this pattern when:**
- ✅ You need specific **individual tools** from another toolkit
- ✅ Your assistant can orchestrate the tool calls itself
- ✅ You don't need to pass custom prompts to the external toolkit's assistant
- ✅ You want GNAI to handle dependency management automatically

#### Subprocess Pattern (For Complete Assistants/Workflows)

**This is the correct pattern for sherlog and displaydebugger** because we need to invoke their complete **assistants** (`sherlog_complex_analyzer`, `displaydebugger`) with custom prompts, not just individual tools.

```python
# src/sherlog_subprocess.py / src/displaydebugger_subprocess.py
gnai_command = f'gnai ask "Analyze GDHM dump ID {gdhm_id}" --assistant=sherlog_complex_analyzer'
subprocess.run(['cmd', '/c', 'start', 'GDHM Analysis', '/wait', 'cmd', '/c', batch_file], check=True)
```

**Use this pattern when:**
- ✅ You need to invoke a complete **assistant** (agentic workflow) from another toolkit
- ✅ You need to pass **custom prompts** to that assistant
- ✅ You need to capture the full output including all sub-tool invocations
- ✅ The external toolkit is designed as an end-to-end analysis workflow (like sherlog/displaydebugger)

**Why subprocess for sherlog/displaydebugger:**
1. **Sherlog** provides `sherlog_complex_analyzer` assistant — a complete GDHM analysis workflow
2. **DisplayDebugger** provides `displaydebugger` assistant — a complete display log analysis workflow
3. Both require **custom prompts** constructed by `sighting_assistant` with HSD context
4. Both perform multi-step analysis with their own tool chains
5. We need the complete output of their end-to-end workflow, not just one tool invocation

#### MCP (Model Context Protocol) - Server Toolkits Only

**MCP is NOT for local-to-local toolkit communication.** Per [GNAI documentation](https://gpusw-docs.intel.com/services/gnai/agentic-workflows/#server-toolkits):

- MCP is for **server toolkits** — deploying toolkits as services accessible platform-wide
- Used for Intel services integration (JIRA, HSD, GTA server-side access)
- Local toolkits use websocket bidirectional communication with GNAI platform
- Not designed for toolkit-to-toolkit invocation

**Summary:**

| Pattern | Use For | Example |
|---------|---------|---------|
| `dependencies:` in toolkit.yaml | Individual tools from other toolkits | sherlog/displaydebugger are listed here for installation/registration; SightingAssistantTool does not call their individual tools directly |
| Subprocess `gnai ask --assistant=<name>` | Complete assistant workflows with custom prompts | ✅ sherlog_complex_analyzer, ✅ displaydebugger |
| MCP server toolkit | Platform-wide service deployment | JIRA/HSD/GTA server toolkits (not local integrations) |

**SightingAssistantTool uses subprocess pattern** for sherlog and displaydebugger because we need to invoke their full agentic workflows, not just individual tools.

### 19.4 Internal RAG Integration for DFD Checklist + BKM

**Verified:** March 2026 on `sighting_assistant` runtime logs.

DFD checklist compliance and category-specific BKM guidance are now retrieved through a local wrapper tool instead of legacy static BKM/checklist YAML tools.

**Tool:** `sighting_rag_search`  
**Files:** `tools/sighting_rag_search.yaml` + `src/sighting_rag_search.py`

**Runtime contract (important):**
- Input params are `search_query`, `profile`, and `max_documents`
- Section 4 calls must set `profile=gpu-debug` on first attempt
- Mandatory checklist query is deterministic (`MANDATORY_CHECKLIST_QUERY`)
- BKM query is deterministic and category/scenario-based (`BKM_QUERY` with `{Category}` + `{Main Issue}`)
- Section 4 output must render checklist table with exact columns: `Checklist Item | Description | Yes/No`

**Why this exists:**
- GNAI runtime may rewrite/normalize reserved parameter names (especially `question`) at execution time
- Using a local wrapper with non-reserved `search_query` avoids that rewrite path and keeps calls deterministic

**Implementation notes:**
- Wrapper reads `GNAI_INPUT_SEARCH_QUERY`, `GNAI_INPUT_PROFILE`, `GNAI_INPUT_MAX_DOCUMENTS`
- `GNAI_URL` is optional; defaults to `https://gnai.intel.com/api`
- Uses raw `requests` + HTTP Basic Auth (`base64(INTEL_USERNAME:INTEL_PASSWORD)`); **no `gnai.client` dependency** (refactored in SGQE-21505)
- Calls `POST /rag/vector/search?profile=<profile>&retrieval_type=hybrid&max_documents=<n>` with body `{"question": "...", "filters": {}}`
- Tool returns `tool-result/v1` payload for clean agent ingestion

**Legacy tools removed (do not reintroduce):**
- `tools/sighting_mandatory_dfd_analyzer.yaml`
- `tools/sighting_display_bkm.yaml`
- `tools/sighting_media_bkm.yaml`
- `tools/sighting_game_bkm.yaml`
- `tools/sighting_ml_content_bkm.yaml`
- `tools/sighting_bsod_tdr_hang_bkm.yaml`
- `tools/sighting_yellow_bang_bkm.yaml`

---

## 20. Known Issues / Workarounds

### Skill Sub-Agent Cannot Execute Python or Toolkit Tools (as of Feb 2026)
Verified during SGQE-21307 development. `default_shell_execute` in a skill sub-agent runs in a stripped `cmd.exe` with no PATH — `python`, `powershell`, and `where` are all unrecognized. `GNAI_TEMP_WORKSPACE`, `GNAI_TOOLKIT_ENTRYPOINT`, and `GNAI_INPUT_*` env vars are not injected. Custom toolkit tools are not available to skill sub-agents.

**Workaround:** Have the parent assistant run the Python tool first, then pass structured output to the skill for interpretation. See Section 13 for the correct architecture pattern.

### SSL Verification Bypass (as of Feb 2026)
Intel internal certificates cause SSL verification errors with `certifi`. All HTTP calls to `hsdes-api.intel.com` use `verify=False` with `urllib3.disable_warnings()` to suppress warnings. This is safe since HSD-ES is only accessible from Intel's network.

```python
import urllib3
urllib3.disable_warnings()
response = requests.get(url, auth=HTTPKerberosAuth(), verify=False, ...)
```

### Reserved Tool Param Rewrite for `question` in RAG Calls (as of Mar 2026)
Observed in runtime logs: calls that transit reserved argument names like `question` may be rewritten and fail under nested delegation paths.

**Workaround:**
- Use `sighting_rag_search` wrapper with non-reserved param `search_query`
- Avoid nested arg remapping to `question`
- Keep deterministic Section 4 calls in `sighting_assistant.yaml`

### `default_*` Built-in Tools Renamed to `system_*` in GNAI v1.153.8 (as of Apr 2026)
After `dt gnai update` to v1.153.8, listing `default_ask_user` or `default_write_file` in an assistant's `tools:` section causes the warning "was not found in any loaded toolkit" and the tool is **excluded** from the LLM's available tool set. The result: the LLM never calls `default_ask_user`, so interactive loops never fire.

**Root cause:** In v1.153.8 the built-in tools were renamed from `default_*` to `system_*`. The `default_*` names no longer resolve in toolkit tool resolution.

**Workaround:**
- Remove `default_ask_user`, `default_write_file`, `default_read_file` from the `tools:` list in all assistant YAMLs — system tools are auto-injected and do NOT need to be listed.
- Update all prompt text references from `default_ask_user` → `system_ask_user`, `default_read_file` → `system_read_file`, `default_write_file` → `system_write_file`.
- The `sighting_assistant.yaml` and `sighting_report_helper.yaml` have already been updated.

### GfxPnP Plots Missing from HTML — Missing `elif` Branch (Fixed Apr 2026, SGQE-21600)
`log_file_analyzer.py gfxpnp` had no `elif` branch in `__main__`. When `sighting_gfxpnp_analyzer` called it directly, it exited silently — no output, no plot path. GfxPnP processing was accidentally piggybacked inside the `ptat` branch, so plots only appeared if PTAT was also selected.

**Fix:** Added standalone `elif args.log_type == 'gfxpnp':` block. PTAT and GfxPnP now run independently in their own branches.

### PTAT/GfxPnP Converted from Agent to Command Tools (Apr 2026, SGQE-21600)
`sighting_ptat_analyzer.yaml` and `sighting_gfxpnp_analyzer.yaml` were originally `kind: agent` (LLM call per file). Python already computes all metrics and generates plots — no LLM reasoning needed. Converted to `kind: command` for instant execution.

- JSON results written to `$GNAI_TEMP_WORKSPACE/ptat_results.json` and `gfxpnp_results.json` (not in chat)
- Human-readable summary (`=== PTAT Analysis Summary ===`) printed to stdout for LLM context

### Phase 3 Gate — LLM Skipping Interactive Prompts (Fixed Apr 2026, SGQE-21600)
LLM was treating wiki query and similar-HSD prompts as background tasks, calling `system_ask_user` but immediately proceeding to Phase 4 before user responses returned.

**Fix:** Renamed section to `PHASE 3 GATE — BLOCKING STEPS` with explicit numbered steps (3A, 3B) each followed by `STOP. Do not start [next step] until this tool call returns the user's actual answer.` Added `PHASE 4 GATE` line immediately before Phase 4 header.

---

*Last updated: 2026-04-21 | Sources: https://gpusw-docs.intel.com/services/gnai/ + https://gpusw-docs.intel.com/services/gnai/agentic-flows/ + https://gpusw-docs.intel.com/services/gnai/developer/agentic-flows/ + https://gpusw-docs.intel.com/services/gnai/models/ + https://gpusw-docs.intel.com/services/gnai/faq/ + https://github.com/intel-sandbox/displaydebugger*
