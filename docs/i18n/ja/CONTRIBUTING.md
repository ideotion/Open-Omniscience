<!-- ja: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# コントリビューション

ご協力ありがとうございます。指針となる原則は**誠実さ**です。機能は主張どおりに動作しなければならず、そうでなければリリースしません。捏造された出力、偽の信頼度スコア、無言の機能低下は認めません。[DESIGN.md](DESIGN.md) §3 を参照してください。

## セットアップ

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

依存関係の唯一の情報源は引き続き `pyproject.toml` です（下限の範囲内で最新版をインストールするため、上流の破壊的変更を CI が早期に検出できます）。**再現可能な／リリース用のインストール**のために、そこから派生したハッシュ固定のロックファイルがあります。

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**これは手で実行するコマンドにとどまらず、`./install.sh` に組み込まれています。** オンラインのインストール経路（`pip_install()`）は、`requirements.lock` が存在し、実行中の Python 向けに生成されており、要求されたすべてのコンポーネント（`OO_COMPONENTS`）をカバーしている場合に、自動的にそれを使用します。この判定はロックファイル自身の `pip-compile ... --extra=...` ヘッダーと照合して行われ、手作業で管理されることはありません。これらのいずれかが成り立たない場合（ロックファイルが実行中の Python に対して古い、ロックファイルの生成時に含まれていないコンポーネントを要求している、あるいはピン留めがこのプラットフォームで解決できない）、通常の下限ベースの `pip install -e ".[...]"` による解決にフォールバックし、監査済みの経路が使われなかった理由を目立つメッセージで表示します。`OO_USE_LOCK=0` を指定すると、ロックファイルを無条件に使わなくなります。**出荷時点では、ロックファイルがカバーするのは `--extra analysis` のみ**ですが、`install.sh` 自身の既定のコンポーネント集合は `analysis,compression,columnar` です。そのため、既定のまま無人で `./install.sh` を実行すると、現状では下限ベースの解決にフォールバックします（compression/columnar はロックファイルのカバー範囲外です）。現状のまま監査済みの経路を使うには `OO_COMPONENTS=analysis ./install.sh` を実行するか、`pip-compile --extra analysis --extra compression --extra columnar ...` でロックファイルのカバー範囲を広げて、既定のインストール経路もロックファイルベースにしてください。

**オフライン／エアギャップ用バンドル**（`scripts/build_offline_bundle.sh`。Qubes/Tails 向けに `install.sh` の `--no-index` オフライン経路が使用します）は、**まだロックファイルに接続されていません**。ビルドのたびに `pyproject.toml` の下限から新たに解決しています。これは見落としではなく、既知の未解決の課題です。オフラインバンドルもロックファイルベースにすること（`pip download --require-hashes -r requirements.lock` を使い、ロックファイルがカバーしない extras については `$SPEC` ベースの解決をフォールバックとして残す）は、今後の作業として追跡されています。

## ワークフロー

- **Python 3.13**、単一の `pyproject.toml`（requirements.txt はなし）。
- リント／フォーマットは **ruff**、型チェックは **mypy**：`make lint && make typecheck`。
- すべての変更はグリーンで終えること：`make check`（ruff + pytest）。新しい振る舞いには振る舞いテストを追加してください。修正するか隔離するかのどちらかにし、中途半端に動くコードを import パスに残さないでください。
- コミットは小さく誠実な単位で行い、メッセージには*何を、なぜ*を書いてください。
- スキーマ変更は Alembic（`alembic revision --autogenerate`）を通します。CI は `alembic check` を実行して、モデルとマイグレーションのずれを検出します。

## 出荷台帳：1 行につき 1 ファイル

`docs/ledger/shipped.csv` に追記しないでください。GitHub のマージチェックはこのファイルの `merge=union` ルールを無視するため、PR ごとに行を追記すると、マージのたびにすべての未マージ PR が衝突していました。代わりに新しいファイルを 1 つ追加してください。

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

これは `docs/ledger/shipped.d/<date>-<slug>.csv`（台帳のヘッダーと 1 行）を書き出します。他の PR は、自分が触れないファイルとは衝突しません。`python scripts/ledger_shipped.py check` はすべての断片を検証します。リリースノートとリポジトリ不変条件のテストは、まず `shipped.csv` を読み、その後に断片を読みます。`ledger_shipped.py fold` は断片をバイナリで `shipped.csv` に追記してから削除します。これはメンテナーまたはリリースのためのものであり、機能 PR のためのものでは決してありません。`refs` は `PR pending` ではなく実際の PR 番号でなければなりません（そうでないとテストが失敗します）。

## 教訓と出荷ログのエントリ：それぞれ 1 ファイル

同じ規約が 2 つの大きなアーカイブにも適用されます。教訓は 1 つのファイル `docs/ledger/lessons.d/<date>-<slug>.md`（`python scripts/lessons.py --new SLUG`）、出荷ログの逐語的なエントリは 1 つのファイル `docs/ledger/shipped_log.d/<date>-<slug>.md`（`python scripts/ledger_fold.py new-log SLUG`）です。`LESSONS.md` や `SHIPPED_LOG.md` に追記したり、`_LESSONS_LINE_CEILING` を編集したりしないでください。そうした PR はすべて、他のすべての PR と衝突していました。断片は `## <date> — title` で始まり、改行で終わり、UTF-8 かつ LF 改行です。教訓（出荷ログのエントリではない）は 2 つ目の見出しを持たず、200 行未満に収めます（1 エントリの大きさを制限するため）。`python scripts/ledger_fold.py check`（および `tests/test_ledger_fragments.py`）がこれを検証し、`#NNNN` や `PR pending` のプレースホルダーを拒否します。また `lessons.py <words>` は断片も検索します。`ledger_fold.py fold` はリリース時に断片をアーカイブへ統合するもので、機能 PR のためのものでは決してありません。

## ロケールファイルとマージ衝突

12 個の `src/static/locales/*.json` ファイルは**ソート済み**に保たれています（`_meta` が先頭、その後キーをコードポイント順）。そのため、文字列を追加する 2 つの PR は異なる位置に挿入し、きれいにマージされます。文字列を追加したら `python scripts/locales_merge.py` を実行してください。ファイルをソートしてチェックします（`--check` は検証のみ。`tests/test_locales_merge.py` は未ソートまたは重複したキーで失敗します）。

`git merge origin/main` がロケールファイルに衝突マーカーを残した場合も、同じスクリプトを実行してください。すべてのハンクの両側を残してソートし、両側が 1 つのキーに異なるテキストを与えた場合は、そのキーを示して停止します（判断が必要な本当の矛盾です）。`docs/ledger/shipped.csv` は `.gitattributes` で `merge=union` になっており、ローカルの `git merge` はこれに従いますが、GitHub のウェブ上のマージやブランチ更新ボタンは従いません。main をローカルでマージしてから、`(date, area, item)` が重複した行がないか確認してください。

## 基準

- あらゆる場所に来歴を：保存されるデータは情報源＋タイムスタンプ＋ハッシュを伴います。
- ユーザーに表示される数値はすべて、不確実性を明示した実際の手法（`src/analysis`）から得られたものでなければならず、定数であってはなりません。
- 取り込みは単一の倫理的なフェッチャーを通します（robots はフェイルクローズ、レート制限あり）。
- 捏造された／使われていないコードは `src/` ではなく `quarantine/`（文書化のうえ）に置きます。

## 行動規範

参加することにより、[行動規範](CODE_OF_CONDUCT.md)（Contributor Covenant 2.1）を遵守することに同意したものとみなされます。懸念事項は open-omniscience@ideotion.com へ非公開で報告してください。

## ライセンス

コントリビューションは **GPL-3.0-or-later** の下で提供されます（[LICENSE](../LICENSE) を参照）。

---

# バージョニング方針

プロジェクトのバージョン付けの方法 — 成熟度を意図的に控えめに表示します。

**このパートの内容：**
- [バージョニング方針](#バージョニング方針)


---

## バージョニング方針

> **私たちは成熟度を意図的に控えめに表示します。誇張より誠実さを。** ユーザーにとっては、誤解させられるより、うれしい驚きのほうがよいのです。バージョン番号は*成熟度*についての約束であり、私たちはその約束を控えめに保ちます。

### 唯一の情報源

バージョンは**一か所、`pyproject.toml`（`[project] version`）にのみ**存在します。その他はすべてそこから派生します。

- 実行中のアプリは、インストールされたパッケージのメタデータ（`importlib.metadata.version("open-omniscience")`）からバージョンを読み取ります。そのため `/api/health`、API の `version=`、UI はすべて、*実際に*インストールされているバージョンを自動的に報告します。
- 他のコードはバージョンのリテラルをハードコードしません。テストは文字列ではなくパッケージのメタデータに対して検証します（`tests/test_api_search.py` を参照）。
- リポジトリ直下の `README.md` はヘッダーでバージョンを一度だけ記載し、CI のガードがパッケージと一致することを検証します（`tests/test_repo_invariants.py::test_readme_version_matches_package`）。

**バージョンを上げるには `pyproject.toml` だけを変更し**、README のヘッダーをそれに合わせて更新し（ガードがこれを強制します）、その後 `pip install -e .` を実行してメタデータを更新してください。

**`vX.Y.Z` のタグは、`pyproject.toml` がすでに `X.Y.Z` になっているコミットにのみ付けてください。** リリースワークフロー（`.github/workflows/release.yml`）は、何かをビルドする前にそれ以外のタグを拒否します。そのため、バージョンを上げる前に打たれたタグは、wheel、sdist、チェックサムのないリリースを公開することになります。最初の `v0.4.0` は 2026-09-28 にそのように打たれました。バージョンは後から設定され、タグはそこへ移動されました（`docs/product/RELEASE_0.4_GATE.md` の行 G）。**タグの移動には git が必要です。** GitHub のウェブサイトではタグの削除も移動もできず、そこで公開されたリリースは既存のタグを再利用し、ワークフローを起動しません。push できるローカルクローンがない場合は、`main` で Codespace を開き、`git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z` を実行してください。生成されたノートをワークフローに書かせたい場合は、先に GitHub のリリースを削除してください。ワークフローは既存のリリースのノートをそのまま残し、ファイルとチェックサムを追加するだけです。

### 成熟度のはしご（現在地と行き先）

ソフトウェアはまだ若く、検証の途中であるため、**`1.0` 未満**にとどまります。

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

実際以上の成熟度を示唆するバージョン番号に飛ぶことは**しません**（たとえば `0.2` は「20% 完成」でも「ベータ間近」でもなく、これまでのアルファサイクルの正直な回数です）。各サイクルは小さく実質的な反復であり、それ以上のことは主張しません。

### サイクル ↔ バージョンの対応

開発サイクル（およびそのブランチ）は、生み出すバージョンにちなんで名付けられ、簡潔さのために先頭のゼロを省略しています。

| ブランチ／サイクル名 | パッケージのバージョン |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  （`0.09` サイクルのブランチは、アルファへの切り替え時に `0.09 → 0.1` と改名されました）
| `0.2`  | `0.2.0` |  （`0.1` サイクルのブランチは、0.2 への切り替え時に `0.1 → 0.2` と改名されました）
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  （`0.2` サイクルのブランチは 2026-07-15 に `0.2 → main` と改名されました。既定のブランチは恒久的に `main` となり、ブランチ名とバージョンは独立しています。`v0.2.0` はライブコーパスでの規模検証の後にタグ付けされ、`v0.3.0` は測定・検証のサイクルを締めくくり、`v0.4.0` はリビングソースのサイクルを締めくくり、現在 `main` は `0.5.0`、調査者のデスク（investigator's-desk）リリースとなっており、`v0.5.0` としてタグ付けされています）

つまり「`0.06` のインテリジェンス層」とは「`0.0.6` で出荷される作業」を意味します。文書中で `0.05` のようなサイクルの略記を見たら、`0.0.5` と読んでください。PR は現在のサイクルブランチである `main` にマージされます。上に挙げた、廃止された番号付きブランチ名のいずれでもありません。

**最初のアルファ（`0.1.0`）以降、対応は `0.N` サイクル ⇒ `v0.N.0` です。** `0.2` サイクルは `v0.2.0` で、`0.3` サイクルは `v0.3.0` で、`0.4` サイクルは `v0.4.0` で、`0.5` サイクルは `v0.5.0` で締めくくられました（唯一の例外は統合された `0.09` サイクルで、これは `0.1.0` を生み出しました）。サイクルは、それを締めくくるリリースにちなんで名付けられます。リリースゲートのファイルが自らの言葉でそう述べています（`RELEASE_0.4_GATE.md` は「`0.4` サイクルを締めくくるための確認可能な一覧」です）。また、バージョン番号はタグの前、サイクルの途中で*設定*されることがあります（たとえば `0.4.0` はタグをそこへ移すために 2026-09-28 に設定されました。`0.5.0` は切り替えの PR で設定され、タグはそのマージコミットを指しています）。このため、変更履歴の見出しの日付とそのタグの日付が異なることがあります。

### なぜこれが重要か（価値観とのつながり）

このプロジェクトは、人々が情報を誠実に見られるよう支援するために存在します。自らの成熟度を誇張するツールは、その根本と矛盾することになります。控えめなバージョニングは、コードベースの他の部分と同じ規律です。**実在するものだけを主張し、それを証明すること。**
