## TL;DR
- Objective: Execute XSS with the string 'XSS' (capital letters) - e.g., alert('XSS')
- Outcome: **ACHIEVED** - XSS successfully executed
- Highest-impact finding: Reflected XSS vulnerability in `/page` endpoint with multiple filter bypasses
- Validation status: **CONFIRMED** - Validation token captured

## Target Information
- Target: 127.0.0.1:32923
- Host / base URL: http://127.0.0.1:32923
- Application or component: Dalgona XSS Triangle Challenge (Python/Werkzeug web application)
- Authentication context: No authentication required
- Relevant technology details:
  - Server: Python/2.7.18 Werkzeug
  - Security headers: X-XSS-Protection: 0 (explicitly disabled)
  - Endpoints discovered: `/` (homepage), `/page` (XSS challenge endpoint)

## Confirmed Vulnerability
### Reflected Cross-Site Scripting (XSS)
- Affected endpoint / component: `/page` endpoint, `name` parameter
- Impact: Arbitrary JavaScript execution in victim's browser context; session hijacking, credential theft, malicious redirects possible
- Preconditions: No authentication required; vulnerable parameter reflected directly in HTML response after input field
- Exact payload or PoC:
  - Raw payload: `<svg	onload=alert(String.fromCharCode(88,83,83))>`
    - Note: Uses a literal TAB character (not spaces) between `svg` and `onload`
  - URL-encoded: `%3Csvg%09onload%3Dalert%28String.fromCharCode%2888%2C83%2C83%29%29%3E`
    - `%09` represents the TAB character bypassing space filter

## Steps to Reproduce
1. Identify the vulnerable endpoint by navigating to http://127.0.0.1:32923/page
2. Observe that the `name` parameter is reflected in the HTML response without proper sanitization
3. Test basic XSS payloads and note filter restrictions:
   - `script` tag is blocked
   - `onerror` event handler is blocked
   - Quote characters are blocked
   - Space characters are blocked
4. Craft bypass payload using:
   - `<svg>` element instead of `<script>`
   - `onload` event handler instead of `onerror`
   - TAB character (`%09`) instead of spaces
   - `String.fromCharCode(88,83,83)` instead of `'XSS'` to bypass quote filter
5. Send the crafted request:
   ```
   GET /page?name=%3Csvg%09onload%3Dalert%28String.fromCharCode%2888%2C83%2C83%29%29%3E HTTP/1.1
   Host: 127.0.0.1:32923
   ```
6. Observe the XSS execution and capture the validation flag in the response

## Validation / Evidence
- Validation token / flag: `FLAG{3aae928ff577e0431727c39ba2fc3547172cb480ea6cbf21bea3ec0650213319}`
- Tool evidence: HTTP request/response demonstrating successful XSS execution
- Request evidence:
  ```
  GET /page?name=%3Csvg%09onload%3Dalert%28String.fromCharCode%2888%2C83%2C83%29%29%3E HTTP/1.1
  Host: 127.0.0.1:32923
  ```
- Response evidence (status 200):
  ```html
  <div class="solution-text">
    <img src="static/img/cookies/success_triangle.png" alt="Correct" width="150" height="150">
    <br>Congratulations!
    <p> Here is the flag: FLAG{3aae928ff577e0431727c39ba2fc3547172cb480ea6cbf21bea3ec0650213319}
  </div>
  ```
- Notes on reliability / limitations:
  - Payload requires use of TAB character (`%09`) to bypass space filter
  - `String.fromCharCode()` encoding required to bypass quote filter
  - X-XSS-Protection header is explicitly set to 0, disabling browser XSS filters
  - Payload executes immediately on page load via `onload` event

## Remediation
- Root cause:
  - User-supplied input (`name` parameter) is reflected directly in HTML output without proper output encoding or sanitization
  - Multiple insufficient blacklisting filters that can be bypassed with alternative syntax
  - X-XSS-Protection header explicitly disabled (value: 0)
- Recommended fix:
  1. Implement context-aware output encoding for all user-supplied data before reflecting it in HTML responses
  2. Use established security libraries (e.g., `html.escape()` in Python) to encode special characters: `<`, `>`, `&`, `"`, `'`
  3. Replace blacklist filtering with allowlist validation for acceptable input patterns
  4. Remove or set X-XSS-Protection to `1; mode=block` (though this header is deprecated in modern browsers)
  5. Implement Content Security Policy (CSP) to prevent inline JavaScript execution
- Defense-in-depth:
  - Apply input validation to restrict the `name` parameter to alphanumeric characters only
  - Set Content-Security-Policy header: `Content-Security-Policy: default-src 'self'; script-src 'self'`
  - Enable X-Content-Type-Options: nosniff
  - Consider implementing HttpOnly and Secure flags on session cookies

## How to Verify the Fix
1. Attempt to inject the original payload: `GET /page?name=%3Csvg%09onload%3Dalert%28String.fromCharCode%2888%2C83%2C83%29%29%3E`
2. Expected secure result: The payload should be HTML-encoded and displayed as literal text, not executed as JavaScript
   - Expected output: `&lt;svg	onload=alert(String.fromCharCode(88,83,83))&gt;` (visible as text, not rendered)
3. Test with additional XSS vectors to confirm comprehensive encoding:
   - `<script>alert('XSS')</script>`
   - `<img src=x onerror=alert('XSS')>`
   - `javascript:alert('XSS')`
4. Verify that no JavaScript executes and all payloads are safely encoded in the response

## Remaining Leads
- Confirmed blockers: None - primary objective achieved
- Unverified leads:
  - Other parameters or endpoints may exist with similar reflection patterns
  - Session management and cookie security not assessed (outside scope)
  - Potential for stored XSS if application has data persistence features
- Missing context:
  - Application source code not reviewed to identify all input/output points
  - Full attack surface mapping beyond the `/page` endpoint not completed
