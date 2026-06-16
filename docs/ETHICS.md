# Ethical Guidelines for Open Omniscience

> **Status (0.0.9 audit, 2026-06):** the software is a working, tested pre-alpha
> (see the repo README for what works today). Early releases carried a
> "not functional" banner here; that stopped being true and was removed —
> these guidelines are **in force now**, not a future reference.
> *Historical note:* the very first concept releases (pre-0.0.4) started from
> the HTTrack website copier; the current codebase is a complete rewrite and
> shares no code with it.

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
7. **IP Throttling:** Avoid rapid-fire requests from a single IP. Respect server fair use.

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


### Social Media Platforms


### Private or Sensitive Data
- Government databases (e.g., `*.gov`, `*.mil` unless explicitly public)
- Medical records (e.g., `*.health`, `*.medical`)
- Financial records (e.g., `*.bank`, `*.finance` unless public)
- Personal data repositories (e.g., `*.personal`, `*.private`)

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

## 📐 Honest metrics — no fabricated scores

Honesty by construction: the app never presents a **composite trust / quality /
credibility score**. Every signal it computes carries its method, a caveat and its
*n*; a card that tried to ship a blended score is mechanically rejected by the card
schema. Dormant scoring columns (`credibility_score`, `political_bias`) are kept
NULL and never serialised to any API response.

**One intentional, narrow exemption — `reliability_score`.** This per-source `1–10`
field is **operator-asserted provenance metadata**: a number *you* (the operator)
set per source via config or CSV import. It is **never computed, never defaulted,
and never derived from article data** by the app — the earlier fabricated `=5`
default was removed (NULLed by migration `f4b5c6d7e8a9`). Because it is your own
assertion (not a verdict the tool manufactured), it is exposed in the source list
and labelled **"operator-set, not computed"** wherever it appears; a briefing card
can still never present it as a score. A repo invariant
(`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`)
keeps it that way, so it cannot quietly become a computed quality verdict.

---

## 📢 Reporting Violations

If you encounter or suspect unethical use of Open Omniscience:
1. **Stop** the violating activity immediately.
2. **Document** the incident (e.g., screenshots, logs, timestamps).
3. **Report** to the maintainers via:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (for public reports)
   - Email: `open-omniscience@ideotion.com` (for sensitive reports)

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

---

# Compliance, licensing & third-party notices

The legal and attribution companion to the ethical principles above.

**In this part:**
- [GPLv3 Compliance Guide](#gplv3-compliance-guide)
- [Third-Party Notices and Attributions](#third-party-notices-and-attributions)


---

## GPLv3 Compliance Guide

This section outlines the compliance of Open Omniscience with the GNU General
Public License Version 3 (GPLv3). It applies to the working software as shipped.

---

### 📜 Open Omniscience License

**License:** GNU General Public License Version 3 (GPLv3)  
**Copyright:** © 2026 Ideotion  
**License File:** [LICENSE](LICENSE)

Open Omniscience is fully licensed under GPLv3, which provides users with the
following freedoms (the software is a working, tested pre-alpha — these apply now):

1. **Freedom 0:** The freedom to run the program for any purpose
2. **Freedom 1:** The freedom to study how the program works and change it
3. **Freedom 2:** The freedom to redistribute copies
4. **Freedom 3:** The freedom to distribute modified versions

---

### ✅ GPLv3 Compliance Checklist

#### For Open Omniscience Project

- [x] **License File**: Full GPLv3 text included in [LICENSE](LICENSE)
- [x] **Source Code Availability**: All source code is publicly available in this repository
- [x] **Copyright Notices**: All files include proper copyright notices
- [x] **License Headers**: All source files include GPLv3 license headers
- [x] **No Additional Restrictions**: No further restrictions beyond GPLv3 are imposed
- [x] **Modified Versions**: All modifications carry prominent notices (Section 5a)
- [x] **Installation Information**: Not applicable (not a User Product as defined in GPLv3)

---

### 📦 Distribution Compliance

#### Source Code Distribution

When distributing Open Omniscience source code:

1. ✅ **Include LICENSE file**: The full GPLv3 license text must be included
2. ✅ **Include ETHICS.md**: Third-party attributions must be included
3. ✅ **Preserve Headers**: All source files must retain their GPLv3 headers
4. ✅ **Preserve Copyrights**: All copyright notices must be preserved
5. ✅ **Document Changes**: Any modifications must be documented

#### Binary Distribution

When distributing Open Omniscience in binary form:

1. ✅ **Include Source Code**: Must provide Corresponding Source (Section 6)
2. ✅ **Include LICENSE**: Full GPLv3 text must be included
3. ✅ **Include ETHICS.md**: Third-party attributions must be included
4. ✅ **Document Changes**: Any modifications must be documented
5. ✅ **No Additional Restrictions**: Cannot add restrictions beyond GPLv3

#### User Product Compliance

If Open Omniscience is distributed as part of a User Product (consumer device):

1. ✅ **Installation Information**: Must provide information to install modified versions (Section 6)
2. ✅ **Source Code Availability**: Must provide Corresponding Source
3. ✅ **No Tivoization**: Cannot prevent users from installing modified versions

**Note:** Open Omniscience itself is not a User Product, but if you embed it in one, these requirements apply.

---

### 🔍 Verification Steps

#### For Developers

1. **Check License Headers**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **Verify LICENSE File**
   ```bash
   head -5 LICENSE
   ```

3. **Check NOTICES File**
   ```bash
   cat ETHICS.md
   ```

4. **Verify No Proprietary Code**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### For Users

1. **Check License**
   ```bash
   cat LICENSE | head -5
   ```

2. **Review Attributions**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 Common Compliance Questions

#### Q: Can I use Open Omniscience for commercial purposes?
**A:** Yes! GPLv3 allows commercial use. However, any modified versions you distribute must also be licensed under GPLv3, and you must provide source code.

#### Q: Can I use Open Omniscience in proprietary software?
**A:** No. GPLv3 requires that derivative works also be licensed under GPLv3. You cannot incorporate Open Omniscience into a closed-source proprietary application.

#### Q: Do I need to release my modifications?
**A:** Only if you distribute them. If you modify Open Omniscience for your own use and don't distribute it, you don't need to release your modifications.

#### Q: What about the Python dependencies?
**A:** Python dependencies (FastAPI, SQLAlchemy, etc.) are separate works with their own licenses. Open Omniscience's GPLv3 license does not affect them. See [ETHICS.md](ETHICS.md) for details.

#### Q: What about the data I scrape?
**A:** The GPLv3 license applies only to the Open Omniscience software itself, not to the data you collect. You are responsible for complying with the copyright and terms of service of the websites you scrape.

---

### 📞 Reporting Compliance Issues

If you have questions or concerns about GPLv3 compliance:

- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 Resources

- [Full GPLv3 License Text](LICENSE)
- [GNU GPLv3 Official Website](https://www.gnu.org/licenses/gpl-3.0.html)
- [GNU GPLv3 FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [Third-Party Notices](ETHICS.md)

---

**Last Updated:** 2026-06-14


---

## Third-Party Notices and Attributions

This section contains notices and attributions for third-party software and
libraries used by Open Omniscience. (*Historical note:* the pre-0.0.4 concept
releases started from HTTrack; the current codebase is a complete rewrite and
no HTTrack code remains.)

---

### 📦 Python Dependencies

Open Omniscience **uses** the following Python packages, each under its own
license. The authoritative, single-sourced list is [`pyproject.toml`](../pyproject.toml);
run `pip show <package>` (or `pip-licenses`) to confirm the license of any
installed version. **Every dependency is FOSS and GPLv3-compatible** — that is an
inclusion requirement (see the FOSS-only invariant in `docs/DESIGN.md`).

**Core (always installed):**

| Package | License | Purpose |
|---------|---------|---------|
| FastAPI | MIT | Web API framework |
| Uvicorn | BSD-3-Clause | ASGI server |
| Jinja2 | BSD-3-Clause | Server-side templating |
| SlowAPI | MIT | Rate limiting |
| Prometheus Client | Apache-2.0 | Metrics endpoint |
| SQLAlchemy | MIT | Database ORM |
| Alembic | MIT | Schema migrations |
| sqlcipher3 | Zlib/BSD-style | At-rest SQLCipher encryption |
| Requests | Apache-2.0 | HTTP client (ethical fetcher) |
| httpx | BSD-3-Clause | HTTP client |
| BeautifulSoup4 | MIT | HTML parsing |
| lxml | BSD-3-Clause | XML/HTML parsing |
| feedparser | BSD-2-Clause | RSS/Atom parsing |
| trafilatura | Apache-2.0 | Article extraction |
| Pydantic | MIT | Data validation |
| PyYAML | MIT | Config parsing |
| Bleach | Apache-2.0 | HTML sanitization |
| bcrypt | Apache-2.0 | Password-hashing primitive |
| defusedxml | PSF-2.0 | Untrusted-XML hardening (Wikipedia dumps) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Ed25519 signatures + Merkle trees |
| Pillow | HPND (MIT-CMU) | EXIF / image metadata |
| structlog | MIT OR Apache-2.0 | Structured logging |
| python-dateutil | Apache-2.0 / BSD | Date parsing |
| tenacity | Apache-2.0 | Retry / backoff |
| cachetools | MIT | In-memory caching |
| orjson | Apache-2.0 OR MIT (with an MPL-2.0 component) | Fast JSON |
| psutil | BSD-3-Clause | Hardware vitals |

**Optional extras (installed on demand):**

| Extra | Packages | License | Purpose |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | Statistics / graphs |
| `analysis` | nltk | Apache-2.0 | Tokenization |
| `analysis` | vaderSentiment | MIT | Lexicon sentiment (English-only) |
| `nlp` | spaCy | MIT | NLP pipeline |
| `crypto` | python-gnupg | LGPL-3.0 | GPG integration |
| `pqc` | pqcrypto | MIT | Post-quantum (ML-DSA) signatures |
| `timestamping` | opentimestamps | LGPL-3.0 | Bitcoin-anchored timestamps |
| `compression` | zstandard, lz4 | BSD | Backup compression |

The local LLM is the **external Ollama** binary (MIT), reached over loopback
HTTP — no model weights or inference libraries are bundled or shipped.

#### Compliance Notes

- Each dependency is a **separate work** under its own license; Open
  Omniscience's GPLv3 does not extend to it, and its license does not restrict
  Open Omniscience.
- All listed licenses are **permissive or weak-copyleft and GPLv3-compatible**
  (the LGPL-3.0 extras `python-gnupg`/`opentimestamps`, and the MPL-2.0 component
  of `orjson`, are each compatible with GPL-3.0). FOSS + GPLv3-compatibility is a
  hard inclusion requirement.
- Users must comply with each dependency's individual license; `pip show <pkg>`
  prints it.

---

### 📄 Fonts and Icons

| Resource | License | Source |
|----------|---------|--------|
| Project Icon | MIT (original) | Included in project |

---

### 📝 Data Sources

Open Omniscience aggregates data from various news sources. Users are responsible for:

1. Respecting the **copyright** of scraped content
2. Complying with **terms of service** of each website
3. Following **robots.txt** directives
4. Adhering to **ethical scraping** guidelines (see [ETHICS.md](ETHICS.md))

**Note:** The GPLv3 license of Open Omniscience does **not** apply to the data scraped using the software. Users are solely responsible for ensuring their use of scraped data complies with all applicable laws and regulations.

---

### 🔍 Verification

To verify compliance with third-party licenses:

1. **Python Dependencies**: Run `pip list` to see all installed packages and their licenses
2. **Source Code**: All Open Omniscience source code is available in this repository

---

### 📞 Contact

For questions about third-party licenses or compliance:
- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Last Updated:** 2026-06-14

