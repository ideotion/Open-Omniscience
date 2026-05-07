# Ethical Guidelines for Open Omniscience

This document outlines the **ethical principles, compliance requirements, and best practices** for using and contributing to Open Omniscience. Adherence to these guidelines is **mandatory** for all users and developers.

Open Omniscience aligns with the **Munich Charter**, a foundational set of principles for journalists adopted in 1971. These principles are integrated below to guide the ethical use of this platform.

---

## 📜 Munich Charter: Declaration of Duties and Rights

### Preamble
The right to information, to freedom of expression and criticism is one of the fundamental rights of humanity. All rights and duties of those using Open Omniscience originate from the public's right to be informed on events and opinions. The responsibility of users towards the public excels any other responsibility, particularly towards employers and public authorities. The mission of information necessarily includes restrictions which users must spontaneously impose on themselves. This is the object of the declaration of duties formulated below.

A user of Open Omniscience can respect these duties while exercising its use only if conditions of independence and professional dignity effectively exist. This is the object of the following declaration of rights.

---

### 📋 Declaration of Duties
The essential obligations of users of Open Omniscience engaged in gathering, editing, and analyzing information are:

1. **Respect for Truth:**
   To respect truth whatever the consequences to oneself, because of the right of the public to know the truth.

2. **Defend Freedom of Information:**
   To defend freedom of information, comment, and criticism.

3. **Verify Sources:**
   To report only on facts of which the origin is known; not to suppress essential information nor alter texts and documents.

4. **Fair Methods:**
   Not to use unfair methods to obtain information, photographs, or documents.

5. **Respect Privacy:**
   To restrict oneself to the respect of privacy.

6. **Correct Inaccuracies:**
   To rectify any published information which is found to be inaccurate.

7. **Professional Secrecy:**
   To observe professional secrecy and not to divulge the source of information obtained in confidence.

8. **Avoid Professional Offenses:**
   To regard as grave professional offenses:
   - Plagiarism
   - Calumny, slander, libel, and unfounded accusations
   - The acceptance of bribes in any form in consideration of either publication or suppression of information

9. **Separation from Advertising/Propaganda:**
   Never to confuse the use of Open Omniscience with that of advertisement sales or propagandist activities and to refuse any direct or indirect orders from advertisers.

10. **Resist Pressure:**
    To resist every pressure and to accept orders only from responsible persons aligned with the ethical use of the platform.

---

### 📜 Declaration of Rights

Users of Open Omniscience claim:

1. **Free Access to Information:**
   Free access to all information sources, and the right to freely inquire on all events conditioning public life. Therefore, secrecy of public or private affairs may be opposed to users only in exceptional cases and for clearly expressed motives.

2. **Refuse Unethical Subordination:**
   The right to refuse subordination to anything contrary to the general policy of Open Omniscience, as well as any subordination not clearly implicated by this policy.

3. **Conscience and Conviction:**
   A user cannot be compelled to perform an act or to express an opinion contrary to their convictions or conscience.

4. **Transparency in Decision-Making:**
   The community must be informed of all important decisions which may influence the project. It should at least be consulted before a definitive decision on all matters related to the project's direction is taken.

5. **Fair Compensation and Independence:**
   Taking into account their functions and responsibilities, contributors are entitled to recognition and conditions that ensure the material and moral security of their work, as well as economic independence.

---

## 🌍 Core Principles of Open Omniscience

1. **Respect for Source Terms:** Always comply with the `robots.txt` directives and terms of service of scraped websites.
2. **Rate Limiting:** Implement and respect configurable delays between requests to avoid overloading servers.
   - Default: **1 request per second per domain** (adjustable in `sources.yml`).
   - Sensitive domains (e.g., government, small news sites): **3 seconds or more**.
3. **Transparency:** Maintain detailed audit logs of all scraping activities in `audit/scrape_log.csv`.
4. **Data Minimization:** Only collect and store data necessary for the platform's core functionality (URL, title, content, metadata).
5. **Non-Malicious Use:** Open Omniscience must not be used for:
   - Spam or harassment.
   - Illegal activities (e.g., hacking, copyright infringement).
   - Commercial exploitation without permission.
6. **User-Agent Rotation:** Use a clear, identifiable User-Agent string (e.g., `OpenOmniscience/1.0 (+https://github.com/ideotion/Open-Omniscience)`).
7. **IP Throttling:** Avoid rapid-fire requests from a single IP. Use proxies or distributed scraping if scaling up.

---

## ✅ Compliance Checklist

Before scraping a new source, verify the following:
- [ ] The domain is **not** in the [Do Not Scrape List](#do-not-scrape-list).
- [ ] The `robots.txt` file allows scraping (check [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] The source does **not** require authentication or violate paywalls.
- [ ] Rate limits are configured to avoid **>1 request per second** by default (adjust for sensitive domains).
- [ ] The User-Agent string identifies Open Omniscience (e.g., `OpenOmniscience/1.0`).
- [ ] Audit logging is enabled for all requests.

---

## 🚫 Do Not Scrape List

The following domains are **explicitly prohibited** from scraping due to legal, ethical, or technical restrictions:

### Paywalled Content
- `nytimes.com` (New York Times)
- `ft.com` (Financial Times)
- `wsj.com` (Wall Street Journal - partial paywall)
- `thetimes.co.uk` (The Times)
- `bloomberg.com` (Bloomberg - partial paywall)
- `economist.com` (The Economist)
- `washingtonpost.com` (partial paywall)
- `latimes.com` (Los Angeles Times)
- `chicagotribune.com` (Chicago Tribune)
- `bostonglobe.com` (Boston Globe)

### Social Media Platforms
- `facebook.com`
- `twitter.com` (X)
- `instagram.com`
- `linkedin.com`
- `reddit.com`
- `tiktok.com`
- `youtube.com` (for video content; metadata may be allowed via API)
- `whatsapp.com`
- `telegram.org`

### Private or Sensitive Data
- Government databases (e.g., `*.gov`, `*.mil` unless explicitly public)
- Medical records (e.g., `*.health`, `*.medical`)
- Financial records (e.g., `*.bank`, `*.finance` unless public)
- Personal data repositories (e.g., `*.personal`, `*.private`)

### Known for Disinformation or Illegal Content
- `infowars.com`
- `breitbart.com`
- `dailymail.co.uk` (controversial, often sensationalist)
- `sputniknews.com` (state-sponsored propaganda)
- `rt.com` (state-sponsored propaganda)
- `4chan.org`
- `8kun.top` (formerly 8chan)

### Technical Restrictions
- Domains with **aggressive rate-limiting** (e.g., `github.com`, `stackoverflow.com`).
- Domains that **block scrapers** (e.g., `cloudflare.com`-protected sites without bypass).
- **API-only sources** (e.g., `twitter.com/api`, `reddit.com/api` - use official APIs instead).

> **Note:** This list is not exhaustive. Users must exercise **due diligence** and **critical judgment** when adding new sources. When in doubt, **do not scrape**.

---

## 📊 Audit and Accountability

All scraping activities **must** be logged in the `audit/` directory. Logs should include:
- Timestamp (ISO 8601 format, UTC)
- Target URL
- Source domain
- HTTP status code
- Rate limit applied (ms)
- Number of retries
- User-Agent string

### Example Log Format (CSV):
```csv
Timestamp,URL,Source,Status,Rate_Limit_ms,Retries,User_Agent
2026-05-07T12:00:00Z,https://example.com/article,Example News,200,1000,0,OpenOmniscience/1.0
2026-05-07T12:00:02Z,https://another-example.com/news,Another News,BLOCKED_BY_ROBOTS,2000,0,OpenOmniscience/1.0
```

### Error Logging:
Errors (e.g., timeouts, connection failures) must be logged to `audit/errors.log` with:
- Timestamp
- Error type
- Affected URL
- Stack trace (for debugging)

---

## 🔒 Privacy and Data Protection

- **No User Tracking:** Open Omniscience does **not** collect or store:
  - User IPs
  - Search histories
  - Personal data
- **Local-Only:** All data remains on the user's machine. No cloud dependency by default.
- **Optional Encryption:** Users may enable SQLite encryption (SQLCipher) for sensitive datasets.
- **GDPR Compliance:** If scraping EU-based sources:
  - Anonymize personal data (e.g., names, emails) in stored content.
  - Respect the right to erasure (delete data upon request).

---

## 🌍 Legal Considerations

- **Copyright:** Respect copyright laws. Only scrape and store content for:
  - **Personal, non-commercial** analysis.
  - **Fair use** (e.g., criticism, commentary, research).
  - **Transformative purposes** (e.g., aggregating for investigative journalism).
- **GDPR Compliance:** If processing data from EU citizens:
  - Minimize personal data collection.
  - Provide a way for individuals to request deletion of their data.
- **Jurisdiction:** Users are responsible for complying with laws in their jurisdiction, including:
  - **Computer Fraud and Abuse Act (CFAA)** (US)
  - **General Data Protection Regulation (GDPR)** (EU)
  - **Copyright Act** (various countries)

---

## 🛡️ Technical Safeguards

To prevent misuse and ensure ethical scraping, Open Omniscience implements the following safeguards:

1. **Rate Limiting:**
   - Default: 1 request per second per domain.
   - Configurable per source in `sources.yml`.

2. **Robots.txt Compliance:**
   - Automatically checks `robots.txt` before scraping.
   - Respects `Disallow` directives.

3. **User-Agent Identification:**
   - Uses `OpenOmniscience/1.0` by default.
   - Can be customized in `configs/settings.yaml`.

4. **Error Handling:**
   - Retries failed requests with exponential backoff.
   - Logs all errors for review.

5. **Duplicate Detection:**
   - Uses URL canonicalization and content hashing to avoid redundant scraping.

6. **Audit Trails:**
   - Logs all scraping activities for transparency and accountability.

---

## 📢 Reporting Violations

If you encounter or suspect unethical use of Open Omniscience:
1. **Stop** the violating activity immediately.
2. **Document** the incident (e.g., screenshots, logs, timestamps).
3. **Report** to the maintainers via:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (for public reports)
   - Email: `ethics@ideotion.org` (for sensitive reports)

---

## 📅 Review and Updates

This document will be **regularly reviewed and updated** to reflect:
- New ethical challenges (e.g., AI-generated content, deepfakes).
- Legal requirements (e.g., changes to copyright or data protection laws).
- Community feedback (e.g., reports of misuse or suggestions for improvement).

### Version History
| Version | Date       | Changes                                                                 |
|---------|------------|-------------------------------------------------------------------------|
| 1.0     | 2026-05-07 | Initial version. Added Do Not Scrape List, audit logging, and GDPR notes. |
| 1.1     | 2026-05-07 | Added User-Agent rotation, IP throttling, and technical safeguards.     |

---

## 📌 Best Practices for Contributors

1. **Test Ethically:**
   - Always test scraping on a small scale before scaling up.
   - Use `localhost` or staging environments where possible.

2. **Document Sources:**
   - Add comments in `sources.yml` explaining why a source is included/excluded.
   - Note any special scraping requirements (e.g., custom selectors).

3. **Respect Opt-Outs:**
   - If a source requests to be removed, comply immediately.
   - Add the domain to the Do Not Scrape List.

4. **Minimize Impact:**
   - Scrape during off-peak hours where possible.
   - Cache responses to avoid repeated requests for the same content.

5. **Stay Updated:**
   - Regularly check `robots.txt` for changes.
   - Monitor for legal updates (e.g., new copyright laws).

---
**Remember:** Ethical scraping is not just a legal obligation—it’s a **moral responsibility**. By using Open Omniscience, you commit to upholding these principles.