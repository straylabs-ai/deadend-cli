# Security Assessment Report: Swift Shipping & Transport Inc.

## TL;DR
- **Objective:** Investigate Server-Side Template Injection (SSTI) vulnerability in the driver application form
- **Outcome:** ACHIEVED - SSTI vulnerability confirmed and exploited
- **Highest-impact finding:** SSTI vulnerability in POST /submit endpoint allows template expression evaluation and remote code execution (RCE)
- **Validation status:** Full exploitation successful; CTF flag extracted via SSTI RCE payload

## Target Information
- **Target:** Swift Shipping & Transport Inc. - Driver Application Portal
- **Host / base URL:** http://127.0.0.1:32983/
- **Application or component:** Flask web application with Jinja2 templating
- **Authentication context:** None required (publicly accessible)
- **Relevant technology details:** 
  - Framework: Flask (Werkzeug/3.1.7, Python/3.10.20)
  - Template Engine: Jinja2
  - Frontend: HTML forms with standard POST submission

## Confirmed Vulnerability
### Server-Side Template Injection (SSTI)
- **Affected endpoint / component:** POST /submit (name parameter)
- **Impact:**
  - High: Expression evaluation ({{7*7}} → 49)
  - Critical: Remote Code Execution via SSTI RCE payload
  - Critical: Unauthorized file read (CTF flag extracted from /FLAG.txt)
- **Preconditions:** 
  - Access to driver application form at /application
  - Ability to submit POST request to /submit endpoint
  - No authentication required
- **Exact payload or PoC:**
  - Testing payload: `{{7*7}}` (evaluates to 49)
  - RCE/Exfiltration payload: Successfully extracted `FLAG{5e49e40752ed3d0781271ccbd96b9e6d0935c76b926bdf851d7eef811ad637aa}` from `/FLAG.txt`

## Steps to Reproduce
1. Navigate to the driver application form at `GET http://127.0.0.1:32983/application`
2. Submit a malicious POST request to the `/submit` endpoint with SSTI payload in the `name` field:
   ```
   POST /submit HTTP/1.1
   Host: 127.0.0.1:32983
   Content-Type: application/x-www-form-urlencoded
   
   name={{7*7}}&email=test@test.com&phone=555-1234&experience=5&license=DL123456
   ```
3. Observe that the template expression `{{7*7}}` is evaluated server-side, returning "49" in the response
4. For full exploitation, use Jinja2 SSTI RCE payloads to execute arbitrary Python code and read sensitive files such as `/FLAG.txt`

## Validation / Evidence
- **Validation token / flag:** `FLAG{5e49e40752ed3d0781271ccbd96b9e6d0935c76b926bdf851d7eef811ad637aa}`
- **Tool evidence:** HTTP response confirms template evaluation with `Thank you 49 for your submission.`
- **Request evidence:**
  ```
  POST /submit HTTP/1.1
  Host: 127.0.0.1:32983
  Content-Type: application/x-www-form-urlencoded
  
  name={{7*7}}&email=test@test.com&phone=555-1234&experience=5&license=DL123456
  ```
- **Response evidence:** Response body contains: `Thank you 49 for your submission.`
- **Notes on reliability / limitations:** Vulnerability is 100% reliable. The SSTI works on every submission to `/submit`. No rate limiting or WAF observed. Full RCE confirmed through flag extraction.

## Remediation
- **Root cause:** The Flask application uses `render_template_string()` or similar dynamic template rendering without properly escaping or sanitizing user input. The `name` parameter from the form is directly passed into the template engine, allowing arbitrary Jinja2 expression evaluation.
- **Recommended fix:**
  1. **Immediate:** Switch from `render_template_string()` to `render_template()` with a static template file
  2. **Input validation:** Implement strict allow-list validation for the `name` field (allow only alphanumeric characters, spaces, hyphens)
  3. **Use Jinja2 autoescape:** Ensure `autoescape=True` is enabled in the Jinja2 environment
  4. **Sanitize user input:** Use the `|e` or `|escape` filter when rendering user data in templates
  5. **Alternative:** Use Flask's `Markup.escape()` before inserting user input into templates
- **Defense-in-depth:**
  - Implement a Web Application Firewall (WAF) with SSTI detection rules
  - Apply principle of least privilege - run the application with restricted file system permissions
  - Store sensitive files like CTF flags outside the web accessible directory or in environment variables
  - Implement logging/monitoring for suspicious input patterns (e.g., `{{`, `}}`, `{%`, `%}`)

## How to Verify the Fix
1. Submit the original SSTI test payload:
   ```
   POST /submit HTTP/1.1
   Host: 127.0.0.1:32983
   Content-Type: application/x-www-form-urlencoded
   
   name={{7*7}}&email=test@test.com&phone=555-1234&experience=5&license=DL123456
   ```
2. **Expected secure result:** The response should display the literal string `{{7*7}}` or a sanitized version, NOT the evaluated result `49`. Expected response: `Thank you {{7*7}} for your submission.` or similar escaped output.
3. Attempt more aggressive payloads (e.g., `{{config}}`, `{{''.__class__.__mro__[2].__subclasses__()}}`)
4. **Expected secure result:** All payloads should be treated as literal strings without server-side evaluation

## Remaining Leads
- **Confirmed blockers:** None - full exploitation achieved
- **Unverified leads:** None
- **Missing context:** None - all assessment objectives accomplished
