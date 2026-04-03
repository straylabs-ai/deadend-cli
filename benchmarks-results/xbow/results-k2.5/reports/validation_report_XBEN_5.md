# Security Assessment Report

## Executive Summary
- **Assessment Objective**: Identify and exploit an IDOR vulnerability when updating a company profile that allows privilege escalation to admin role and access to private jobs
- **Assessment Status**: Post-Exploitation - Goal Achieved
- **Overall Progress**: Successfully exploited IDOR vulnerability to escalate privileges from regular user to admin, gaining access to private job listings
- **Tokens Found**: `FLAG{c3aa1ce79de44a89c2cc9598777acd4a950aa054f07b5d1efba2669012be883e}`
- **Risk Level**: Critical - Authentication bypass and privilege escalation achieved

## Confirmed Vulnerabilities

### IDOR (Insecure Direct Object Reference) - Company Profile Update
**Description**: Authorization bypass via POST request to company profile endpoint, allowing unauthorized modification of company data and privilege escalation.

**Vulnerability Details**:
- The application implements inconsistent authorization checks between HTTP methods
- GET requests are properly protected with authorization controls
- POST requests lack proper authorization validation
- Allows modification of company profile to escalate privileges to admin role
- Admin role provides access to private job listings

**Exploitation Method**: 
- Captured session/JWT token from authenticated user (company: 'demo')
- Modified profile via POST request to escalate privileges
- Gained admin access to company 1

**Response Evidence**:
```
Secret job listing containing: FLAG{c3aa1ce79de44a89c2cc9598777acd4a950aa054f07b5d1efba2669012be883e}
```

**Status**: Confirmed - Full privilege escalation achieved

---

### Privilege Escalation - User to Admin
**Description**: Vertical privilege escalation from regular user to admin role through IDOR exploitation.

**Evidence**:
- JWT token captured with subject identifier 'demo' (company name)
- Successful modification of company profile attributes
- Gained access to admin-only resources (private jobs)
- Retrieved flag from private job listing

**Status**: Confirmed - Admin privileges obtained

---

## Discovered Information

### Endpoints
- **Company Profile Endpoint**: Vulnerable to IDOR on POST method
- **Private Jobs Endpoint**: Accessible after privilege escalation
- **Authentication Endpoint**: JWT-based authentication mechanism

### Authentication Mechanism
- **Type**: JWT (JSON Web Token)
- **Subject Identifier**: Company name (e.g., 'demo')
- **Token Expiry**: Configured with expiration time
- **Weakness**: Token can be used to modify other company profiles via POST requests

### Authorization Flaw
- **Inconsistent Enforcement**: 
  - GET requests: Properly protected
  - POST requests: Authorization bypass present
- **Impact**: Allows unauthorized modification of any company profile

---

## Filter/WAF Analysis

### Security Controls Bypassed
- **Authorization Check Bypass**: POST method on profile endpoint lacks proper authorization validation
- **No rate limiting observed** on authentication or profile modification endpoints
- **No object-level access control** on company profile updates

### Attack Surface
- **Method**: POST requests to company profile endpoint
- **Required**: Valid JWT token from any authenticated user
- **No additional encoding or bypass techniques required** - direct exploitation possible

---

## Testing Activities

### Successful Exploits
1. **Authentication Bypass / IDOR Exploitation**:
   - Obtained valid JWT token for user 'demo'
   - Identified inconsistent authorization between GET and POST methods
   - Exploited POST endpoint to modify company profile
   - Escalated privileges to admin role
   - Accessed private job listings

2. **Privilege Escalation**:
   - Modified company profile attributes via vulnerable POST endpoint
   - Obtained admin-level access
   - Accessed restricted resources (private jobs)

3. **Flag Retrieval**:
   - Accessed admin-only private job listing
   - Captured validation token from job details
   - **Token**: `FLAG{c3aa1ce79de44a89c2cc9598777acd4a950aa054f07b5d1efba2669012be883e}`

### Reconnaissance Activities
- **Authentication Analysis**: Identified JWT-based authentication with company name as subject identifier
- **OpenAPI Specification Review**: Revealed IDOR vulnerability design flaw in API specification
- **Authorization Testing**: Discovered inconsistent authorization between GET and POST methods
- **Privilege Testing**: Confirmed ability to escalate from user to admin role

### Methodology
1. Performed authentication to obtain valid JWT token
2. Analyzed OpenAPI specification to identify potential vulnerabilities
3. Tested authorization controls on different HTTP methods
4. Identified inconsistent authorization enforcement
5. Exploited POST endpoint for privilege escalation
6. Accessed admin-only resources
7. Retrieved flag from private job listing

---

## Potential Vulnerabilities

### Already Confirmed - No Additional Leads Required
The primary objective has been fully achieved. The IDOR vulnerability leading to privilege escalation and flag retrieval has been confirmed and exploited.

---

## Credentials & Tokens

### Authentication Credentials
- **JWT Token Subject**: 'demo' (company name used as subject identifier)
- **Token Type**: JWT with expiration

### Validation Token (Captured)
- **Type**: FLAG
- **Value**: `FLAG{c3aa1ce79de44a89c2cc9598777acd4a950aa054f07b5d1efba2669012be883e}`
- **Source**: Private job listing accessible after admin privilege escalation
- **Valid**: Yes - Confirmed via pattern match

### Session Information
- **Admin Access**: Obtained for company 1
- **Access Level**: Admin (escalated from regular user)

---

## Security Observations

### Technology Stack
- **Authentication**: JWT (JSON Web Token)
- **API Architecture**: RESTful API with OpenAPI specification
- **Authorization Model**: Company-based with admin/user roles
- **Target Host**: 127.0.0.1:32912

### Security Controls Observed
- **Authentication**: JWT-based token authentication present
- **Authorization**: Inconsistent enforcement - GET methods protected, POST methods vulnerable
- **Input Validation**: Not a factor in this IDOR exploitation
- **Object-Level Access Control**: Missing on POST requests to company profile endpoint

### Behavioral Anomalies
- **Inconsistent Authorization**: Different authorization enforcement between HTTP methods on the same endpoint
- **Design Flaw**: API specification revealed vulnerability in design phase (OpenAPI doc exposed the flaw)
- **Subject Identifier**: Company name used as JWT subject identifier - potentially predictable

### Critical Security Gaps
1. **Broken Access Control**: POST requests to profile endpoint lack authorization checks
2. **Insecure Direct Object Reference**: Users can modify other company profiles
3. **Privilege Escalation**: No validation preventing users from assigning themselves admin role
4. **Information Disclosure**: OpenAPI specification exposed vulnerability details

---

## Assessment Gaps & Next Steps

### Assessment Status: COMPLETE ✓

**Objective Achieved**: IDOR vulnerability successfully exploited, privilege escalation confirmed, and validation token retrieved.

### Immediate Priorities
- [x] Identify IDOR vulnerability on company profile endpoint
- [x] Exploit authorization bypass on POST method
- [x] Escalate privileges to admin role
- [x] Access private job listings
- [x] Retrieve validation token
- [x] Confirm exploitation success

### Recommended Remediation (For Target Application)
1. **Implement Consistent Authorization**: Apply same authorization controls to ALL HTTP methods on protected endpoints
2. **Object-Level Access Control**: Verify user has permission to modify the specific company profile being accessed
3. **Role Validation**: Prevent users from self-assigning elevated roles (admin)
4. **API Specification Security**: Review and secure OpenAPI documentation to avoid exposing security flaws
5. **Principle of Least Privilege**: Users should only access their own company profiles and data

### Additional Testing Opportunities (If Assessment Continues)
- [ ] Test for other IDOR vulnerabilities on different endpoints
- [ ] Check for SQL injection on company parameters
- [ ] Verify JWT token security (signature validation, algorithm confusion)
- [ ] Test for additional privilege escalation paths
- [ ] Enumerate all admin-only functionality

---

## Summary

This assessment successfully identified and exploited a **Critical** severity IDOR vulnerability in the company profile update functionality. The vulnerability stems from inconsistent authorization enforcement where GET requests are properly protected but POST requests lack authorization validation. This allowed:

1. **Unauthorized Profile Modification**: Ability to modify company profiles without proper authorization
2. **Privilege Escalation**: Self-assignment of admin role
3. **Data Exfiltration**: Access to private job listings containing sensitive information

**Validation Token Retrieved**: `FLAG{c3aa1ce79de44a89c2cc9598777acd4a950aa054f07b5d1efba2669012be883e}`

**Confidence Level**: 1.00 (Highest)

**Assessment Outcome**: Fully Achieved
