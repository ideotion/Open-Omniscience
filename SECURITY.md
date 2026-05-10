# Security Policy for Open Omniscience

**Last Updated:** May 7, 2026

At **Ideotion**, we take the security of **Open Omniscience** seriously. This document outlines our **security practices**, **vulnerability reporting process**, and **guidelines for contributors** to ensure the platform remains secure and trustworthy.

---

## 🔒 Security Practices

### 1. Secure Development Lifecycle
Open Omniscience follows a **secure development lifecycle (SDL)** to minimize vulnerabilities:

| Phase | Security Measures |
|-------|-------------------|
| **Design** | Threat modeling, privacy impact assessments. |
| **Development** | Code reviews, static analysis, dependency scanning. |
| **Testing** | Penetration testing, fuzz testing, security audits. |
| **Deployment** | Secure defaults, minimal permissions, audit logging. |
| **Maintenance** | Regular updates, patch management, incident response. |

### 2. Dependency Security
- **Regular updates**: Dependencies are updated to the latest **stable versions** (see [requirements.txt](requirements.txt)).
- **Vulnerability scanning**: We use `safety` and `dependabot` to scan for known vulnerabilities:
  ```bash
  pip install safety
  safety check
  ```
- **Minimal dependencies**: We avoid unnecessary libraries to reduce the attack surface.

### 3. Input Validation
All **user inputs** (API requests, form submissions, etc.) are **validated and sanitized** to prevent:
- **SQL Injection**: Use **SQLAlchemy ORM** (parameterized queries) instead of raw SQL.
- **Cross-Site Scripting (XSS)**: Escape HTML/JS in user-generated content.
- **Command Injection**: Avoid `eval()`, `exec()`, or shell commands with user input.
- **Path Traversal**: Validate file paths and restrict access to allowed directories.

### 4. Authentication and Authorization
- **API Rate Limiting**: Default rate limits are enforced (e.g., 100 requests/hour) to prevent abuse.
- **No Authentication (Current)**: Open Omniscience currently **does not require authentication** for local use. For production deployments, we recommend:
  - **Reverse proxy authentication** (e.g., Nginx Basic Auth).
  - **IP whitelisting** (restrict access to trusted IPs).
  - **API keys** (future feature).

### 5. Data Protection
- **Local-Only**: All data remains on the user's machine. No cloud dependency by default.
- **Encryption**: Users can enable **SQLite encryption** (SQLCipher) for sensitive datasets.
- **Minimization**: Only **necessary data** (URL, title, content, metadata) is stored. No personal data is collected.

### 6. Audit Logging
- **Scraping Activities**: All scraping actions are logged in `audit/scrape_log.csv` with:
  - Timestamp
  - Target URL
  - Source domain
  - HTTP status code
  - Rate limit applied
- **API Requests**: All API requests are logged with:
  - Timestamp
  - Endpoint
  - IP address (if enabled)
  - Status code
- **Errors**: All errors are logged in `audit/errors.log`.

### 7. Secure Defaults
| Setting | Default | Description |
|---------|---------|-------------|
| `rate_limit_ms` | 2000 | 2 seconds between requests per domain. |
| `enabled` | `true` | Sources are enabled by default (but respect `robots.txt`). |
| `DATABASE_URL` | SQLite | Local database (no remote connections by default). |
| `User-Agent` | `OpenOmniscience/1.0` | Identifiable User-Agent string. |
| `CORS` | `*` | Open CORS for development (restrict in production). |

---

## 🚨 Vulnerability Reporting

If you discover a **security vulnerability** in Open Omniscience, **please report it responsibly** to minimize risk to users. Do **not** disclose the vulnerability publicly until it has been fixed.

### How to Report a Vulnerability
1. **Do not open a public GitHub issue** (this could expose the vulnerability to malicious actors).
2. **Email the security team** at `open-omniscience@ideotion.com` with:
   - A **clear description** of the vulnerability.
   - **Steps to reproduce** the issue.
   - **Impact** of the vulnerability (e.g., data exposure, remote code execution).
   - **Suggested fix** (if you have one).
3. **Wait for a response** (typically within **48 hours**).
4. **Collaborate on a fix**: Work with the maintainers to address the issue.
5. **Public disclosure**: Once the fix is released, we will **publicly acknowledge** your contribution (with your permission).

### What We Consider a Vulnerability
- **Remote Code Execution (RCE)**: Ability to execute arbitrary code on the server.
- **SQL Injection**: Ability to execute arbitrary SQL queries.
- **Cross-Site Scripting (XSS)**: Ability to inject malicious scripts into the UI.
- **Cross-Site Request Forgery (CSRF)**: Ability to perform actions on behalf of a user.
- **Authentication Bypass**: Ability to access restricted resources without authentication.
- **Information Disclosure**: Exposure of sensitive data (e.g., database contents, user credentials).
- **Denial of Service (DoS)**: Ability to crash or slow down the application.
- **Supply Chain Attacks**: Vulnerabilities in dependencies (e.g., malicious PyPI packages).

### What We Do Not Consider a Vulnerability
- **Missing Features**: Lack of functionality (e.g., no authentication) is not a vulnerability unless it leads to a security risk.
- **Performance Issues**: Slow queries or high memory usage (unless it causes a DoS).
- **Usability Issues**: Poor UX or bugs that do not pose a security risk.

---

## 🛡️ Security Checklist for Contributors

If you are contributing code to Open Omniscience, **please ensure your changes do not introduce security vulnerabilities**:

### ✅ Do:
- **Use parameterized queries** (SQLAlchemy ORM) to prevent SQL injection.
- **Sanitize user inputs** (e.g., escape HTML, validate URLs, check file paths).
- **Use HTTPS** for all external requests (e.g., `requests.get` with `verify=True`).
- **Validate file uploads** (if applicable) to prevent malicious files.
- **Follow the principle of least privilege** (e.g., database users should have minimal permissions).
- **Log security-relevant events** (e.g., failed logins, rate limit hits).
- **Use environment variables** for secrets (e.g., database passwords).

### ❌ Do Not:
- **Use `eval()` or `exec()`** with user input.
- **Concatenate SQL queries** with user input (use SQLAlchemy ORM instead).
- **Store secrets in code** (e.g., API keys, passwords). Use environment variables or secret managers.
- **Disable SSL/TLS verification** (e.g., `verify=False` in `requests`).
- **Trust user input** without validation (e.g., file paths, URLs, database queries).
- **Expose sensitive data** in logs or error messages (e.g., database credentials, API keys).
- **Use outdated dependencies** with known vulnerabilities.

### Example: Safe Database Query
```python
# UNSAFE: SQL injection vulnerability
query = f"SELECT * FROM articles WHERE title = '{user_input}'"

# SAFE: Use SQLAlchemy ORM
from database.models import Article
articles = session.query(Article).filter_by(title=user_input).all()
```

### Example: Safe File Path Handling
```python
# UNSAFE: Path traversal vulnerability
file_path = user_input
with open(file_path, "r") as f:
    content = f.read()

# SAFE: Restrict to allowed directory
import os
from pathlib import Path

ALLOWED_DIR = Path("/safe/directory")
file_path = Path(user_input).resolve()
if file_path.parent != ALLOWED_DIR:
    raise ValueError("Invalid file path")
with open(file_path, "r") as f:
    content = f.read()
```

---

## 🔍 Security Audits

Open Omniscience undergoes **regular security audits** to identify and fix vulnerabilities. Here’s how we do it:

### 1. Automated Scanning
- **Dependency Scanning**: `safety check` and `dependabot` for vulnerable dependencies.
- **Static Analysis**: `bandit` for Python code:
  ```bash
  pip install bandit
  bandit -r src/
  ```
- **Secret Scanning**: `gitleaks` to detect accidentally committed secrets:
  ```bash
  gitleaks detect --source . --verbose
  ```

### 2. Manual Review
- **Code Reviews**: All PRs are reviewed for security issues before merging.
- **Threat Modeling**: We perform threat modeling for new features (e.g., authentication, file uploads).
- **Penetration Testing**: We occasionally perform **internal penetration tests** to identify vulnerabilities.

### 3. Third-Party Audits
- We may engage **external security experts** for independent audits.
- Results will be **disclosed transparently** (with fixes).

---

## 📅 Security Updates

When a **security vulnerability** is discovered and fixed, we will:
1. **Release a patch** as soon as possible (typically within **7 days** for critical vulnerabilities).
2. **Disclose the vulnerability** in a **security advisory** (GitHub Security Advisories or [our website](https://ideotion.com)).
3. **Notify users** via:
   - GitHub **releases** and **advisories**.
   - **Email** (for registered users, if applicable).
   - **Social media** (Twitter, Mastodon).

### Versioning
Security fixes are included in **patch releases** (e.g., `0.2.1`) for critical issues or **minor releases** (e.g., `0.3.0`) for non-critical issues.

---

## 🚫 Known Limitations

Open Omniscience is **not a security-hardened application** by default. Here are some **known limitations** and how to mitigate them:

| Limitation | Risk | Mitigation |
|------------|------|------------|
| **No Authentication** | Unauthorized access to the GUI/API. | Use a reverse proxy (Nginx, Apache) with authentication. |
| **SQLite Default** | Local file access vulnerabilities. | Use PostgreSQL for production. Restrict file permissions. |
| **CORS Open by Default** | Cross-origin requests from any website. | Restrict CORS in production (see [FastAPI CORS](https://fastapi.tiangolo.com/tutorial/cors/)). |
| **No Rate Limiting for Scraper** | Potential for abuse if exposed. | Run the scraper on a **private server** (not publicly accessible). |
| **User Input in Logs** | Sensitive data may be logged. | Avoid logging user inputs. Use `repr()` for strings. |

### Example: Restrict CORS in Production
```python
from fastapi.middleware.cors import CORSMiddleware

app.add_middleware(
    CORSMiddleware,
    allow_origins=["https://yourdomain.com"],  # Restrict to your domain
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
```

---

## 📌 Best Practices for Deployments

### 1. Use HTTPS
- **Always use HTTPS** in production to encrypt traffic.
- Use **Let’s Encrypt** for free SSL certificates:
  ```bash
  sudo apt install certbot python3-certbot-nginx
  sudo certbot --nginx -d yourdomain.com
  ```

### 2. Restrict Access
- **IP Whitelisting**: Restrict access to trusted IPs (e.g., your office, VPN).
- **Authentication**: Use a reverse proxy with **Basic Auth** or **OAuth2**. 
- **Firewall**: Block unnecessary ports (e.g., only allow 80/443).

### 3. Monitor and Log
- **Enable audit logging** (already enabled by default).
- **Monitor logs** for suspicious activity:
  ```bash
  tail -f audit/scrape_log.csv
  tail -f audit/errors.log
  ```
- **Set up alerts** for failed login attempts or rate limit hits.

### 4. Keep Dependencies Updated
- Regularly update dependencies:
  ```bash
  pip install -r requirements.txt --upgrade
  pip list --outdated
  ```
- Use `dependabot` for automated dependency updates.

### 5. Backup Data
- **Regular backups** of the database:
  ```bash
  # SQLite
  cp data/open_omniscience.db data/open_omniscience_backup.db

  # PostgreSQL
  pg_dump -U open_omniscience -d open_omniscience > open_omniscience_backup.sql
  ```
- **Test restores** to ensure backups are valid.

### 6. Harden the Server
- **Disable root login** (SSH):
  ```bash
  sudo sed -i 's/PermitRootLogin yes/PermitRootLogin no/' /etc/ssh/sshd_config
  sudo systemctl restart sshd
  ```
- **Use a firewall** (UFW):
  ```bash
  sudo ufw allow 22/tcp   # SSH
  sudo ufw allow 80/tcp   # HTTP
  sudo ufw allow 443/tcp  # HTTPS
  sudo ufw enable
  ```
- **Keep the OS updated**:
  ```bash
  sudo apt update && sudo apt upgrade -y
  ```

---

## 📞 Contact

For **security-related inquiries**, contact us at:
- **Email:** `open-omniscience@ideotion.com`
- **GPG Key:** [Our GPG key](https://ideotion.com/security.asc) (for encrypted reports).

For **general inquiries**, use:
- **GitHub Issues:** [https://github.com/ideotion/Open-Omniscience/issues](https://github.com/ideotion/Open-Omniscience/issues)
- **Email:** `open-omniscience@ideotion.com`

---

## 📄 License
This security policy is part of the **Open Omniscience** project, licensed under the [MIT License](LICENSE).

---
**© 2026 Ideotion. All rights reserved.**