<!-- zh: Translation of docs/ETHICS.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 50 of 50 headings. Corrections are welcome as a pull request. -->

# Open Omniscience 伦理准则

> **状态（2026-10-08 复核）：** 本软件是一个可运行、经过测试的 **alpha 版**
> （`v0.5.0`——当前可用的功能见仓库 README；下文中 0.0.9 时期的措辞作为这些准则
> 生效时间的历史记录予以保留）。早期版本在此处带有
> “尚不可用”的横幅；该说法早已不再属实，因此已被移除——
> 这些准则**现已生效**，而非供未来参考。
> *历史说明：* 最早的概念版本（0.0.4 之前）以 HTTrack 网站复制工具为起点；
> 当前代码库是彻底重写的版本，与其不共享任何代码。

本文档阐述使用和参与开发 Open Omniscience 时的**伦理原则、合规要求和最佳实践**。所有用户和开发者都**必须**遵守这些准则。

Open Omniscience 遵循 **《慕尼黑宪章》**——这是 1971 年通过的一套记者基本原则。下文融入了这些原则，以指导对本平台的合乎伦理的使用。

---

## 📜 《慕尼黑宪章》：义务与权利宣言

### 序言
获取信息、自由表达和批评的权利是人类的基本权利之一。使用 Open Omniscience 的人所享有的一切权利和承担的一切义务，都源于公众了解事件和观点的权利。用户对公众的责任高于其他任何责任，尤其是对雇主和公共权力机构的责任。信息使命必然包含用户必须自觉加诸自身的限制。这正是下文所列义务宣言的目的。

只有在独立性和职业尊严的条件切实存在时，Open Omniscience 的用户才能在使用过程中履行这些义务。这正是下文权利宣言的目的。

---

### 📋 义务宣言
使用 Open Omniscience 从事信息收集、编辑和分析的用户，其基本义务是：

1. **尊重真相：**
   无论对自身产生何种后果，都要尊重真相，因为公众有权了解真相。

2. **捍卫信息自由：**
   捍卫信息、评论和批评的自由。

3. **核实来源：**
   只报道来源已知的事实；不隐瞒重要信息，也不篡改文本和文件。

4. **正当手段：**
   不以不正当手段获取信息、照片或文件。

5. **尊重隐私：**
   恪守对隐私的尊重。

6. **更正错误：**
   对任何已发布但被发现不准确的信息予以更正。

7. **职业保密：**
   遵守职业保密义务，不泄露在保密前提下获得的信息的来源。

8. **避免职业过错：**
   将以下行为视为严重的职业过错：
   - 剽窃
   - 诽谤、中伤、诋毁及无根据的指控
   - 以任何形式收受贿赂，以换取发布或压制信息

9. **与广告/宣传相区隔：**
   绝不将 Open Omniscience 的使用与广告销售或宣传活动混为一谈，并拒绝广告商的任何直接或间接指令。

10. **抵御压力：**
    抵御一切压力，只接受与本平台合乎伦理的使用相一致的负责人员的指令。

---

### 📜 权利宣言

Open Omniscience 的用户主张：

1. **自由获取信息：**
   自由获取所有信息来源，并有权自由调查一切影响公共生活的事件。因此，只有在特殊情况下、并基于明确表述的理由，才能以公共或私人事务的保密性对抗用户。

2. **拒绝不合伦理的从属：**
   有权拒绝从属于任何与 Open Omniscience 总体方针相悖的事项，以及任何并非该方针明确涉及的从属关系。

3. **良知与信念：**
   不得强迫用户做出违背其信念或良知的行为或表达违背其信念或良知的意见。

4. **决策透明：**
   社区必须被告知可能影响本项目的一切重要决定。在就项目方向的所有事项作出最终决定之前，至少应征询社区意见。

5. **公平回报与独立性：**
   考虑到其职能与责任，贡献者有权获得认可，并享有保障其工作的物质与精神安全以及经济独立的条件。

---

## 🌍 Open Omniscience 的核心原则

1. **尊重来源条款：** 始终遵守被抓取网站的 `robots.txt` 指令和服务条款。
2. **速率限制：** 唯一的抓取路径（`EthicalFetcher`）对每个主机强制执行最小
   请求间隔，并为每个主机加锁，因此对同一主机任何时候都只有一个请求在进行中。
   - 默认值：**每个主机每秒 1 个请求**——即 `EthicalFetcher` 中的
     `min_interval_s`，由 `OO_FETCH_MIN_INTERVAL` 环境变量设定。
   - 当某主机的 `robots.txt` 公布了 **`Crawl-delay`** 时，会予以遵守：
     实际间隔为 `max(min_interval, Crawl-delay)`。
   - （`sources.yml` 中针对每个来源的 `rate_limit_ms` 只是一个数据字段，**并未**接入
     抓取器的间隔设置；真正起节流作用的是上面两项。）
3. **透明：** 抓取活动记录在本地，供操作者自行
   查看——每个来源/订阅源的判定结果写入 `data/source_preflight.jsonl` 和
   `data/feed_preflight.jsonl`，实地测试结果写入 `data/field_test.jsonl`，
   应用错误写入 `data/app_errors.jsonl`。这些文件保留在本机上，**仅在点击时**才会
   被打包进“设置 → 诊断”中的**调试包**——绝不会自动发送。
   （不存在 `audit/scrape_log.csv`；那是早期的设计，已被本地优先、无遥测的立场所取代。）
4. **数据最小化：** 只收集和存储平台核心功能所必需的数据（URL、标题、内容、元数据）。
5. **非恶意使用：** Open Omniscience 不得用于：
   - 垃圾信息或骚扰。
   - 非法活动（例如黑客攻击、侵犯版权）。
   - 未经许可的商业利用。
6. **User-Agent 标识：** 使用清晰、可识别的 User-Agent 字符串。爬虫发送
   `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`
   （受保护的/经 Tor 路由的抓取则发送通用浏览器 UA，以免引人注目）。
7. **IP 节流：** 避免从单个 IP 快速连续发出请求。尊重服务器的合理使用规则。

---

## ✅ 合规检查清单

在抓取新来源之前，请确认以下各项：
- [ ] 该域名**不在**[禁止抓取清单](#禁止抓取清单)中。
- [ ] `robots.txt` 文件允许抓取（查看 [https://{domain}/robots.txt](https://{domain}/robots.txt)）。
- [ ] 该来源**不**需要身份验证，抓取也**不**会绕过付费墙。
- [ ] 速率限制的配置默认避免**每秒超过 1 个请求**（对敏感域名可另行调整）。
- [ ] User-Agent 字符串标明了 Open Omniscience（`OpenOmniscienceBot/{version}`）。
- [x] 抓取判定结果记录在本地（`data/*_preflight.jsonl`），点击时
  通过“设置”中的调试包呈现——绝不自动发送。

---

## 🚫 禁止抓取清单

本清单是**给操作者的指引**，而非机械执行的拒绝名单：应用并未内置对这些
域名的硬编码屏蔽。代码层面的防护是唯一的 `EthicalFetcher` 路径中的
**robots.txt 失败即关闭**机制——如果某个来源的 `robots.txt` 无法获取，或未明确
允许该 URL，该来源会被拒绝，而不会被抓取。操作者在添加来源时仍应
自行判断，避开以下类别：

### 付费墙内容


### 社交媒体平台


### 私人或敏感数据
- 政府数据库（例如 `*.gov`、`*.mil`，除非明确公开）
- 医疗记录（例如 `*.health`、`*.medical`）
- 财务记录（例如 `*.bank`、`*.finance`，除非公开）
- 个人数据存储库（例如 `*.personal`、`*.private`）

### 技术限制
- 实施**严格速率限制**的域名（例如 `github.com`、`stackoverflow.com`）。
- **屏蔽爬虫**的域名（例如受 `cloudflare.com` 保护且未提供绕过方式的网站）。
- **仅限 API 的来源**（例如 `twitter.com/api`、`reddit.com/api`——请改用官方 API）。

> **注意：** 本清单并不详尽。用户在添加新来源时必须进行**尽职调查**并运用**批判性判断**。如有疑问，**不要抓取**。 

---

## 📊 审计与问责

抓取活动**在本地**记录，供操作者自行查看，并且**仅在点击时**
共享——绝不自动发送（无遥测；设计上即本地优先）。
实际机制如下（早期的 `audit/scrape_log.csv` 设计已被其取代）：

- **预检判定**——每个来源和每个订阅源的可达性/robots/传输方式
  结果追加写入 `data/source_preflight.jsonl` 和
  `data/feed_preflight.jsonl`（每行包括：时间戳、来源/域名、考虑传输方式的
  判定结果，以及如实的原因）。它们支撑着“重试失败的数据源”这一交互，以及
  指数/市场中每个订阅源的判定结果。
- **实地测试结果**——实地测试模式开启时，对抓取路径的测试结果会被
  原样写入 `data/field_test.jsonl`。
- **应用错误**——限量写入 `data/app_errors.jsonl`（保留最新的若干行）。

### 为获取支持而共享

不存在自动上传的 CSV/`errors.log`。操作者可以生成一个**调试包**
（设置 → 诊断），它汇总上述 JSONL 日志以及关键词/网络
诊断信息；调试包写入磁盘，只有操作者明确操作时才会共享。
这是维护者的流程：在应用中逐一点击操作，然后交出调试包。

---

## 🔒 隐私与数据保护

- **不跟踪用户：** Open Omniscience **不**收集或存储：
  - 用户 IP
  - 搜索历史
  - 个人数据
- **仅限本地：** 所有数据都保留在用户的机器上。默认不依赖任何云服务。
- **静态加密（默认开启）：** 新语料库在创建时即使用 SQLCipher **加密**，
  由用户在首次启动时设定的口令保护。使用**明文**数据库是一种
  明确的选择退出，需要通过键入方式确认已告知的风险。忘记口令**无法恢复**
  （语料库可以通过重新抓取来重建，因此不增设恢复密钥/第二个解密入口）。
  威胁模型是被扣押或被复制的、处于**关机**状态的机器——而不是
  已被入侵、正在运行的会话（见 `SECURITY.md`）。
- **GDPR 合规：** 如果抓取位于欧盟的来源：
  - 对存储内容中的个人数据（例如姓名、电子邮件）进行匿名化处理。
  - 尊重删除权（应要求删除数据）。

---

## 🌍 法律考量

- **版权：** 遵守版权法。仅出于以下目的抓取和存储内容：
  - **个人、非商业性**分析。
  - **合理使用**（例如批评、评论、研究）。
  - **转化性目的**（例如为调查性新闻进行汇总）。
- **GDPR 合规：** 如果处理欧盟公民的数据：
  - 尽量减少个人数据的收集。
  - 为个人提供请求删除其数据的途径。
- **司法管辖：** 用户有责任遵守其所在司法管辖区的法律，包括：
  - **《计算机欺诈和滥用法》（CFAA）**（美国）
  - **《通用数据保护条例》（GDPR）**（欧盟）
  - **版权法**（各国）

---

## 🛡️ 技术保障措施

为防止滥用并确保合乎伦理的抓取，Open Omniscience 实施了以下保障措施：

1. **速率限制：**
   - 默认值：每个主机每秒 1 个请求（`min_interval_s`，来自 `OO_FETCH_MIN_INTERVAL`）。
   - 若主机 robots 中的 `Crawl-delay` 更大，则予以遵守；每个主机同一时间只有一个请求。

2. **遵守 Robots.txt：**
   - 在抓取前自动检查 `robots.txt`。
   - 遵守 `Disallow` 指令。

3. **User-Agent 标识：**
   - 发送 `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`。
   - 受保护的（经 Tor 路由的）抓取发送通用浏览器 UA，以免被单独识别出来。

4. **错误处理：**
   - 以指数退避方式重试失败的请求。
   - 记录所有错误以供审查。

5. **重复检测：**
   - 使用 URL 规范化和内容哈希来避免重复抓取。

6. **审计轨迹：**
   - 记录所有抓取活动，以实现透明和问责。

---

## 📐 诚实的指标——没有编造的评分

诚实源于设计本身：应用从不呈现**综合性的可信度/质量/
公信力评分**。它计算的每一个信号都附带其方法、一条注意事项及其
*n*；试图发布混合评分的卡片会被卡片
模式机械地拒绝。休眠的评分列（`credibility_score`、`political_bias`）保持为
NULL，并且从不序列化到任何 API 响应中。

**唯一一个有意为之的、范围狭窄的例外——`reliability_score`。** 这个针对每个来源的 `1–10`
字段是**由操作者声明的出处元数据**：是*你*（操作者）通过配置或 CSV 导入
为每个来源设定的数字。应用**从不计算它、从不为它设默认值，
也从不从文章数据中推导它**——早先编造的 `=5`
默认值已被移除（由迁移 `f4b5c6d7e8a9` 置为 NULL）。由于它是你自己的
声明（而非工具制造出来的判定），它在来源列表中可见，
并且在出现的任何地方都标注为**“由操作者设定，非计算得出”**；简报卡片
仍然绝不能把它作为评分呈现。一条仓库不变式
（`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`）
确保了这一点，使它无法悄然变成计算得出的质量判定。

---

## 📢 举报违规行为

如果你遇到或怀疑存在对 Open Omniscience 的不道德使用：
1. 立即**停止**违规活动。
2. **记录**事件（例如截图、日志、时间戳）。
3. 通过以下途径向维护者**举报**：
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues)（用于公开举报）
   - 电子邮件：`open-omniscience@ideotion.com`（用于敏感举报）

---

## 📅 审查与更新

本文档将**定期审查和更新**，以反映：
- 新的伦理挑战（例如 AI 生成内容、深度伪造）。
- 法律要求（例如版权法或数据保护法的变化）。
- 社区反馈（例如滥用举报或改进建议）。

### 版本历史
| 版本 | 日期       | 变更                                                                 |
|---------|------------|-------------------------------------------------------------------------|
| 1.0     | 2026-05-07 | 初始版本。新增禁止抓取清单、审计日志和 GDPR 说明。 |
| 1.1     | 2026-05-07 | 新增 User-Agent 标识、IP 节流和技术保障措施。 |

---

## 📌 贡献者最佳实践

1. **合乎伦理地测试：**
   - 在扩大规模之前，始终先进行小规模的抓取测试。
   - 尽可能使用 `localhost` 或预发布（staging）环境。

2. **记录来源：**
   - 在 `sources.yml` 中添加注释，说明为何纳入/排除某个来源。
   - 注明任何特殊的抓取要求（例如自定义选择器）。

3. **尊重退出请求：**
   - 如果某个来源要求被移除，应立即照办。
   - 将该域名加入禁止抓取清单。

4. **尽量减少影响：**
   - 尽可能在非高峰时段抓取。
   - 缓存响应，避免对同一内容重复请求。

5. **保持更新：**
   - 定期检查 `robots.txt` 的变化。
   - 关注法律动态（例如新的版权法）。

---
**请记住：** 合乎伦理的抓取不仅是法律义务——更是一种**道德责任**。使用 Open Omniscience，即表示你承诺恪守这些原则。

---

# 合规、许可与第三方声明

上述伦理原则在法律与署名方面的配套内容。

**本部分包括：**
- [GPLv3 合规指南](#gplv3-合规指南)
- [第三方声明与署名](#第三方声明与署名)


---

## GPLv3 合规指南

本节概述 Open Omniscience 对 GNU 通用公共许可证第 3 版（GPLv3）的
遵守情况。它适用于随发布提供的可运行软件。

---

### 📜 Open Omniscience 许可证

**许可证：** GNU 通用公共许可证第 3 版（GPLv3）  
**版权：** © 2026 Ideotion  
**许可证文件：** [LICENSE](../LICENSE)

Open Omniscience 完全以 GPLv3 授权，该许可证赋予用户
以下自由（本软件是一个可运行、经过测试的 pre-alpha 版——这些自由现已适用）：

1. **自由 0：** 出于任何目的运行本程序的自由
2. **自由 1：** 研究本程序如何运作并加以修改的自由
3. **自由 2：** 再分发副本的自由
4. **自由 3：** 分发修改版本的自由

---

### ✅ GPLv3 合规检查清单

#### 针对 Open Omniscience 项目

- [x] **许可证文件**：完整的 GPLv3 文本包含在 [LICENSE](../LICENSE) 中
- [x] **源代码可获取性**：所有源代码都在本仓库中公开提供
- [x] **版权声明**：源代码模块带有 `Copyright (C) 2026 Ideotion`
  声明；项目的 [LICENSE](../LICENSE) 适用于整个作品
- [x] **许可证头部**：大多数源代码模块带有 `GPL-3.0-or-later` SPDX 风格的
  头部（少数空的包 `__init__.py` 标记文件和几个小模块
  没有）。GPLv3 **并不**要求每个文件都带有头部——[LICENSE](../LICENSE) 文件对
  整个作品具有权威性；各模块中的声明只是一种礼节，而非声称
  每个文件都带有该声明
- [x] **无附加限制**：未在 GPLv3 之外施加任何进一步的限制
- [x] **修改版本**：所有修改均带有醒目的声明（第 5a 条）
- [x] **安装信息**：不适用（并非 GPLv3 所定义的用户产品）

---

### 📦 分发合规

#### 源代码分发

分发 Open Omniscience 源代码时：

1. ✅ **包含 LICENSE 文件**：必须包含完整的 GPLv3 许可证文本
2. ✅ **包含 ETHICS.md**：必须包含第三方署名
3. ✅ **保留头部**：所有源文件必须保留其 GPLv3 头部
4. ✅ **保留版权声明**：必须保留所有版权声明
5. ✅ **记录变更**：任何修改都必须有记录

#### 二进制分发

以二进制形式分发 Open Omniscience 时：

1. ✅ **包含源代码**：必须提供对应源代码（第 6 条）
2. ✅ **包含 LICENSE**：必须包含完整的 GPLv3 文本
3. ✅ **包含 ETHICS.md**：必须包含第三方署名
4. ✅ **记录变更**：任何修改都必须有记录
5. ✅ **无附加限制**：不得在 GPLv3 之外增加限制

#### 用户产品合规

如果 Open Omniscience 作为用户产品（消费类设备）的一部分分发：

1. ✅ **安装信息**：必须提供安装修改版本所需的信息（第 6 条）
2. ✅ **源代码可获取性**：必须提供对应源代码
3. ✅ **禁止 Tivo 化**：不得阻止用户安装修改版本

**注意：** Open Omniscience 本身并非用户产品，但如果你将其嵌入用户产品，上述要求即适用。

---

### 🔍 核查步骤

#### 针对开发者

1. **检查许可证头部**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **核对 LICENSE 文件**
   ```bash
   head -5 LICENSE
   ```

3. **检查 NOTICES 文件**
   ```bash
   cat ETHICS.md
   ```

4. **确认没有专有代码**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### 针对用户

1. **查看许可证**
   ```bash
   cat LICENSE | head -5
   ```

2. **查看署名**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 常见合规问题

#### 问：我可以将 Open Omniscience 用于商业目的吗？
**答：** 可以！GPLv3 允许商业使用。但是，你分发的任何修改版本也必须以 GPLv3 授权，并且你必须提供源代码。

#### 问：我可以在专有软件中使用 Open Omniscience 吗？
**答：** 不可以。GPLv3 要求衍生作品同样以 GPLv3 授权。你不能将 Open Omniscience 并入闭源的专有应用程序中。

#### 问：我需要公开我的修改吗？
**答：** 只有在你分发这些修改时才需要。如果你修改 Open Omniscience 仅供自己使用而不分发，则无需公开你的修改。

#### 问：Python 依赖项怎么办？
**答：** Python 依赖项（FastAPI、SQLAlchemy 等）是各自拥有许可证的独立作品。Open Omniscience 的 GPLv3 许可证不会影响它们。详见 [ETHICS.md](ETHICS.md)。

#### 问：我抓取的数据怎么办？
**答：** GPLv3 许可证仅适用于 Open Omniscience 软件本身，不适用于你收集的数据。你有责任遵守所抓取网站的版权和服务条款。

---

### 📞 报告合规问题

如果你对 GPLv3 合规有疑问或顾虑：

- **电子邮件：** open-omniscience@ideotion.com
- **GitHub：** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues：** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 资源

- [GPLv3 许可证全文](../LICENSE)
- [GNU GPLv3 官方网站](https://www.gnu.org/licenses/gpl-3.0.html)
- [GNU GPLv3 常见问题](https://www.gnu.org/licenses/gpl-faq.html)
- [第三方声明](ETHICS.md)

---

**最后更新：** 2026-06-14


---

## 第三方声明与署名

本节包含 Open Omniscience 所使用的第三方软件和库的
声明与署名。（*历史说明：* 0.0.4 之前的概念
版本以 HTTrack 为起点；当前代码库是彻底重写的版本，
其中不再包含任何 HTTrack 代码。）

---

### 📦 Python 依赖项

Open Omniscience **使用**以下 Python 包，每个包都采用其自身的
许可证。权威的、唯一来源的清单是 [`pyproject.toml`](../pyproject.toml)；
运行 `pip show <package>`（或 `pip-licenses`）即可确认任何
已安装版本的许可证。**每个依赖项都是 FOSS 且与 GPLv3 兼容**——这是一项
纳入要求（见 `docs/DESIGN.md` 中的“仅限 FOSS”不变式）。

**核心（始终安装）：**

| 包 | 许可证 | 用途 |
|---------|---------|---------|
| FastAPI | MIT | Web API 框架 |
| Uvicorn | BSD-3-Clause | ASGI 服务器 |
| Jinja2 | BSD-3-Clause | 服务器端模板 |
| SlowAPI | MIT | 速率限制 |
| Prometheus Client | Apache-2.0 | 指标端点 |
| SQLAlchemy | MIT | 数据库 ORM |
| Alembic | MIT | 模式迁移 |
| sqlcipher3 | Zlib/BSD-style | 基于 SQLCipher 的静态加密 |
| Requests | Apache-2.0 | HTTP 客户端（合乎伦理的抓取器） |
| httpx | BSD-3-Clause | HTTP 客户端 |
| BeautifulSoup4 | MIT | HTML 解析 |
| lxml | BSD-3-Clause | XML/HTML 解析 |
| feedparser | BSD-2-Clause | RSS/Atom 解析 |
| trafilatura | Apache-2.0 | 文章提取 |
| Pydantic | MIT | 数据验证 |
| PyYAML | MIT | 配置解析 |
| Bleach | Apache-2.0 | HTML 净化 |
| bcrypt | Apache-2.0 | 密码哈希原语 |
| defusedxml | PSF-2.0 | 不可信 XML 加固（Wikipedia 转储） |
| cryptography | Apache-2.0 OR BSD-3-Clause | Ed25519 签名 + Merkle 树 |
| Pillow | HPND (MIT-CMU) | EXIF / 图像元数据 |
| python-dateutil | Apache-2.0 / BSD | 日期解析 |
| tenacity | Apache-2.0 | 重试 / 退避 |
| cachetools | MIT | 内存缓存 |
| orjson | Apache-2.0 OR MIT（含一个 MPL-2.0 组件） | 快速 JSON |
| psutil | BSD-3-Clause | 硬件状态 |

**可选附加组件（按需安装）：**

| 附加组件 | 包 | 许可证 | 用途 |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | 统计 / 图 |
| `analysis` | nltk | Apache-2.0 | 分词 |
| `analysis` | vaderSentiment | MIT | 基于词典的情感分析（仅限英语） |
| `nlp` | spaCy | MIT | NLP 流水线 |
| `crypto` | python-gnupg | LGPL-3.0 | GPG 集成 |
| `pqc` | pqcrypto | MIT | 后量子（ML-DSA）签名 |
| `timestamping` | opentimestamps | LGPL-3.0 | 锚定于比特币的时间戳 |
| `compression` | zstandard, lz4 | BSD | 备份压缩 |

本地 LLM 是**外部的 Ollama** 二进制程序（MIT），通过环回
HTTP 访问——不捆绑或分发任何模型权重或推理库。

#### 合规说明

- 每个依赖项都是采用其自身许可证的**独立作品**；Open
  Omniscience 的 GPLv3 不延及它们，它们的许可证也不限制
  Open Omniscience。
- 所列的全部许可证都是**宽松型或弱 copyleft 型，并与 GPLv3 兼容**
  （LGPL-3.0 附加组件 `python-gnupg`/`opentimestamps`，以及 `orjson` 中的
  MPL-2.0 组件，均与 GPL-3.0 兼容）。FOSS + 与 GPLv3 兼容是一项
  硬性纳入要求。
- 用户必须遵守每个依赖项各自的许可证；`pip show <pkg>`
  会显示该许可证。

---

### 📄 字体与图标

| 资源 | 许可证 | 来源 |
|----------|---------|--------|
| 项目图标 | MIT（原创） | 包含在项目中 |
| 内置字体——Inter、Outfit、Manrope、JetBrains Mono、Source Serif 4、Cantarell | SIL Open Font License 1.1 | `src/static/fonts/`（每种字体附有其 `OFL-*.txt`） |

### 📦 内置数据与资源

这些非代码资源以各自的许可证收录在仓库中。
它们登记在 `configs/external_artifacts.yml` 中（时效性/署名在那里跟踪）。

| 资源 | 许可证 | 署名 / 说明 |
|-------|---------|---------------------|
| 字体（Inter · Outfit · Manrope · JetBrains Mono · Source Serif 4 · Cantarell） | SIL OFL 1.1 | `src/static/fonts/*.woff2`，许可证文本位于 `src/static/fonts/OFL-*.txt` |
| Alpine.js v3.14.1（GUI 图库） | MIT | 本地收录，sha256 固定，不使用 CDN——`src/static/guis/vendor/alpine.min.js` |
| vaderSentiment 3.3.2——为线性时间而改写的三个分析器方法 | MIT | **Copyright (c) 2016 C.J. Hutto**；该声明转载于 `src/analytics/vader_linear.py`，它只在与其核对过的那个确切文件上运行（sha256 固定） |
| DB-IP IP-to-Country Lite（离线地理定位） | CC BY 4.0 | **须署名：** "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0"——`src/geo/data/dbip_country_lite.csv.gz` |
| stopwords-iso（多语言停用词表） | MIT | `configs/stopwords_iso/*.txt` |
| Natural Earth（海岸线 + 国家多边形） | 公有领域 | `src/static/world_outline.json`、`src/static/world_countries.json` |

---

### 📝 数据来源

Open Omniscience 汇集来自各种新闻来源的数据。用户有责任：

1. 尊重所抓取内容的**版权**
2. 遵守每个网站的**服务条款**
3. 遵循 **robots.txt** 指令
4. 遵守**合乎伦理的抓取**准则（见 [ETHICS.md](ETHICS.md)）

**注意：** Open Omniscience 的 GPLv3 许可证**不**适用于使用本软件抓取的数据。用户全权负责确保其对所抓取数据的使用符合所有适用的法律法规。

---

### 🔍 核查

要核查对第三方许可证的遵守情况：

1. **Python 依赖项**：运行 `pip list` 查看所有已安装的包及其许可证
2. **源代码**：Open Omniscience 的全部源代码都在本仓库中提供

---

### 📞 联系方式

有关第三方许可证或合规的问题：
- **电子邮件：** open-omniscience@ideotion.com
- **GitHub：** https://github.com/ideotion/Open-Omniscience

---

**最后更新：** 2026-06-14
