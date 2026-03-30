Below is a **practical implementation interpretation** of the paper for **agent memory over long Markdown (`.md`) and JSON (`.json`) files**.

The key paper idea is to **not stuff the whole long context into the model prompt**. Instead, treat the long context as an **external environment** that the model can inspect, decompose, and query recursively over selected snippets. That is the right mental model for agent memory too: memory should be **stored externally, navigated programmatically, and only selectively exposed to the LM**. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# Step-by-step implementation for agent memory from long `.md` and `.json` files

## 1. Core idea: use files as external memory, not prompt text

For agent memory, the paper maps well to this pattern:

- **Memory store** = files on disk / object store / DB
- **Working memory** = a Python environment with handles to those files
- **Reasoning loop** = root LM decides what to inspect
- **Semantic compression** = sub-LM calls on selected chunks
- **Final answer / plan** = built from buffers, not from re-reading everything

This follows the paper’s main design: long context is treated as part of the environment, and the LM examines only relevant pieces rather than ingesting the whole thing at once. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

## 2. What “agent memory” means here

For your use case, memory can be split into 3 practical types:

### A. Documentation memory
Useful for `.md` files:
- README files
- design docs
- architecture notes
- meeting notes
- changelogs
- runbooks
- ADRs

### B. Structured state memory
Useful for `.json` files:
- config files
- workflow state
- prior tool outputs
- event histories
- API responses
- cache entries
- task metadata

### C. Episodic agent memory
Can be either `.md` or `.json`:
- previous conversations
- previous plans
- previous failures
- execution traces
- summaries of completed work

The paper’s idea is especially good when this memory is **large, heterogeneous, and too long to fit cleanly in context**. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 3. Best usage patterns for `.md` and `.json`

## Markdown memory is best for:
- human-written notes
- long-form explanations
- sectioned documents
- docs where headings matter
- retrieval by topic

### Why
Markdown usually has natural structure:
- headings
- bullet lists
- code blocks
- sections
- subsections

That makes it ideal for **structural chunking**:
- split by heading
- summarize per section
- recurse on relevant sections only

This matches the paper’s examples where the LM first inspects context structure, then chooses a chunking strategy and queries chunks selectively. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

## JSON memory is best for:
- explicit state
- machine-readable observations
- logs
- repeated records
- nested objects
- tool outputs

### Why
JSON is easier to:
- filter by key
- slice by path
- aggregate programmatically
- count, deduplicate, sort, compare

This matches the paper’s strong result that the environment is valuable not just for reading, but for **programmatic manipulation** before asking the LM for semantic interpretation. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 4. Recommended memory architecture

Use a **two-layer memory design**.

## Layer 1: Raw memory store
Keep original files unchanged.

Example:
```text
memory/
  docs/
    architecture.md
    roadmap.md
    incidents.md
  state/
    workflow_state.json
    tool_results.json
    tasks.json
  episodic/
    2026-03-25-session-summary.md
    prior_runs.json
```

## Layer 2: Derived navigation artifacts
Precompute lightweight metadata:

- file manifest
- section index for markdown
- JSON path index
- embeddings per chunk
- keyword / BM25 index
- timestamps
- tags

Example:
```json
{
  "file": "docs/architecture.md",
  "type": "markdown",
  "sections": [
    {"id": "sec1", "heading": "System Overview", "start": 0, "end": 1800},
    {"id": "sec2", "heading": "Memory Layer", "start": 1801, "end": 4200}
  ]
}
```

This is important because the paper’s scaffold works best when the model can inspect **structure and chunk boundaries** before reading content in detail. That is directly aligned with the prompt fields describing context type and chunk lengths. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 5. Memory operations your agent should support

Implement tools that let the LM inspect memory without reading it all.

## Minimum tool set

### For all files
- `list_files()`
- `get_file_metadata(path)`
- `grep_memory(pattern, path=None)`
- `read_chars(path, start, end)`
- `read_lines(path, start, end)`

### For Markdown
- `list_md_sections(path)`
- `read_md_section(path, heading_or_id)`
- `read_md_outline(path)`
- `search_md_headings(query)`

### For JSON
- `json_keys(path, json_path=None)`
- `json_get(path, json_path)`
- `json_search(path, key=None, value_contains=None)`
- `json_sample_array(path, json_path, start, end)`
- `json_schema(path)`

### For semantic recursion
- `llm_query(prompt, content)`
- `summarize_chunk(chunk, task)`
- `classify_chunk(chunk, labels)`
- `extract_facts(chunk, schema)`

This follows the paper’s pattern: the LM should be able to inspect, filter, decompose, and then call a sub-LM over selected snippets. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 6. Step-by-step implementation

## Step 1: Create file loaders

### Markdown loader
```python
from pathlib import Path

def load_markdown(path: str) -> str:
    return Path(path).read_text(encoding="utf-8")
```

### JSON loader
```python
import json
from pathlib import Path

def load_json(path: str):
    return json.loads(Path(path).read_text(encoding="utf-8"))
```

---

## Step 2: Build structure-aware chunkers

## Markdown chunker
Prefer splitting by headings, not fixed token windows.

```python
import re

def split_markdown_sections(text: str):
    pattern = r'^(#{1,6})\s+(.*)$'
    lines = text.splitlines()
    sections = []
    current = {"heading": "ROOT", "level": 0, "content": []}

    for line in lines:
        m = re.match(pattern, line)
        if m:
            if current["content"]:
                sections.append({
                    "heading": current["heading"],
                    "level": current["level"],
                    "content": "\n".join(current["content"]).strip()
                })
            current = {
                "heading": m.group(2).strip(),
                "level": len(m.group(1)),
                "content": []
            }
        else:
            current["content"].append(line)

    if current["content"]:
        sections.append({
            "heading": current["heading"],
            "level": current["level"],
            "content": "\n".join(current["content"]).strip()
        })
    return sections
```

### Why this matters
For markdown, **semantic sections are the natural memory unit**. The paper explicitly suggests inspecting structure and choosing a chunking strategy rather than blindly feeding raw text. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

## Step 3: Build JSON path-based slicing

```python
def json_keys(obj):
    if isinstance(obj, dict):
        return list(obj.keys())
    if isinstance(obj, list):
        return [f"[{i}]" for i in range(min(len(obj), 20))]
    return []
```

Use JSONPath-like access:

```python
def json_get(obj, path: str):
    cur = obj
    for part in path.strip(".").split("."):
        if "[" in part and "]" in part:
            key, idx = part[:-1].split("[")
            if key:
                cur = cur[key]
            cur = cur[int(idx)]
        else:
            cur = cur[part]
    return cur
```

### Why this matters
With JSON, the best pattern is:
1. inspect schema
2. identify relevant branches
3. read samples
4. aggregate in code
5. use LM only where semantics are needed

That is very close to the paper’s successful trajectories: use code first, LM second. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

## Step 4: Build derived indexes

## Markdown index
Store:
- headings
- section text length
- keywords
- embedding
- timestamps if present

## JSON index
Store:
- top-level keys
- nested paths
- arrays and lengths
- event types
- record IDs
- embedding of flattened records where useful

Example manifest:
```python
memory_manifest = {
    "docs/architecture.md": {
        "type": "markdown",
        "sections": ["System Overview", "Memory Layer", "Failure Modes"]
    },
    "state/tasks.json": {
        "type": "json",
        "top_keys": ["tasks", "updated_at", "owner"]
    }
}
```

---

## Step 5: Create a persistent memory REPL

The paper’s central scaffold uses a persistent REPL environment where the LM can store variables, inspect context, and call sub-LMs. For agent memory, your REPL should expose memory tools instead of one raw giant string. ([arxiv.org](https://arxiv.org/abs/2512.24601))

### Suggested environment
```python
class MemoryEnv:
    def __init__(self, root_dir, sub_llm):
        self.root_dir = Path(root_dir)
        self.vars = {}
        self.sub_llm = sub_llm

    def list_files(self):
        return [str(p.relative_to(self.root_dir))
                for p in self.root_dir.rglob("*") if p.is_file()]

    def read_text(self, path):
        return (self.root_dir / path).read_text(encoding="utf-8")

    def load_json(self, path):
        import json
        return json.loads((self.root_dir / path).read_text(encoding="utf-8"))

    def llm_query(self, instruction, content):
        prompt = f"{instruction}\n\nCONTENT:\n{content}"
        return self.sub_llm(prompt)
```

---

## Step 6: Give the root LM the right policy

Your root LM should be instructed to do this:

1. **Inspect available files first**
2. **Infer structure before reading deeply**
3. **Use code/tools to narrow search**
4. **Batch related content into sub-LM calls**
5. **Store summaries/facts in variables**
6. **Aggregate programmatically**
7. **Only then produce final answer**

That is the same high-level behavior encouraged by the paper’s REPL prompt. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 7. Specific workflows

## Workflow A: long Markdown memory

### Example use case
“Find the latest architectural decisions and unresolved risks across all docs.”

### Step-by-step
1. `list_files()`
2. filter `.md`
3. `read_md_outline()` or parse headings
4. find candidate sections:
   - “Decision”
   - “Architecture”
   - “Risk”
   - “Open Questions”
5. read only those sections
6. batch 3–10 sections into sub-LM summaries
7. store extracted facts:
   - decision
   - rationale
   - risk
   - owner
   - status
8. merge and deduplicate
9. final answer

### Why this works
Markdown is mostly **topic-organized**, so the agent should first navigate the outline, not the prose.

---

## Workflow B: long JSON memory

### Example use case
“Summarize all failed tool executions in the last 7 runs and explain recurring causes.”

### Step-by-step
1. load JSON file
2. inspect top-level keys
3. find `runs`, `events`, `status`, `error`, `timestamp`
4. filter in Python:
   - last 7 runs
   - failed events only
5. build compact records
6. send batched error records to sub-LM
7. ask sub-LM:
   - classify failures
   - identify recurring causes
   - map to probable remediation
8. aggregate counts in Python
9. final answer

### Why this works
JSON is better handled as **code-manipulated state**, with the LM used mostly for semantic grouping.

---

## Workflow C: mixed `.md` + `.json`

### Example use case
“Use architecture docs plus workflow state to explain why the last deployment failed.”

### Step-by-step
1. search markdown for deployment architecture / rollout / failure handling
2. inspect JSON for recent deployment event logs
3. extract:
   - expected behavior from docs
   - actual behavior from logs
4. send side-by-side evidence to sub-LM
5. ask for mismatch analysis
6. build final incident explanation

This is one of the best uses of the paper’s idea: the LM uses external memory as a workspace across heterogeneous sources instead of trying to absorb everything at once. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 8. When to use retrieval vs recursive memory access

## Use retrieval first when:
- you know likely keywords
- files are numerous
- only a few sections matter

## Use recursive chunk-by-chunk analysis when:
- answer depends on many sections
- structure matters more than keywords
- you need aggregation over many records
- the task is information-dense

This mirrors the paper’s distinction between easier sparse tasks and more information-dense tasks where sub-calls and programmatic aggregation matter much more. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 9. A concrete implementation plan

## Phase 1: basic memory agent
Implement:
- markdown section splitter
- json path accessor
- file manifest
- root loop
- sub-LM batching
- final aggregation buffer

### Result
A working “memory-aware” agent that does not overflow context.

---

## Phase 2: richer memory tools
Add:
- BM25 or embedding search
- markdown heading search
- JSON schema introspection
- regex over files
- cached chunk summaries
- timestamps and recency weighting

---

## Phase 3: memory compaction
Persist derived memory:
- per-section summary
- per-run summary
- per-error summary
- semantic tags
- embeddings
- entity graph

Now the agent can reason over:
- raw memory when needed
- compact memory when enough

---

# 10. Sample root-loop pseudocode

```python
def memory_agent(query, env, root_llm, max_turns=20):
    messages = [
        {"role": "system", "content": MEMORY_AGENT_PROMPT},
        {"role": "user", "content": query}
    ]

    for _ in range(max_turns):
        reply = root_llm(messages)
        text = reply["content"]

        if text.startswith("FINAL("):
            return text[len("FINAL("):-1]

        code_blocks = extract_repl_blocks(text)
        if code_blocks:
            outputs = []
            for code in code_blocks:
                outputs.append(run_in_memory_env(env, code))
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "\n\n".join(outputs)})
        else:
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "Continue with memory inspection or return FINAL(...)."})

    raise RuntimeError("No final answer")
```

---

# 11. Recommended root prompt for memory gathering

You can adapt the paper’s RLM prompt into a memory-specific version:

```text
You are an agent with access to external memory stored in markdown and JSON files.

Do not try to read everything at once.
First inspect the available files and their structure.
Use code/tools to:
- list files
- inspect markdown outlines
- inspect JSON schemas/keys
- search for likely relevant sections
- read only needed chunks
- batch semantically related chunks into sub-LLM calls
- store intermediate findings in variables

Prefer programmatic filtering for JSON.
Prefer heading/section-based navigation for Markdown.

When you have enough evidence, provide FINAL(...)
```

That is not a verbatim paper prompt, but it is the most direct practical adaptation of the paper’s mechanism to agent memory. The paper’s own scaffold centers on environment access, chunking, buffering, and recursive sub-calls. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

# 12. Important pitfalls

## Pitfall 1: treating memory as one giant prompt
Bad:
- concatenate all docs and logs
- send to LLM

Good:
- inspect structure first
- read targeted parts only

## Pitfall 2: using the LM for operations code should do
Bad:
- ask LM to count statuses in JSON

Good:
- count in Python
- ask LM only to interpret patterns

## Pitfall 3: overusing sub-calls
The paper notes that too many sub-calls can explode cost and runtime; batching is better. ([arxiv.org](https://arxiv.org/abs/2512.24601))

## Pitfall 4: no persistent buffers
If the agent does not store intermediate findings, it will repeatedly rediscover the same information.

## Pitfall 5: fixed-size chunking for markdown
Heading-aware chunking is much better than arbitrary slices for docs.

---

# 13. Minimal production-ready design

If you want the simplest robust version, I’d build this:

## Inputs
- directory of `.md` and `.json`

## Preprocessing
- markdown heading split
- json schema/path extraction
- embeddings per chunk
- manifest

## Runtime tools
- list/search/read for markdown
- schema/get/filter for json
- `llm_query()` for semantic interpretation

## Agent policy
- search → inspect structure → narrow → batch summarize → aggregate

## Outputs
- final answer
- optional memory summary artifact written back to disk

---

# 14. Best practical use cases

This pattern is especially strong for:

- coding agents reading README + config + tool state
- research agents reading notes + results JSON
- ops agents reading incident docs + event logs
- product agents reading specs + task histories
- autonomous workflows that need memory across many prior runs

---

# Final takeaway

For long `.md` and `.json` files, the paper’s most useful lesson for agent memory is:

> **Memory should be external, inspectable, structured, and selectively queried—not blindly stuffed into the context window.** ([arxiv.org](https://arxiv.org/abs/2512.24601))

So the implementation recipe is:

1. store raw memory in files  
2. derive structural indexes  
3. expose memory tools in a persistent environment  
4. let the root LM inspect structure first  
5. use code for filtering/aggregation  
6. use sub-LMs only for semantic interpretation  
7. build the final answer from buffers

If you want, I can now turn this into a **full Python implementation** for:
- **Markdown + JSON memory loader**
- **REPL-style memory environment**
- **sub-LLM querying scaffold**
- **agent loop**