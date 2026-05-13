# GPLv3 Compliance Guide

This document outlines Open Omniscience's compliance with the GNU General Public License Version 3 (GPLv3) and its relationship with HTTrack.

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

## 🔗 Relationship with HTTrack

### Current Status

**Open Omniscience does NOT contain HTTrack source code.**

The project uses HTTrack in the following ways:

1. **As an External Command-Line Tool**
   - The `pillar1/src/httrack_wrapper.py` module calls HTTrack as an external program
   - HTTrack must be installed separately on the user's system
   - No HTTrack source code is included in Open Omniscience

2. **Optional C Library Integration**
   - The wrapper can optionally load HTTrack's C library (`libhttrack.so`, `httrack.dll`, etc.)
   - This is for direct integration but still uses HTTrack as an external dependency

### Historical Context

Earlier versions of Open Omniscience may have included HTTrack C source code in the repository. This code has been **moved to the archive directory** (`archive/outdated/httrack_source/`) and is **no longer part of the active project**.

### HTTrack License

- **HTTrack Website:** https://www.httrack.com/
- **HTTrack Repository:** https://github.com/xroche/httrack
- **HTTrack License:** GNU General Public License Version 3 (GPLv3)

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

### For HTTrack Compliance

Since Open Omniscience uses HTTrack as an external dependency:

- [x] **License Compatibility**: Open Omniscience uses GPLv3, which is compatible with HTTrack's GPLv3
- [x] **No Source Code Distribution**: Open Omniscience does not distribute HTTrack source code
- [x] **Attribution**: Proper attribution is given to HTTrack in [NOTICES.md](NOTICES.md)
- [x] **Separate Work**: Open Omniscience is a separate work that uses HTTrack, not a modification of HTTrack

### For Users

When using Open Omniscience:

- [x] **HTTrack Installation**: Users must install HTTrack separately (not bundled)
- [x] **HTTrack License**: Users must comply with HTTrack's GPLv3 license when using it
- [x] **No Redistribution**: Open Omniscience does not redistribute HTTrack

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
   cat NOTICES.md | grep -A 5 "HTTrack"
   ```

4. **Verify No HTTrack Source Code**
   ```bash
   find . -name "*.c" -o -name "*.h" | grep -v archive | grep -v ".git"
   ```
   (Should return no results)

### For Users

1. **Verify HTTrack Installation**
   ```bash
   httrack --version
   ```

2. **Check License**
   ```bash
   cat LICENSE | head -5
   ```

3. **Review Attributions**
   ```bash
   cat NOTICES.md
   ```

---

## 📝 Common Compliance Questions

### Q: Can I use Open Omniscience without HTTrack?
**A:** Yes. While Open Omniscience is designed to work with HTTrack, the HTTrack wrapper is optional. You can use other scraping methods or implement your own crawler.

### Q: Do I need to install HTTrack to use Open Omniscience?
**A:** Only if you want to use the HTTrack-based crawling functionality. The `pillar1/src/httrack_wrapper.py` module requires HTTrack to be installed. Other parts of Open Omniscience (API, database, etc.) do not require HTTrack.

### Q: Can I distribute a modified version of Open Omniscience?
**A:** Yes, as long as you comply with GPLv3 requirements:
- Include the full GPLv3 license
- Provide source code for your modifications
- Document your changes
- Do not add additional restrictions

### Q: Can I use Open Omniscience in a proprietary application?
**A:** No. GPLv3 requires that derivative works also be licensed under GPLv3. You cannot incorporate Open Omniscience into a closed-source proprietary application.

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
- [HTTrack Website](https://www.httrack.com/)
- [HTTrack Repository](https://github.com/xroche/httrack)
- [Third-Party Notices](NOTICES.md)

---

**Last Updated:** June 2025
