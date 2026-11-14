<!-- zh: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# 快速入门——运行本应用

这是**值得信赖的核心功能**（本应用是一个如实标注的 **alpha 版**——`v0.5.0`，即
`0.5`“调查员工作台”周期，于 2026-10-26 打标签；正在运行的应用会报告其确切
版本）：添加来源 → 以合乎伦理的方式抓取 → 连同来源信息一起存储 →
布尔全文搜索 → 导出。本地优先，仅限回环地址，无需账户。

---

## 0. 最简单的方式——一条命令，之后双击即可运行

如果你只是想使用本应用（之后不需要任何命令行知识）：

**Linux / macOS**——在终端中运行：

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11**——在 PowerShell 中。先下载，*然后*再运行：

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

即便如此，Windows Defender 仍可能隔离该文件——它没有签名，而且是新文件。这是
误报；[§C](#c-在-windows-11-上powershell) 会准确说明原因，并提供一种
不依赖脚本、不会被任何软件删除的安装途径。

Windows 上的支持范围比 Linux 窄，两者的差别在
[§C](#c-在-windows-11-上powershell) 中有明确说明——依赖它之前请先阅读。

> **先检查，再信任。** 把脚本通过管道交给 shell，就是在你的电脑上运行代码。
> 这两个脚本都刻意写得很短——愿意的话可以先读一读
> （[scripts/bootstrap.sh](../scripts/bootstrap.sh)、[install.ps1](../install.ps1)）。
> 它们会检查 git 和 Python 3.13，把本仓库克隆到 `~/open-omniscience`
> （Windows 上为 `%USERPROFILE%\Open-Omniscience`），再交给仓库内的
> 安装程序。你也完全可以自己克隆，然后运行 `./install.sh` / `install.ps1`。

`install.sh` **不会弹出任何提问**——**没有组件菜单**。一条命令即可安装
合理的默认组合：

| 默认安装 | 你将获得 |
|----------------------|--------------|
| **核心（Core）** *（始终安装）* | 抓取 · 连同来源信息存储 · 布尔搜索 · 导出 |
| **分析** | 关键词 · 报道框架比较 · 情感分析 |
| **压缩（Compression）** | 语料库在磁盘上的存储更快 |

本地 LLM / Ollama 的配置**不**属于安装程序——它完全位于
应用的 **设置 → AI** 标签页中（见 §E）。可以用
`OO_COMPONENTS="…"` 环境变量覆盖安装组合（例如 `OO_COMPONENTS="analysis,nlp"`）；重新运行
`./install.sh` 是幂等的，只会安装缺少的部分。

**随后它会自动启动。** 安装程序会创建一个 **Open Omniscience** 启动器（应用
菜单 + 桌面），并在浏览器中打开应用。以后要再次启动：

- 打开应用程序菜单并搜索 **Open Omniscience**，**或者**
- 双击**桌面**上的 **Open Omniscience** 图标。

屏幕上会出现一个小的终端窗口，应用随之启动，浏览器会打开
**http://127.0.0.1:8000**。**关闭该窗口（或使用顶栏的电源 / 关闭
按钮）即可停止应用。**（在 macOS 上，启动器是桌面上的 `Open Omniscience.command`；
在 Windows 上，它是由 `install.ps1` 创建的桌面和“开始”菜单快捷方式。）

**首次启动。** 全新安装时，应用会在进入主界面*之前*引导你完成一次简短的
一次性设置：**选择语言 → 阅读并接受法律条款**
（拒绝将通过输入确认来**卸载**本应用）**→ 创建语料库
口令**。语料库**默认进行静态加密**（SQLCipher 4），口令一旦丢失
**无法找回**（丢失口令的代价是重新采集所花的时间——语料库可以从网络上重建）。
随后应用以**离线状态（飞行模式）**启动；切换为联网时会经过**一个同意弹窗**，
在发出任何请求之前，它会说明将要执行的操作并显示你的本地网络接口 IP。

更喜欢用终端？`cd ~/open-omniscience && ./scripts/launch.sh` 效果相同。

**以后检查或移除它：**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. 在 Qubes OS 的 Debian AppVM 上（目标平台）

Qubes 每次启动都会重置 AppVM 的根文件系统；只有 `/home`（以及
`/usr/local`、`/rw`）会保留下来。因此系统软件包要装在 **TemplateVM** 中，而
应用、虚拟环境和数据库则放在 **AppVM** 的 `/home` 下。

**1. 在 TemplateVM 中（只需一次）：**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
关闭 TemplateVM，然后**重启 AppVM**，让这些软件包可见。

**2. 在 AppVM 中（以你自己的用户身份，不用 sudo）：**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. 运行（仅绑定到 127.0.0.1）：**
双击 **Open Omniscience** 启动器（应用菜单 / 桌面），或者：
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
在 AppVM 的浏览器中打开 **http://127.0.0.1:8000**。

服务器从不在回环地址以外监听。如果想在运行一次之后完全离线，可以断开该
AppVM 的 NetVM——界面没有任何外部依赖，会继续基于已存储的数据工作。

---

## B. 本地开发运行（任何装有 Python 3.13 的 Linux）

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

常用环境变量：`OO_DATA_DIR`（SQLite 数据库和数据的存放位置）、`OO_HOST`/`OO_PORT`、
`OO_FETCH_MIN_INTERVAL`（针对每个主机的礼貌间隔，单位为秒）。

### 在 Tails 上

Debian/Ubuntu/Tails 把标准库的 `venv`/`ensurepip` 放在一个**单独的 apt 软件包**中，所以
在安装它之前 `python3 -m venv` 会失败。`install.sh` 现在会**自动**安装它
——在 Tails 上这需要一个**管理员密码**（在欢迎屏幕上设置；默认是关闭的）以及可用的
**Tor 连接**（apt 通过 Tor 下载）。如果你更愿意自己运行 apt，可以用 `OO_NO_APT=1` 关闭此功能。

Tails 特有的两点如实说明：

- **Python 版本。** Tails 基于 Debian 12 → **Python 3.11**，但本应用面向 **3.13**。
  你必须准备好一个 3.13 解释器，并让安装程序指向它
  （`OO_PYTHON=python3.13 ./install.sh`）；3.13 及其 `python3.13-venv` 软件包**不在**
  Tails 的默认软件源中。
- **失忆特性。** 任何通过 apt 安装的东西——以及整个 `.venv`——都会**在重启后丢失**，除非
  它们位于持久存储中：通过**持久存储 → 附加软件（Persistent Storage → Additional
  Software）**添加 venv 软件包，并把代码检出目录和 `OO_DATA_DIR` 放在持久卷上。

### 升级已有数据库

全新安装会自动建立数据库结构（`init_db()`），并把数据库
标记为当前的迁移基线。当未来某个版本修改了数据库结构时，
用以下命令升级已有数据库：
```bash
alembic upgrade head
```
`alembic check` 会报告模型与迁移是否一致（CI 会检查这一点）。

---

## C. 在 Windows 11 上（PowerShell）

**如实的支持状态——请先阅读。** 每次 CI 运行都会在
`windows-latest` 上证明三件事：依赖安装、**启动检查**（整个应用能够导入），
以及 **SQLCipher 静态加密**——最后一项运行在*阻断式*通道上，所以
加密不是猜测。除此之外没有任何东西得到证明。Windows 上的 **pytest 通道
会挂起**（最近完成的几次运行在 `pytest` 中分别停留了 3 小时 21 分钟和约 6 小时，而
macOS 上只需 18 分钟），而且**还没有人在 Windows 上把界面逐一点过一遍**。所以：安装
和启动应该能正常工作，启动之后的一切都应视为未经验证，出了问题请告诉我们。
Linux 仍然是发布的把关标准。

### 1. 安装

打开 **PowerShell**（除非需要安装 Python 本身，否则不需要管理员权限）。
下载安装程序，愿意的话先读一读，然后运行它：

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

它只在缺少 Git 和 Python 3.13 时才通过 `winget` 安装它们，克隆到
`%USERPROFILE%\Open-Omniscience`，建立一个 `.venv`，并通过导入真实的应用来
验证结果。去掉 `-Extras` 参数即可安装更完整的默认组合，或参见
[安装程序选项](#安装程序选项)。

已经克隆过了？就地运行即可——它会识别出自己所在的检出目录并跳过克隆：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **为什么不用一行 `irm … | iex`？** 因为获取远程代码并直接在内存中执行，
> 是 Windows 恶意软件最常见的投递方式，所以无论脚本内容是什么，
> Defender 都会把这种形式判定为恶意。先把文件写到磁盘上，既不容易被拦截，也更坦诚
> ——你可以在它运行之前读一读它。

### 2. 如果 Windows Defender 隔离了安装程序

它可能会一见到 `install.ps1` 就将其删除。这是**误报**，但你不必
只听我们的一面之词——下面准确说明了为什么会这样，由你自己判断：

- 该文件**没有签名而且是新文件**，所以 Defender 的云信誉服务从未见过它。
  未知 + 未签名，单凭这一点就足以触发机器学习启发式检测；
  检测名称通常以 `!ml` 结尾。
- 它的**形态**就是安装程序的形态：它会调用包管理器，从注册表重新读取 `PATH`，
  写入“开始”菜单快捷方式，而它的 `-Uninstall` 分支会删除
  目录。投放型恶意程序（dropper）也做同样的事。分类器判断的是形态，而不是意图。

它*不*包含以下内容，你可以在大约 500 行可读代码中自行核实：没有
`Invoke-Expression`，没有编码或混淆的载荷，没有 `WebClient`，没有隐藏
窗口，除了本仓库之外也不下载任何东西。

三种解决办法，按推荐程度排序：

1. **使用不依赖脚本的途径**——见下文的[手动安装](#手动安装不用脚本)。
   与安装程序执行的命令相同，没有可被隔离的文件。这种方法总是可行。
2. **向 Microsoft 报告误报**，地址为
   <https://www.microsoft.com/en-us/wdsi/filesubmission>（选择 *Software developer*）。
   通常一两天内就会处理，而且修复会惠及在你之后安装的所有人
   ——而不只是你自己。
3. **排除该文件夹**（Windows 安全中心 → 病毒和威胁防护 → 管理
   设置 → 排除项）。这样做之前请清楚其中的取舍：排除项会让
   Defender *完全*停止扫描该文件夹，对其中的一切、无限期地——而不只是
   这一个文件。这是你的电脑，由你决定；我们不会假装这样做没有代价。

我们这边真正的解决办法是代码签名，而我们目前还没有。

### 3. 运行

安装程序会在**桌面**和
**“开始”菜单**中创建一个 **Open Omniscience** 快捷方式。双击它：会出现一个终端窗口，等应用真正响应后，
浏览器会打开 **http://127.0.0.1:8000**。关闭该窗口（或使用
应用的电源按钮）即可停止。

也可以从终端运行：`scripts\launch.cmd`。

### 4. 首次启动

与所有平台相同的一次性流程：**选择语言 → 阅读并接受
法律条款 → 创建语料库口令**。语料库**默认进行静态
加密**，口令一旦丢失**无法找回**。随后应用以
**离线状态（飞行模式）**启动；联网时会经过**一个同意弹窗**。

### 安装程序选项

| 参数 | 作用 |
|------|--------------|
| *（无）* | 核心 + `analysis,compression,columnar`，然后验证并创建启动器 |
| `-Path <dir>` | 安装到 `%USERPROFILE%\Open-Omniscience` 以外的位置 |
| `-Extras "analysis"` | 选择 pip 附加组件（`""` 表示仅核心） |
| `-Ref <branch>` | 克隆指定的分支或标签 |
| `-NoPython` | 从不自动安装 Git/Python；改为报错并给出说明 |
| `-NoLauncher` | 跳过桌面 / “开始”菜单快捷方式 |
| `-Check` | 健康报告（与 `open-omniscience doctor` 相同） |
| `-Uninstall` | 移除 `.venv` 和启动器；除非另行确认，否则保留数据 |
| `-Yes` | 对所有提示默认回答“是”（无人值守） |

在 Windows 上，只有 `analysis` 经过了 CI 验证。如果更完整的默认组合
安装失败，脚本会**回退到 `analysis` 并明确告知**，而不是悄无声息地
失败，或假装附加组件已经装好。

### 手动安装（不用脚本）

```powershell
# 1. Prerequisites -- skip either line if you already have it
winget install --id Git.Git -e --source winget
winget install --id Python.Python.3.13 -e --source winget --scope user

# 2. Find the interpreter. winget frequently installs Python WITHOUT adding it to
#    PATH, so `python` and `py` can still resolve to nothing on a freshly restarted
#    machine. This reads the record the installer itself writes (PEP 514) -- the same
#    one py.exe uses -- so it answers whatever PATH says:
Get-ChildItem 'HKCU:\SOFTWARE\Python','HKLM:\SOFTWARE\Python' -Recurse -ErrorAction SilentlyContinue |
  Where-Object PSChildName -eq 'InstallPath' |
  ForEach-Object { (Get-ItemProperty $_.PSPath).'(default)' }

$py = "$env:LOCALAPPDATA\Programs\Python\Python313\python.exe"   # or whatever that printed

# 3. Clone
git clone --depth 1 https://github.com/ideotion/Open-Omniscience.git $HOME\Open-Omniscience
cd $HOME\Open-Omniscience

# 4. Virtual environment. Everything is called by full path on purpose: activating a
#    venv needs Activate.ps1, which the default execution policy blocks.
& $py -m venv .venv
.\.venv\Scripts\python.exe -m pip install --upgrade pip
.\.venv\Scripts\python.exe -m pip install -e ".[analysis]"

# 5. Verify -- the exact check CI's Windows lane runs
.\.venv\Scripts\python.exe -c "from src.api.main import app; print(sum(1 for _ in app.routes))"

# 6. Run
.\.venv\Scripts\open-omniscience.exe
```

### Windows 相关说明

- **执行策略。** 默认策略会阻止 `.\.venv\Scripts\Activate.ps1`。
  这里没有任何地方需要它：按路径调用 `.venv\Scripts\python.exe`，整个问题就
  不存在了。命令行上的 `-ExecutionPolicy Bypass` 覆盖了安装程序本身。
- **会打开 Microsoft Store 的 `python`。** 全新的 Windows 11 自带一个
  名为 `python.exe` 的执行别名占位程序，它会打开应用商店而不是运行
  代码。安装程序会忽略它（占位程序不会输出版本号），并使用 `py -3.13`
  启动器。如果你手动安装，请优先使用 `py -3.13` 而不是 `python`。
- **你的数据存放在哪里。** 因为这是源代码检出，语料库、签名
  密钥和设置都放在 **`<repo>\data`** 中——而不是 `%APPDATA%`。设置 `OO_DATA_DIR` 可以把
  它们放到另一个驱动器上。
- **文件夹权限。** 在 Linux 上，数据目录被锁定为仅你的用户可访问
  （`chmod 0700`）；该调用在 Windows 上不起作用，所以该文件夹继承普通的
  Windows ACL。在多人共用的电脑上，请自行限制 `<repo>\data` 的访问权限。无论哪种情况，
  语料库数据库本身仍然是静态加密的。
- **SmartScreen / Defender。** 这里没有任何东西经过代码签名，所以 Windows 会把它们全部
  视为未知：SmartScreen 可能会对启动器发出警告，Defender 可能会直接隔离
  `install.ps1`——关于这是怎么回事以及该怎么办，请参见
  [§2](#2-如果-windows-defender-隔离了安装程序)。实时扫描也会明显拖慢
  第一次 `pip install`。
- **端口。** 在启动前设置 `OO_PORT` 即可不使用 8000；`scripts\launch.cmd`
  会遵循该设置。
- **架构（x64 / ARM64 / 32 位）。** 由安装程序检测并处理；以下是
  它的判断依据。决定 `pip install` 能否成功的不是
  机器本身，而是针对*解释器*所在平台存在哪些 wheel。2026-08-23 对照
  PyPI 测得，针对 CPython 3.13、覆盖本项目的全部依赖：

  | 解释器 | wheel |
  |---|---|
  | `win-amd64` | **所有依赖。** 唯一完整的架构。 |
  | `win-arm64` | 除三个之外全部都有——`cryptography`（核心）、`httptools`（核心，经由 `uvicorn[standard]`）和 `statsmodels`（`analysis`） |
  | `win32` | `cryptography` 完全没有发布 |

  ARM 上的 Windows 可以透明地运行 x64 二进制文件，所以**在 ARM64 上 x64 解释器同样是
  正确答案**——不是妥协，而是完整的组合。因此 `install.ps1`
  在所有情况下都优先选择 `win-amd64`，如果机器上没有，就会去获取一个：
  先用指明架构的 winget，再用用户范围的 winget，最后从 nuget.org 获取 Python
  软件基金会发布的自包含 x64 CPython——并对照 nuget 为它提供的 SHA-512 进行校验，
  解压到 `%LOCALAPPDATA%\Open-Omniscience\python-x64`，不需要提权，不修改 PATH，
  也不写入注册表项。它被有意放在检出目录**之外**：它是一项机器
  资源，所以删除应用文件夹后它依然保留（否则基于它建立的 `.venv`
  会损坏），而第二个 `-Path` 检出目录也会复用它。`-Uninstall` 会移除它。如果哈希不匹配，或者
  某个版本 nuget 没有提供哈希，安装程序会**拒绝**。

  如果每一步都失败，你会得到一个附带“下载一项即可修复”说明的停止提示，而不是一场
  耗时二十分钟、最后以 `linker link.exe not found` 告终的 Rust 编译。

  已有的 `.venv` 会**被实际探测，而不只是被找到**：它保留着当初建立它的那个解释器的版本和 wheel
  平台，所以之前某次运行基于另一个 Python 留下的 `.venv`
  会被替换而不是复用——否则上述所有工作都会在
  最后一步被悄悄抵消。匹配的 `.venv` 会原封不动地复用。因此，重新运行
  安装程序就是修复半途而废的安装的方法；不需要手动
  删除任何东西。

  - **为什么不自动启用原生 ARM64 安装。** 那需要把 `cryptography`
    固定在 46.0.0–46.0.3，这是唯一提供 ARM64 wheel 的版本系列。该版本带有
    **13 条未解决的安全公告记录**（其中包括一条静态链接 OpenSSL 的问题，已在
    48.0.1 中修复）。本应用要对证据进行签名；悄悄安装这样的版本就是安全
    表演。如果你的电脑确实装有 Visual Studio Build Tools **以及** Rust
    工具链，`-AllowSourceBuilds` 会在本机编译这三个依赖——这是一个明确的选择，
    从来不是默认设置。
  - **不支持 32 位 Windows**，这是一项真实的限制，而不是人为设置的门槛：
    `cryptography` 不提供 `win32` wheel。必须使用 64 位 Windows。

---

## D. 端到端流程（界面或 API）

> **来源已预先配置。** 首次启动时（或在运行 `install.sh --appvm` 期间），
> 精心整理的目录（`configs/sources.yml` 约 3,200 家公共利益媒体，外加
> 市场、政治光谱和法律/知识产权目录——**合计约 3,395 个不重复的域名**）
> 会被自动导入——所以你可以立即开始采集。
> （这些数字会随着目录的增长而**变化**；实际数字以
> `configs/*.yml` 当前包含的内容为准。）重新导入是幂等的。可以用
> `OO_AUTOSEED=0` 关闭自动导入；也可以用 `python scripts/seed_sources.py` 或
> `POST /api/sources/seed-defaults` 手动重新导入。订阅源 URL 和 robots 策略会随时间变化；
> 合乎伦理的抓取器会拒绝任何它无法确认的内容，所以请根据你的调查需要
> 精简或扩充这份清单。

**在界面中：** **联网**一次（飞行模式开关 → 一个同意弹窗），之后
**采集会在后台自动运行**——按语言和来源标签分层进行，
遵守 robots 规则并限制速率。然后**在“浏览”中搜索**（侧边栏标签页；在顶栏或 Ctrl/⌘-K 的全能栏中按 Enter，
会在新的浏览器标签页中打开“浏览”）——匹配文章的分析会显示在
结果下方，你可以在那里筛选、阅读、运行布尔查询并**导出**（CSV/JSON、方法
附录、签名证据）。你仍然可以在**设置 → 高级 → 采集 / 来源**中手动添加来源，
并对单个订阅源或 URL 执行*采集（Ingest）*。

**通过 API：**
```bash
# add a source
curl -X POST http://127.0.0.1:8000/api/sources/ -H 'Content-Type: application/json' \
  -d '{"name":"Example News","domain":"example.com","rss_url":"https://example.com/feed.xml"}'

# ingest its feed (ethical: robots.txt respected fail-closed, rate-limited)
curl -X POST http://127.0.0.1:8000/api/sources/1/ingest

# or ingest a single article URL under that source
curl -X POST http://127.0.0.1:8000/api/ingest -H 'Content-Type: application/json' \
  -d '{"source_id":1,"url":"https://example.com/some-article"}'

# Boolean full-text search (AND / OR / NOT, "phrases", parentheses)
curl 'http://127.0.0.1:8000/api/articles?query=(climate OR energy) AND policy NOT opinion'

# export the filtered set
curl 'http://127.0.0.1:8000/api/articles/export?format=csv&query=climate'
```

机器可读的 API 模式位于 **http://127.0.0.1:8000/openapi.json**。交互式 Swagger 页面默认关闭（它会从第三方主机加载资源）；开发者可以用 `OO_API_DOCS=1` 启动应用，以便在 `/docs` 访问它。

---

## E. 分析功能

所有功能都是本地优先，出问题时会明确报错（绝不伪造结果）。完整的模式见 `/openapi.json`。

**本地 LLM（Ollama）。** 在 **设置 → AI** 中进行配置：应用内置一个
**经过校验和验证**的 Ollama 安装程序（Linux），外加一个**模型下载队列**（真实的
字节进度，可取消）、一个当前模型选择器和一个可编辑提示词面板。你也可以
自己从 **ollama.com** 安装 Ollama 并运行 `ollama pull llama3.2:3b`。拉取模型时会
**经由 Ollama 进程通过明网（clearnet）**向外连接（而不是走应用的 Tor 路径）——这一点会在
征求同意时说明。顶栏的 LLM 标签会显示实时状态（点击它可打开 设置 → AI）；每条
搜索结果都有 **摘要** 和 **翻译** 按钮。API：
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
如果 Ollama 没有运行，这些接口会返回 HTTP 503 并附带清楚的说明——而不是一份假摘要。

**大宗商品价格 + 如实的相关性分析。**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
相关性分析会返回由 scipy（Pearson/Spearman）计算出的真实系数 + p 值 + n，
并附带“相关 ≠ 因果”的提示；重叠数据太少 → `insufficient_data`。

**监测。** `GET /api/monitoring/health` 会执行真实的可达性
检查（通过合乎伦理的抓取器）；`GET /api/monitoring/anomalies` 会按 z 分数标记
文章数量的突增。**电子邮件：** `POST /api/sources/{id}/ingest-email`
（IMAP）会把邮件并入同一个可搜索的语料库。

**图片元数据核查。** `POST /api/verify/image-metadata`
（上传一张图片）会返回其格式、尺寸、EXIF 和 GPS 信息，并附上平实的事实性
观察（例如存在图像编辑软件标记、没有拍摄时间戳）。其范围如实限定为
*元数据检查*——**不是**深度伪造/篡改检测（那项功能是
伪造的，已从工作树中隔离移除；参见
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)）。

**签名证据包。** 分析窗口中的 **导出签名证据**
按钮（或 `POST /api/reports/evidence`）会生成一个以 Merkle 根为基础、
经 Ed25519 签名的证据包。任何人都可以离线验证它，无需本应用：
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**保管链。** 界面中的 **保管链** 面板记录经过签名、
可发现篡改的来源信息，并允许你在运行时切换其行为：
后量子签名、锚定模式（离线的 `local`，或锚定到比特币的
**OpenTimestamps**），以及采集时自动记录。这些开关只是*偏好设置*——
面板显示的是**实际生效**的状态，所以如果某项功能所需的附加组件没有安装，
就不会显示为已开启。API：
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
完整的模型、威胁模型和隐私注意事项：[USER_MANUAL.md](USER_MANUAL.md)。

---

## “合乎伦理的采集”保证什么

- robots.txt 会被获取、按主机缓存，并且**失败即关闭**：如果无法
  确认它（网络错误、超时、5xx，或受限的 401/403），该 URL
  **不会**被抓取。
- 对每个主机强制执行最小访问间隔（遵循 `Crawl-delay`）。
- 只有一条抓取路径，使用可识别身份的 User-Agent（保护模式下使用通用 User-Agent，但发往 Wikimedia 服务器的 API 和转储请求除外），文章只抓取 HTML——没有绕过机制。
- 正文提取使用 trafilatura；如果找不到真正的文章正文，就什么也不存储
  （不会出现伪造的“No Title / No Content”记录）。
- 每篇已存储的文章都带有来源信息：来源、原始 URL、规范 URL、
  内容哈希（用于去重）、抓取时间。
