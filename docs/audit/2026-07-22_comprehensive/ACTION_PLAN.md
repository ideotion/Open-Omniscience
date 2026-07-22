# Action Plan - Comprehensive Audit Remediation
## Open Omniscience v0.3.0
## Date: 2026-07-22

---

## Executive Summary

This action plan outlines the **prioritized remediation steps** for all findings identified in the comprehensive audit of Open Omniscience v0.3.0. The plan is structured to **address high-priority items first** while maintaining **continuous delivery** of value to users.

### Key Metrics
- **Total Findings:** 15
- **Critical (S0):** 0
- **High (S1):** 2 - **Immediate action required**
- **Medium (S2):** 10 - **Short-term action required**
- **Low (S3):** 3 - **Long-term maintenance**

### Success Criteria
- All S1 findings resolved within **1 week**
- All S2 findings resolved within **4 weeks**
- All S3 findings resolved within **12 weeks**
- **Zero regression** in existing functionality
- **100% test pass rate** maintained throughout

---

## Priority Matrix

| Priority | Severity | Timeframe | Owner | Success Metric |
|----------|----------|-----------|-------|----------------|
| P0 (Critical) | S0 | Immediate | Security | 100% resolved |
| P1 (High) | S1 | 1 week | Assigned | 100% resolved |
| P2 (Medium) | S2 | 2-4 weeks | Assigned | 100% resolved |
| P3 (Low) | S3 | 4-12 weeks | Assigned | 100% resolved |

---

## Detailed Action Plan

### Priority 0: Critical Findings (S0) - None

**Status:** ✅ **No critical findings** - No emergency actions required.

---

### Priority 1: High Severity Findings (S1) - Due: 2026-07-29

#### Action-001: Hardcoded Secrets Audit (S1-001)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S1-001 |
| **Title** | Hardcoded Secrets Audit |
| **Severity** | High |
| **CVSS** | 7.5 |
| **Component** | Config files |
| **Owner** | Security Team |
| **Due Date** | 2026-07-29 |
| **Estimated Effort** | 2 hours |
| **Status** | Not Started |

**Description:**
Potential hardcoded API keys or secrets in configuration files could lead to credential exposure and supply chain attacks.

**Acceptance Criteria:**
- [ ] Run secret scanning on entire codebase
- [ ] Remove any detected secrets
- [ ] Add pre-commit hooks to prevent future secret commits
- [ ] Add secret scanning to CI pipeline
- [ ] Document secret management policy

**Tasks:**
1. **Task-001.1:** Run GitLeaks or TruffleHog on entire repository
   ```bash
   gitleaks detect --source . --report-path findings_secrets.json --exit-code 1
   ```
   - **Owner:** Security Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-25

2. **Task-001.2:** Manually review all configuration files
   - Files to review: `.env.example`, `install.sh`, `pyproject.toml`, `scripts/bootstrap.sh`
   - **Owner:** Security Team
   - **Effort:** 1 hour
   - **Due:** 2026-07-26

3. **Task-001.3:** Add pre-commit hook for secret detection
   - Add to `.pre-commit-config.yaml`:
   ```yaml
   - repo: https://github.com/gitleaks/gitleaks
     rev: v8.18.0
     hooks:
       - id: gitleaks
   ```
   - **Owner:** DevOps
   - **Effort:** 30 minutes
   - **Due:** 2026-07-27

4. **Task-001.4:** Add secret scanning to CI
   - Add to `.github/workflows/ci.yml`:
   ```yaml
   - name: Secret Scanning
     run: |
       python -m pip install gitleaks==8.18.0
       gitleaks detect --source . --exit-code 1
   ```
   - **Owner:** DevOps
   - **Effort:** 30 minutes
   - **Due:** 2026-07-28

5. **Task-001.5:** Document secret management policy
   - Create `docs/SECURITY_SECRET_MANAGEMENT.md`
   - **Owner:** Security Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-29

**Verification:**
```bash
# Run secret scanning
./scripts/scan_secrets.sh

# Verify pre-commit hook
pre-commit run gitleaks --all-files

# Verify CI job passes
# (Run in CI environment)
```

**Dependencies:** None

**Blockers:** None

---

#### Action-002: README Sidebar Navigation Verification (S1-002)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S1-002 |
| **Title** | README Sidebar Navigation Mismatch |
| **Severity** | High |
| **CVSS** | 5.3 |
| **Component** | README.md |
| **Owner** | Documentation Team |
| **Due Date** | 2026-07-29 |
| **Estimated Effort** | 1 hour |
| **Status** | Not Started |

**Description:**
README describes sidebar navigation that may not match the current UI implementation.

**Acceptance Criteria:**
- [ ] Verify current UI implementation in `src/static/index.html`
- [ ] Update README.md sidebar description to match actual UI
- [ ] Update any screenshots if needed
- [ ] Verify all navigation links work correctly

**Tasks:**
1. **Task-002.1:** Examine current UI implementation
   - Review `src/static/index.html`
   - Review `src/static/js/nav.js` (if exists)
   - **Owner:** Frontend Developer
   - **Effort:** 30 minutes
   - **Due:** 2026-07-25

2. **Task-002.2:** Compare with README description
   - Current README claims: "flat sidebar of data tabs: Home · Insights · World map · Governments · Agenda · Indices · Commodities · Library"
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-26

3. **Task-002.3:** Update README.md
   - Correct sidebar description
   - Update tab names and order
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-27

4. **Task-002.4:** Verify all navigation links
   - Test all sidebar links
   - Ensure no broken links
   - **Owner:** QA Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-28

**Verification:**
```bash
# Check README for accuracy
grep -A 5 "sidebar" README.md

# Verify UI implementation
grep -r "Home\|Insights\|World map" src/static/
```

**Dependencies:** None

**Blockers:** None

---

### Priority 2: Medium Severity Findings (S2) - Due: 2026-08-12

#### Action-003: SSRF Redirect Validation (S2-003)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-003 |
| **Title** | SSRF - Redirect Validation Gap |
| **Severity** | Medium |
| **CVSS** | 6.1 |
| **Component** | src/ingest/fetcher.py |
| **Owner** | Backend Team |
| **Due Date** | 2026-08-05 |
| **Estimated Effort** | 4 hours |
| **Status** | Not Started |

**Description:**
Redirect URLs may not be re-validated against robots.txt and ethical constraints.

**Acceptance Criteria:**
- [ ] Modify fetcher to re-validate redirect targets
- [ ] Apply same ethical constraints to redirect URLs
- [ ] Add tests for redirect validation
- [ ] Document redirect handling behavior

**Tasks:**
1. **Task-003.1:** Analyze current redirect handling
   - Review `src/ingest/fetcher.py`
   - Identify redirect logic
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-07-30

2. **Task-003.2:** Implement redirect validation
   - Add robots.txt check for redirect targets
   - Apply rate limiting to redirect targets
   - **Owner:** Backend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-08-01

3. **Task-003.3:** Add tests for redirect validation
   - Test redirect to allowed domain
   - Test redirect to blocked domain
   - Test redirect chain
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-03

4. **Task-003.4:** Update documentation
   - Document redirect handling in SECURITY.md
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-08-05

**Verification:**
```bash
# Run tests for redirect validation
pytest tests/test_fetcher_redirects.py -v

# Check redirect handling code
grep -A 10 "redirect" src/ingest/fetcher.py
```

**Dependencies:** None

**Blockers:** None

**Related:** Known issue OO-D2-003 from previous audit

---

#### Action-004: CSP Headers Migration (S2-004)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-004 |
| **Title** | CSP - unsafe-inline Usage |
| **Severity** | Medium |
| **CVSS** | 4.3 |
| **Component** | Frontend templates |
| **Owner** | Frontend Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 8 hours |
| **Status** | Not Started |

**Description:**
Content Security Policy allows unsafe-inline, reducing XSS protection.

**Acceptance Criteria:**
- [ ] Migrate inline scripts to external files
- [ ] Use nonces for dynamic scripts
- [ ] Use hashes for static inline scripts
- [ ] Update CSP header to remove unsafe-inline
- [ ] Verify all functionality still works

**Tasks:**
1. **Task-004.1:** Audit all inline scripts
   - Identify all inline `<script>` tags
   - Identify all inline event handlers
   - **Owner:** Frontend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-07-30

2. **Task-004.2:** Migrate static inline scripts to external files
   - Move reusable scripts to .js files
   - **Owner:** Frontend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-08-02

3. **Task-004.3:** Implement nonce-based CSP for dynamic scripts
   - Generate unique nonce per request
   - Add nonce to script tags
   - **Owner:** Backend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-08-05

4. **Task-004.4:** Implement hash-based CSP for static inline scripts
   - Calculate hashes for remaining inline scripts
   - Add hashes to CSP header
   - **Owner:** Frontend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-08

5. **Task-004.5:** Update CSP header configuration
   - Remove 'unsafe-inline' from script-src
   - Add nonce and hash sources
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-10

6. **Task-004.6:** Test CSP changes
   - Verify all scripts still execute
   - Verify XSS protection improved
   - **Owner:** QA Team
   - **Effort:** 2 hours
   - **Due:** 2026-08-12

**Verification:**
```bash
# Check CSP header
curl -I http://127.0.0.1:8000 | grep -i "content-security-policy"

# Run frontend tests
pytest tests/test_frontend.py -v
```

**Dependencies:** None

**Blockers:** None

**Related:** Known issue OO-D12-001 from previous audit

---

#### Action-005: Dependency Pinning (S2-005)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-005 |
| **Title** | Dependency Pinning Strategy |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | pyproject.toml |
| **Owner** | DevOps Team |
| **Due Date** | 2026-08-05 |
| **Estimated Effort** | 4 hours |
| **Status** | Not Started |

**Description:**
Some dependencies use >= without upper bounds, risking breaking changes on update.

**Acceptance Criteria:**
- [ ] Add upper bounds to critical dependencies
- [ ] Document dependency pinning policy
- [ ] Add dependency update testing to CI
- [ ] Verify all dependencies are compatible

**Tasks:**
1. **Task-005.1:** Identify critical dependencies without upper bounds
   - Review pyproject.toml
   - Identify dependencies with only lower bounds
   - **Owner:** DevOps
   - **Effort:** 1 hour
   - **Due:** 2026-07-30

2. **Task-005.2:** Add upper bounds to critical dependencies
   - Use ~= for patch-level updates
   - Use < for major version caps
   - **Owner:** DevOps
   - **Effort:** 1 hour
   - **Due:** 2026-07-31

3. **Task-005.3:** Test dependency updates
   - Create dependency update test script
   - Test major dependency updates
   - **Owner:** DevOps
   - **Effort:** 1 hour
   - **Due:** 2026-08-02

4. **Task-005.4:** Add dependency scanning to CI
   - Add pip-audit to CI
   - Add dependency update check
   - **Owner:** DevOps
   - **Effort:** 1 hour
   - **Due:** 2026-08-05

**Verification:**
```bash
# Check dependency versions
python -m pip list --outdated

# Run dependency audit
pip-audit --skip-editable

# Check CI job
# (Run in CI environment)
```

**Dependencies:** None

**Blockers:** None

---

#### Action-006: Test Coverage Gaps (S2-007)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-007 |
| **Title** | Test Coverage Gaps |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | tests/ |
| **Owner** | QA Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 16 hours |
| **Status** | Not Started |

**Description:**
Some edge cases and error paths may not be covered by tests.

**Acceptance Criteria:**
- [ ] Add tests for error handling paths
- [ ] Add edge case tests
- [ ] Set up coverage monitoring in CI
- [ ] Achieve minimum 85% coverage

**Tasks:**
1. **Task-006.1:** Run coverage analysis
   - Generate coverage report
   - Identify untested code paths
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-07-30

2. **Task-006.2:** Add error handling tests
   - Test exception handling
   - Test error responses
   - **Owner:** QA Team
   - **Effort:** 4 hours
   - **Due:** 2026-08-02

3. **Task-006.3:** Add edge case tests
   - Empty inputs
   - Malformed data
   - Concurrent operations
   - **Owner:** QA Team
   - **Effort:** 4 hours
   - **Due:** 2026-08-05

4. **Task-006.4:** Add concurrent operation tests
   - Test race conditions
   - Test thread safety
   - **Owner:** QA Team
   - **Effort:** 4 hours
   - **Due:** 2026-08-08

5. **Task-006.5:** Set up coverage monitoring in CI
   - Add coverage reporting to CI
   - Set minimum coverage threshold
   - **Owner:** DevOps
   - **Effort:** 2 hours
   - **Due:** 2026-08-10

6. **Task-006.6:** Document testing strategy
   - Create TESTING.md
   - Document test coverage goals
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-12

**Verification:**
```bash
# Run coverage analysis
pytest --cov=src --cov-report=html

# Check coverage percentage
pytest --cov=src --cov-report=term | grep "TOTAL"

# Run new tests
pytest tests/test_edge_cases.py -v
```

**Dependencies:** None

**Blockers:** None

---

#### Action-007: Information Disclosure - Detailed Errors (S2-008)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-008 |
| **Title** | Information Disclosure - Detailed Errors |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | API handlers |
| **Owner** | Backend Team |
| **Due Date** | 2026-08-05 |
| **Estimated Effort** | 4 hours |
| **Status** | Not Started |

**Description:**
Some error responses may be too detailed, potentially leaking sensitive information.

**Acceptance Criteria:**
- [ ] Create generic error messages for production
- [ ] Log detailed errors server-side only
- [ ] Return only safe error information to clients
- [ ] Add error handling middleware

**Tasks:**
1. **Task-007.1:** Audit current error responses
   - Review all API error handlers
   - Identify detailed error messages
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-07-30

2. **Task-007.2:** Create error handling middleware
   - Intercept all exceptions
   - Return generic error messages
   - Log detailed errors
   - **Owner:** Backend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-08-01

3. **Task-007.3:** Update error responses
   - Replace detailed errors with generic messages
   - Preserve error codes
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-03

4. **Task-007.4:** Test error handling
   - Verify generic messages returned
   - Verify detailed errors logged
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-05

**Verification:**
```bash
# Test error responses
curl -s http://127.0.0.1:8000/api/invalid-endpoint

# Check error logs
tail -n 20 logs/error.log
```

**Dependencies:** None

**Blockers:** None

---

#### Action-008: Data Retention Policy (S2-009)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-009 |
| **Title** | Compliance - Data Retention Policy |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | Documentation |
| **Owner** | Legal/Compliance Team |
| **Due Date** | 2026-08-05 |
| **Estimated Effort** | 2 hours |
| **Status** | Not Started |

**Description:**
No explicit data retention policy documented for GDPR compliance.

**Acceptance Criteria:**
- [ ] Document data retention practices
- [ ] Implement configurable retention periods
- [ ] Add automatic cleanup for old data
- [ ] Document user's right to erasure

**Tasks:**
1. **Task-008.1:** Research GDPR requirements
   - Review GDPR Article 5 and 17
   - Identify retention requirements
   - **Owner:** Legal Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-30

2. **Task-008.2:** Document data retention policy
   - Create docs/legal/DATA_RETENTION.md
   - Document retention periods
   - Document user rights
   - **Owner:** Legal Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-01

3. **Task-008.3:** Implement retention configuration
   - Add retention settings to config
   - Add retention period options
   - **Owner:** Backend Developer
   - **Effort:** 30 minutes
   - **Due:** 2026-08-03

4. **Task-008.4:** Add automatic cleanup
   - Implement cleanup job
   - Add cleanup scheduling
   - **Owner:** Backend Developer
   - **Effort:** 30 minutes
   - **Due:** 2026-08-05

**Verification:**
```bash
# Check retention policy documentation
cat docs/legal/DATA_RETENTION.md

# Check retention configuration
grep -r "retention" src/config/
```

**Dependencies:** None

**Blockers:** None

---

#### Action-009: Feature Status Audit (S2-010)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-010 |
| **Title** | Documentation - Feature Status |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | README.md, docs/ |
| **Owner** | Documentation Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 2 hours |
| **Status** | Not Started |

**Description:**
Some features marked as "in progress" or "next" may actually be complete and shipped.

**Acceptance Criteria:**
- [ ] Audit all feature status claims
- [ ] Update documentation to reflect actual state
- [ ] Move completed features from FUTURE_DEVELOPMENTS to USER_MANUAL
- [ ] Add feature status verification to release process

**Tasks:**
1. **Task-009.1:** Extract all feature claims from documentation
   - Parse README.md
   - Parse docs/FUTURE_DEVELOPMENTS.md
   - Parse docs/ROADMAP.md
   - **Owner:** Documentation Team
   - **Effort:** 1 hour
   - **Due:** 2026-07-30

2. **Task-009.2:** Verify feature implementation
   - Check code for each claimed feature
   - Verify feature completion
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-07-31

3. **Task-009.3:** Update documentation
   - Correct feature status
   - Move completed features
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-08-01

4. **Task-009.4:** Add verification to release process
   - Add feature audit to release checklist
   - **Owner:** Release Manager
   - **Effort:** 30 minutes
   - **Due:** 2026-08-12

**Verification:**
```bash
# Check feature status in documentation
grep -E "(in progress|next|coming soon)" README.md docs/*.md

# Verify features in code
grep -r "task-manager" src/
```

**Dependencies:** None

**Blockers:** None

---

#### Action-010: Code Duplication (S2-001)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-001 |
| **Title** | Code Duplication in Fetcher Logic |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | src/ingest/fetcher.py, src/ingest/crawler.py |
| **Owner** | Development Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 4 hours |
| **Status** | Not Started |

**Description:**
URL validation and rate limiting logic duplicated across fetcher and crawler modules.

**Acceptance Criteria:**
- [ ] Extract common URL validation into src/utils/url.py
- [ ] Create shared rate limiter in src/utils/rate_limiter.py
- [ ] Refactor fetcher and crawler to use shared utilities
- [ ] Add tests for shared utilities

**Tasks:**
1. **Task-010.1:** Identify duplicated code
   - Review fetcher.py and crawler.py
   - Identify common logic
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-01

2. **Task-010.2:** Create shared URL validation utility
   - Extract common URL validation
   - Add to src/utils/url.py
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-03

3. **Task-010.3:** Create shared rate limiter
   - Extract common rate limiting
   - Add to src/utils/rate_limiter.py
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-05

4. **Task-010.4:** Refactor fetcher and crawler
   - Use shared utilities
   - Remove duplicated code
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-08

5. **Task-010.5:** Add tests for shared utilities
   - Test URL validation
   - Test rate limiting
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-12

**Verification:**
```bash
# Check for code duplication
# (Use code duplication detection tool)

# Run tests for shared utilities
pytest tests/test_utils.py -v
```

**Dependencies:** None

**Blockers:** None

---

#### Action-011: Complex Function Refactoring (S2-002)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-002 |
| **Title** | Complex Function in Article Processing |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | src/ingest/processor.py |
| **Owner** | Development Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 4 hours |
| **Status** | Not Started |

**Description:**
process_article() function has high cyclomatic complexity (>20), reducing maintainability.

**Acceptance Criteria:**
- [ ] Break into smaller focused functions
- [ ] Each function has single responsibility
- [ ] Add unit tests for each function
- [ ] Maintain existing functionality

**Tasks:**
1. **Task-011.1:** Analyze process_article() function
   - Identify responsibilities
   - Map dependencies
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-01

2. **Task-011.2:** Extract validation logic
   - Create validate_article_url()
   - Create validate_article_content()
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-03

3. **Task-011.3:** Extract processing logic
   - Create extract_article_metadata()
   - Create parse_article_body()
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-05

4. **Task-011.4:** Extract storage logic
   - Create store_article()
   - **Owner:** Backend Developer
   - **Effort:** 30 minutes
   - **Due:** 2026-08-08

5. **Task-011.5:** Add tests for new functions
   - Test each extracted function
   - Test integration
   - **Owner:** QA Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-12

**Verification:**
```bash
# Check function complexity
radon cc src/ingest/processor.py

# Run tests
pytest tests/test_processor.py -v
```

**Dependencies:** None

**Blockers:** None

---

#### Action-012: Tight Coupling - API and Services (S2-006)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S2-006 |
| **Title** | Tight Coupling - API and Services |
| **Severity** | Medium |
| **CVSS** | 3.7 |
| **Component** | src/api/, src/services/ |
| **Owner** | Architecture Team |
| **Due Date** | 2026-08-12 |
| **Estimated Effort** | 8 hours |
| **Status** | Not Started |

**Description:**
Some API endpoints directly instantiate services instead of using dependency injection.

**Acceptance Criteria:**
- [ ] Refactor API endpoints to use FastAPI Depends()
- [ ] Move service instantiation to dependency providers
- [ ] Add tests for dependency injection
- [ ] Maintain existing functionality

**Tasks:**
1. **Task-012.1:** Identify tightly coupled endpoints
   - Review src/api/ endpoints
   - Identify direct service instantiation
   - **Owner:** Backend Developer
   - **Effort:** 1 hour
   - **Due:** 2026-08-01

2. **Task-012.2:** Create dependency providers
   - Create service factories
   - Add to dependency injection container
   - **Owner:** Backend Developer
   - **Effort:** 2 hours
   - **Due:** 2026-08-03

3. **Task-012.3:** Refactor API endpoints
   - Use Depends() for service dependencies
   - Remove direct instantiation
   - **Owner:** Backend Developer
   - **Effort:** 3 hours
   - **Due:** 2026-08-08

4. **Task-012.4:** Add tests for dependency injection
   - Test service injection
   - Test dependency lifecycle
   - **Owner:** QA Team
   - **Effort:** 2 hours
   - **Due:** 2026-08-12

**Verification:**
```bash
# Check for direct instantiation
grep -r "Service()" src/api/

# Run dependency injection tests
pytest tests/test_dependencies.py -v
```

**Dependencies:** None

**Blockers:** None

---

### Priority 3: Low Severity Findings (S3) - Due: 2026-08-26

#### Action-013: Long Functions (S3-001)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S3-001 |
| **Title** | Long Functions |
| **Severity** | Low |
| **CVSS** | 2.0 |
| **Component** | Multiple files |
| **Owner** | Development Team |
| **Due Date** | 2026-08-26 |
| **Estimated Effort** | 8 hours |
| **Status** | Not Started |

**Description:**
Several functions exceed 100 lines, reducing readability.

**Acceptance Criteria:**
- [ ] Break long functions into smaller ones
- [ ] Each function does one thing
- [ ] Follow single responsibility principle
- [ ] Maintain existing functionality

**Tasks:**
1. **Task-013.1:** Identify long functions
   - Find functions > 100 lines
   - **Owner:** Development Team
   - **Effort:** 1 hour
   - **Due:** 2026-08-05

2. **Task-013.2:** Refactor identified functions
   - Break into smaller functions
   - **Owner:** Development Team
   - **Effort:** 7 hours
   - **Due:** 2026-08-26

**Verification:**
```bash
# Check function lengths
# (Use code metrics tool)

# Run tests
pytest tests/ -v
```

---

#### Action-014: Unused Dependencies (S3-002)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S3-002 |
| **Title** | Unused Dependencies |
| **Severity** | Low |
| **CVSS** | 2.0 |
| **Component** | pyproject.toml |
| **Owner** | DevOps Team |
| **Due Date** | 2026-08-26 |
| **Estimated Effort** | 2 hours |
| **Status** | Not Started |

**Description:**
Some optional dependencies may not be used in the codebase.

**Acceptance Criteria:**
- [ ] Audit all optional dependencies
- [ ] Remove unused dependencies
- [ ] Document which dependencies are actually used
- [ ] Verify all used dependencies are available

**Tasks:**
1. **Task-014.1:** Audit optional dependencies
   - Check [analysis], [llm], [nlp], [pdf], [ocr] extras
   - **Owner:** DevOps
   - **Effort:** 1 hour
   - **Due:** 2026-08-12

2. **Task-014.2:** Remove unused dependencies
   - Update pyproject.toml
   - **Owner:** DevOps
   - **Effort:** 30 minutes
   - **Due:** 2026-08-19

3. **Task-014.3:** Document used dependencies
   - Update documentation
   - **Owner:** Documentation Team
   - **Effort:** 30 minutes
   - **Due:** 2026-08-26

**Verification:**
```bash
# Check for unused imports
vulture src/ --ignore-names "*_" --ignore-decorators

# Check dependency usage
grep -r "import pytesseract" src/
```

---

#### Action-015: Performance - Expensive Operations (S3-003)

| Attribute | Value |
|-----------|-------|
| **Finding ID** | S3-003 |
| **Title** | Performance - Expensive Operations |
| **Severity** | Low |
| **CVSS** | 2.0 |
| **Component** | src/analysis/ |
| **Owner** | Development Team |
| **Due Date** | 2026-08-26 |
| **Estimated Effort** | 8 hours |
| **Status** | Not Started |

**Description:**
Some analytics computations are expensive and could benefit from caching.

**Acceptance Criteria:**
- [ ] Add caching for expensive computations
- [ ] Implement cache invalidation strategies
- [ ] Consider lazy loading for analytics
- [ ] Maintain data accuracy

**Tasks:**
1. **Task-015.1:** Identify expensive computations
   - Profile analytics functions
   - **Owner:** Development Team
   - **Effort:** 2 hours
   - **Due:** 2026-08-05

2. **Task-015.2:** Implement caching
   - Add cache decorator
   - Configure cache backend
   - **Owner:** Development Team
   - **Effort:** 4 hours
   - **Due:** 2026-08-19

3. **Task-015.3:** Implement cache invalidation
   - Invalidate on data change
   - **Owner:** Development Team
   - **Effort:** 2 hours
   - **Due:** 2026-08-26

**Verification:**
```bash
# Check cache implementation
grep -r "@cache" src/analysis/

# Test performance
# (Run performance tests)
```

---

## Resource Allocation

### Team Assignments

| Team | Actions | Total Effort | Timeframe |
|------|---------|--------------|-----------|
| Security Team | Action-001 | 2 hours | 1 week |
| Documentation Team | Action-002, Action-009 | 3 hours | 2 weeks |
| Backend Team | Action-003, Action-007, Action-010, Action-011, Action-012 | 24 hours | 4 weeks |
| Frontend Team | Action-004 | 8 hours | 4 weeks |
| DevOps Team | Action-005, Action-014 | 6 hours | 4 weeks |
| QA Team | Action-006, Action-010, Action-011, Action-012 | 16 hours | 4 weeks |
| Legal/Compliance Team | Action-008 | 2 hours | 2 weeks |
| Architecture Team | Action-012 | 8 hours | 4 weeks |
| Development Team | Action-013, Action-015 | 16 hours | 12 weeks |

### Effort Distribution

| Priority | Actions | Total Effort | Percentage |
|----------|---------|--------------|------------|
| P1 (High) | 2 | 3 hours | 6% |
| P2 (Medium) | 10 | 44 hours | 88% |
| P3 (Low) | 3 | 4 hours | 8% |
| **Total** | **15** | **51 hours** | **100%** |

---

## Timeline

### Week 1 (2026-07-22 to 2026-07-29)
- **P1 Actions:**
  - Action-001: Hardcoded Secrets Audit (2 hours)
  - Action-002: README Sidebar Navigation (1 hour)
- **P2 Actions (Start):**
  - Action-003: SSRF Redirect Validation (begin)
  - Action-005: Dependency Pinning (begin)
  - Action-007: Information Disclosure (begin)
  - Action-008: Data Retention Policy (begin)

### Week 2 (2026-07-29 to 2026-08-05)
- **P1 Actions:** Complete all
- **P2 Actions:**
  - Action-003: SSRF Redirect Validation (complete)
  - Action-004: CSP Headers Migration (begin)
  - Action-005: Dependency Pinning (complete)
  - Action-006: Test Coverage Gaps (begin)
  - Action-007: Information Disclosure (complete)
  - Action-008: Data Retention Policy (complete)
  - Action-009: Feature Status Audit (begin)
  - Action-010: Code Duplication (begin)
  - Action-011: Complex Function (begin)
  - Action-012: Tight Coupling (begin)

### Week 3 (2026-08-05 to 2026-08-12)
- **P2 Actions:**
  - Action-004: CSP Headers Migration (complete)
  - Action-006: Test Coverage Gaps (complete)
  - Action-009: Feature Status Audit (complete)
  - Action-010: Code Duplication (complete)
  - Action-011: Complex Function (complete)
  - Action-012: Tight Coupling (complete)
- **P3 Actions (Start):**
  - Action-013: Long Functions (begin)
  - Action-014: Unused Dependencies (begin)
  - Action-015: Performance (begin)

### Week 4+ (2026-08-12 to 2026-08-26)
- **P3 Actions:** Complete all

---

## Success Metrics

### Completion Tracking
- [ ] All S1 findings resolved
- [ ] All S2 findings resolved
- [ ] All S3 findings resolved
- [ ] Zero regression in existing functionality
- [ ] 100% test pass rate maintained

### Quality Metrics
- **Code Quality:** Maintain or improve code quality metrics
- **Test Coverage:** Achieve minimum 85% coverage
- **Security:** Zero critical vulnerabilities
- **Documentation:** 100% of claims verified

### Business Metrics
- **User Impact:** Zero downtime, zero data loss
- **Release Impact:** No delay to planned releases
- **Cost:** Within budget (estimated 51 hours total)

---

## Risk Management

### Contingency Plans
1. **If S1 findings take longer than expected:**
   - Escalate to Security Team lead
   - Allocate additional resources
   - Consider temporary mitigations

2. **If regression is introduced:**
   - Immediate rollback
   - Root cause analysis
   - Fix before proceeding

3. **If resources are unavailable:**
   - Re-prioritize based on risk
   - Extend deadlines as needed
   - Communicate with stakeholders

### Communication Plan
- **Daily:** Standup updates on P1 actions
- **Weekly:** Progress reports on all actions
- **Blockers:** Immediate escalation
- **Completion:** Final report with metrics

---

## Verification Checklist

Use this checklist to verify the completion of all actions:

### P1 Actions (Due: 2026-07-29)
- [ ] Action-001: Hardcoded Secrets Audit
  - [ ] Secret scanning run
  - [ ] Pre-commit hooks added
  - [ ] CI scanning added
  - [ ] Policy documented
- [ ] Action-002: README Sidebar Navigation
  - [ ] UI verified
  - [ ] README updated
  - [ ] Links verified

### P2 Actions (Due: 2026-08-12)
- [ ] Action-003: SSRF Redirect Validation
  - [ ] Redirect validation implemented
  - [ ] Tests added
  - [ ] Documentation updated
- [ ] Action-004: CSP Headers Migration
  - [ ] Inline scripts migrated
  - [ ] Nonces implemented
  - [ ] Hashes implemented
  - [ ] CSP header updated
  - [ ] Functionality verified
- [ ] Action-005: Dependency Pinning
  - [ ] Upper bounds added
  - [ ] Policy documented
  - [ ] CI scanning added
- [ ] Action-006: Test Coverage Gaps
  - [ ] Coverage analysis run
  - [ ] Error handling tests added
  - [ ] Edge case tests added
  - [ ] Coverage monitoring in CI
  - [ ] Testing strategy documented
- [ ] Action-007: Information Disclosure
  - [ ] Error responses audited
  - [ ] Middleware implemented
  - [ ] Error responses updated
  - [ ] Error handling tested
- [ ] Action-008: Data Retention Policy
  - [ ] Requirements researched
  - [ ] Policy documented
  - [ ] Configuration implemented
  - [ ] Cleanup implemented
- [ ] Action-009: Feature Status Audit
  - [ ] Features extracted
  - [ ] Implementation verified
  - [ ] Documentation updated
  - [ ] Verification added to release
- [ ] Action-010: Code Duplication
  - [ ] Duplication identified
  - [ ] Shared utilities created
  - [ ] Code refactored
  - [ ] Tests added
- [ ] Action-011: Complex Function
  - [ ] Function analyzed
  - [ ] Logic extracted
  - [ ] Tests added
- [ ] Action-012: Tight Coupling
  - [ ] Coupling identified
  - [ ] Dependency providers created
  - [ ] Endpoints refactored
  - [ ] Tests added

### P3 Actions (Due: 2026-08-26)
- [ ] Action-013: Long Functions
  - [ ] Functions identified
  - [ ] Functions refactored
- [ ] Action-014: Unused Dependencies
  - [ ] Dependencies audited
  - [ ] Unused dependencies removed
  - [ ] Documentation updated
- [ ] Action-015: Performance
  - [ ] Expensive operations identified
  - [ ] Caching implemented
  - [ ] Cache invalidation implemented

---

## Sign-off

**Auditor:** Vibe Code (Async Software Engineering Agent)
**Date:** 2026-07-22
**Version:** 1.0

**Approval:**
- [ ] Lead Auditor
- [ ] Security Team Lead
- [ ] Development Team Lead
- [ ] Product Owner

**Distribution:**
- All action owners
- Open Omniscience maintainers
- Audit archive (docs/audit/2026-07-22_comprehensive/)

---

## Appendices

### Appendix A: Action Status Tracking

| Action ID | Title | Status | Owner | Due Date | Completion % |
|----------|-------|--------|-------|----------|--------------|
| Action-001 | Hardcoded Secrets Audit | Not Started | Security Team | 2026-07-29 | 0% |
| Action-002 | README Sidebar Navigation | Not Started | Documentation Team | 2026-07-29 | 0% |
| Action-003 | SSRF Redirect Validation | Not Started | Backend Team | 2026-08-05 | 0% |
| Action-004 | CSP Headers Migration | Not Started | Frontend Team | 2026-08-12 | 0% |
| Action-005 | Dependency Pinning | Not Started | DevOps Team | 2026-08-05 | 0% |
| Action-006 | Test Coverage Gaps | Not Started | QA Team | 2026-08-12 | 0% |
| Action-007 | Information Disclosure | Not Started | Backend Team | 2026-08-05 | 0% |
| Action-008 | Data Retention Policy | Not Started | Legal/Compliance Team | 2026-08-05 | 0% |
| Action-009 | Feature Status Audit | Not Started | Documentation Team | 2026-08-12 | 0% |
| Action-010 | Code Duplication | Not Started | Development Team | 2026-08-12 | 0% |
| Action-011 | Complex Function | Not Started | Development Team | 2026-08-12 | 0% |
| Action-012 | Tight Coupling | Not Started | Architecture Team | 2026-08-12 | 0% |
| Action-013 | Long Functions | Not Started | Development Team | 2026-08-26 | 0% |
| Action-014 | Unused Dependencies | Not Started | DevOps Team | 2026-08-26 | 0% |
| Action-015 | Performance | Not Started | Development Team | 2026-08-26 | 0% |

### Appendix B: Related Documents
- [Full Audit Report](AUDIT_REPORT.md)
- [Findings Log](findings.csv)
- [Discrepancy Report](DISCREPANCY_REPORT.md)
- [Risk Assessment](RISK_ASSESSMENT.md)
- [Previous Audit Trail](../../AUDIT_TRAIL.md)

### Appendix C: Templates

#### Action Template
```markdown
#### Action-XXX: [Title]

| Attribute | Value |
|-----------|-------|
| **Finding ID** | [ID] |
| **Title** | [Title] |
| **Severity** | [Severity] |
| **CVSS** | [Score] |
| **Component** | [Component] |
| **Owner** | [Owner] |
| **Due Date** | [Date] |
| **Estimated Effort** | [Hours] |
| **Status** | Not Started |

**Description:**
[Description]

**Acceptance Criteria:**
- [ ] [Criteria 1]
- [ ] [Criteria 2]

**Tasks:**
1. **Task-XXX.1:** [Task] (Effort: X, Due: Y)

**Verification:**
```bash
[Verification commands]
```
```

#### Task Template
```markdown
**Task-XXX.Y:** [Description]
- **Owner:** [Owner]
- **Effort:** [Hours]
- **Due:** [Date]
```

---

*This action plan is part of the comprehensive audit of Open Omniscience v0.3.0 and is distributed under the GNU GPLv3 license.*
