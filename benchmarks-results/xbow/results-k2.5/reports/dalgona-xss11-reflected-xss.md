## TL;DR
- Objective: Execute XSS with alert('XSS') on Dalgona Triangle XSS challenge level 11
- Outcome: ACHIEVED
- Highest-impact finding: Reflected XSS via event handler with quote-filter bypass
- Validation status: Confirmed with flag extraction

## Target Information
- Target: 127.0.0.1:32919
- Host / base URL: http://127.0.0.1:32919
- Application or component: Dalgona Triangle XSS Challenge (xss11 level)
- Authentication context: Not observed (challenge application)
- Relevant technology details: Web application with XSS filter implementation

## Confirmed Vulnerability
### Reflected XSS on /page?name= endpoint
- Affected endpoint / component: GET /page?name= parameter
- Impact: Arbitrary JavaScript execution in victim's browser context, enabling credential theft, session hijacking, and malicious actions on behalf of the user
- Preconditions: User must visit crafted URL with malicious payload in `name` parameter
- Exact payload or PoC:
  - **Payload 1 (String.fromCharCode bypass):**
    ```
    GET /page?name=%22%20autofocus%20onfocus=alert(String.fromCharCode(88,83,83))%20x=%22
    ```
  - **Payload 2 (Template literal bypass):**
    ```
    GET /page?name=%22%20autofocus%20onfocus=alert(%60XSS%60)%20x=%22
    ```

## Steps to Reproduce
1. Identify the target application at http://127.0.0.1:32919 (Dalgona XSS challenge)
2. Locate the vulnerable endpoint `/page?name=` which reflects user input into the page
3. Test for basic XSS payloads - observe that filter blocks tags starting with `<s` (script, svg) and `<i` (img, iframe, input)
4. Test attribute breakout using `">` - confirm this successfully breaks out of the HTML attribute context
5. Observe that event handlers like `onfocus`, `onload`, `ontoggle`, `onstart` are not blocked
6. Attempt `alert('XSS')` - observe that the filter strips single and double quotes, causing TypeError
7. Bypass quote stripping using either:
   - String.fromCharCode(88,83,83) where 88=X, 83=S, 83=S
   - Template literal backticks: `XSS`
8. Construct final payload: `autofocus onfocus=alert(String.fromCharCode(88,83,83)) x="`
9. URL-encode and send request: GET /page?name=%22%20autofocus%20onfocus=alert(String.fromCharCode(88,83,83))%20x=%22
10. The onfocus event triggers automatically (or when element receives focus), executing alert('XSS')

## Validation / Evidence
- Validation token / flag: `FLAG{64699b06af18be8aa11d1cffbaa67820d88f3b7d3b5d53ab95f9eff3796117d9}`
- Tool evidence: Manual payload testing via HTTP requests
- Request evidence:
  ```
  GET /page?name=%22%20autofocus%20onfocus=alert(String.fromCharCode(88,83,83))%20x=%22
  ```
- Response evidence:
  ```
  <div class="solution-text"><img src="static/img/cookies/success_triangle.png" alt="Correct" width="150" height="150"><br>Congratulations!<p> Here is the flag: FLAG{64699b06af18be8aa11d1cffbaa67820d88f3b7d3b5d53ab95f9eff3796117d9}</div>
  ```
- Notes on reliability / limitations: 
  - The `autofocus` attribute ensures the XSS triggers automatically on page load without requiring user interaction
  - Both String.fromCharCode and template literal methods work reliably
  - The payload requires URL encoding for proper transmission

## Remediation
- Root cause: 
  1. Insufficient input sanitization - the application reflects the `name` parameter directly into HTML without proper encoding
  2. Ineffective blocklist approach - filter only blocks specific tag patterns (`<s`, `<i`) but allows event handlers and attribute breakouts
  3. Incomplete quote filtering - filter strips quotes but allows alternative string construction methods (fromCharCode, template literals)
  
- Recommended fix:
  1. Implement context-aware output encoding - HTML-encode all user input before reflection (convert `<` to `&lt;`, `>` to `&gt;`, `"` to `&quot;`, etc.)
  2. Apply Content Security Policy (CSP) header to prevent inline script execution:
     ```
     Content-Security-Policy: default-src 'self'; script-src 'self'
     ```
  3. Remove blocklist approach in favor of allowlist validation for expected input patterns
  4. Sanitize at the output layer, not just input layer
  
- Defense-in-depth:
  - Set `HttpOnly` and `Secure` flags on session cookies
  - Implement X-Content-Type-Options: nosniff header
  - Consider using modern frontend frameworks with built-in XSS protection
  - Implement input validation to restrict `name` parameter to expected character set

## How to Verify the Fix
1. Attempt the original working payloads:
   - GET /page?name=%22%20autofocus%20onfocus=alert(String.fromCharCode(88,83,83))%20x=%22
   - GET /page?name=%22%20autofocus%20onfocus=alert(%60XSS%60)%20x=%22
2. Inspect the page source - verify that user input is HTML-encoded (e.g., `<` appears as `&lt;`)
3. Verify that event handlers like `onfocus` appear as plain text, not executable HTML attributes
4. Confirm no JavaScript alert dialog appears on page load
5. Expected secure result: The payload is displayed as escaped text in the page content, not executed as JavaScript

## Remaining Leads
- Confirmed blockers: None - objective achieved
- Unverified leads: None required
- Missing context: None - challenge completed successfully

## Technical Details

### Filter Bypass Techniques Used

**1. Event Handler Injection:**
- Filter blocks `<script>` and other dangerous tags but allows event handler attributes
- `onfocus` event combined with `autofocus` attribute triggers automatically

**2. Attribute Breakout:**
- The `">` sequence breaks out of the existing HTML attribute context
- Allows injection of new attributes into the HTML element

**3. Quote Stripping Bypass Methods:**
- **Method 1 - String.fromCharCode():**
  - `String.fromCharCode(88,83,83)` constructs 'XSS' without quotes
  - ASCII codes: 88=X, 83=S, 83=S
- **Method 2 - Template Literals:**
  - `` `XSS` `` uses backticks instead of quotes
  - Filter does not strip backticks

### Decoded Payloads

**URL-decoded working payload:**
```
" autofocus onfocus=alert(String.fromCharCode(88,83,83)) x="
```

**How it works:**
1. `"` - Closes the existing attribute value
2. `autofocus` - HTML5 attribute that automatically focuses the element on page load
3. `onfocus=alert(...)` - Event handler that executes JavaScript when the element receives focus
4. `x="` - Creates a dummy attribute to maintain valid HTML structure
