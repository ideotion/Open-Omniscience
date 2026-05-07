# Contributing to Open Omniscience

**First off, thanks for taking the time to contribute!** 🎉

Open Omniscience is an **open-source project** dedicated to **ethical, global intelligence gathering** for investigative journalism. We welcome contributions from everyone, whether you're a **developer, journalist, designer, or ethical hacker**.

This document outlines how to **contribute** to Open Omniscience, including:
- [How to Get Started](#-how-to-get-started)
- [Types of Contributions](#-types-of-contributions)
- [Development Setup](#-development-setup)
- [Submitting Changes](#-submitting-changes)
- [Code of Conduct](#-code-of-conduct)
- [Recognition](#-recognition)

---

## 🚀 How to Get Started

### 1. Familiarize Yourself with the Project
- Read the [README.md](README.md) to understand the **mission, features, and architecture**.
- Review the [ETHICS.md](ETHICS.md) to ensure you understand our **ethical guidelines**.
- Explore the [User Guide](docs/USER_GUIDE.md) and [Developer Guide](docs/DEVELOPER_GUIDE.md).

### 2. Join the Community
- **GitHub Discussions**: Ask questions, share ideas, and discuss features in [Discussions](https://github.com/ideotion/Open-Omniscience/discussions).
- **GitHub Issues**: Report bugs or request features in [Issues](https://github.com/ideotion/Open-Omniscience/issues).
- **Email**: Contact us at `contact@ideotion.org` for private inquiries.

### 3. Find a Way to Contribute
- **Browse open issues**: Look for issues labeled [`good first issue`](https://github.com/ideotion/Open-Omniscience/labels/good%20first%20issue) or [`help wanted`](https://github.com/ideotion/Open-Omniscience/labels/help%20wanted).
- **Suggest new features**: Open an issue with your idea.
- **Improve documentation**: Fix typos, add examples, or write tutorials.
- **Add new sources**: Help expand our list of **ethical, scrapable news sources**.

---

## 🌟 Types of Contributions

| Type | Description | Examples |
|------|-------------|----------|
| **Code** | Improve the scraper, API, or frontend. | Add Boolean search, optimize database queries, fix bugs. |
| **Documentation** | Improve guides, tutorials, or API docs. | Update README.md, add examples, write tutorials. |
| **Testing** | Add or improve tests. | Write unit tests, integration tests, or end-to-end tests. |
| **New Sources** | Add ethical news sources to `sources.yml`. | Add local news outlets, niche blogs, or multilingual sources. |
| **UI/UX** | Improve the frontend design or usability. | Redesign the GUI, add dark mode, improve accessibility. |
| **Ethical Reviews** | Audit sources for compliance. | Check `robots.txt`, update the Do Not Scrape List. |
| **Community** | Help others, answer questions. | Respond to GitHub Discussions, review PRs. |
| **Translations** | Translate the UI or docs. | Add support for non-English languages. |

---

## 💻 Development Setup

### Prerequisites
- **Python 3.10+**
- **Git**
- **PostgreSQL** (optional, for production testing)

### Step-by-Step Setup
1. **Fork the repository**:
   ```bash
   git clone https://github.com/your-username/Open-Omniscience
   cd Open-Omniscience
   ```
2. **Set up a virtual environment**:
   ```bash
   python -m venv venv
   source venv/bin/activate  # Linux/macOS
   # OR
   .\venv\Scripts\activate   # Windows
   ```
3. **Install dependencies**:
   ```bash
   pip install -r requirements.txt
   pip install pytest pytest-mock black flake8 isort  # Dev dependencies
   ```
4. **Initialize the database**:
   ```bash
   mkdir -p data/
   ```
   For PostgreSQL, see [DATABASE.md](docs/DATABASE.md).
5. **Start the development server**:
   ```bash
   uvicorn src.api.main:app --reload
   ```
6. **Run tests**:
   ```bash
   pytest tests/
   ```

---

## 📤 Submitting Changes

### 1. Create a Feature Branch
- Use a **descriptive branch name**:
  ```bash
  git checkout -b feature/add-boolean-search
  git checkout -b fix/scraper-rate-limiting
  git checkout -b docs/update-readme
  ```

### 2. Make Your Changes
- Follow the **code style** (PEP 8 for Python, Airbnb for JavaScript).
- **Document your changes** (comments, docstrings, README updates).
- **Add tests** for new features or bug fixes.
- **Update the changelog** (if applicable).

### 3. Commit Your Changes
- Use **clear, descriptive commit messages**:
  ```
  git commit -m "Add Boolean search support (AND, OR, NOT)"
  git commit -m "Fix scraper rate limiting for sensitive domains"
  ```
- Reference **related issues** in your commit message:
  ```
  git commit -m "Add new sources (closes #123)"
  ```

### 4. Push to Your Fork
```bash
git push origin feature/your-feature-name
```

### 5. Open a Pull Request
1. Go to the [Open Omniscience GitHub](https://github.com/ideotion/Open-Omniscience).
2. Click **"New Pull Request"**.
3. Select your **feature branch** and the **main branch** of `ideotion/Open-Omniscience`.
4. Fill out the **PR template** (see below).
5. Click **"Create Pull Request"**.

### Pull Request Template
```markdown
## Description
[Brief description of the changes. What problem does this solve?]

## Related Issues
- Closes #[issue-number]
- Related to #[issue-number]

## Changes Made
- [ ] Added new feature
- [ ] Fixed bug
- [ ] Improved performance
- [ ] Updated documentation
- [ ] Added tests
- [ ] Other (describe):

## Testing
- [ ] All existing tests pass (`pytest tests/`)
- [ ] New tests added for the changes
- [ ] Manually tested the changes

## Screenshots (if applicable)
[Add screenshots for UI changes or visual output]

## Checklist
- [ ] Code follows the project's style (PEP 8, Airbnb JS).
- [ ] All tests pass.
- [ ] Documentation is updated (if needed).
- [ ] No sensitive data (API keys, passwords) is included.
- [ ] The changes are **ethically compliant** (see [ETHICS.md](ETHICS.md)).
```

### 6. Wait for Review
- A **maintainer** will review your PR within **7 days**.
- Address any **feedback** or **requested changes**.
- Once approved, your PR will be **merged** into the `main` branch.

---

## 📜 Code of Conduct

By participating in this project, you agree to abide by our **Code of Conduct**. Open Omniscience is dedicated to providing a **harassment-free experience** for everyone, regardless of:
- Gender, gender identity, or gender expression
- Sexual orientation
- Disability
- Physical appearance
- Body size
- Race, ethnicity, or nationality
- Age
- Religion
- Technology choices (e.g., editor, OS, programming language)

### Our Standards
Examples of behavior that contributes to a positive environment:
- **Being respectful** of differing viewpoints and experiences.
- **Giving and gracefully accepting** constructive feedback.
- **Focusing on what is best** for the community.
- **Showing empathy** towards other community members.

Examples of unacceptable behavior:
- **Trolling, insulting, or derogatory comments**.
- **Public or private harassment**.
- **Publishing others' private information** (e.g., email addresses) without permission.
- **Other conduct which could reasonably be considered inappropriate** in a professional setting.

### Enforcement
Violations of the Code of Conduct may result in:
- A **warning** from the maintainers.
- **Temporary or permanent ban** from the project.
- **Removal of contributions** (e.g., commits, issues, PRs).

To report a violation, contact `conduct@ideotion.org` or open an issue labeled `code-of-conduct`.

---

## 🏆 Recognition

All contributions are **valued and recognized**. Here’s how we say thanks:

### 1. GitHub Contributors
- Your **GitHub profile** will appear in the [contributors list](https://github.com/ideotion/Open-Omniscience/graphs/contributors).

### 2. Changelog
- Your **name and contribution** will be listed in the `CHANGELOG.md` (coming soon).

### 3. Release Notes
- Major contributions will be highlighted in **release notes**.

### 4. Social Media
- We may **tweet or post** about significant contributions (with your permission).

### 5. Maintainer Status
- **Regular contributors** may be invited to become **maintainers** with write access to the repository.

---

## 📌 Guidelines for Specific Contributions

### Adding New Sources
1. **Check `robots.txt`**:
   - Visit `https://{domain}/robots.txt` and ensure scraping is allowed.
2. **Avoid paywalled/sensitive domains**:
   - See the [Do Not Scrape List](ETHICS.md#do-not-scrape-list).
3. **Test the source**:
   - Use the scraper to verify it works:
     ```bash
     python -c "from src.scraper.scraper import Scraper; s = Scraper(); print(s.scrape_source({'name': 'Test', 'domain': 'test.com', 'rss_url': 'https://test.com/rss', 'rate_limit_ms': 2000, 'enabled': True}))"
     ```
4. **Add metadata**:
   - Include `name`, `domain`, `rss_url` (if available), `rate_limit_ms`, `priority`, and `tags`.

### Reporting Bugs
1. **Check for duplicates**:
   - Search [existing issues](https://github.com/ideotion/Open-Omniscience/issues) before creating a new one.
2. **Provide details**:
   - **Steps to reproduce** the bug.
   - **Expected vs. actual behavior**.
   - **Screenshots or logs** (if applicable).
   - **Environment** (OS, Python version, browser, etc.).
3. **Use the bug report template**:
   ```markdown
   ## Description
   [Clear description of the bug]

   ## Steps to Reproduce
   1. [First step]
   2. [Second step]
   3. [Third step]

   ## Expected Behavior
   [What you expected to happen]

   ## Actual Behavior
   [What actually happened]

   ## Environment
   - OS: [e.g., Ubuntu 22.04]
   - Python: [e.g., 3.10.6]
   - Browser: [e.g., Chrome 110]
   ```

### Suggesting Features
1. **Check for duplicates**:
   - Search [existing issues](https://github.com/ideotion/Open-Omniscience/issues) for similar requests.
2. **Provide context**:
   - **Why is this feature needed?**
   - **How would it work?**
   - **What are the alternatives?**
3. **Use the feature request template**:
   ```markdown
   ## Feature Request
   [Clear description of the feature]

   ## Motivation
   [Why is this feature important?]

   ## Proposed Solution
   [How could this be implemented?]

   ## Alternatives
   [Are there other ways to achieve this?]
   ```

---

## 📚 Resources for Contributors

| Resource | Description |
|----------|-------------|
| [README.md](README.md) | Project overview, installation, and features. |
| [ETHICS.md](ETHICS.md) | Ethical guidelines and compliance. |
| [USER_GUIDE.md](docs/USER_GUIDE.md) | User guide for Open Omniscience. |
| [DEVELOPER_GUIDE.md](docs/DEVELOPER_GUIDE.md) | Development setup, architecture, and API docs. |
| [DATABASE.md](docs/DATABASE.md) | Database setup and configuration. |
| [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) | Report bugs or request features. |
| [GitHub Discussions](https://github.com/ideotion/Open-Omniscience/discussions) | Ask questions or share ideas. |

---

## 🙏 Thank You!
Your contributions help make Open Omniscience **better, more ethical, and more powerful** for everyone. Whether you're fixing a bug, adding a feature, or improving the docs, **we appreciate your help**!

**Happy coding!** 🚀

---
**© 2026 Ideotion. All rights reserved.**