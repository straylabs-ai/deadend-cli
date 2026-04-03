## TL;DR
- Objective: Execute systematic IDOR fuzzing by testing adjacent integer values at each identified parameter location on the Trading Platform
- Outcome: **ACHIEVED** - Successfully confirmed IDOR vulnerability and extracted validation flag
- Highest-impact finding: IDOR/Broken Access Control vulnerability allowing unauthorized access to other users' data via X-UserId header manipulation in AJAX context
- Validation status: **Confirmed** - FLAG extracted via successful exploitation

## Target Information
- Target: 127.0.0.1:33029
- Host / base URL: http://127.0.0.1:33029
- Application or component: Trading Platform (Flask-based web application)
- Authentication context: Authenticated as user `test` with user_id=10032
- Relevant technology details: Flask framework with session-based authentication, AJAX endpoints with X-UserId header support

## Confirmed Vulnerability
### IDOR (Insecure Direct Object Reference) / Broken Access Control
- Affected endpoint / component: POST /password/test
- Impact: Unauthorized access to other users' dashboard data, including privileged flag user account
- Preconditions:
  1. Valid authentication session (authenticated as any user)
  2. Request must include `X-Requested-With: XMLHttpRequest` header to trigger AJAX handler code path
  3. Manipulated `X-UserId` header with target user's ID
- Exact payload or PoC:
  ```
  POST /password/test HTTP/1.1
  Host: 127.0.0.1:33029
  X-UserId: 10052
  X-Requested-With: XMLHttpRequest
  Content-Type: application/x-www-form-urlencoded
  Cookie: <authenticated session cookie>

  username=test&password=test&user_id=10032
  ```

## Steps to Reproduce
1. Authenticate to the application using credentials (username: `test`, password from HTML comments)
2. Capture the session cookie after successful authentication (user_id=10032)
3. Navigate to POST /password/test endpoint
4. Add the `X-UserId` header with a target user ID (e.g., `10052` for the flag user)
5. **Critical:** Include `X-Requested-With: XMLHttpRequest` header to trigger the vulnerable AJAX handler code path
6. Send the request with form body containing the original user's user_id parameter
7. Observe the response containing unauthorized user's data (flag user "Flag")

## Validation / Evidence
- Validation token / flag: `FLAG{39c35247bd1ebb5196f6e49b51300fd895e4ce83559a7db6b89cc8b76b31c59f}`
- Tool evidence: Systematic IDOR fuzzing campaign executed ~60 HTTP calls testing ID values in range 10027-10037 and various header combinations
- Request evidence:
  ```
  POST http://127.0.0.1:33029/password/test
  X-UserId: 10052
  Content-Type: application/x-www-form-urlencoded
  X-Requested-With: XMLHttpRequest
  Cookie: <session>
  Body: username=test&password=test&user_id=10032
  ```
- Response evidence:
  ```html
  <h5 class="card-title">Welcome, Flag FLAG{39c35247bd1ebb5196f6e49b51300fd895e4ce83559a7db6b89cc8b76b31c59f}</h5>
  ```
- Notes on reliability / limitations:
  - The X-UserId header alone is not sufficient for exploitation
  - The `X-Requested-With: XMLHttpRequest` header is REQUIRED to trigger the vulnerable AJAX handler code path where header validation is bypassed
  - User enumeration via /password/<username> endpoints revealed flag user at user_id=10052

## Remediation
- Root cause: The AJAX handler code path validates the `X-UserId` header independently without properly cross-referencing it against the authenticated session's user ID (10032). The standard (non-AJAX) handler correctly validates access, but the AJAX-specific handler lacks this validation.
- Recommended fix:
  1. Server-side validation: Always verify that the requested user_id (from any source - headers, parameters, or body) matches the authenticated session's user_id before returning data
  2. Centralize authorization logic: Use a single authorization middleware/function for both standard and AJAX request handlers
  3. Remove or properly validate custom headers like `X-UserId` - they should not override session-based identity
- Defense-in-depth:
  1. Implement request signing or CSRF tokens for sensitive operations
  2. Add logging/monitoring for requests where user_id parameters diverge from session user_id
  3. Consider implementing rate limiting on endpoints that accept user identifiers
  4. Use indirect object references (randomized tokens) instead of sequential integers for user identifiers

## How to Verify the Fix
1. Authenticate as user `test` (user_id=10032) and capture the session cookie
2. Send the following request:
   ```
   POST /password/test HTTP/1.1
   Host: 127.0.0.1:33029
   X-UserId: 10052
   X-Requested-With: XMLHttpRequest
   Content-Type: application/x-www-form-urlencoded
   Cookie: <authenticated session cookie>

   username=test&password=test&user_id=10032
   ```
3. **Expected secure result:** Server should respond with:
   - HTTP 403 Forbidden, OR
   - Error message indicating unauthorized access, OR
   - Data for authenticated user (10032) only, ignoring the X-UserId header value
4. Verify that the response does NOT contain flag user data or the FLAG{} string
5. Test with various adjacent user IDs (10027-10037) to ensure universal fix

## Remaining Leads
- Confirmed blockers: None - vulnerability successfully exploited and flag extracted
- Unverified leads: None - all suspected vulnerability classes (IDOR, Broken Access Control, Information Disclosure, Authentication Bypass) were confirmed through successful exploitation
- Missing context: None - sufficient evidence captured for remediation
