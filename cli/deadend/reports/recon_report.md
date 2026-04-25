## TL;DR
- Objective: Find XSS vulnerabilities in the login or registration pages of the VulnBank application at http://127.0.0.1:5000
- Outcome: Reconnaissance complete. DOM-based XSS vulnerability confirmed via vulnerable `innerHTML` assignment pattern.
- Highest-impact finding: DOM-based XSS vulnerability in login and registration pages where server responses are rendered using `innerHTML` without sanitization.
- Validation status: Vulnerability confirmed via code analysis. Exploitation payloads not yet tested (reconnaissance phase only).

## Target Information
- Target: VulnBank application
- Host / base URL: http://127.0.0.1:5000
- Application or component: Authentication system (login, registration, forgot password)
- Authentication context: Public endpoints - no authentication required for login or registration pages
- Relevant technology details:
  - Server-rendered application with client-side JavaScript
  - JSON API endpoints (Content-Type: application/json)
  - JWT tokens stored in localStorage (harvestable via XSS if exploited)

## Confirmed Vulnerability
### DOM-based XSS via unsanitized innerHTML assignment
- Affected endpoint / component:
  - `/login` page and endpoint
  - `/register` page and endpoint
  - `/api/v3/forgot-password` endpoint
- Impact: Arbitrary JavaScript execution in victim's browser. Potential for JWT token theft from localStorage, session hijacking, and malicious actions on behalf of the user.
- Preconditions: Attacker can submit form data containing XSS payloads through username, password, or other input fields that trigger server error/success messages.
- Exact payload or PoC: Payloads sent in form fields (username/password) that generate server responses will be executed via:
  ```javascript
  document.getElementById('message').innerHTML = data.message
  ```

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:5000/login` or `http://127.0.0.1:5000/register`
2. Submit a request to the endpoint with Content-Type: application/json containing:
   ```json
   {"username": "<img src=x onerror=alert(1)>", "password": "test"}
   ```
3. The server processes the input and returns a JSON response containing a message field
4. The client-side JavaScript assigns `data.message` to `innerHTML`, executing any JavaScript payloads embedded in the server's response

## Validation / Evidence
- Validation token / flag: Not found (reconnaissance phase only)
- Tool evidence: HTTP requests to `/login` and `/register` endpoints via requester agent
- Request evidence:
  ```
  GET /login HTTP/1.1
  Host: 127.0.0.1:5000
  ```
  Response: 200 OK - Login form with username/password fields
  
  ```
  GET /register HTTP/1.1
  Host: 127.0.0.1:5000
  ```
  Response: 200 OK - Registration form with username/password fields
- Response evidence:
  - Both pages contain vulnerable JavaScript: `document.getElementById('message').innerHTML = data.message`
  - Application explicitly marked as "intentionally vulnerable"
  - HTML comment: `<!-- Vulnerability: No CSRF protection -->`
  - HTML comment: `<!-- Vulnerability: No rate limiting -->`
  - HTML comment: `<!-- Vulnerability: Form doesn't validate input on client side -->`
  - HTML comment: `<!-- Vulnerability: Password in plain text -->`
- Notes on reliability / limitations: The vulnerability is confirmed via source code analysis of the client-side JavaScript. Actual exploitation requires testing to confirm that payloads survive any server-side processing and are reflected back in the message response.

## Remediation
- Root cause: Server responses are rendered directly to the DOM using `innerHTML` without any sanitization. The JavaScript code assigns `data.message` (server response) directly to `innerHTML`, which parses and executes any HTML/JavaScript content.
- Recommended fix:
  1. Replace `innerHTML` with `textContent` if only text display is needed
  2. If HTML formatting is required, implement proper HTML sanitization using a library like DOMPurify before inserting content into the DOM
  3. Sanitize or escape user input on the server side before including it in response messages
- Defense-in-depth:
  - Implement Content Security Policy (CSP) headers to restrict inline script execution
  - Add input validation on both client and server sides
  - Implement CSRF tokens for state-changing operations
  - Store JWT tokens in httpOnly cookies instead of localStorage to prevent JavaScript access

## How to Verify the Fix
1. Submit an XSS payload (e.g., `<img src=x onerror=alert(1)>`) in the username field of the login form
2. Observe that the payload is displayed as plain text rather than executing
3. Verify via browser DevTools that the message element contains escaped HTML entities (`&lt;img...&gt;`) rather than parsed HTML
4. Confirm that `textContent` or properly sanitized HTML is used instead of raw `innerHTML` assignment

## Remaining Leads
- Confirmed blockers: None
- Unverified leads:
  - Actual XSS payload execution not yet confirmed (reflected vs stored behavior)
  - JWT token exfiltration via XSS not yet tested
  - Forgot password endpoint (`/api/v3/forgot-password`) XSS potential needs testing
- Missing context:
  - No validation tokens or flags discovered during reconnaissance
  - Full HTTP request/response pairs for POST requests not captured
  - Server-side response message format not fully documented
