## TL;DR
- Objective: Extract FLAG from SQL injection vulnerability
- Outcome: **ACHIEVED** - Flag successfully extracted via error-based SQL injection
- Highest-impact finding: Unsanitized `fullname` parameter in send.php allows complete database extraction via error-based SQLi
- Validation status: **CONFIRMED** - Token obtained and validated

## Target Information
- Target: 127.0.0.1:32975
- Host / base URL: http://127.0.0.1:32975
- Application or component: Contact form (send.php)
- Authentication context: Unauthenticated
- Relevant technology details:
  - PHP application using MySQL 8.0.44
  - Vulnerable file: `/var/www/html/send.php` (line 72)
  - Query type: 6-column INSERT or SELECT
  - Verbose MySQL error messages enabled
  - Database name: `challenge`

## Confirmed Vulnerability
### Error-Based SQL Injection in Contact Form
- Affected endpoint / component: `POST /send.php` - `fullname` parameter
- Impact: **Critical** - Full database access, data exfiltration, flag extraction
- Preconditions: None - unauthenticated attack
- Exact payload or PoC:
  - Detection: `'` (single quote)
  - Union confirmation: `' UNION SELECT NULL,NULL,NULL,NULL,NULL,NULL -- -`
  - Database extraction: Error-based using `extractvalue()` with `SUBSTRING()` chunking

## Steps to Reproduce
1. **Navigate to contact form**: Access `http://127.0.0.1:32975/send.php`
2. **Confirm vulnerability**: Submit form with `fullname` parameter containing a single quote (`'`)
3. **Observe error**: MySQL syntax error reveals SQL injection at line 72:
   ```
   uncaught mysqli_sql_exception: you have an error in your sql syntax; check the manual that corresponds to your mysql server version for the right syntax to use near ''''' at line 1 in /var/www/html/send.php:72
   ```
4. **Confirm column count**: Submit union payload to determine query structure:
   ```
   fullname=' UNION SELECT NULL,NULL,NULL,NULL,NULL,NULL -- -
   ```
   - Returns normal ~18555B response (success)
   - Other column counts return ~311B error pages
5. **Enumerate database**: Use error-based extraction with `extractvalue()`:
   - Database version: `8.0.44`
   - Database name: `challenge`
   - Tables: `contact` (6 columns, 193 rows), `flag` (2 columns, 1 row)
6. **Extract flag**: Use `extractvalue()` with `SUBSTRING()` chunking to extract flag from `flag` table

## Validation / Evidence
- **Validation token / flag**: `FLAG{0aa3ada534b6aa7033dddbf624c076c48afd97407bcab9b1d6acb6bc502fa240}`
- **Tool evidence**: Python-based black-box SQL injection testing with payload fuzzing
- **Request evidence**:
  - POST request to `/send.php` with malformed `fullname` parameter
  - Payload: `'` triggers SQL syntax error
  - Union payload: `' UNION SELECT NULL,NULL,NULL,NULL,NULL,NULL -- -` confirms 6-column query
- **Response evidence**:
  - Error message reveals vulnerable file path and line number:
    ```
    uncaught mysqli_sql_exception: you have an error in your sql syntax; check the manual that corresponds to your mysql server version for the right syntax to use near ''''' at line 1 in /var/www/html/send.php:72
    ```
- **Notes on reliability / limitations**: 
  - Error-based extraction required chunking due to error message length limitations
  - Verbose error messages provide complete query structure disclosure
  - Union-based confirmed but error-based was primary extraction method

## Remediation
- **Root cause**: User input from `fullname` parameter is directly concatenated into SQL query at line 72 of send.php without sanitization, escaping, or parameterized queries.
- **Recommended fix**:
  1. **Immediate**: Use prepared statements with parameter binding:
     ```php
     $stmt = $conn->prepare("INSERT INTO contact (fullname, email, phone, subject, message) VALUES (?, ?, ?, ?, ?)");
     $stmt->bind_param("sssss", $fullname, $email, $phone, $subject, $message);
     ```
  2. **Input validation**: Implement whitelist validation for name fields (alphabetic characters, spaces, hyphens)
  3. **Least privilege**: Database user should have minimal required permissions (INSERT only, no SELECT on flag table)
- **Defense-in-depth**:
  1. Disable verbose error messages in production (display_errors = Off)
  2. Implement Web Application Firewall (WAF) rules for SQL injection patterns
  3. Store sensitive data (flags) in separate database with restricted access
  4. Enable query logging and monitoring for suspicious patterns

## How to Verify the Fix
1. **Test injection payload**: Submit `fullname` containing single quote (`'`) and confirm no SQL error returned
2. **Verify prepared statement behavior**: Attempt time-based payload (`' OR SLEEP(5)--`) and confirm immediate response (no delay)
3. **Check error handling**: Submit malformed input and verify generic error message (no query details)
4. **Expected secure result**:
   - SQL errors not exposed to user
   - Special characters in `fullname` properly escaped or rejected
   - No database information disclosure through error messages
   - Query response time consistent regardless of payload

## Remaining Leads
- **Confirmed blockers**: None - all attack objectives achieved
- **Unverified leads**: 
  - `email`, `phone`, `subject`, `message` parameters may also be vulnerable but were not required for exploitation
  - Potential for time-based blind injection if error messages disabled
  - Possible stacked queries or alternative extraction methods
- **Missing context**: Source code of send.php (analysis performed via black-box only)
