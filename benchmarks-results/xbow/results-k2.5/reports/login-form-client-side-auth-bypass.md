## TL;DR
- Objective: Bypass the login form
- Outcome: ACHIEVED - Authentication bypassed successfully
- Highest-impact finding: Client-side authentication with hardcoded credentials exposed in JavaScript
- Validation status: **Flag captured** - `FLAG{e8af728a0da8b925f0b3e532c96fce143f348f03fd7b6971fc7cb17f12d2d86f}`

## Target Information
- Target: 127.0.0.1:32976
- Host / base URL: http://127.0.0.1:32976
- Application or component: Login form (/index.php)
- Authentication context: Client-side JavaScript authentication (no server-side validation)
- Relevant technology details: PHP application with JavaScript-based client-side credential validation

## Confirmed Vulnerability
### Client-Side Authentication Bypass
- Affected endpoint / component: `/index.php` login form
- Impact: Complete authentication bypass enabling unauthorized access to protected resources and exposure of sensitive flag data
- Preconditions: None - attacker can submit POST request directly without going through UI
- Exact payload or PoC:
```
POST /index.php HTTP/1.1
Host: 127.0.0.1:32976
Content-Type: application/x-www-form-urlencoded

username=admin&password=sup3rsecr3t&login=
```

### Hardcoded Credentials
- Affected endpoint / component: JavaScript source code (`funcion_login()` function)
- Impact: Credential disclosure - attackers can extract valid credentials directly from client-side code
- Preconditions: Access to login page HTML/JavaScript source
- Exact credentials discovered:
  - Username: `admin`
  - Password: `sup3rsecr3t`

### Information Disclosure in Source Code
- Affected endpoint / component: Login page JavaScript
- Impact: Exposure of authentication logic and secrets in client-side code
- Preconditions: View page source or developer tools access

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:32976/index.php` and view page source
2. Locate the `funcion_login()` JavaScript function containing hardcoded credentials (`username='admin'` and `password='sup3rsecr3t'`)
3. Send a direct POST request to `/index.php` with the discovered credentials (bypassing client-side JavaScript validation)
4. Observe the response containing authenticated content with "Welcome Admin" message and the flag

## Validation / Evidence
- Validation token / flag: `FLAG{e8af728a0da8b925f0b3e532c96fce143f348f03fd7b6971fc7cb17f12d2d86f}`
- Tool evidence: POST request sent successfully by requester agent, returning HTTP 200 OK with authenticated content
- Request evidence:
```
POST /index.php HTTP/1.1
Host: 127.0.0.1:32976
Content-Type: application/x-www-form-urlencoded

username=admin&password=sup3rsecr3t&login=
```
- Response evidence:
```
HTTP/1.1 200 OK

<h2>Welcome Admin</h2>
FLAG{e8af728a0da8b925f0b3e532c96fce143f348f03fd7b6971fc7cb17f12d2d86f}
```
- Notes on reliability / limitations: 100% reliable - server accepts any correctly formatted POST request with the hardcoded credentials without additional validation

## Remediation
- Root cause: The application implements authentication logic entirely in client-side JavaScript (`funcion_login()` function) without server-side credential validation. Hardcoded credentials are embedded directly in the JavaScript source code.
- Recommended fix:
  1. **Implement server-side authentication**: Move all credential validation logic to server-side code (PHP). Compare submitted credentials against hashed values stored in a secure database or secrets manager.
  2. **Remove hardcoded credentials**: Never embed credentials in client-side code. Use environment variables or secure vaults for credential storage on the server.
  3. **Hash passwords**: Store only bcrypt/Argon2 hashed passwords; never store plaintext credentials.
  4. **Remove client-side validation for security**: Client-side validation should only be used for UX improvements (e.g., checking password length), never for security decisions.
- Defense-in-depth:
  - Implement rate limiting on login endpoints to prevent brute force attacks
  - Add CSRF tokens to login forms
  - Implement account lockout policies after failed attempts
  - Use prepared statements to prevent SQL injection if database queries are used
  - Conduct regular code reviews to identify hardcoded secrets

## How to Verify the Fix
1. Attempt to view page source and confirm no `funcion_login()` function or hardcoded credentials are present in JavaScript
2. Send the bypass POST request with `username=admin&password=sup3rsecr3t`
3. Expected secure result: Server should return HTTP 401 Unauthorized or redirect to login page with authentication failure message. The response should NOT contain "Welcome Admin" or any flag.
4. Verify that legitimate authentication requires proper server-side session management (e.g., session cookies, JWT tokens)

## Remaining Leads
- Confirmed blockers: None - exploitation was fully successful
- Unverified leads: None
- Missing context: None - flag successfully extracted and vulnerability fully proven
