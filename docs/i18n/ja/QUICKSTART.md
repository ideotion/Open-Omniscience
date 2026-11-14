<!-- ja: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# クイックスタート — アプリを動かす

ここで説明するのは**信頼できる中核機能**です（このアプリは正直に言って**アルファ版**です — `v0.5.0`、
`0.5` の「調査者のデスク」サイクルで、2026-10-26 にタグ付けされました。実行中のアプリが正確な
バージョンを表示します）。情報源を追加する → 倫理的にスクレイピングする → 来歴付きで保存する →
ブール演算による全文検索 → エクスポートする。ローカルファースト、ループバックのみ、アカウント不要です。

---

## 0. 簡単な方法 — コマンドを 1 つ実行し、あとはダブルクリックで起動

アプリを使いたいだけなら（その後はコマンドラインの知識は不要です）：

**Linux / macOS** — ターミナルで：

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — PowerShell で。まずダウンロードし、*それから*実行します：

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

それでも Windows Defender がこのファイルを隔離することがあります — 署名がなく、新しいファイルだからです。これは
誤検知です。[§C](#c-windows-11-の場合powershell) でその理由を正確に説明し、何にも消されることのない
スクリプト不要の手順も示しています。

Windows のサポートは Linux より限定的で、その違いは [§C](#c-windows-11-の場合powershell) に
はっきりと書いてあります — 頼りにする前に読んでください。

> **信頼する前に中身を確認してください。** スクリプトをシェルにパイプで渡すと、あなたの
> マシン上でコードが実行されます。どちらのスクリプトも意図的に小さくしてあります — よければ先に読んでください
> （[scripts/bootstrap.sh](../scripts/bootstrap.sh)、[install.ps1](../install.ps1)）。
> これらは git と Python 3.13 があるかを確認し、このリポジトリを `~/open-omniscience`
> （Windows では `%USERPROFILE%\Open-Omniscience`）にクローンして、リポジトリ内の
> インストーラーに処理を引き継ぎます。自分でクローンして `./install.sh` / `install.ps1` を実行してもかまいません。

`install.sh` は**対話なし**で動きます — **コンポーネントのメニューはありません**。コマンド 1 つで
妥当な既定のセットがインストールされます：

| 既定でインストールされるもの | 得られる機能 |
|----------------------|--------------|
| **コア（Core）** *（常に）* | スクレイピング · 来歴付きの保存 · ブール検索 · エクスポート |
| **分析** | キーワード · 論調（フレーミング）の比較 · 感情分析 |
| **圧縮（Compression）** | コーパスをディスク上により高速に保存 |

ローカル LLM / Ollama のセットアップはインストーラーには**含まれません** — すべてアプリの
**設定 → AI** タブで行います（§E を参照）。インストールするセットは
`OO_COMPONENTS="…"` 環境変数で上書きできます（例：`OO_COMPONENTS="analysis,nlp"`）。
`./install.sh` は何度実行しても同じ結果になり（冪等）、足りないものだけをインストールします。

**その後、自動で起動します。** インストーラーは **Open Omniscience** のランチャー（アプリ
メニューとデスクトップ）を作成し、ブラウザーでアプリを開きます。あとで再び起動するには：

- アプリケーションメニューを開いて **Open Omniscience** を検索する、**または**
- **デスクトップ**の **Open Omniscience** アイコンをダブルクリックします。

小さなターミナルウィンドウが現れてアプリが起動し、ブラウザーで
**http://127.0.0.1:8000** が開きます。**アプリを止めるには、そのウィンドウを閉じる（またはトップバーの電源 / 終了
ボタンを使う）だけです。**（macOS ではランチャーはデスクトップ上の `Open Omniscience.command` です。
Windows では `install.ps1` が作成するデスクトップとスタートメニューのショートカットです。）

**初回起動。** 新規インストールでは、メイン画面の*前に*、短い一度きりのセットアップを
案内します：**言語を選ぶ → 利用規約を読んで同意する**
（同意しない場合は、確認の文字入力を経てアプリが**アンインストール**されます）**→ コーパスの
パスフレーズを作成する**。コーパスは**既定で保存時に暗号化**され（SQLCipher 4）、パスフレーズを
なくした場合の**復旧手段はありません**（パスフレーズをなくすと再収集の時間がかかります — コーパスは
Web から作り直すことになります）。アプリはその後**オフライン（機内モード）**で起動します。
オンラインに切り替えるときは、何らかのリクエストが送信される前に、操作の内容を示しローカルの
インターフェース IP を表示する**同意ポップアップを 1 回**経由します。

ターミナルのほうがよければ、`cd ~/open-omniscience && ./scripts/launch.sh` でも同じことができます。

**あとで確認・削除するには：**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Qubes OS の Debian AppVM の場合（主な対象環境）

Qubes は AppVM のルートファイルシステムを起動のたびにリセットします。永続するのは `/home`（と
`/usr/local`、`/rw`）だけです。そのため、システムパッケージは **TemplateVM** に入れ、
アプリ、virtualenv、データベースは **AppVM** の `/home` 以下に置きます。

**1. TemplateVM で（1 回だけ）：**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
TemplateVM をシャットダウンしてから、パッケージが見えるように **AppVM を再起動**します。

**2. AppVM で（通常ユーザーとして、sudo なしで）：**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. 実行する（127.0.0.1 のみにバインドします）：**
**Open Omniscience** ランチャー（アプリメニュー / デスクトップ）をダブルクリックするか、次を実行します：
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
AppVM のブラウザーで **http://127.0.0.1:8000** を開きます。

サーバーはループバック以外では決して待ち受けません。実行後に完全にオフラインにするには、AppVM の
NetVM を切り離してください — UI は外部への依存がなく、保存済みのデータで動作し続けます。

---

## B. ローカルでの開発用実行（Python 3.13 がある任意の Linux）

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

便利な環境変数：`OO_DATA_DIR`（SQLite データベースとデータの保存場所）、`OO_HOST`/`OO_PORT`、
`OO_FETCH_MIN_INTERVAL`（ホストごとの配慮のための待ち時間、秒）。

### Tails の場合

Debian/Ubuntu/Tails では、標準ライブラリの `venv`/`ensurepip` が**別の apt パッケージ**になっているため、
それをインストールするまで `python3 -m venv` は失敗します。現在は `install.sh` がこれを
**自動で**インストールします — Tails ではそのために**管理者パスワード**（ようこそ画面で
設定します。既定ではオフです）と、動作している **Tor 接続**（apt は Tor 経由で
ダウンロードします）が必要です。apt を自分で実行したい場合は、`OO_NO_APT=1` で自動インストールを止められます。

Tails に特有の、正直にお伝えすべき注意点が 2 つあります：

- **Python のバージョン。** Tails は Debian 12 ベース → **Python 3.11** ですが、このアプリは **3.13** を対象としています。
  3.13 のインタープリターを用意し、インストーラーにそれを指定する必要があります
  （`OO_PYTHON=python3.13 ./install.sh`）。3.13 とその `python3.13-venv` パッケージは、Tails の既定の
  リポジトリには**ありません**。
- **記憶を残さない仕組み（Amnesia）。** apt でインストールしたもの — そして `.venv` 全体 — は、
  永続ストレージ（Persistent Storage）上に置かない限り**再起動で失われます**。venv パッケージは
  **永続ストレージ → 追加ソフトウェア（Persistent Storage → Additional Software）**から追加し、
  チェックアウトと `OO_DATA_DIR` は永続ボリューム上に置いてください。

### 既存のデータベースのアップグレード

新規インストールではスキーマが自動で構築され（`init_db()`）、データベースには
現在のマイグレーションのベースラインが記録されます。将来のリリースでスキーマが
変わったときは、既存のデータベースを次のコマンドでアップグレードします：
```bash
alembic upgrade head
```
`alembic check` はモデルとマイグレーションが一致しているかを報告します（CI がこれを監視しています）。

---

## C. Windows 11 の場合（PowerShell）

**サポート状況の正直な説明 — まずこれを読んでください。** CI は実行のたびに、
`windows-latest` 上で 3 つのことを証明しています：依存関係のインストール、**起動チェック**（アプリ全体が
インポートできること）、そして **SQLCipher による保存時の暗号化** — 最後のものは*ブロッキング*レーンで
確認しているので、暗号化は推測ではありません。それ以外は何も証明されていません。Windows の **pytest レーンは
停止したまま進まなくなります**（最近完了した実行は `pytest` で 3 時間 21 分と約 6 時間止まっていました。
macOS では 18 分です）。また、**Windows で UI を実際にクリックして確認した人はまだいません**。ですから、
インストールと起動は動くと考えてよいものの、起動より先のことはすべて未検証として扱い、
問題があればぜひ報告してください。リリースの判定基準は引き続き Linux です。

### 1. インストール

**PowerShell** を開きます（Python 自体をインストールする必要がない限り、管理者権限は
不要です）。インストーラーをダウンロードし、よければ中身を読んでから、実行します：

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Git と Python 3.13 がない場合に限り `winget` でインストールし、
`%USERPROFILE%\Open-Omniscience` にクローンして `.venv` を作成し、実際のアプリを
インポートして結果を検証します。より充実した既定のセットにするには `-Extras` フラグを外してください。または
[インストーラーのオプション](#インストーラーのオプション)を参照してください。

すでにクローン済みですか？ その場で実行してください — 自身のチェックアウトを検出し、クローンを省略します：

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **なぜ `irm … | iex` の 1 行にしないのですか？** リモートのコードを取得して
> メモリから直接実行するのは、Windows のマルウェアが送り込まれる最も一般的な手口なので、
> Defender はスクリプトの中身にかかわらず、その形を危険と判定するからです。先にファイルを
> 書き出すほうが、ブロックされにくく、しかもより誠実です — 実行される前に中身を読めるからです。

### 2. Windows Defender がインストーラーを隔離した場合

Defender は `install.ps1` を見つけた瞬間に削除することがあります。これは**誤検知**ですが、私たちの言葉を
そのまま信じる必要はありません — なぜそうなるのかを正確に説明しますので、ご自身で判断してください：

- このファイルは**署名がなく新しい**ため、Defender のクラウド評価がまだ一度も見たことがありません。
  不明かつ署名なしというだけで、機械学習によるヒューリスティックに引っかかるのに十分です。
  検出名は通常 `!ml` で終わります。
- その**形**がいかにもインストーラーらしいものです：パッケージマネージャーを呼び出し、レジストリから `PATH` を
  読み直し、スタートメニューのショートカットを書き込み、`-Uninstall` の処理ではディレクトリを
  削除します。ドロッパー（マルウェアを設置するプログラム）も同じことをします。分類器が判定するのは意図ではなく形です。

含まれて*いない*もの — 約 500 行の読みやすいコードでご自身で確認できます：
`Invoke-Expression` はなく、エンコードや難読化されたペイロードもなく、`WebClient` もなく、隠し
ウィンドウもなく、このリポジトリ以外からのダウンロードもありません。

対処方法は 3 つあります。おすすめ順に：

1. **スクリプト不要の手順を使う** — 下の[手動インストール](#手動インストールスクリプトなし)です。
   インストーラーが実行するのと同じコマンドで、隔離されるファイルがありません。この方法は必ずうまくいきます。
2. **誤検知を Microsoft に報告する** —
   <https://www.microsoft.com/en-us/wdsi/filesubmission> から（*Software developer* を選びます）。
   たいてい 1〜2 日で対応され、あなただけでなく、あなたの後にインストールする
   すべての人について修正されます。
3. **フォルダーを除外する**（Windows セキュリティ（Windows Security）→ ウイルスと脅威の防止 → 設定の管理
   → 除外）。実行する前に、何と引き換えになるかを知っておいてください：除外すると Defender は
   そのフォルダーのスキャンを*完全に*、あらゆるものについて、無期限に停止します — この 1 つのファイルだけではありません。
   あなたのマシンですから、判断はあなた次第です。私たちは、これに代償がないふりをするつもりはありません。

私たちの側での誠実な解決策はコード署名ですが、まだ用意できていません。

### 3. 実行する

インストーラーは**デスクトップ**と**スタートメニュー**に **Open Omniscience** のショートカットを
作成します。それをダブルクリックすると、ターミナルウィンドウが現れ、アプリが実際に応答し始めた時点で
ブラウザーで **http://127.0.0.1:8000** が開きます。止めるには、そのウィンドウを閉じる（またはアプリの
電源ボタンを使う）だけです。

代わりにターミナルから起動するには：`scripts\launch.cmd`。

### 4. 初回起動

どのプラットフォームとも同じ一度きりの流れです：**言語を選ぶ → 利用規約を読んで
同意する → コーパスのパスフレーズを作成する**。コーパスは**既定で保存時に暗号化**され、
パスフレーズをなくした場合の**復旧手段はありません**。アプリはその後
**オフライン（機内モード）**で起動します。オンラインにするときは**同意ポップアップを 1 回**経由します。

### インストーラーのオプション

| フラグ | 動作 |
|------|--------------|
| *（なし）* | コア + `analysis,compression,columnar` をインストールし、検証してランチャーを作成 |
| `-Path <dir>` | `%USERPROFILE%\Open-Omniscience` 以外の場所にインストール |
| `-Extras "analysis"` | pip のエクストラを選択（コアのみなら `""`） |
| `-Ref <branch>` | 特定のブランチまたはタグをクローン |
| `-NoPython` | Git/Python を自動インストールしない。代わりに手順を示して失敗する |
| `-NoLauncher` | デスクトップ / スタートメニューのショートカットを作らない |
| `-Check` | 健全性レポート（`open-omniscience doctor` と同じ） |
| `-Uninstall` | `.venv` とランチャーを削除。データは別途確認しない限り残す |
| `-Yes` | 確認にすべて「はい」と答える（無人実行） |

Windows で CI により証明されているのは `analysis` だけです。より充実した既定のセットのインストールに
失敗した場合、スクリプトは黙って失敗したり、エクストラが入ったふりをしたりせずに、**`analysis` に切り替え、
そのことを表示します**。

### 手動インストール（スクリプトなし）

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

### Windows 固有の注意点

- **実行ポリシー。** 既定のポリシーでは `.\.venv\Scripts\Activate.ps1` がブロックされます。
  ここでの手順はどれもそれを必要としません：`.venv\Scripts\python.exe` をパスで直接呼び出せば、問題そのものが
  なくなります。インストーラー自体については、コマンドラインの `-ExecutionPolicy Bypass` で対応しています。
- **Microsoft Store を開いてしまう `python`。** 新しい Windows 11 には、`python.exe` という名前の
  実行エイリアスのスタブが入っており、コードを実行する代わりに Store を起動します。インストーラーは
  これを無視し（スタブはバージョンを表示しません）、`py -3.13` ランチャーを使います。手動でインストールする
  場合は、`python` より `py -3.13` を使ってください。
- **データの保存場所。** これはソースのチェックアウトなので、コーパス、署名
  鍵、設定は `%APPDATA%` ではなく **`<repo>\data`** に置かれます。別のドライブに置くには `OO_DATA_DIR` を
  設定してください。
- **フォルダーの権限。** Linux ではデータディレクトリはあなたのユーザーだけがアクセスできるように制限されます
  （`chmod 0700`）。この呼び出しは Windows では何もしないため、フォルダーは通常の
  Windows の ACL を継承します。共有 PC では、`<repo>\data` へのアクセスをご自身で制限してください。どちらの場合も、
  コーパスのデータベース自体は保存時に暗号化されています。
- **SmartScreen / Defender。** ここにあるものはどれもコード署名されていないため、Windows はすべてを
  不明なものとして扱います：SmartScreen がランチャーについて警告することがあり、Defender が
  `install.ps1` をそのまま隔離することもあります — それが何で、どう対処すればよいかは
  [§2](#2-windows-defender-がインストーラーを隔離した場合) を参照してください。リアルタイムスキャンにより、最初の `pip install` も目に見えて遅くなります。
- **ポート。** 8000 以外にするには、起動前に `OO_PORT` を設定してください。`scripts\launch.cmd` も
  この設定に従います。
- **アーキテクチャ（x64 / ARM64 / 32 ビット）。** インストーラーが検出して対処します。ここでは
  それが何を判断しているかを説明します。`pip install` が成功するかどうかを左右するのは
  マシンではなく、*インタープリター*のプラットフォーム向けにどの wheel が存在するかです。2026-08-23 に
  PyPI で、CPython 3.13 について、このプロジェクトの依存関係全体を対象に計測した結果は次のとおりです：

  | インタープリター | wheel |
  |---|---|
  | `win-amd64` | **すべての依存関係。** 唯一の完全なアーキテクチャです。 |
  | `win-arm64` | 3 つを除くすべて — `cryptography`（コア）、`httptools`（コア、`uvicorn[standard]` 経由）、`statsmodels`（`analysis`） |
  | `win32` | `cryptography` が 1 つも公開していません |

  ARM 版 Windows は x64 のバイナリを透過的に実行できるので、**ARM64 でも x64 のインタープリターが
  正解です** — 妥協ではなく、完全なセットが揃うからです。そのため `install.ps1` は
  どこでも `win-amd64` を優先し、マシンにない場合は入手します：
  まずアーキテクチャを指定した winget、次にユーザースコープでの winget、最後に Python
  Software Foundation が nuget.org で提供する自己完結型の x64 CPython です — これは nuget が証明する
  SHA-512 と照合して検証され、`%LOCALAPPDATA%\Open-Omniscience\python-x64` に展開されます。
  管理者権限への昇格も、PATH の変更も、レジストリへの登録も必要ありません。これは意図的にチェックアウトの
  **外**に置かれています：マシンのリソースなので、アプリのフォルダーを削除しても残り（そうしないと、
  その上に作られた `.venv` が壊れてしまいます）、2 つ目の `-Path` のチェックアウトでも再利用されます。`-Uninstall` で削除されます。ハッシュが一致しない場合や、
  nuget がハッシュを証明していないバージョンの場合は、**拒否**します。

  すべての手段が失敗した場合は、20 分かけた Rust のビルドの末に `linker link.exe not found` で
  終わるのではなく、ダウンロード 1 つで済む解決策を示して停止します。

  既存の `.venv` は**見つけるだけでなく、中身を調べます**：`.venv` は、それを作ったインタープリターの
  バージョンと wheel のプラットフォームを保持しているので、以前の実行で別の Python によって
  作られたものは再利用せずに置き換えます — そうしなければ、上で説明したことがすべて最後の段階で
  黙って無効になってしまいます。一致するものはそのまま再利用します。したがって、インストールが
  途中で終わった場合は、インストーラーを再実行すれば直ります。手作業で何かを削除する必要はありません。

  - **ネイティブの ARM64 インストールが自動で有効にならない理由。** そのためには `cryptography` を
    46.0.0〜46.0.3 に固定する必要があります。ARM64 の wheel があるのはこの系列だけです。このリリースには
    **未解決のセキュリティ勧告が 13 件**あります（48.0.1 で修正された、静的リンクされた OpenSSL に
    関するものを含みます）。このアプリは証拠に署名します。それを黙ってインストールするのは、見せかけだけの
    セキュリティにすぎません。お使いのマシンに Visual Studio Build Tools **と** Rust の
    ツールチェーンが本当にあるなら、`-AllowSourceBuilds` でこの 3 つをネイティブにコンパイルできます — 明示的な選択であり、
    既定には決してなりません。
  - **32 ビット版 Windows はサポートされていません**。これは方針による制限ではなく、実際の制約です：
    `cryptography` は `win32` 用の wheel を提供していません。64 ビット版 Windows が必要です。

---

## D. 一連の流れ（UI または API）

> **情報源はあらかじめ設定されています。** 初回起動時（または `install.sh --appvm` の実行中）に、
> 厳選されたカタログ（`configs/sources.yml` の約 3,200 の公益性のある報道機関に加え、
> 市場、政治的スペクトラム、法律/知的財産のカタログ — **合計で約 3,395 の重複しないドメイン**）が
> 自動で登録されるので、すぐに取り込みを始められます。
> （これらの数はカタログの拡充とともに**変動**します。実際の数値は、その時点で
> `configs/*.yml` に含まれているものです。）再登録は冪等です。自動登録は
> `OO_AUTOSEED=0` で無効にできます。手動で再登録するには `python scripts/seed_sources.py` または
> `POST /api/sources/seed-defaults` を使います。フィードの URL や robots のポリシーは時間とともに変わります。
> 倫理的フェッチャーは確認できないものはすべて拒否するので、調査に合わせてリストを整理・拡張してください。

**UI では：** 一度**オンラインにする**と（機内モードの切り替え → 同意ポップアップを 1 回）、
**収集はバックグラウンドで自動的に進みます** — 言語と情報源のタグごとに層別され、robots を尊重し、
速度制限をかけて行われます。次に**探索で検索**します（サイドバーのタブ。トップバーか Ctrl/⌘-K のオムニバーで Enter を押すと、
探索が新しいブラウザタブで開きます）— 一致した記事の分析が検索結果の下に表示され、
そこで絞り込み、閲覧、ブール検索の実行、**エクスポート**（CSV/JSON、手法の
付録、署名済みエビデンス）ができます。**設定 → 詳細 → 収集 / 情報源**から、情報源を追加して、
1 つのフィードや URL を手動で*取り込む（Ingest）*こともできます。

**API 経由では：**
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

機械可読な API スキーマは **http://127.0.0.1:8000/openapi.json** にあります。対話型の Swagger ページは既定でオフです（第三者のホストからアセットを読み込むためです）。開発者は `OO_API_DOCS=1` を付けてアプリを起動すると、`/docs` で利用できます。

---

## E. 分析機能

いずれもローカルファーストで、うまく動かないときははっきりとそう示します（決してでっち上げません）。完全なスキーマは `/openapi.json` にあります。

**ローカル LLM（Ollama）。** **設定 → AI** からセットアップします：アプリ内の
**チェックサム検証付き** Ollama インストーラー（Linux）に加え、**モデルのダウンロードキュー**（実際の
バイト単位の進捗、キャンセル可）、使用するモデルの選択、編集可能なプロンプトのパネルがあります。または、
**ollama.com** から Ollama を自分でインストールし、`ollama pull llama3.2:3b` を実行します。モデルの取得は
**Ollama のプロセスを経由してクリアネット**で通信します（アプリの Tor 経路ではありません）— このことは
同意時に開示されます。トップバーの LLM ピルが現在の状態を表示します（クリックすると 設定 → AI が開きます）。各
検索結果には **要約** と **翻訳** のボタンがあります。API：
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Ollama が動いていない場合、これらは偽の要約ではなく、わかりやすいメッセージ付きの HTTP 503 を返します。

**商品価格と誠実な相関分析。**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
相関分析は scipy（Pearson/Spearman）による実際の係数、p 値、n を返し、
「相関 ≠ 因果」の注意書きを添えます。重なりが少なすぎる場合は → `insufficient_data` です。

**監視。** `POST /api/monitoring/health` は（倫理的フェッチャーを通じて）実際の到達可能性を
確認します。`GET /api/monitoring/anomalies` は記事数の急増を z スコアで
検出します。**メール：** `POST /api/sources/{id}/ingest-email`
（IMAP）はメッセージを同じ検索可能なコーパスに取り込みます。

**画像メタデータの検証。** `POST /api/verify/image-metadata`
（画像をアップロード）は、その形式、寸法、EXIF、GPS を、事実に基づく平易な
所見（例：編集ソフトのタグがある、撮影日時がない）とともに返します。範囲は正直に
*メタデータの確認*に限っています — ディープフェイクや改ざんの検出では**ありません**（その機能は
でっち上げであったため、作業ツリーから隔離されました。
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md) を参照）。

**署名済みエビデンスバンドル。** 分析ウィンドウの **署名済みエビデンスをエクスポート**
ボタン（または `POST /api/reports/evidence`）で、Merkle ルート付きの
Ed25519 署名バンドルが作成されます。このアプリがなくても、誰でもオフラインで検証できます：
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**証拠保全の連鎖。** **証拠保全の連鎖** の UI パネルは、署名され、
改ざんを検知できる来歴を記録し、その動作を実行中に切り替えられます：
ポスト量子署名、アンカーのモード（オフラインの `local` か、Bitcoin にアンカーする
**OpenTimestamps** か）、取り込み時の自動記録です。切り替えは*希望の設定*にすぎません — パネルには
**実際に有効な**状態が表示されるので、必要な追加機能がインストールされていないのにオンだと
主張するものはありません。API：
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
完全なモデル、脅威モデル、プライバシーに関する注意点：[USER_MANUAL.md](USER_MANUAL.md)。

---

## 「倫理的な取り込み」が保証すること

- robots.txt を取得し、ホストごとにキャッシュし、**確認できなければ取得しません（フェイルクローズ）**：
  確認できない場合（ネットワークエラー、タイムアウト、5xx、または制限付きの 401/403）、その URL は
  取得**しません**。
- ホストごとの最小間隔を守ります（`Crawl-delay` に従います）。
- 取得経路は 1 つだけで、身元を明かす User-Agent を使い（保護モードでは汎用の User-Agent。ただし Wikimedia のサーバーへの API とダンプのリクエストは除く）、記事は HTML のみを対象とします — 生の回避経路はありません。
- 本文の抽出には trafilatura を使います。実際の記事本文が見つからなければ、何も保存しません
  （「タイトルなし / 内容なし」のようなでっち上げの行は作りません）。
- 保存されるすべての記事には来歴が付きます：情報源、元の URL、正規 URL、
  コンテンツのハッシュ（重複排除に使用）、取得日時。
