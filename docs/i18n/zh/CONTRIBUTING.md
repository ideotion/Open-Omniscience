<!-- zh: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# 参与贡献

感谢你的帮助。指导原则是**诚实**：一项功能必须做到它所声称的事，否则就不发布。不允许捏造的输出、虚假的置信度评分、悄无声息的降级——参见 [DESIGN.md](DESIGN.md) §3。

## 环境搭建

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` 仍是依赖的唯一权威来源（我们在下限范围内安装最新版本，以便 CI 尽早发现上游的破坏性变更）。为了实现**可复现的/发布用的安装**，有一个由它派生、带哈希锁定的锁文件：

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**这已接入 `./install.sh`，而不只是一条需要手动运行的命令。** 在线安装路径（`pip_install()`）会在以下条件同时满足时自动使用 `requirements.lock`：该文件存在、它是为你正在运行的 Python 生成的，并且它覆盖了你要求的所有组件（`OO_COMPONENTS`）——这一判断依据锁文件自身的 `pip-compile ... --extra=...` 头部进行核对，从不手工维护。只要其中任一条件不成立（锁文件对你的 Python 来说已过时，或要求了生成锁文件时未包含的组件，或某个锁定版本在当前平台上无法解析），它就会回退到普通的基于下限的 `pip install -e ".[...]"` 解析，并以醒目的消息说明为何没有使用经过审计的路径——`OO_USE_LOCK=0` 可无条件地不使用锁文件。**按目前发布的状态，锁文件只覆盖 `--extra analysis`**，而 `install.sh` 自身的默认组件集合是 `analysis,compression,columnar`——因此，以默认设置无人值守地运行 `./install.sh`，目前会回退到基于下限的解析（compression/columnar 不在锁文件的覆盖范围内）。运行 `OO_COMPONENTS=analysis ./install.sh` 可按现状使用经过审计的路径，或者用 `pip-compile --extra analysis --extra compression --extra columnar ...` 扩大锁文件的覆盖范围，使默认安装路径也基于锁文件。

**离线/物理隔离安装包**（`scripts/build_offline_bundle.sh`，供 `install.sh` 面向 Qubes/Tails 的 `--no-index` 离线路径使用）**尚未接入锁文件**——每次构建时它仍从 `pyproject.toml` 的下限重新解析。这是一个已知的、尚未解决的缺口，而不是疏忽：让离线安装包也基于锁文件（`pip download --require-hashes -r requirements.lock`，并对锁文件未覆盖的 extras 保留基于 `$SPEC` 的解析作为回退）已作为后续工作在跟踪。

## 工作流程

- **Python 3.13**，单一的 `pyproject.toml`（没有 requirements.txt）。
- 用 **ruff** 进行 lint/格式化；用 **mypy** 做类型检查：`make lint && make typecheck`。
- 每次改动都以全绿结束：`make check`（ruff + pytest）。为新行为添加行为测试；要么修复，要么隔离——不要把半成品代码留在导入路径中。
- 以小而诚实的增量提交，提交信息要说明*做了什么以及为什么*。
- 模式（schema）变更通过 Alembic（`alembic revision --autogenerate`）进行；CI 运行 `alembic check` 以发现模型与迁移之间的偏差。

## 发布台账：每行一个文件

不要向 `docs/ledger/shipped.csv` 追加内容。GitHub 的合并检查会忽略该文件的 `merge=union` 规则，因此每个 PR 都追加一行，曾导致每次合并之后所有未合并的 PR 都发生冲突。请改为新增一个文件：

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

它会写出 `docs/ledger/shipped.d/<date>-<slug>.csv`（台账的表头加一行）。其他 PR 不会与它不触及的文件发生冲突。`python scripts/ledger_shipped.py check` 校验每一个片段；发布说明和仓库不变量测试先读取 `shipped.csv`，再读取这些片段。`ledger_shipped.py fold` 以二进制方式把片段追加到 `shipped.csv` 并删除它们；它供维护者或发布时使用，绝不用于功能 PR。`refs` 必须是真实的 PR 编号，而不是 `PR pending`（否则会有测试失败）。

## 经验教训与发布日志条目：各一个文件

同样的约定也适用于两个大型归档。一条经验教训是一个文件 `docs/ledger/lessons.d/<date>-<slug>.md`（`python scripts/lessons.py --new SLUG`）；一条逐字的发布日志条目是一个文件 `docs/ledger/shipped_log.d/<date>-<slug>.md`（`python scripts/ledger_fold.py new-log SLUG`）。绝不要向 `LESSONS.md` 或 `SHIPPED_LOG.md` 追加内容，也绝不要编辑 `_LESSONS_LINE_CEILING`：每个这样做的 PR 都曾与其他所有 PR 冲突。片段以 `## <date> — title` 开头，以换行结尾，使用 UTF-8 编码和 LF 换行符；经验教训（而非发布日志条目）不得有第二个标题，且保持在 200 行以内（以限制单条的大小）；`python scripts/ledger_fold.py check`（以及 `tests/test_ledger_fragments.py`）会校验它，拒绝 `#NNNN` 和 `PR pending` 占位符，并且 `lessons.py <words>` 也会搜索这些片段。`ledger_fold.py fold` 在发布时把它们合并进归档，绝不用于功能 PR。

## 语言文件与合并冲突

12 个 `src/static/locales/*.json` 文件保持**有序**（`_meta` 在最前，其余键按码点顺序排列），因此两个添加字符串的 PR 会插入到不同位置，能够干净地合并。添加字符串后，运行 `python scripts/locales_merge.py`；它会对文件排序并进行检查（`--check` 只做校验；`tests/test_locales_merge.py` 在键未排序或重复时失败）。

如果 `git merge origin/main` 在语言文件中留下了冲突标记，运行同一个脚本：它保留每个冲突块的两侧，进行排序，并在两侧为同一个键给出不同文本时停下并指出该键（这是需要决定的真正矛盾）。`docs/ledger/shipped.csv` 在 `.gitattributes` 中设为 `merge=union`，本地的 `git merge` 会遵循它，但 GitHub 的网页合并和更新分支按钮不会：请在本地合并 main，然后检查是否有 `(date, area, item)` 重复的行。

## 标准

- 处处保留来源信息：存储的数据都带有信源 + 时间戳 + 哈希。
- 展示给用户的任何数字都必须来自注明不确定性的真实方法（`src/analysis`），绝不能是常量。
- 采集通过唯一的合乎伦理的抓取器进行（robots 失败即关闭、限速）。
- 捏造的/无用的代码应放在 `quarantine/`（附说明），而不是 `src/`。

## 行为准则

参与即表示你同意遵守[行为准则](CODE_OF_CONDUCT.md)（Contributor Covenant 2.1）。如有疑虑，请私下报告至 open-omniscience@ideotion.com。

## 许可证

贡献内容采用 **GPL-3.0-or-later** 许可（参见 [LICENSE](../LICENSE)）。

---

# 版本策略

项目如何编排版本号——有意低调地表述成熟度。

**本部分内容：**
- [版本策略](#版本策略)


---

## 版本策略

> **我们有意低调地表述成熟度。诚实胜于炒作。** 让用户感到惊喜，好过让用户被误导。版本号是关于*成熟度*的承诺，我们让这个承诺保持保守。

### 唯一权威来源

版本号只存在于**一个地方：`pyproject.toml`（`[project] version`）**。其他一切都由它派生：

- 运行中的应用从已安装包的元数据中读取它（`importlib.metadata.version("open-omniscience")`）——因此 `/api/health`、API 的 `version=` 和 UI 都会自动报告*真实*安装的版本。
- 其他代码都不硬编码版本字面量。测试依据包元数据而非字符串进行断言（参见 `tests/test_api_search.py`）。
- 仓库根目录的 `README.md` 在其页首说明一次版本号，CI 守卫会断言它与包版本一致（`tests/test_repo_invariants.py::test_readme_version_matches_package`）。

**要提升版本号，只修改 `pyproject.toml`**，同时更新 README 页首使之一致（守卫会强制执行），然后运行 `pip install -e .` 以刷新元数据。

**只在 `pyproject.toml` 已经写为 `X.Y.Z` 的提交上打 `vX.Y.Z` 标签。** 发布工作流（`.github/workflows/release.yml`）在构建任何东西之前就会拒绝其他标签，因此在版本提升之前打下的标签会发布一个没有 wheel、sdist 和校验和的版本。第一个 `v0.4.0` 就是在 2026-09-28 这样打下的；版本号是之后才设置的，标签随后被移到了那里（`docs/product/RELEASE_0.4_GATE.md` 第 G 行）。**移动标签需要使用 git：** GitHub 网站既不能删除也不能移动标签，而在网站上发布的版本会复用现有标签，不会启动工作流。如果没有可以推送的本地克隆，请在 `main` 上打开一个 Codespace 并运行 `git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z`。如果希望由工作流写入自动生成的说明，请先删除 GitHub 上的该版本：工作流会保留已有版本的说明，只添加文件和校验和。

### 成熟度阶梯（我们在哪里，要去哪里）

软件还很年轻，仍在验证之中，因此保持在 **`1.0` 以下**：

```
0.0.x  pre-alpha    the first, un-public pre-alpha iterations (0.0.4 .. 0.0.9).
0.x    alpha        ← we are here (0.5.0). Public, working, honestly-labelled — open
                     to feedback, but not yet consolidated (each cycle is still an
                     "honest about every limit, not finished" release, per the README
                     header — see it for the current cycle's exact status).
0.x    beta         once things consolidate (a deliberate, later maintainer call —
                     not implied by any particular `0.x` number crossing over from alpha).
1.0    release      an official, stable release.
```

我们**不会**跳到一个暗示超出实际成熟度的版本号（例如，`0.2` 并不意味着"完成了 20%"或"接近 beta"——它只是迄今为止 alpha 周期的诚实计数）。每个周期都是一次小而真实的迭代——不作更多声称。

### 周期 ↔ 版本对应

开发周期（及其分支）以它们产出的版本命名，为简洁起见省略了前导零：

| 分支/周期名称 | 包版本 |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  （`0.09` 周期分支在切换到 alpha 时被重命名为 `0.09 → 0.1`）
| `0.2`  | `0.2.0` |  （`0.1` 周期分支在切换到 0.2 时被重命名为 `0.1 → 0.2`）
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  （`0.2` 周期分支于 2026-07-15 被重命名为 `0.2 → main`——默认分支现在永久为 `main`，分支名与版本号相互独立；`v0.2.0` 在实时语料库规模验证之后打上标签，`v0.3.0` 结束了"测量与验证"周期，`v0.4.0` 结束了"活的信源"周期，而 `main` 现在为 `0.5.0`，即"调查者工作台"（investigator's-desk）版本，标签为 `v0.5.0`）

所以"`0.06` 的情报层"指的是"在 `0.0.6` 中发布的工作"。当你在文档中读到 `0.05` 这样的周期简写时，请把它读作 `0.0.5`。PR 合入当前的周期分支 `main`——而不是上面列出的任何已退役的编号分支名。

**自第一个 alpha（`0.1.0`）以来，对应关系是 `0.N` 周期 ⇒ `v0.N.0`**——`0.2` 周期以 `v0.2.0` 结束，`0.3` 周期以 `v0.3.0` 结束，`0.4` 周期以 `v0.4.0` 结束，`0.5` 周期以 `v0.5.0` 结束（唯一的例外是合并后的 `0.09` 周期，它产出的是 `0.1.0`）。周期以结束它的版本命名——发布关卡文件用自己的话这样说明（`RELEASE_0.4_GATE.md` 是"结束 `0.4` 周期的可核查清单"）——并且版本号可能在打标签之前、周期中途就被*设置*（例如 `0.4.0` 于 2026-09-28 设置，以便把标签移过去；`0.5.0` 在切换 PR 中设置，标签指向其合并提交），这就是为什么变更日志标题中的日期与其标签日期可能不同。

### 为什么这很重要（与价值观的联系）

本项目的存在是为了帮助人们诚实地看待信息。一个夸大自身成熟度的工具，会从根本上与此相矛盾。保守的版本策略与代码库其余部分遵循的是同一种纪律：**只声称真实存在的东西，并证明它。**
