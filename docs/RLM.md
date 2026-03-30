# Step-by-step implementation guide from **Recursive Language Models**

## Resource List
- **Recursive Language Models** — Alex L. Zhang, Tim Kraska, Omar Khattab, **2026** (arXiv v2, revised January 28, 2026), **arXiv:2512.24601**. ([arxiv.org](https://arxiv.org/abs/2512.24601))

---

## Title: Recursive Language Models

**Citation:** Zhang, Kraska, Khattab, 2026, arXiv:2512.24601 (v2). ([arxiv.org](https://arxiv.org/abs/2512.24601))

**Summary:**  
The paper proposes a long-context inference scaffold called a **Recursive Language Model (RLM)**. Instead of feeding the full long prompt into the model, the prompt is stored in an external environment, and the LM interacts with it through a persistent Python REPL. The LM can inspect the context, transform it with code, and call a sub-LM on selected chunks. This lets the system handle inputs far beyond the base model’s context window while preserving more fine-grained access than summarization-based methods. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### Research Question / Problem
The paper asks how to let LLMs process **arbitrarily long prompts** without relying only on larger context windows or lossy summarization. The authors argue that long-context failure depends not just on input length but also on task complexity, and that many tasks need dense access to the prompt rather than a compressed summary. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### Method & Reasoning
The core design is simple:

1. Treat the long prompt as part of the **external environment**, not as direct LM input. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
2. Start a **persistent Python REPL** with a `context` variable containing the prompt and a helper like `llm_query(...)` for sub-LM calls. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
3. Let the root LM iteratively emit REPL code, inspect outputs, maintain variables/buffers, and eventually return an answer using `FINAL(...)` or `FINAL_VAR(...)`. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
4. Use sub-LM calls when semantic interpretation is needed on chunks that are still too large or too dense for the root LM to reason about directly. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

The paper’s reason for this architecture is that code execution gives the LM a symbolic way to search, filter, partition, and aggregate over huge inputs, while recursive LM calls let it delegate hard semantic work on manageable subproblems. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### Findings & Chain of Evidence
Empirically, the RLM scaffold outperformed direct model calls and several long-context baselines across CodeQA, BrowseComp+, OOLONG, and OOLONG-Pairs. On the GPT-5 setup, the RLM beat the base model on all four listed benchmarks and handled BrowseComp+ inputs in the 6M–11M token range that the base model could not fit directly. The paper also shows that the REPL alone already helps with long inputs, while recursive sub-calls are especially important for **information-dense** tasks like OOLONG and OOLONG-Pairs. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

The qualitative trajectory analysis supports the implementation choices: successful runs often use regex or lightweight probing first, then chunking, then sub-LM calls over selected pieces, then programmatic aggregation into buffers or final variables. The paper also shows failure cases where models over-verify, make too many sub-calls, or fail to return a prepared variable cleanly. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### Strengths & Limitations
**Strengths**
- Handles contexts far beyond the base context window. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Preserves fine-grained access to source material better than iterative summarization. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Supports long outputs by building them in variables and returning `FINAL_VAR(...)`. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Works as an inference scaffold without retraining the base model. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

**Limitations**
- The paper’s implementation uses **blocking/sequential** sub-calls, which hurts runtime. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Final-answer detection via `FINAL(...)` / `FINAL_VAR(...)` is brittle. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Models with weak coding ability or insufficient output budget perform poorly as RLMs. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- The paper only uses **max recursion depth 1** in experiments, so “recursive” here is operationally shallow in the reported system. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

---

## Integration Guidelines

If you want to implement the paper faithfully, the safest interpretation is:

- Build an **agent scaffold**, not a new neural architecture. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Use a **persistent Python execution environment** as the working memory. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Expose at minimum:
  - `context`
  - `print()`
  - `llm_query(prompt)` for sub-LM inference. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
- Prompt the root LM to:
  - inspect context first,
  - choose a chunking/filtering strategy,
  - batch work into sub-calls,
  - store intermediate results in variables,
  - return only when ready with `FINAL(...)` or `FINAL_VAR(...)`. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

The paper also suggests two practical heuristics:
1. For sparse-retrieval-style tasks, start with **regex/keyword probing** and only sub-call on likely relevant snippets. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))
2. For information-dense tasks, do **systematic chunking plus sub-LM semantic labeling**, then aggregate programmatically. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

---

# Step-by-step implementation blueprint

## 1. Define the external interface
Your RLM should look like a normal function:

```python
answer = rlm(query: str, context: Any) -> str
```

The paper says the RLM should preserve the same external abstraction as an LM: accept a prompt/context and return a string answer, while internally offloading the context into the environment. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 2. Load the context into a persistent REPL
Create a sandboxed Python session with persistent variables:

```python
state = {
    "context": context,
}
```

Also compute metadata the paper includes in the system prompt:
- `context_type`
- `context_total_length`
- `context_lengths` for chunks/documents/sections. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

A practical implementation:

```python
def describe_context(context):
    if isinstance(context, str):
        return {
            "context_type": "string",
            "context_total_length": len(context),
            "context_lengths": [len(context)],
        }
    elif isinstance(context, list):
        return {
            "context_type": "List[str]",
            "context_total_length": sum(len(x) for x in context),
            "context_lengths": [len(x) for x in context],
        }
    elif isinstance(context, dict):
        # adapt as needed
        text = str(context)
        return {
            "context_type": "dict",
            "context_total_length": len(text),
            "context_lengths": [len(text)],
        }
```

This mirrors the prompt fields shown in Appendix D. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 3. Expose the REPL tools
The minimum environment from the paper is:

- `context`
- `llm_query(...)`
- `print(...)` with visible truncated output. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

A minimal helper layer:

```python
class RLMEnv:
    def __init__(self, context, sub_llm, max_print_chars=4000):
        self.globals = {"context": context}
        self.sub_llm = sub_llm
        self.max_print_chars = max_print_chars

    def llm_query(self, prompt: str) -> str:
        return self.sub_llm(prompt)

    def run(self, code: str) -> str:
        import io, contextlib
        buf = io.StringIO()
        self.globals["llm_query"] = self.llm_query
        with contextlib.redirect_stdout(buf):
            exec(code, self.globals, self.globals)
        out = buf.getvalue()
        return out[:self.max_print_chars]
```

The truncation behavior is important because the paper explicitly tells the model that REPL outputs are truncated and that variables should be used as buffers for larger intermediate state. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 4. Use the paper’s root system prompt
The most implementation-critical part of the paper is the RLM system prompt. At minimum, keep these behaviors:

- The LM is told it can analyze context in a REPL.
- It is told `context` contains key information.
- It is told `llm_query` can query a sub-LM with about **500K characters** of context.
- It is told to inspect the context, choose chunking, use buffers, and finish with `FINAL(...)` or `FINAL_VAR(...)`. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

A faithful condensed version:

```text
You are tasked with answering a query with associated context.
You can access, transform, and analyze this context interactively in a REPL environment
that can recursively query sub-LLMs. You will be queried iteratively until you provide
a final answer.

Your context is a {context_type} with {context_total_length} total characters,
and is broken up into chunks of char lengths: {context_lengths}.

The REPL environment is initialized with:
1. A `context` variable that contains extremely important information.
2. A `llm_query` function that allows you to query an LLM inside your REPL environment.
3. The ability to use `print()` statements to view REPL output.

You will only be able to see truncated outputs from the REPL environment.
Use variables as buffers to build up your final answer.

Make sure to explicitly look through the entire context in REPL before answering your query.
A good strategy is to inspect the context, choose a chunking strategy, query an LLM per chunk,
store answers in buffers, and aggregate them.

When you want to execute Python code, wrap it in ```repl ... ```.

When done, return either:
FINAL(your final answer here)
or
FINAL_VAR(variable_name)
```

That is a paraphrased implementation-oriented reduction of the Appendix D prompt. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 5. Build the iterative root loop
The root LM should operate in turns:

1. Send system prompt + user query.
2. Get assistant output.
3. If it emits `repl` code blocks, execute them in the persistent environment.
4. Return the execution output as the next user/tool message.
5. Repeat until `FINAL(...)` or `FINAL_VAR(...)` appears. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

Pseudo-logic:

```python
def run_rlm(root_llm, sub_llm, query, context, max_turns=30):
    meta = describe_context(context)
    env = RLMEnv(context, sub_llm)
    messages = [
        {"role": "system", "content": build_system_prompt(meta)},
        {"role": "user", "content": query},
    ]

    for _ in range(max_turns):
        assistant = root_llm(messages)
        text = assistant["content"]

        final = parse_final(text)
        if final is not None:
            return final.resolve(env.globals)

        code_blocks = extract_repl_blocks(text)
        if code_blocks:
            outputs = []
            for code in code_blocks:
                outputs.append(env.run(code))
            messages.append({"role": "assistant", "content": text})
            messages.append({"role": "user", "content": "\n\n".join(outputs)})
        else:
            messages.append({"role": "assistant", "content": text})
            messages.append({
                "role": "user",
                "content": "Continue reasoning in REPL, or return FINAL(...) / FINAL_VAR(...)."
            })

    raise RuntimeError("RLM did not terminate")
```

The explicit final tags are paper-faithful, but the authors also report that this termination method is brittle, so add parser safeguards and a max-turn budget. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 6. Implement `FINAL(...)` and `FINAL_VAR(...)`
The paper’s prompt requires two completion modes:

- `FINAL(answer text)`
- `FINAL_VAR(variable_name)` to return a variable built inside the REPL. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

This is especially useful for long outputs, where the root model should build the answer incrementally in Python lists/strings and then return the variable instead of regenerating it from scratch. That pattern is directly motivated by the OOLONG-Pairs behavior described in the paper. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## 7. Keep recursion shallow at first
For a faithful reproduction, make sub-calls plain LM calls rather than full nested RLM calls. The paper’s experiments used **max recursion depth 1**, meaning sub-calls were LMs, not deeper recursive environments. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

So:

```python
def llm_query(prompt):
    return sub_llm(prompt)   # no nested REPL by default
```

That is the simplest way to match the paper before experimenting with deeper recursion.

## 8. Choose root and sub models deliberately
The paper used stronger models with coding ability as root controllers and, in at least the GPT-5 setup, a cheaper smaller model for sub-calls: GPT-5 for the root and GPT-5-mini for recursive calls. It also reports that smaller models with weak coding ability struggled as RLMs. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

Implementation takeaway:
- **Root LM:** prioritize coding ability, tool use, long reasoning.
- **Sub LM:** prioritize cost-efficiency and sufficient context length.

## 9. Add batching constraints to `llm_query`
The Qwen-specific prompt tweak in the paper is operationally important: batch information aggressively and avoid many tiny sub-calls. The added guidance recommends aiming for roughly **200K characters per call** and warns against issuing one sub-call per line or item. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

So your helper should support bulk chunks:

```python
def batch_strings(items, target_chars=200_000):
    batch, batches, size = [], [], 0
    for item in items:
        if size + len(item) > target_chars and batch:
            batches.append(batch)
            batch, size = [], 0
        batch.append(item)
        size += len(item)
    if batch:
        batches.append(batch)
    return batches
```

## 10. Encode the paper’s common successful strategies as defaults
From the trajectory analysis, three patterns should be turned into implementation priors:

### A. Probe first, then narrow
Start with small inspections:
- print the first few lines,
- inspect structure,
- regex-search likely keywords,
- identify candidate chunks. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### B. Use sub-LM calls for semantic transforms
If the task requires label inference, meaning extraction, or question answering over chunks, send the chunk plus a focused question to `llm_query`. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

### C. Aggregate programmatically
Have the root LM use Python to:
- collect chunk answers,
- count labels,
- deduplicate entities/pairs,
- build final formatted output. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

---

# Recommended MVP implementation plan

## Phase 1: Minimal faithful reproduction
Implement:
- persistent Python REPL
- `context`
- `llm_query`
- iterative loop
- `FINAL` / `FINAL_VAR`
- output truncation
- max turns and max sub-call budget. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## Phase 2: Production hardening
Add:
- sandboxing for code execution,
- async sub-calls,
- per-query cost budget,
- retry/repair when code fails,
- anti-loop heuristics when repeated verification appears. The paper explicitly points to asynchronous sub-calls and sandboxed REPLs as promising improvements over its own implementation. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

## Phase 3: Routing logic
Because the paper notes that base LMs can outperform RLMs on smaller contexts, add a simple router:
- small/simple prompt → direct LM
- large or information-dense prompt → RLM. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

---

# Practical design choices the paper leaves underspecified

Based on the text available in the paper, these items are **not fully specified**, so you will need to choose them yourself:

- exact REPL sandbox implementation,
- exact stdout truncation length,
- exact parsing grammar for `FINAL(...)`,
- retry behavior for malformed code,
- message format between assistant turn and REPL feedback,
- whether sub-LM calls inherit any special system prompt. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

So if your goal is a working system, treat the paper as a **strong scaffold design**, not a drop-in full spec. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

---

# Cross-Resource Synthesis
For this paper, the main actionable insight is: **move long context out of the LM’s token stream and into an executable environment**. Then let the LM decide how to inspect, chunk, delegate, and aggregate. The paper’s experiments support three implementation priorities: use a persistent REPL, let the model call a sub-LM on selected chunks, and keep intermediate state in variables rather than repeatedly re-generating answers. The biggest engineering upgrades beyond the paper are likely async sub-calls, stronger loop control, and safer sandboxing. ([ar5iv.org](https://ar5iv.org/html/2512.24601v2))

If you want, I can next turn this into one of these:
1. a **Python skeleton implementation**,  
2. an **OpenAI API-based version**, or  
3. a **LangGraph / agent-framework version**.