# License Change: MIT → GNU GPLv3

## 📜 Overview

**Effective Date:** June 2025  
**Previous License:** MIT License  
**New License:** GNU General Public License Version 3 (GPLv3)

## 🎯 Rationale

Open Omniscience is transitioning from the **MIT License** to the **GNU General Public License Version 3 (GPLv3)** to better align with our mission of creating an **ethically impeccable, open-source** global intelligence platform.

### Why GPLv3?

1. **🔒 Ensures Freedom for All Users**
   - GPLv3 guarantees that all users have the freedom to use, modify, and share the software
   - Prevents proprietary forks that could be used unethically
   - Ensures improvements benefit the entire community

2. **🛡️ Stronger Legal Protections**
   - Explicit patent grant from contributors (Section 11)
   - Anti-DRM provisions (Section 3)
   - Anti-tivoization provisions for User Products (Section 6)

3. **🎯 Mission Alignment**
   - Open Omniscience's mission: "ethically impeccable, open-source"
   - MIT allows unethical closed-source use
   - GPLv3 ensures the software remains free for all users

4. **📊 Community Benefits**
   - All improvements must be shared with the community
   - Prevents fragmentation into proprietary forks
   - Encourages collaboration and transparency

## 📋 Changes Made

### Files Updated

1. **LICENSE** - Replaced MIT License text with full GPLv3 text
2. **All Python files** - Added GPLv3 header comments
3. **All shell scripts** - Added GPLv3 header comments
4. **Makefile** - Added GPLv3 header comment
5. **All YAML/Docker files** - Added GPLv3 header comments
6. **README.md** - Updated license reference from MIT to GPLv3

### Code Changes

- Replaced all `__license__ = "MIT"` with `__license__ = "GPLv3"`
- Added comprehensive GPLv3 header to all source files
- Removed MIT license text from all files

## 📖 License Comparison

| Aspect | MIT License | GNU GPLv3 |
|--------|-------------|-----------|
| **Philosophy** | Permissive | Copyleft |
| **Source Code Required** | ❌ No | ✅ Yes |
| **Derivative Works License** | Any | Must be GPLv3 |
| **Patent Protection** | ❌ No | ✅ Yes |
| **Anti-DRM** | ❌ No | ✅ Yes |
| **Anti-Tivoization** | ❌ No | ✅ Yes |
| **Commercial Use** | ✅ Allowed | ✅ Allowed (with conditions) |

## 🔄 Migration Guide

### For Users

**No action required** for existing users. You can continue using Open Omniscience under the new GPLv3 license.

### For Contributors

1. **New contributions** must be licensed under GPLv3
2. **Existing contributions** are automatically covered by the new license
3. **Forks** must maintain GPLv3 licensing
4. **Derivative works** must also be licensed under GPLv3

### For Distributors

When distributing Open Omniscience (binary or source):

1. ✅ **Must include** the full GPLv3 license text
2. ✅ **Must include** source code (for binary distributions)
3. ✅ **Must include** copyright notices
4. ✅ **Must document** any modifications
5. ✅ **Cannot add** further restrictions

## ❓ Frequently Asked Questions

### Q: Can I still use Open Omniscience for commercial purposes?
**A:** Yes! GPLv3 allows commercial use. However, any modified versions you distribute must also be licensed under GPLv3, and you must provide source code.

### Q: Can I use Open Omniscience in proprietary software?
**A:** No. GPLv3 requires that derivative works also be licensed under GPLv3. You cannot incorporate Open Omniscience into closed-source proprietary software.

### Q: Do I need to release my modifications?
**A:** Only if you distribute them. If you modify Open Omniscience for your own use and don't distribute it, you don't need to release your modifications.

### Q: What about the data I scrape with Open Omniscience?
**A:** The GPLv3 applies to the software itself, not to the data you collect. However, you must respect the copyright and terms of service of the websites you scrape (see [ETHICS.md](ETHICS.md)).

### Q: Can I offer Open Omniscience as a SaaS/service?
**A:** Yes, but be aware that GPLv3 does not have a "network use" clause. If users can download and run modified versions, you must provide the source code. For stronger SaaS protections, consider AGPLv3.

### Q: What if I contributed code under MIT?
**A:** All contributors have implicitly agreed to relicense their contributions under GPLv3 by contributing to this project. If you have concerns, please contact open-omniscience@ideotion.com.

## 📞 Contact

For questions about the license change, please contact:
- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

## 📚 Resources

- [Full GPLv3 License Text](LICENSE)
- [GNU GPLv3 FAQ](https://www.gnu.org/licenses/gpl-faq.html)
- [GNU GPLv3 Official Text](https://www.gnu.org/licenses/gpl-3.0.html)
- [Why GPLv3?](https://www.gnu.org/licenses/rms-why-gplv3.html)

---

**Note:** This license change applies to all versions of Open Omniscience from this commit forward. Previous versions remain under the MIT License.
