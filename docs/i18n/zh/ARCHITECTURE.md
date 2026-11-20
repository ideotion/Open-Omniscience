<!-- zh: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# 架构与技术参考

用户手册的技术配套文档：数据库/配置、HTTP API 一览，以及国际化。

## 目录
- [Open Omniscience 的数据库配置](#open-omniscience-的数据库配置)
- [API 参考](#api-参考)
- [国际化（i18n）——让应用支持多种语言](#国际化i18n让应用支持多种语言)


---

## Open Omniscience 的数据库配置

> **状态（已在 v0.0.7 审计中核实，`docs/archive/audits/00_BASELINE.md`）：** 数据库层
> **可以运行并经过测试**——服务器能够启动，创建/使用 SQLite 存储，应用 Alembic
> 迁移，完整测试套件（800 多项）在其上全部通过。以前放在这里的“早期概念——
> 尚不可用”横幅描述的是重建之前的状态，早已过时。

### 🗃️ SQLite——受支持的存储

SQLite 是**默认的、也是唯一受支持并经过测试的后端**。它契合本产品
本地优先、单一操作者的设计。

- **零配置：** 数据库在首次运行时自动创建，位于
  `<data dir>/open_omniscience.db`。数据目录若设置了 `OO_DATA_DIR` 则为该值，否则在源码检出中为仓库的
  `data/`，再否则为 `$XDG_DATA_HOME/open-omniscience`（见 `src/paths.py`）。
- **自动调优：** 引擎在每个连接上都会应用 `WAL` 日志模式、`foreign_keys=ON`、
  `busy_timeout=30000` 和 `synchronous=NORMAL`
  （`src/database/session.py`）——你无需自行设置这些参数。
- **全文搜索**使用 SQLite **FTS5**（`article_fts`，外部内容表，由
  触发器保持同步——`src/database/fts.py`）。
- **更改存储位置**请使用 `DATABASE_URL` 环境变量（**不要**编辑
  源文件）：`DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **维护：** 偶尔执行一次 `sqlite3 <db> "VACUUM;"` 即可回收空间（v0.0.7 审计
  还删除了一个冗余索引，它在大型语料库上约占文件大小的 63%；升级后运行一次 `make
  migrate`，即可从现有数据库中删除该索引）。

### 🐘 PostgreSQL——实验性脚手架，不受支持

诚实胜于空想（审计发现 ARCH-06）：引擎层*能识别* PostgreSQL 的
`DATABASE_URL`（通过 `DB_POOL_SIZE`/`DB_MAX_OVERFLOW` 提供连接池），**但是**

- **PostgreSQL 上不存在全文搜索**——FTS5 的设置在非 SQLite 引擎上
  刻意不执行任何操作，因此“搜索”标签页将无法使用；
- 测试套件从不针对 PostgreSQL 运行，也没有任何 CI 覆盖它；
- 没有任何已发布的部署使用过它。

请将 PostgreSQL 视为**为可能的未来准备的、未经测试的脚手架**，而不是你今天就能
做出的选择。如果多写入者的规模有朝一日成为真正的需求，路线图上的事项是一条
`tsvector` 搜索路径加上 PostgreSQL CI 矩阵——在此之前，本页不会
假装它可用。

### 🔄 迁移

Alembic 配置在**仓库根目录**（`alembic.ini`、`migrations/`）。Alembic
随应用一起安装（它是核心依赖项——无需单独安装）。

- **新数据库**在启动时会被完整创建（`create_all` + FTS），并自动标记为
  当前的迁移头版本。
- **升级现有数据库：**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **创建迁移**（贡献者）：编辑 `src/database/models.py`，然后
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  并检查生成的文件——autogenerate 会遗漏 FTS 虚拟表（它们位于
  `src/database/fts.py`，在启动时应用）。
- **回滚：** `alembic downgrade -1`。

---

### 📊 数据库模式

#### 表：

##### `sources`
| 列 | 类型 | 说明 |
|--------|------|-------------|
| `id` | INTEGER | 主键 |
| `name` | STRING(100) | 来源名称（例如 "BBC News"） |
| `domain` | STRING(255) | 来源的域名（例如 "bbc.com"） |
| `rss_url` | STRING(500) | RSS 订阅源的 URL（如有） |
| `rate_limit_ms` | INTEGER | 请求之间的延迟（毫秒） |
| `enabled` | BOOLEAN | 该来源是否启用抓取 |
| `priority` | INTEGER | 优先级（1 = 高，3 = 低） |
| `tags` | STRING(500) | 以逗号分隔的标签列表 |

##### `articles`
| 列 | 类型 | 说明 |
|--------|------|-------------|
| `id` | INTEGER | 主键 |
| `url` | STRING(1000) | 文章的原始 URL |
| `canonical_url` | STRING(1000) | 规范化后的 URL（用于重复检测） |
| `source_id` | INTEGER | 指向 `sources` 的外键 |
| `title` | STRING(500) | 文章标题 |
| `content` | TEXT | 文章的全文内容 |
| `published_at` | DATETIME | 发布日期/时间（ISO 格式） |
| `language` | STRING(10) | 语言代码（例如 "en"、"fr"） |
| `hash` | STRING(64) | 内容的 SHA-256 哈希（用于重复检测） |
| `created_at` | DATETIME | 文章被采集入库时的时间戳 |

> 以上各列是核心字段；实际模式（`src/database/models.py`）
> 以及 `migrations/versions/` 下的 Alembic 迁移才是权威依据。
> `articles` 还带有出处/分析字段（author、word_count、region、
> country、sentiment）以及一个压缩内容列。

##### 其他表（完整列见模型 / 迁移）

| 表 | 用途 |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | 来源分组 + 地理/robots 元数据 |
| `commodity_prices` | 观测到的价格点（品种代码、日期、价格、货币、**单位**、市场、来源）——用于图表 + 价格↔新闻相关性 |
| `market_extraction_rules` | 针对每个来源的规则（CSS 选择器 / 属性 / 正则表达式），在某一页面上定位某一金融工具的价格；类别为 financial/stock/commodity |
| `keywords` | 不重复的关键词/实体词项（规范化后的形式、语言、`is_entity`/`entity_type`、**`extractor`** 出处） |
| `keyword_mentions` | 每个（文章，关键词）对一行：计数 + 首个字符偏移 + 反规范化的 `observed_on`/`country`/`city`——支撑“洞察”中的趋势、关联、上下文和地图 |
| `wiki_pages` | 某个语言版本中一个被跟踪的 Wikipedia 页面；保存**一份**压缩的全文基线 |
| `wiki_revisions` | 一次被跟踪的编辑：**差异 + 带符号的字节变化量** + 标记/标签（而非再存一份副本）、可选的 ORES 评分、如实的大幅编辑标记 + 原因 |
| `article_analyses` | 派生的 LLM 结果（摘要/翻译），附带模型 + 提示词出处 |
| `keyword_categories`, `external_sources`, `article_links`, … | 关键词分类 + 链接/来源关系跟踪 |

#### 索引：
- `idx_article_hash`：`hash` 上的唯一索引（用于重复检测）。
- `idx_article_canonical_url`：`canonical_url` 上的索引（用于 URL 查找）。
- `idx_article_source_id`：`source_id` 上的索引（用于按来源查询）。
- `idx_article_content`：`content` 上的索引（用于全文搜索）。

---

### 🔍 全文搜索

全文搜索**已经构建并接入**——无需任何启用操作。存储中
带有一个由触发器保持同步的 FTS5 外部内容表（`article_fts`）；模式见
`src/database/fts.py`，查询路径见 `src/api/main.py` 中的 `search_ids`
（按最终顺序只解析 id，只为当前页加载完整行）。

本节过去曾为 SQLite 提供一份“考虑创建虚拟表”的做法，并为 PostgreSQL 提供一份
`to_tsvector` 做法。两者都是错误的：SQLite 那份描述的是手工构建
一张应用本身就会提供并维护的表（而且名称*不同*，照做将会
产生第二个无人维护的索引），而 PostgreSQL 在这里根本没有搜索路径，
上面的存储一节已将此列为它不是受支持后端的首要原因。

---

### 📉 监控与维护

- **查看数据库大小**：
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **查看表的大小**：
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  在**加密**存储上，`sqlite3` 命令行工具根本无法打开该文件（这正是
  加密的意义所在）——请使用应用内“设置 → 诊断”中的功能，它们通过应用本身使用的
  同一个受保护的连接工厂读取存储。

---

### 🚨 故障排除

#### 常见问题：

##### SQLite：
- **"Database is locked"（数据库被锁定）**：
  - SQLite 同一时间只允许一个写入者。WAL 模式默认启用
    （`src/database/session.py`），并且进程级的单写入者闸门
    （`src/database/writer.py`）会将应用内的写入串行化，因此并发的采集 +
    导入不再冲突。如果锁定持续存在，说明有另一个*进程*正在写入。

- **"Too many open files"（打开的文件过多）**：
  - SQLite 会为每个线程打开一个新连接。请限制线程数量或使用连接池。

- **"Relation does not exist" / "no such table"（关系不存在 / 没有这张表）**：
  - 运行迁移：`alembic upgrade head`。

---

### 📌 最佳实践

1. **通过应用备份，不要用 `cp`**：
   - 使用“设置 → 备份”（或用 `GET /api/database/backup` 获取一致性快照）。
     手工复制 `open_omniscience.db` **不算**备份：存储运行在 WAL
     模式下，因此当前文件中缺少仍在 `-wal` 里的内容；而在默认的
     **加密**存储上，复制出来的文件没有口令就毫无用处，也不带任何
     完整性承诺。应用自身的备份路径会执行检查点、以流式方式输出并签名。

2. **测试迁移**：
   - 在将迁移应用于生产环境之前，务必先在数据库的备份上进行测试。

3. **监控性能**：
   - “设置 → 诊断”提供慢查询日志、请求延迟日志和
     写入闸门报告；`sqlite3` 命令行工具可用于明文存储。

4. **优化查询**：
   - 工具是 `EXPLAIN QUERY PLAN`。注意，SQLite 对裸表扫描和仅索引扫描
     **都**会写 `SCAN`——`SCAN <table> USING [COVERING] INDEX …` 是
     正常的；可疑的是不带 `USING` 的裸 `SCAN <table>`
     （`src/monitoring/slowquery.py` 正是据此分类的）。

5. **限制数据保留**：
   - 定期归档或删除旧文章，使数据库保持在可管理的规模。
   - 示例：删除一年以前的文章：
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion。依据 GNU 通用公共许可证第 3 版
或更高版本（GPL-3.0-or-later）授权——见 [LICENSE](../LICENSE)。这是自由软件；
你可以依据这些条款再分发和修改它。*


---

## API 参考

实时且始终准确的 API 参考由应用自身生成：

- **Swagger UI / ReDoc：** 默认关闭（它们会从第三方主机加载资源）；使用 `OO_API_DOCS=1` 启动应用即可访问 http://127.0.0.1:8000/docs 和 `/redoc`
- **OpenAPI JSON：** http://127.0.0.1:8000/openapi.json

应用只绑定到环回地址，并且（对于单个本地用户）无需身份验证。

### 端点分组

这是**主要分组的一览，而非详尽列表**——实时的
`/openapi.json`（见上）始终是权威依据。各路由器在
`src/api/main.py` 中通过 `include_router(...)` 接入；标记为 **[analysis]** 的分组需要
`[analysis]` 附加组件（没有它应用仍能启动，只是这些端点被禁用）。

| 前缀 | 作用 |
|--------|--------------|
| `GET /api/health` | 存活检查 + 版本 |
| `GET /api/articles`, `/api/articles/export` | 布尔全文搜索（FTS5）+ CSV/JSON 导出 |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | 合乎伦理的采集：单个 URL、RSS 订阅源、IMAP 邮箱 |
| `… /api/sources`, `/api/sources/...` | 来源 + 分组 + 元数据管理 |
| `POST /api/sources/seed-defaults` | 填充精选来源目录（新闻 + 市场 + 生成的世界目录） |
| `GET /api/database/stats`, `/coverage`, `/countries` | 语料库行数 + 磁盘占用；国家覆盖情况；每个国家的来源数 + 主题关键词 |
| `GET /api/database/backup` | 下载一致性的 SQLite 快照（仅限明文 SQLite 存储；对来自其他站点的请求、或对 DNS 重绑定防护不服务的 Host 发出的请求予以拒绝；在非环回名称上，对未注明来源页面的请求也予以拒绝，除非其发送 `X-OO-Download: 1`；每个进程同一时间只处理一个；写入数据库旁边的私有 `.oo-backup-*` 文件夹，并在下载结束或进程停止时删除（进程被强制终止时会留给下一次启动时的清理，该清理会立即删除已不存在的所有者的文件夹）；数据卷无法容纳时返回 507） |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | 通过已签名的 `oo-backup-2` 产物进行**仅追加式**恢复：先预览合并计划，再提交。恢复**绝不会覆盖你的语料库**——它以不产生重复的方式合并，发生冲突时保留本地值（破坏性的替换路径已于 2026-06-13 移除） |
| `GET/PUT /api/settings` | GUI 偏好（主题、默认结果数量上限） |
| `… /api/scheduler/...` | 后台采集：状态、启动、停止、立即运行、配置。自 `0.4` 周期起，采集以**并行的多条通道**（`rss` / `crawl` / `markets` / `wiki` / `law`）运行，而非单一的调度器模式——每条通道的存储在 `… /api/storage/...` 下，**活跃信息源**标签页读取 `… /api/living/...`（Wikipedia、法律和地图中发生了哪些变化） |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | 针对每个来源的价格提取规则 + 一次“测试”运行 + 市场概览 |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | 官方 CSV 价格数据源目录 + 导入（FRED/World Bank/EIA）+ 自定义 URL 导入 |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | 来源列表的 CSV 导出 / 模板 / 列 / 按域名更新或插入的导入 |
| `… /api/insights/...` | 关键词与实体分析：状态、重建索引、热门、上升趋势、趋势、关联（PMI）、上下文、地图 |
| `GET /api/timemap`, `/timemap/range` | 在同一张地图 + 时间轴上呈现的时空信号（锚点 + 经过地理编码的语料库 + 可选的灾害/文中提及的日期）；`?kinds`、`?start`/`?end` 小数年份窗口、`?hazards`、`?articles`、`?mentions`、`?days` |
| `… /api/article-dates/...` | 从文章正文中提取的日期，作为可由人工确认的逐篇文章标签：按文章列出/提取、确认/拒绝、批量建立索引、按日期筛选语料库 |
| `GET/POST /api/llm/...` | 本地 LLM（Ollama）：健康状态、模型、生成、为文章生成摘要 |
| `… /api/commodities/...` | 大宗商品价格（导入 / CSV / 列表）+ 如实的价格↔新闻相关性 |
| `POST /api/analysis/...` | 符合科学严谨性的统计：t 检验、相关性、ANOVA、Mann-Whitney、置信区间 |
| `GET /api/monitoring/...` | 真实的来源可用性健康状况 + 语料库数量异常 |
| `POST /api/verify/image-metadata` | 如实的图像 EXIF/元数据提取 |
| `POST /api/reports/evidence`, `/evidence/verify` | 已签名、可发现篡改的证据包 |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | 仅追加、哈希链式、已签名的证据保管链日志 + 离线验证 |
| `GET/PUT /api/custody/settings` | 运行时的保管链偏好（后量子签名、锚定模式、自动记录）——报告的是*实际生效的*、考虑了可用性的状态 |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | 锚定一个 Merkle 根（本地 / OpenTimestamps）+ 提供方的可用性 |
| `POST /api/custody/reconcile` | 补写因故障而欠下的 INGEST 条目，每条都在其已签名的元数据中标记为迟到；`scan` 统计更早的缺口，`record_gaps` 将其排入队列（2026-09-24，CUST-1） |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** 关键词提取 + 文章相似度 |
| `GET /api/search/omni` | 基于索引的联合全能搜索栏（文章 FTS5 + 关键词 + 来源 + wiki/法律） |
| `… /api/jobs/...` | 任务管理器的作业汇总（采集轮次、进行中的抓取、wiki 转储队列 + 重新排序） |
| `… /api/system/...` | 系统状态 + 网络状态/同意（飞行模式总开关、本地网络接口 IP） |
| `… /api/safety/...` | 安全控制：总开关、发现闸门、从加密产物恢复 |
| `… /api/briefing/...` | 主页简报的生成器（按证据分级的卡片；方法 + 注意事项 + n） |
| `… /api/insights/...`, `/api/insights/who`, `/where` | 关键词/实体分析 + 全语料库的“谁/何地”汇总 |
| `… /api/links/...` (shared, preview) | 共享外链/引用图分析 + 本地链接预览对话框 |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | 日程事件，包括在本地计算的天文事件（Meeus）+ 厄尔尼诺表 |
| `POST /api/weather/context` | 经同意的、有边界的 Open-Meteo 再分析数据切片，用于佐证 |
| `… /api/law/...` | 被跟踪的立法/原始资料变更信息流 |
| `… /api/integrity/...` | 回声 / 协同 / 源流信号 |
| `… /api/annotations/...` | 本地的、可选签名的文章批注 |
| `… /api/wiki/...` | Wikipedia 语言版本、关注的页面、转储下载/读取、语料库同步 |
| `… /api/hazards/...`, `/api/timemap` | 灾害叠加层 + 时空地图 |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | 静态加密：锁定启动时的解锁界面、创建加密/明文存储、文件头证明、单向加密工具 |

标记为 **[analysis]** 的路由器（大宗商品、统计、关键词、框架分析）
需要 `[analysis]` 附加组件；没有它，应用仍能以核心
主干启动，只是这些端点被禁用。

行为说明：
- 采集只通过合乎伦理的抓取器进行抓取（robots.txt 失败即关闭、有速率
  限制）；如果 Ollama 不可用，LLM 端点返回 **503**（绝不返回伪造的答案）。
- 证据验证：传入签名者的公钥，以证明出处，而不仅仅是
  完整性（见 [QUICKSTART](QUICKSTART.md) 和 `scripts/verify_evidence.py`）。
- 保管链设置是*偏好*，而非保证：`GET/PUT /api/custody/settings`
  始终报告**实际生效的**状态（偏好**以及**库的可用性），因此当
  所需的附加组件不存在时，后量子 / OpenTimestamps 绝不会显示为已启用。
  锚定默认使用离线的 `local` 提供方；OpenTimestamps 和
  公链锚定附带隐私警告（见
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)）。


---

## 国际化（i18n）——让应用支持多种语言

> 目标：让**整个界面**（并逐步让**文档**）以大约
> 十几种语言提供，从而把开放获取扩展到“几乎所有人”。以
> 本项目的方式实现：**离线、不使用 CDN、不使用运行时翻译 API、无遥测**，并且
> 对翻译质量**保持诚实**（我们不会把机器猜测当作
> 权威内容发布）。

---

### 十几种语言（第 1 阶段的语言集）

依据覆盖面（母语 + 第二语言使用者）选定，并刻意纳入
全球南方（遵循 `ROADMAP.md` 的反偏见目标）：

| 代码 | 语言 | 本族语名称 | 文字 / 方向 | 状态 |
|---|---|---|---|---|
| `en` | 英语 | English | LTR | **源语言**（完整） |
| `fr` | 法语 | Français | LTR | **完整**（已核准） |
| `es` | 西班牙语 | Español | LTR | **完整**（已核准） |
| `de` | 德语 | Deutsch | LTR | **完整**（已核准） |
| `zh` | 中文（普通话） | 中文 | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `hi` | 印地语 | हिन्दी | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `ar` | 阿拉伯语 | العربية | **RTL** | 完整（已翻译，`0.4` 周期；尚未核准） |
| `bn` | 孟加拉语 | বাংলা | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `ru` | 俄语 | Русский | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `pt` | 葡萄牙语 | Português | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `id` | 印度尼西亚语 | Bahasa Indonesia | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |
| `ja` | 日语 | 日本語 | LTR | 完整（已翻译，`0.4` 周期；尚未核准） |

为扩大覆盖面而容易增加的下一批语言：**斯瓦希里语（`sw`）**、**乌尔都语（`ur`，RTL）**、意大利语
（`it`）、土耳其语（`tr`）、越南语（`vi`）。

**诚实立场。** *存根*（stub）让一种语言**现在即可选择**，任何未翻译的字符串都
回退为英语——不完整的语言包绝不会破坏界面（这正是
任何未来语言包——`it`、`tr`、`vi`……——的起点机制）。我们将每个语言包标记为 `complete | draft | stub`。维护者
只发布自己能够核准的内容；其余部分则通过**社区
贡献**来补充（这恰恰是开源扩大获取途径的方式）。

---

### 架构（离线、无依赖）

`src/static/i18n.js` + `src/static/locales/<code>.json`。无构建步骤，无网络访问。

- **英语就是键。** 语言包文件将**英文界面字符串 → 其译文**进行映射
  （例如 `"Search the corpus": "Rechercher dans le corpus"`）。这让我们无需给每个元素打标记就能
  改造现有界面，并保持英语作为权威
  来源。
- **`OOI18N.setLang(code)`** 加载 `locales/<code>.json`，将选择保存在
  `localStorage`（`oo.lang`）中，设置 `document.documentElement.lang` 和 `dir`（对
  `ar`/`ur` 为 RTL），然后 **`apply()`** 遍历 DOM——翻译去除首尾空白后
  与某个键匹配的文本节点，以及 `placeholder`/`title`/`aria-label` 属性。未知的
  字符串保持原样（回退为英语）——绝不会造成任何破坏。
- **动态内容**（数据：文章标题、来源名称、计数）**从不**
  被翻译——只翻译界面外壳。由 JS 渲染的界面外壳（命令面板、抽屉）在渲染后调用
  `OOI18N.apply()`。
- 每个语言包都带有 `_meta`（`name`、`native`、`dir`、`status`）。

#### 集成方法（第 2 阶段——已发布；Desk 此后已停用）

在 `index.html` 中加两行（在 2026-06-10 停用之前，`desk.html` 中也是如此），
然后加一个语言选择器：

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

**语言**选择器位于“设置”中，调用 `OOI18N.setLang(code)`，
并与其他本地界面偏好一起保存。

---

### 多语言文档

文档篇幅长，翻译质量比简短的界面字符串更重要，因此：

- 结构：`docs/i18n/<code>/<DOC>.md` 与 `docs/` 一一对应。
- **英文文档始终是权威版本**；翻译是社区/维护者的工作，
  每篇都标注其翻译日期以及所跟踪的英文提交。
- 我们**不会**对文档进行自动机器翻译并将其作为权威版本呈现——那
  将违反本项目的诚实原则。每种语言都从价值最高、篇幅最短的
  文档开始（QUICKSTART、“你首先会看到的内容”导览、ETHICS）。

---

### 贡献流程（设计上即开放获取）

1. 将 `locales/en.json` 复制为 `locales/<code>.json`，翻译各个值，设置 `_meta.status`。
2. 对于 RTL 语言，设置 `_meta.dir: "rtl"`。
3. 运行（计划中的）键覆盖检查：报告相对于 `en.json` 缺失/多余的键。
4. 提交。未翻译的键在补齐之前会直接回退为英语。

---

### 状态

**第 1 阶段（已完成）：** i18n 引擎（`i18n.js`）、全部 12 种
语言的语言包框架，以及 **en/fr/es/de** 的完整参考译文。

**第 1b 阶段（已完成，`0.4.0`）：** 其余的界面字符串已被设为键并
翻译成**全部十二种**语言（见 `CHANGES.md` 0.4.0），因此
`src/static/locales/*.json` 中的每个语言包现在都带有完整的键集（已核实：
12 个文件，每个 6,991 个键，无一缺失）。诚实原则不变：名称是
专有名词，不予翻译；不完整的语言包仍会回退为
英语，而不会造成破坏。

**第 2 阶段（已完成——有待真实浏览器检验）：** `i18n.js` 已包含在
`index.html` 中（在 Desk 于 2026-06-10 停用之前也包含在 `desk.html` 中）；
**语言**选择器（`#oo-lang-select`）位于“设置”中并已自动接线；动态渲染的界面外壳由
一个带防抖的 `MutationObserver` 自动翻译（无需四处调用 `apply()`）；切换到英语
会恢复原文；RTL 通过 `<html dir>` 实现。结构/语法已经过验证，但
其行为仍应在浏览器中亲眼检查。

**第 3 阶段（下一步）：** 将 `en.json` 扩展到*完整的*字符串目录（目前它
覆盖高频使用的界面外壳），补全存根语言包（社区），并完善
`ar`/`ur` 的 RTL 布局。


## 导出契约（带版本）

机器可读的导出带有稳定的、自描述的契约（模式 `oo-export-1`，
0.0.8 第 2 部分 / RM-15），使下游流水线无需猜测：

- **JSON**（`/api/articles/export?format=json`、`/api/links/export.json`）：一个封套——
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`。
  `query` 对象是原样保留的生成选择条件；出处随数据一起传递。
- **CSV**（`/api/articles/export?format=csv`）：没有注释行（注释行会破坏简单的读取程序）；
  同样的封套以 HTTP 头的形式传递（`X-OO-Export-Schema`、`X-OO-App-Version`、
  `X-OO-Generated-At`、`X-OO-Query`）。各列保持原有顺序，新列只会
  追加在末尾：`Fetched From Host`（队列事项 61），即页面在经过重定向后
  实际抓取所用的主机，未记录时为空；JSON 导出中对应的字段为 `fetched_host`。
- **引用图**（`/api/links/export.graphml`、`.json`）：谁引用谁的关系图
  （已存储的文章 → 外部可注册域名）。**只有计数——没有推断出的
  可信度，没有评分**；注意事项就嵌入在文件本身中。GraphML 可在
  Gephi/yEd/NetworkX 中打开。

模式变更时会递增 `oo-export-N`；现有字段绝不会被悄然挪作他用。在其旁边新增的字段
（末尾的 CSV 列、新的 JSON 键）不会改变任何现有读取程序所用字段的位置，
因此不会递增模式版本。
