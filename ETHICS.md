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
3. **Transparency:** Maintain detailed audit logs of all scraping activities.
4. **Data Minimization:** Only collect and store data necessary for the platform's core functionality.
5. **Non-Malicious Use:** Open Omniscience must not be used for spam, harassment, or any illegal activities.

---

## ✅ Compliance Checklist

Before scraping a new source, verify the following:
- [ ] The domain is **not** in the [Do Not Scrape List](#do-not-scrape-list).
- [ ] The `robots.txt` file allows scraping (check [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] The source does **not** require authentication or violate paywalls.
- [ ] Rate limits are configured to avoid **>1 request per second** by default.
- [ ] The User-Agent string identifies Open Omniscience (e.g., `OpenOmniscience/1.0`).

---

## 🚫 Do Not Scrape List

The following domains are **explicitly prohibited** from scraping due to legal, ethical, or technical restrictions:
- Paywalled content (e.g., `nytimes.com`, `ft.com`).
- Social media platforms (e.g., `facebook.com`, `twitter.com`).
- Private or sensitive data sources (e.g., government databases, medical records).
- Domains known for disinformation or illegal content.

> **Note:** This list is not exhaustive. Users must exercise **due diligence** and **critical judgment** when adding new sources.

---

## 📊 Audit and Accountability

All scraping activities **must** be logged in the `audit/` directory. Logs should include:
- Timestamp
- Target URL
- Source domain
- HTTP status code
- Rate limit applied
- User-Agent string

Example log format (CSV):
```csv
Timestamp,URL,Source,Status,Rate_Limit_ms,Retries,User_Agent
2026-05-07T12:00:00Z,https://example.com/article,Example News,200,1000,0,OpenOmniscience/1.0
```

---

## 🔒 Privacy and Data Protection

- **No User Tracking:** Open Omniscience does **not** collect or store user IPs, search histories, or personal data.
- **Local-Only:** All data remains on the user's machine. No cloud dependency.
- **Optional Encryption:** Users may enable SQLite encryption (SQLCipher) for sensitive datasets.

---

## 🌍 Legal Considerations

- **Copyright:** Respect copyright laws. Only scrape and store content for **personal, non-commercial** analysis.
- **GDPR Compliance:** If scraping EU-based sources, ensure compliance with GDPR (e.g., anonymize personal data).
- **Jurisdiction:** Users are responsible for complying with laws in their jurisdiction.

---

## 📢 Reporting Violations

If you encounter or suspect unethical use of Open Omniscience:
1. **Stop** the violating activity immediately.
2. **Document** the incident (e.g., screenshots, logs).
3. **Report** to the maintainers via [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues).

---

## 📅 Review and Updates

This document will be **regularly reviewed and updated** to reflect new ethical challenges, legal requirements, and community feedback.
