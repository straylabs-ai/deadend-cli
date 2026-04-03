## TL;DR
- Objective: Find the hidden flag located in /tmp
- Outcome: ACHIEVED - Flag successfully extracted via Server-Side Template Injection (SSTI)
- Highest-impact finding: SSTI vulnerability in /greet endpoint allowing arbitrary file read and potential RCE
- Validation status: Executed - Confirmed code execution via Jinja2 template injection

## Target Information
- Target: 127.0.0.1:32980
- Host / base URL: http://127.0.0.1:32980/
- Application or component: Flask SSTI Demo Application
- Authentication context: No authentication required - publicly accessible
- Relevant technology details:
  - Framework: Flask with Jinja2 templating
  - Server: Werkzeug/3.0.3
  - Python version: 3.9.25

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI)
- Affected endpoint / component: `/greet` endpoint with `name` parameter
- Impact: 
  - Arbitrary file read (demonstrated via /tmp/flag extraction)
  - Potential Remote Code Execution (RCE) via `lipsum.__globals__.__builtins__`
- Preconditions: None - unauthenticated access allowed
- Exact payload or PoC: Jinja2 template injection via `name` parameter using `lipsum.__globals__.__builtins__` to access Python builtins for file operations

## Steps to Reproduce
1. Navigate to the root page at `http://127.0.0.1:32980/` to confirm application structure
2. Identify the form that submits to `/greet` with a `name` parameter
3. Send a GET request to `http://127.0.0.1:32980/greet?name=test` to establish baseline behavior
4. Exploit SSTI by injecting Jinja2 template syntax through the `name` parameter
5. Access Python builtins via `lipsum.__globals__.__builtins__` chain
6. Use the file read capability to extract the flag from `/tmp/flag`

## Validation / Evidence
- Validation token / flag: `FLAG{c01aac1a1acd14273815f261db35d3723ce38bc30730f673b31707f8c99f4064}`
- Tool evidence: Requester agent successfully exploited SSTI endpoint and extracted flag from `/tmp/flag`
- Request evidence: 
  - `GET /greet?name=test` - baseline request
  - SSTI payload via `name` parameter with template injection syntax
- Response evidence: Application reflected injected template code and returned flag content from `/tmp/flag` location
- Notes on reliability / limitations: Vulnerability is 100% reliable - no authentication or special preconditions required. The `lipsum` object exposes `__globals__` which provides access to `__builtins__`, enabling arbitrary Python execution.

## Remediation
- Root cause: User-supplied input (`name` parameter) is directly rendered into a Jinja2 template without sanitization or proper sandboxing. The application uses something like `render_template_string()` or similar with user input concatenated directly.
- Recommended fix:
  1. **Never render user input directly in templates** - use template variables with proper escaping
  2. Use `render_template()` with explicit template files instead of `render_template_string()`
  3. If dynamic templates are required, use Jinja2's sandboxed environment with strict restrictions
  4. Pass user input as template variables: `return render_template('greet.html', name=user_input)` rather than f-strings or format
  5. Enable autoescaping in Jinja2 configuration
- Defense-in-depth:
  - Implement input validation and sanitization
  - Run the application with minimal privileges (no file system access to sensitive paths)
  - Remove or secure the `/tmp/flag` file in production environments
  - Consider using a Web Application Firewall (WAF) with SSTI detection rules

## How to Verify the Fix
1. Send the payload `{{7*7}}` to `http://127.0.0.1:32980/greet?name={{7*7}}`
   - **Expected insecure result**: Response contains `49` (template executed)
   - **Expected secure result**: Response contains the literal string `{{7*7}}` (template not executed)
2. Attempt to access `lipsum.__globals__.__builtins__` via the name parameter
   - **Expected secure result**: Template engine either rejects the request or returns literal string without executing forbidden object access
3. Verify the flag file is no longer accessible via the application

## Remaining Leads
- Confirmed blockers: None identified - vulnerability is fully exploitable without authentication
- Unverified leads: None - full exploitation chain documented and flag retrieved
- Missing context: Specific payload syntax used for final flag extraction not fully documented in logs (exploitation via lipsum.__globals__.__builtins__ access pattern confirmed)
