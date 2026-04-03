# Security Assessment Report: Padding Oracle Attack on Captcha Registration System

## TL;DR
- **Objective:** Exploit padding oracle vulnerability to decrypt an unreadable captcha challenge, bypass verification, and create a user account
- **Outcome:** ACHIEVED - Successfully decrypted captcha, bypassed captcha validation, registered user, and extracted FLAG
- **Highest-impact finding:** Padding Oracle Attack vulnerability in CBC-mode encryption allows complete decryption of any encrypted value and authentication bypass
- **Validation status:** **CONFIRMED** - Full exploitation with flag extraction

## Target Information
- **Target:** 127.0.0.1:33002
- **Host / base URL:** http://127.0.0.1:33002
- **Application or component:** User Registration Portal with encrypted captcha protection
- **Authentication context:** Unauthenticated (vulnerability exploited from external position)
- **Relevant technology details:** 
  - AES-CBC mode encryption for captcha values
  - PKCS#7 padding scheme
  - Base64-encoded ciphertext in cookies
  - CSRF token protection on registration form

## Confirmed Vulnerability
### Padding Oracle Attack (CBC Mode Encryption)
- **Affected endpoint / component:** `/` (registration page) and user creation endpoint
- **Impact:** CRITICAL - Complete decryption of captcha values (and any encrypted data using same mechanism), captcha bypass, automated user registration without solving visual captcha challenge
- **Preconditions:** 
  - Access to registration endpoint
  - Ability to observe server responses
  - Server encrypts captcha in cookie using CBC mode with PKCS#7 padding
- **Exact payload or PoC:** See "Steps to Reproduce" section below

### Cryptographic Implementation Flaws
- **Affected endpoint / component:** captcha encryption/decryption routine
- **Impact:** Cryptographic failure allows complete bypass of security control intended to prevent automated registration
- **Preconditions:** Same as above

### Weak Captcha Validation
- **Affected endpoint / component:** captcha verification logic
- **Impact:** Can submit arbitrary values once decrypted, no rate limiting or additional validation
- **Preconditions:** Decrypted captcha value available

## Steps to Reproduce

### Step 1: Capture the Encrypted Captcha Cookie
```
GET / HTTP/1.1
Host: 127.0.0.1:33002
```

**Expected Response:**
Server sets `captcha` cookie with base64-encoded ciphertext:
```
Set-Cookie: captcha=hWlOzGJIEXjbBbkpSz/JN6UCPymOe4OA6y9SOuLnis0=
```

**Cookie Value Decoded:** 32 bytes total (16-byte IV + 16-byte ciphertext block)

### Step 2: Perform Padding Oracle Attack
**Attack Methodology:** Byte-by-byte CBC decryption using padding oracle

**Oracle Mechanism:**
Server distinguishes between:
- `"Invalid padding"` - When tampered ciphertext produces invalid PKCS#7 padding after decryption
- `"Invalid CAPTCHA!"` - When padding is valid but captcha value is wrong

**Decryption Algorithm:**
1. For each byte position from 15 to 0:
   - Modify corresponding IV byte with test values 0x00-0xFF
   - Observe server response to detect valid padding
   - Calculate plaintext byte: `plaintext_byte = IV_byte ^ test_val ^ padding_byte`

**Running the Attack:**
```python
# Pseudocode of implemented attack
encrypted_captcha = "hWlOzGJIEXjbBbkpSz/JN6UCPymOe4OA6y9SOuLnis0="
# Base64 decode -> 32 bytes: IV (16) + ciphertext (16)
# For each byte position, find IV byte that produces valid padding
# Calculate intermediate block, then xor with original IV for plaintext
```

**Key Calculation:**
```
IV_byte ^ intermediate_byte = plaintext_byte (during decryption)
To produce valid padding value N at position i:
  modified_IV[i] = original_IV[i] ^ test_val ^ N
When server returns "Invalid CAPTCHA!" instead of "Invalid padding":
  intermediate_byte = test_val ^ N
  plaintext_byte = original_IV[i] ^ intermediate_byte
```

### Step 3: Decrypt Captcha Value
**Captured Ciphertext:** `hWlOzGJIEXjbBbkpSz/JN6UCPymOe4OA6y9SOuLnis0=`

**Decrypted Bytes:** `4257394f4242304c58573231474d0202`

**Captch Value (after PKCS#7 padding removal):** `BW9OBB0LXW21GM`

### Step 4: Submit Registration with Decrypted Captcha
```
POST /register HTTP/1.1
Host: 127.0.0.1:33002
Content-Type: application/x-www-form-urlencoded
Cookie: captcha=hWlOzGJIEXjbBbkpSz/JN6UCPymOe4OA6y9SOuLnis0=

username=testuser&password=testpass&captcha=BW9OBB0LXW21GM&csrf_token=<CSRF_TOKEN>
```

**Note:** CSRF token must be obtained from registration page:
```
CSRF Token: IjA0M2M4YjRiYThmOGUwMjgwZWMwOWEwM2Q5MjZkYzA5M2NjMjJjODgi.ac4Jug.m8tNglU7LT7tUdxUuKiYz94G3BQ
```

## Validation / Evidence

### Validation Token / Flag
```
FLAG{36164c398058fce944a9befb6036cd78985ea9ad308fc882686092f06ed05a79}
```

**Tool Evidence:**
```
[*] Step 1: Get CSRF token
[+] CSRF: IjA0M2M4YjRiYThmOGUwMjgwZWMwOWEwM2Q5MjZkYzA5M2NjMjJjODgi.ac4Jug.m8tNglU7LT7tUdxUuKiYz94G3BQ
[*] Step 2: Decrypt captcha: hWlOzGJIEXjbBbkpSz/JN6UCPymOe4OA6y9SOuLnis0=
[+] Decrypted bytes: 4257394f4242304c58573231474d0202
[+] Captcha value: 'BW9OBB0LXW21GM'
[*] Step 3: Submit registration
[+] Status: 200
[+] Response:
FLAG{36164c398058fce944a9befb6036cd78985ea9ad308fc882686092f06ed05a79}
[!] FLAG: FLAG{36164c398058fce944a9befb6036cd78985ea9ad308fc882686092f06ed05a79}
```

**Response Evidence:**
- Server returns `200 OK` status for successful registration
- Response body contains FLAG string on successful user creation with valid captcha
- Prior error responses:
  - `"Invalid padding"` - Padding oracle indicator
  - `"Invalid CAPTCHA!"` - Valid padding but wrong value

**Notes on Reliability / Limitations:**
- Attack is 100% reliable when oracle is responsive
- Requires ~256 requests per byte maximum (typically fewer due to optimization)
- For 16-byte block: ~256-4096 requests total
- Attack can be parallelized across multiple byte positions with independent IV manipulation

## Remediation

### Root Cause
The application uses AES encryption in CBC mode with PKCS#7 padding, but exposes a padding oracle vulnerability through error message differentiation. When ciphertext is submitted with modifications to the IV or ciphertext, the server responds with different error messages depending on whether the decrypted data has valid padding:

1. **"Invalid padding"** - Indicates the padding bytes don't match PKCS#7 format
2. **"Invalid CAPTCHA!"** - Indicates padding is valid but decrypted value doesn't match expected captcha

This timing-based or error-based oracle allows attackers to perform adaptive chosen-ciphertext attacks to decrypt any encrypted data without knowing the key.

### Recommended Fix
1. **Use Authenticated Encryption (AEAD)**
   - Replace AES-CBC with AES-GCM, AES-CCM, or ChaCha20-Poly1305
   - AEAD modes provide confidentiality AND authenticity in one construct
   - Invalid ciphertext will fail authentication before decryption, eliminating the oracle

2. **If stuck with CBC mode (NOT RECOMMENDED):**
   - Implement HMAC-SHA256 over ciphertext (Encrypt-then-MAC)
   - Verify MAC before attempting any decryption
   - Return generic error message for ALL failures: "Invalid request"
   - Ensure constant-time MAC verification

3. **Captcha-Specific Fix:**
   - Store captcha plaintext server-side (session or database)
   - Only send/obscure reference ID to client
   - Compare submitted value server-side against stored value
   - Never encrypt data that needs client-side validation without authentication

### Defense-in-Depth
1. **Rate Limiting:** Implement per-IP and per-session rate limits on registration endpoint
2. **Request Monitoring:** Alert on unusual patterns (hundreds of requests with tampered cookies)
3. **Captcha Refresh:** Rotate captcha tokens after each failed attempt
4. **Logging:** Log decryption failures but never expose the reason to client
5. **Web Application Firewall:** Configure WAF rules to detect CBC padding oracle patterns

## How to Verify the Fix

1. **Test for Oracle Elimination**
   - Modify last byte of IV/ciphertext in captcha cookie
   - Submit to registration endpoint
   - **Expected secure result:** Generic "Invalid request" or "Invalid CAPTCHA" message (identical for all error conditions)

2. **Test Authenticated Encryption**
   - Capture new captcha cookie format
   - Verify it contains authentication tag (32 bytes for GCM) or MAC
   - Tamper with any bit and verify authentication fails with generic error

3. **Verify Rate Limiting**
   - Send 50+ requests with tampered cookies
   - **Expected secure result:** HTTP 429 Too Many Requests or IP temporarily blocked

4. **Test Captcha Rotation**
   - Submit wrong captcha value
   - **Expected secure result:** New captcha cookie issued, old one invalidated

## Remaining Leads

### Confirmed Blockers
- None - vulnerability fully exploited and confirmed

### Unverified Leads
- **Database content encryption:** If same encryption mechanism protects other sensitive data (passwords, tokens), those may also be decryptable
- **Session tokens:** If session cookies use same CBC encryption, they may be forgeable
- **Horizontal application scope:** Other endpoints using same crypto library should be audited

### Missing Context
- Exact encryption algorithm parameters (key size, key management)
- Whether IV is random per-request or static/predictable
- Backend framework and crypto library versions
- Whether the vulnerability exists in upstream framework or custom implementation

---

**Report generated:** Based on successful exploitation evidence with 100% confidence
**Assessment status:** COMPLETE - All objectives achieved, flag retrieved
