# Context and Agent Output Improvements

## Summary

This document describes the changes made to improve context management and agent output structuring in the Deadend CLI agent framework.

## Problems Addressed

1. **Truncated Information**: Key findings, techniques, and next_steps were cut off with "..."
2. **Duplicate Information**: Target and goal appeared multiple times in context
3. **No Reproduction Steps**: When FLAG FOUND, no clear way to reproduce it
4. **Incomplete Test History**: "... and N more" instead of showing all tested techniques
5. **Poor Structure**: Agent outputs not properly extracted into context

---

## Changes Made

### 1. New Data Models (`context_engine.py`)

#### ExecutionRecord
Structured record of each agent execution with full payload storage:
```python
@dataclass
class ExecutionRecord:
    action: str              # "HTTP POST", "Python Script", "Shell Command"
    target_endpoint: str     # The endpoint tested
    technique: str           # Full technique description (no truncation)
    parameters: Dict         # Full payload, method, response (no truncation)
    result_status: str       # success, failed, blocked, error
    key_finding: str         # What was learned (no truncation)
    agent_name: str          # Which agent performed this
```

#### AgentThought
Captured agent reasoning with summarization:
```python
@dataclass
class AgentThought:
    agent_name: str
    thought: str        # Full reasoning
    summary: str        # Concise summary for context
    relevance: float    # 0.0-1.0, only >=0.6 shown
```

### 2. Agent Output Models

#### RequesterOutput (`request_agent.py`)
Added:
- `payloads_tested: list[TestedPayload]` - Every payload with endpoint, result, why_failed
- `key_findings: str` - Most important discovery (no truncation)
- `next_steps: str` - Suggested actions

#### PythonInterpreterOutput (`python_interpreter_agent.py`)
Added:
- `techniques_tested: list[TestedTechnique]` - Every technique with outcome
- `key_findings: str`
- `next_steps: str`

#### ShellOutput (`shell_agent.py`)
Added:
- `commands_executed: list[ExecutedCommand]` - Every command with result
- `key_findings: str`
- `next_steps: str`

#### RequesterSecOutput (`webapp_recon_agent.py`)
Added:
- `endpoints_discovered: list[DiscoveredEndpoint]` - Full endpoint details
- `key_findings: str`
- `next_steps: str`

### 3. Context Output Format (`get_unified_context`)

**Before**: Messy, truncated, duplicated
```
## Target
127.0.0.1:8080

## Goal
...

## Target  <- DUPLICATE
127.0.0.1:8080

## Already Tested
/endpoint
  - technique1
  - technique2
  - ... and 8 more  <- TRUNCATED
```

**After**: Clean, complete, no duplicates
```
Target: 127.0.0.1:8080
Goal: Test SSTI

## ⚑ FLAG/EXPLOIT FOUND - REPRODUCTION STEPS
Action: Python Script
Endpoint: /error?error_type=
Technique: Jinja2 {{config}}
Parameters: {'payload': '{{config}}', 'method': 'GET'}
Result: Config object exposed

## COMPLETE TEST HISTORY
Every technique tested per endpoint:

### /profile?id=
✓ WORKED:
  - Authentication bypass
    → 200 OK, session created
✗ FAILED:
  - Jinja2 {{7*7}} [302 redirect]
  - Jinja2 class traversal [302 redirect]
  - Template inclusion [302 redirect]

### /error
✓ WORKED:
  - SSTI {{config}}
    → Config object in response

## KEY DISCOVERIES
[finding] finding_SSTI_test: SSTI confirmed on /error endpoint
  next_steps: Escalate to RCE via __class__.__mro__

## VULNERABILITIES
[CONFIRMED] SSTI: Tested with confidence 0.95
  Payload: {{config}}

## INSIGHTS
[python_interpreter] SSTI confirmed via config extraction
```

### 4. Extraction Logic (`architecture.py`)

Updated `_extract_agent_output_to_context()` to:
- Extract ALL payloads_tested/techniques_tested/commands_executed
- Store full payloads in parameters (no truncation)
- Extract key_findings without truncation
- Store next_steps as actionable fact
- Handle all agent types uniformly

### 5. Agent Prompts

Updated all prompts to document required output fields:
- `requester.instructions.jinja2`
- `python_interpreter.instructions.jinja2`
- `shell.instructions.jinja2`
- `webapp_recon.instructions.jinja2`

Each now includes:
```
### REQUIRED OUTPUT FIELDS

**techniques_tested** (List - REQUIRED):
Record EVERY technique tested with outcome...

**key_findings** (String - REQUIRED):
The single most important discovery...

**next_steps** (String - REQUIRED):
What should be tested next...

**updated_state** (Dict - REQUIRED):
Structured discoveries...
```

---

## New Context Sections

| Section | Purpose |
|---------|---------|
| Target + Goal | Single header line (no duplication) |
| FLAG/EXPLOIT FOUND | Full reproduction steps with payload, endpoint, parameters |
| COMPLETE TEST HISTORY | ALL techniques per endpoint, grouped by success/failure |
| KEY DISCOVERIES | Full findings with next_steps attached |
| ENDPOINTS | Discovered endpoints with auth status, params, technologies |
| VULNERABILITIES | Confirmed/suspected vulns with payloads |
| INSIGHTS | High-relevance agent thoughts |

---

## Benefits

1. **No Information Loss**: Full payloads, findings, and next_steps preserved
2. **Clear Reproduction**: FLAG FOUND includes exact steps to reproduce
3. **Complete History**: Every technique tested is shown, grouped by endpoint
4. **No Duplication**: Target/goal appear once only
5. **Actionable Context**: Next steps and insights clearly highlighted
6. **Agent Learning**: Subsequent agents know exactly what was tried and why it failed

---

## Files Changed

- `deadend_agent/context/context_engine.py` - ExecutionRecord, AgentThought, get_unified_context()
- `deadend_agent/agents/architecture.py` - _extract_agent_output_to_context()
- `deadend_agent/agents/factory.py` - summarize_agent_thought(), AgentOutput.thought_summary
- `deadend_agent/agents/generic_agents/request_agent.py` - TestedPayload, RequesterOutput
- `deadend_agent/agents/generic_agents/python_interpreter_agent.py` - TestedTechnique, PythonInterpreterOutput
- `deadend_agent/agents/generic_agents/shell_agent.py` - ExecutedCommand, ShellOutput
- `deadend_agent/agents/generic_agents/webapp_recon_agent.py` - DiscoveredEndpoint, RequesterSecOutput
- `deadend_prompts/requester.instructions.jinja2` - Required output fields
- `deadend_prompts/python_interpreter.instructions.jinja2` - Required output fields
- `deadend_prompts/shell.instructions.jinja2` - Required output fields
- `deadend_prompts/webapp_recon.instructions.jinja2` - Required output fields
