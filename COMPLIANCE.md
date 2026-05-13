# GPLv3 Compliance Guide

This document outlines Open Omniscience's compliance with the GNU General Public License Version 3 (GPLv3).

---

## 📜 Open Omniscience License

**License:** GNU General Public License Version 3 (GPLv3)  
**Copyright:** © 2026 Ideotion  
**License File:** [LICENSE](LICENSE)

Open Omniscience is fully licensed under GPLv3, which provides users with the following freedoms:

1. **Freedom 0:** The freedom to run the program for any purpose
2. **Freedom 1:** The freedom to study how the program works and change it
3. **Freedom 2:** The freedom to redistribute copies
4. **Freedom 3:** The freedom to distribute modified versions

---

## ✅ GPLv3 Compliance Checklist

### For Open Omniscience Project

- [x] **License File**: Full GPLv3 text included in [LICENSE](LICENSE)
- [x] **Source Code Availability**: All source code is publicly available in this repository
- [x] **Copyright Notices**: All files include proper copyright notices
- [x] **License Headers**: All source files include GPLv3 license headers
- [x] **No Additional Restrictions**: No further restrictions beyond GPLv3 are imposed
- [x] **Modified Versions**: All modifications carry prominent notices (Section 5a)
- [x] **Installation Information**: Not applicable (not a User Product as defined in GPLv3)

---

## 📦 Distribution Compliance

### Source Code Distribution

When distributing Open Omniscience source code:

1. ✅ **Include LICENSE file**: The full GPLv3 license text must be included
2. ✅ **Include NOTICES.md**: Third-party attributions must be included
3. ✅ **Preserve Headers**: All source files must retain their GPLv3 headers
4. ✅ **Preserve Copyrights**: All copyright notices must be preserved
5. ✅ **Document Changes**: Any modifications must be documented

### Binary Distribution

When distributing Open Omniscience in binary form:

1. ✅ **Include Source Code**: Must provide Corresponding Source (Section 6)
2. ✅ **Include LICENSE**: Full GPLv3 text must be included
3. ✅ **Include NOTICES.md**: Third-party attributions must be included
4. ✅ **Document Changes**: Any modifications must be documented
5. ✅ **No Additional Restrictions**: Cannot add restrictions beyond GPLv3

### User Product Compliance

If Open Omniscience is distributed as part of a User Product (consumer device):

1. ✅ **Installation Information**: Must provide information to install modified versions (Section 6)
2. ✅ **Source Code Availability**: Must provide Corresponding Source
3. ✅ **No Tivoization**: Cannot prevent users from installing modified versions

**Note:** Open Omniscience itself is not a User Product, but if you embed it in one, these requirements apply.

---

## 🔍 Verification Steps

### For Developers

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
   cat NOTICES.md
   ```

4. **Verify No Proprietary Code**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

### For Users

1. **Check License**
   ```bash
   cat LICENSE | head -5
   ```

2. **Review Attributions**
   ```bash
   cat NOTICES.md
   ```

---

## 📝 Common Compliance Questions

### Q: Can I use Open Omniscience for commercial purposes?
**A:** Yes! GPLv3 allows commercial use. However, any modified versions you distribute must also be licensed under GPLv3, and you must provide source code.

### Q: Can I use Open Omniscience in proprietary software?
**A:** No. GPLv3 requires that derivative works also be licensed under GPLv3. You cannot incorporate Open Omniscience into a closed-source proprietary application.

### Q: Do I need to release my modifications?
**A:** Only if you distribute them. If you modify Open Omniscience for your own use and don't distribute it, you don't need to release your modifications.

### Q: What about the Python dependencies?
**A:** Python dependencies (FastAPI, SQLAlchemy, etc.) are separate works with their own licenses. Open Omniscience's GPLv3 license does not affect them. See [NOTICES.md](NOTICES.md) for details.

### Q: What about the data I scrape?
**A:** The GPLv3 license applies only to the Open Omniscience software itself, not to the data you collect. You are responsible for complying with the copyright and terms of service of the websites you scrape.

---

## 📞 Reporting Compliance Issues

If you have questions or concerns about GPLv3 compliance:

- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues

---

## 📚 Resources

- [Full GPLv3 License Text](LICENSE)
- [GNU GPLv3 Official Website](https://www.gnu.org/licenses/gpl-3.0.html)
- [GNU GPLv3 FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [Third-Party Notices](NOTICES.md)

---

**Last Updated:** June 2025
