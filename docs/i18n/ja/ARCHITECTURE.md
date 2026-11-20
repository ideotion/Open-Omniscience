<!-- ja: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# アーキテクチャと技術リファレンス

ユーザーマニュアルの技術的な補足です：データベース／設定、HTTP API の概観、そして国際化について説明します。

## 目次
- [Open Omniscience のデータベース設定](#open-omniscience-のデータベース設定)
- [API リファレンス](#api-リファレンス)
- [国際化（i18n）— アプリを多言語にする](#国際化i18n-アプリを多言語にする)


---

## Open Omniscience のデータベース設定

> **状況（v0.0.7 の監査 `docs/archive/audits/00_BASELINE.md` で確認済み）：** データベース層は
> **動作し、テストされています** — サーバーが起動し、SQLite ストアを作成・使用し、Alembic の
> マイグレーションを適用し、テストスイート全体（800 件以上）がそれに対して合格します。以前ここにあった
> 「初期コンセプト — 機能しません」というバナーは、再構築前の状態を述べたもので、
> ずっと前から古くなっていました。

### 🗃️ SQLite — サポートされているストア

SQLite は**デフォルトであり、サポートされテストされている唯一のバックエンド**です。製品の
ローカルファースト・単一運用者という設計に適合しています。

- **設定不要：** データベースは初回実行時に自動的に作成され、場所は
  `<data dir>/open_omniscience.db` です。データディレクトリは、`OO_DATA_DIR` が設定されていればそれ、
  そうでなければソースチェックアウトではリポジトリの `data/`、それ以外では `$XDG_DATA_HOME/open-omniscience` です
  （`src/paths.py` を参照）。
- **自動的に調整：** エンジンはすべての接続で `WAL` ジャーナルモード、`foreign_keys=ON`、
  `busy_timeout=30000`、`synchronous=NORMAL` を適用します
  （`src/database/session.py`）— これらを自分で設定する必要はありません。
- **全文検索**は SQLite の **FTS5** です（`article_fts`、外部コンテンツ型、トリガーで同期を
  維持 — `src/database/fts.py`）。
- **保存場所の変更**は環境変数 `DATABASE_URL` で行います（ソースファイルは
  **編集しないでください**）：`DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **メンテナンス：** ときどき `sqlite3 <db> "VACUUM;"` を実行すると領域を回収できます（v0.0.7 の監査では、
  大規模なコーパスでファイルの約 63% を占めていた冗長なインデックスも削除しました。アップグレード後に一度
  `make migrate` を実行して、既存のデータベースからそれを削除してください）。

### 🐘 PostgreSQL — 実験的な足場であり、サポートされていない

理想より正直さを（監査所見 ARCH-06）：エンジン層は PostgreSQL の `DATABASE_URL` を
*認識*します（`DB_POOL_SIZE`/`DB_MAX_OVERFLOW` による接続プーリング）が、**しかし**

- **PostgreSQL では全文検索が存在しません** — FTS5 のセットアップは SQLite 以外のエンジンでは
  意図的に何もしないため、検索タブは機能しなくなります。
- テストスイートは PostgreSQL に対して一度も実行されず、それをカバーする CI もありません。
- 公開されたデプロイメントでそれを使用したものはありません。

PostgreSQL は、今日選べる選択肢ではなく、**将来の可能性のためのテストされていない足場**として
扱ってください。マルチライターの規模が実際の要件になった場合のロードマップ項目は、
`tsvector` による検索経路と PostgreSQL の CI マトリクスです — それが実現するまで、このページは
取り繕うことをしません。

### 🔄 マイグレーション

Alembic は**リポジトリのルート**（`alembic.ini`、`migrations/`）で設定されています。Alembic は
アプリと一緒にインストールされます（コア依存パッケージなので、別途インストールする必要はありません）。

- **新しいデータベース**は完全な状態（`create_all` + FTS）で作成され、起動時に自動的に
  現在のマイグレーションの head でスタンプされます。
- **既存のデータベースのアップグレード：**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **マイグレーションの作成**（貢献者向け）：`src/database/models.py` を編集してから、
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  を実行し、生成されたファイルを確認してください — autogenerate は FTS の仮想テーブルを見落とします（それらは
  `src/database/fts.py` にあり、起動時に適用されます）。
- **ロールバック：** `alembic downgrade -1`。

---

### 📊 データベーススキーマ

#### テーブル：

##### `sources`
| 列 | 型 | 説明 |
|--------|------|-------------|
| `id` | INTEGER | 主キー |
| `name` | STRING(100) | 情報源の名前（例："BBC News"） |
| `domain` | STRING(255) | 情報源のドメイン（例："bbc.com"） |
| `rss_url` | STRING(500) | RSS フィードの URL（ある場合） |
| `rate_limit_ms` | INTEGER | リクエスト間の遅延（ミリ秒） |
| `enabled` | BOOLEAN | スクレイピング対象として有効かどうか |
| `priority` | INTEGER | 優先度（1 = 高、3 = 低） |
| `tags` | STRING(500) | タグのカンマ区切りリスト |

##### `articles`
| 列 | 型 | 説明 |
|--------|------|-------------|
| `id` | INTEGER | 主キー |
| `url` | STRING(1000) | 記事の元の URL |
| `canonical_url` | STRING(1000) | 正規化された URL（重複検出用） |
| `source_id` | INTEGER | `sources` への外部キー |
| `title` | STRING(500) | 記事のタイトル |
| `content` | TEXT | 記事の本文全体 |
| `published_at` | DATETIME | 公開日時（ISO 形式） |
| `language` | STRING(10) | 言語コード（例："en"、"fr"） |
| `hash` | STRING(64) | 本文の SHA-256 ハッシュ（重複検出用） |
| `created_at` | DATETIME | 記事が取り込まれた時刻 |

> 上記の列は中核となるフィールドです。実際のスキーマ（`src/database/models.py`）
> と `migrations/versions/` 以下の Alembic マイグレーションが正式な情報源です。
> `articles` には、来歴／分析用のフィールド（author、word_count、region、
> country、sentiment）と、圧縮された本文の列もあります。

##### その他のテーブル（すべての列はモデル／マイグレーションを参照）

| テーブル | 目的 |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | 情報源のグループ化 + 地理／robots のメタデータ |
| `commodity_prices` | 観測された価格点（銘柄、日付、価格、通貨、**単位**、市場、情報源）— チャート + 価格とニュースの相関 |
| `market_extraction_rules` | 1 つのページ上で 1 つの銘柄の価格を特定する、情報源ごとのルール（CSS セレクター／属性／正規表現）。カテゴリーは financial/stock/commodity |
| `keywords` | 個別のキーワード／エンティティ語（正規化済み、言語、`is_entity`/`entity_type`、**`extractor`** による来歴） |
| `keyword_mentions` | （記事、キーワード）ごとに 1 件：出現回数 + 最初の文字オフセット + 非正規化された `observed_on`/`country`/`city` — インサイトのトレンド、関連、文脈、地図を支える |
| `wiki_pages` | 1 つの言語版で追跡している Wikipedia のページ。圧縮された全文のベースラインを **1 つ**保持する |
| `wiki_revisions` | 追跡している 1 件の編集：**差分 + 符号付きのバイト増減** + フラグ／タグ（再コピーではない）、任意の ORES スコア、正直な大規模編集フラグ + その理由 |
| `article_analyses` | 派生した LLM の結果（要約／翻訳）。モデルとプロンプトの来歴付き |
| `keyword_categories`, `external_sources`, `article_links`, … | キーワードの分類 + リンク／情報源の関係の追跡 |

#### インデックス：
- `idx_article_hash`：`hash` に対する一意インデックス（重複検出用）。
- `idx_article_canonical_url`：`canonical_url` に対するインデックス（URL の検索用）。
- `idx_article_source_id`：`source_id` に対するインデックス（情報源ベースのクエリ用）。
- `idx_article_content`：`content` に対するインデックス（全文検索用）。

---

### 🔍 全文検索

全文検索は**すでに構築され、接続されています** — 有効にする必要があるものはありません。ストアには
トリガーで同期が保たれる FTS5 の外部コンテンツテーブル（`article_fts`）があります。スキーマについては
`src/database/fts.py` を、クエリの経路については `src/api/main.py` の `search_ids` を参照してください
（最終的な順序で ID のみを解決し、行全体はそのページの分だけ読み込みます）。

このセクションには以前、SQLite 向けの「仮想テーブルの作成を検討する」という手順と、PostgreSQL 向けの
`to_tsvector` の手順が載っていました。どちらも誤りでした：SQLite の手順は、アプリが出荷し維持している
テーブルを手作業で構築する方法を説明しており（しかも*別の*名前で。従えば、維持されない第二の
インデックスができていたはずです）、PostgreSQL にはここでの検索経路がまったく存在しません。
これは上記のストアのセクションで、サポート対象のバックエンドでない第一の理由として述べたとおりです。

---

### 📉 監視とメンテナンス

- **データベースのサイズを確認する**：
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **テーブルのサイズを確認する**：
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  **暗号化された**ストアでは、`sqlite3` CLI はファイルをまったく開けません（それこそが
  暗号化の目的です）— アプリ内の設定 → 診断の画面を使ってください。これらは、アプリ自身が使うのと
  同じ保護された接続ファクトリーを通じてストアを読み取ります。

---

### 🚨 トラブルシューティング

#### よくある問題：

##### SQLite：
- **「Database is locked」**：
  - SQLite は同時に 1 つの書き込みしか許可しません。WAL モードはデフォルトで有効になっており
    （`src/database/session.py`）、プロセス全体の単一ライターゲート
    （`src/database/writer.py`）がアプリ内の書き込みを直列化するため、取り込みと
    インポートが同時に行われても衝突しなくなりました。ロックが続く場合は、別の*プロセス*が書き込んでいます。

- **「Too many open files」**：
  - SQLite はスレッドごとに新しい接続を開きます。スレッドの数を制限するか、接続プーリングを使用してください。

- **「Relation does not exist」／「no such table」**：
  - マイグレーションを実行してください：`alembic upgrade head`。

---

### 📌 ベストプラクティス

1. **`cp` ではなくアプリを通じてバックアップする**：
   - 設定 → バックアップ（または一貫したスナップショットのための `GET /api/database/backup`）を使用してください。
     `open_omniscience.db` を手作業でコピーすることはバックアップでは**ありません**：ストアは WAL
     モードで動作しているため、稼働中のファイルには `-wal` にまだ残っている内容が欠けており、デフォルトの
     **暗号化された**ストアでは、コピーしたファイルはパスフレーズなしでは役に立たず、
     完全性を保証するものも何も付いていません。アプリ自身の経路はチェックポイントを行い、ストリームし、署名します。

2. **マイグレーションをテストする**：
   - 本番環境に適用する前に、必ずデータベースのバックアップでマイグレーションをテストしてください。

3. **パフォーマンスを監視する**：
   - 設定 → 診断には、スロークエリログ、リクエスト遅延ログ、
     書き込みゲートのレポートがあります。`sqlite3` CLI は平文のストアで動作します。

4. **クエリを最適化する**：
   - 使う道具は `EXPLAIN QUERY PLAN` です。SQLite は、単純なテーブルスキャンとインデックスのみのスキャンの
     **両方**で `SCAN` と書くことに注意してください — `SCAN <table> USING [COVERING] INDEX …` は
     健全です。問題の兆候は `USING` のない単なる `SCAN <table>` です
     （`src/monitoring/slowquery.py` はまさにその点で分類します）。

5. **データの保持を制限する**：
   - データベースを扱いやすく保つため、古い記事を定期的にアーカイブまたは削除してください。
   - 例：1 年より古い記事を削除する：
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Copyright © 2026 Ideotion. GNU General Public License v3.0
またはそれ以降（GPL-3.0-or-later）の下でライセンスされています — [LICENSE](../LICENSE) を参照してください。これはフリーソフトウェアです。
これらの条件の下で再配布および改変することができます。*


---

## API リファレンス

常に正確な最新の API リファレンスは、アプリ自体が生成します：

- **Swagger UI / ReDoc：** デフォルトでは無効です（サードパーティのホストからアセットを読み込むため）。http://127.0.0.1:8000/docs と `/redoc` を使うには、`OO_API_DOCS=1` を付けてアプリを起動してください
- **OpenAPI JSON：** http://127.0.0.1:8000/openapi.json

アプリはループバックにのみバインドし、（単一のローカル利用者向けには）認証を必要としません。

### エンドポイントのグループ

これは**主要なグループの概観であり、網羅的な一覧ではありません** — 実際の
`/openapi.json`（上記）が常に正式なものです。ルーターは `src/api/main.py` で
`include_router(...)` によって接続されています。**[analysis]** と記されたグループには
`[analysis]` 追加機能が必要です（それがなくてもアプリは起動し、それらのエンドポイントは無効になります）。

| プレフィックス | 機能 |
|--------|--------------|
| `GET /api/health` | 稼働確認 + バージョン |
| `GET /api/articles`, `/api/articles/export` | ブール演算による全文検索（FTS5）+ CSV/JSON エクスポート |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | 倫理的な取り込み：単一の URL、RSS フィード、IMAP メールボックス |
| `… /api/sources`, `/api/sources/...` | 情報源 + グループ + メタデータの管理 |
| `POST /api/sources/seed-defaults` | 厳選された情報源カタログの投入（ニュース + マーケット + 生成された世界カタログ） |
| `GET /api/database/stats`, `/coverage`, `/countries` | コーパスの行数 + ディスク上のサイズ。国別のカバレッジ。国ごとの情報源数 + トピックのキーワード |
| `GET /api/database/backup` | 一貫した SQLite スナップショットのダウンロード（平文の SQLite ストアのみ。別のサイトからのリクエストや、DNS リバインディング防御が受け付けない Host へのリクエストは拒否され、ループバック以外の名前では、`X-OO-Download: 1` を送らない限り、送信元のページを示さないリクエストも拒否される。プロセスごとに一度に 1 件のみ。データベースの隣にある非公開の `.oo-backup-*` フォルダーに書き出され、ダウンロードの終了時またはプロセスの停止時に削除される（強制終了された場合は次回起動時の一掃に委ねられ、そこで所有者が消えたフォルダーは直ちに削除される）。データボリュームに収まらない場合は 507） |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | 署名付きの `oo-backup-2` アーティファクトによる**追加のみ**の復元：統合計画をプレビューしてから、コミットする。復元は**コーパスを決して上書きしない** — 重複なく統合し、衝突時にはローカルの値を保持する（破壊的な置換の経路は 2026-06-13 に削除された） |
| `GET/PUT /api/settings` | GUI の設定（テーマ、デフォルトの結果件数） |
| `… /api/scheduler/...` | バックグラウンドの収集：状態、開始、停止、今すぐ実行、設定。`0.4` サイクル以降、収集は単一のスケジューラーモードではなく、**並行するレーン**（`rss` / `crawl` / `markets` / `wiki` / `law`）として動作する — レーンごとのストレージは `… /api/storage/...`、**生きた情報源**タブは `… /api/living/...`（Wikipedia、法令、地図で何が変わったか）を読み取る |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | 情報源ごとの価格抽出ルール +「テスト」実行 + マーケットの概要 |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | 公式 CSV 価格フィードのカタログ + インポート（FRED/World Bank/EIA）+ カスタム URL からのインポート |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | 情報源リストの CSV エクスポート／テンプレート／列／ドメイン単位で更新挿入するインポート |
| `… /api/insights/...` | キーワードとエンティティの分析：状態、再インデックス、上位、急上昇、トレンド、関連（PMI）、文脈、地図 |
| `GET /api/timemap`, `/timemap/range` | 1 つの地図 + 時間軸上の時空間シグナル（アンカー + ジオコーディングされたコーパス + オプトインの災害／言及された日付）。`?kinds`、`?start`/`?end` の小数年のウィンドウ、`?hazards`、`?articles`、`?mentions`、`?days` |
| `… /api/article-dates/...` | 記事本文中で言及された日付を抽出し、人が確認できる記事ごとのタグにする：記事ごとの一覧／抽出、確認／却下、一括インデックス、日付によるコーパスの絞り込み |
| `GET/POST /api/llm/...` | ローカル LLM（Ollama）：稼働状態、モデル、生成、記事の要約 |
| `… /api/commodities/...` | 商品価格（インポート／CSV／一覧）+ 正直な価格とニュースの相関 |
| `POST /api/analysis/...` | 科学的に厳密な統計：t 検定、相関、分散分析（ANOVA）、マン・ホイットニー検定、信頼区間 |
| `GET /api/monitoring/...` | 情報源の実際の稼働状況 + コーパスの量の異常 |
| `POST /api/verify/image-metadata` | 画像の EXIF／メタデータの正直な抽出 |
| `POST /api/reports/evidence`, `/evidence/verify` | 署名付きで改ざんを検知できる証拠バンドル |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | 追記専用でハッシュ連鎖された、署名付きの証拠保全（チェーン・オブ・カストディ）ログ + オフライン検証 |
| `GET/PUT /api/custody/settings` | 実行時の証拠保全の設定（ポスト量子署名、アンカリングモード、自動記録）— 利用可能性を考慮した*実効的な*状態を報告する |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | マークルルートのアンカリング（ローカル／OpenTimestamps）+ プロバイダーの利用可能性 |
| `POST /api/custody/reconcile` | 障害によって未記録のまま残った INGEST エントリーを書き込み、それぞれ署名付きメタデータで遅延記録と明示する。`scan` はそれ以前の欠落を数え、`record_gaps` はそれらをキューに入れる（2026-09-24、CUST-1） |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** キーワード抽出 + 記事の類似度 |
| `GET /api/search/omni` | インデックスに基づく統合オムニバー（記事の FTS5 + キーワード + 情報源 + wiki／法令） |
| `… /api/jobs/...` | タスクマネージャーのジョブ集約（収集パス、実行中の取得、wiki ダンプのキュー + 並べ替え） |
| `… /api/system/...` | システムのバイタル + ネットワークの状態／同意（機内モードのキルスイッチ、ローカルインターフェースの IP） |
| `… /api/safety/...` | 安全制御：キルスイッチ、発見ゲート、暗号化アーティファクトからの復元 |
| `… /api/briefing/...` | ホームのブリーフィング生成器（証拠の段階に応じたカード。手法 + 注意書き + n） |
| `… /api/insights/...`, `/api/insights/who`, `/where` | キーワード／エンティティの分析 + コーパス全体の「誰が／どこで」の集計 |
| `… /api/links/...` (shared, preview) | 共有された外部リンク／引用グラフの分析 + ローカルのリンクプレビューダイアログ |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | アジェンダのイベント。ローカルで計算された天文現象（Meeus）+ エルニーニョの表を含む |
| `POST /api/weather/context` | 裏付けのための、同意を得たうえで範囲を限定した Open-Meteo の再解析データの切り出し |
| `… /api/law/...` | 追跡している法令／一次資料の変更フィード |
| `… /api/integrity/...` | エコー／連携／系譜のシグナル |
| `… /api/annotations/...` | ローカルの、任意で署名できる記事の注釈 |
| `… /api/wiki/...` | Wikipedia の言語版、ウォッチしているページ、ダンプのダウンロード／読み取り、コーパスとの同期 |
| `… /api/hazards/...`, `/api/timemap` | 災害のオーバーレイ + 時空間地図 |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | 保存時の暗号化：ロックされた状態で起動したときのロック解除画面、暗号化／平文のストアの作成、ヘッダーの証明、一方向の暗号化ツール |

**[analysis]** と記されたルーター（commodities、statistics、keywords、framing）には
`[analysis]` 追加機能が必要です。それがなくても、アプリは中核部分のみで起動し、
それらのエンドポイントは無効になります。

動作に関する注記：
- 取り込みは倫理的な取得処理のみを通じて取得します（robots.txt のフェイルクローズ、レート
  制限付き）。Ollama が利用できない場合、LLM のエンドポイントは **503** を返します（偽の回答は決して返しません）。
- 証拠の検証：完全性だけでなく来歴を証明するには、署名者の公開鍵を渡してください
  （[QUICKSTART](QUICKSTART.md) と `scripts/verify_evidence.py` を参照）。
- 証拠保全の設定は*希望*であって保証ではありません：`GET/PUT /api/custody/settings` は
  常に**実効的な**状態（希望**と**ライブラリの利用可能性）を報告するため、
  対応する追加機能がない場合に、ポスト量子署名や OpenTimestamps が有効であるかのように表示されることはありません。
  アンカリングのデフォルトはオフラインの `local` プロバイダーです。OpenTimestamps と
  パブリックチェーンへのアンカリングにはプライバシーに関する警告が付きます
  （[CHAIN_OF_CUSTODY](USER_MANUAL.md) を参照）。


---

## 国際化（i18n）— アプリを多言語にする

> 目標：**UI 全体**（そして、いずれは**ドキュメント**も）を約 12 の言語で
> 利用できるようにし、「ほぼすべての人類」へのオープンなアクセスを広げること。プロジェクトの流儀で
> 行います：**オフライン、CDN なし、実行時の翻訳 API なし、テレメトリーなし**、そして
> 翻訳の品質について**正直に**（機械による推測を、正式なものであるかのように出荷しません）。

---

### 12 の言語（フェーズ 1 のセット）

到達範囲（母語話者 + 第二言語話者）を基準に選び、グローバルサウスを意図的に含めています
（`ROADMAP.md` の反バイアスの目標に従って）：

| コード | 言語 | 自称 | 文字体系／方向 | 状態 |
|---|---|---|---|---|
| `en` | 英語 | English | LTR | **原文**（完全） |
| `fr` | フランス語 | Français | LTR | **完全**（保証済み） |
| `es` | スペイン語 | Español | LTR | **完全**（保証済み） |
| `de` | ドイツ語 | Deutsch | LTR | **完全**（保証済み） |
| `zh` | 中国語（標準中国語） | 中文 | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `hi` | ヒンディー語 | हिन्दी | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `ar` | アラビア語 | العربية | **RTL** | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `bn` | ベンガル語 | বাংলা | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `ru` | ロシア語 | Русский | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `pt` | ポルトガル語 | Português | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `id` | インドネシア語 | Bahasa Indonesia | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |
| `ja` | 日本語 | 日本語 | LTR | 完全（`0.4` サイクルで翻訳。まだ保証されていない） |

到達範囲を広げるために追加しやすい次の候補：**スワヒリ語（`sw`）**、**ウルドゥー語（`ur`、RTL）**、イタリア語
（`it`）、トルコ語（`tr`）、ベトナム語（`vi`）。

**正直さの姿勢。** *スタブ*は言語を**今すぐ選択可能**にし、未翻訳の文字列については英語に
フォールバックします — 部分的なロケールが UI を壊すことは決してありません（これは、将来のあらゆるロケール
— `it`、`tr`、`vi` など — が出発点とする仕組みです）。各ロケールには `complete | draft | stub` の印を付けます。メンテナーは
自らが保証できるものだけを出荷し、それ以外はすべて**コミュニティの貢献**によって埋められます
（これこそが、オープンソースがアクセスを広げる方法です）。

---

### アーキテクチャ（オフライン、依存関係なし）

`src/static/i18n.js` + `src/static/locales/<code>.json`。ビルド手順もネットワークも不要です。

- **英語がキーです。** ロケールファイルは**英語の UI 文字列 → その翻訳**を対応付けます
  （例：`"Search the corpus": "Rechercher dans le corpus"`）。これにより、すべての要素にタグを付けることなく
  既存の UI に後から組み込むことができ、英語を正規の原文として保つことができます。
- **`OOI18N.setLang(code)`** は `locales/<code>.json` を読み込み、選択を
  `localStorage`（`oo.lang`）に保存し、`document.documentElement.lang` と `dir`（`ar`/`ur` では RTL）を
  設定してから、**`apply()`** で DOM を走査します — 前後の空白を除いたテキストがキーと一致するテキストノードと、
  `placeholder`/`title`/`aria-label` 属性を翻訳します。未知の文字列はそのまま残されます
  （英語へのフォールバック）— 何も壊れることはありません。
- **動的なコンテンツ**（データ：記事のタイトル、情報源の名前、件数）は**決して**
  翻訳されません — 翻訳されるのは UI の枠組みだけです。JS で描画される枠組み（コマンドパレット、ドロワー）は、
  描画後に `OOI18N.apply()` を呼び出します。
- 各ロケールには `_meta`（`name`、`native`、`dir`、`status`）があります。

#### 組み込み方（フェーズ 2 — 出荷済み。Desk はその後廃止）

`index.html`（および、2026-06-10 に廃止される前は `desk.html`）に 2 行を加え、
それから言語ピッカーを置きます：

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

**言語**セレクターは設定にあり、`OOI18N.setLang(code)` を呼び出します。
選択は他のローカル UI の設定と一緒に保存されます。

---

### 多言語のドキュメント

ドキュメントは長く、短い UI 文字列よりも翻訳の品質が重要になるため、次のようにします：

- 構成：`docs/i18n/<code>/<DOC>.md` は `docs/` と同じ構造にします。
- **英語のドキュメントが引き続き正規のもの**です。翻訳はコミュニティ／メンテナーの作業であり、
  それぞれに翻訳日と、追跡している英語版のコミットを記します。
- ドキュメントを自動で機械翻訳し、それを正式なものとして提示することは**しません** — それは
  プロジェクトの正直さの原則に反します。言語ごとに、最も価値が高く最も短いドキュメント
  （QUICKSTART、「最初に目にするもの」のツアー、ETHICS）から始めます。

---

### 貢献のワークフロー（設計としてのオープンアクセス）

1. `locales/en.json` を `locales/<code>.json` にコピーし、値を翻訳して、`_meta.status` を設定します。
2. RTL の言語では `_meta.dir: "rtl"` を設定します。
3. （計画中の）キーのカバレッジ確認を実行します：`en.json` と比べて欠けているキー／余分なキーを報告します。
4. 提出します。未翻訳のキーは、埋められるまで単に英語にフォールバックします。

---

### 状況

**フェーズ 1（完了）：** i18n エンジン（`i18n.js`）、12 言語すべてのロケールの
雛形、そして **en/fr/es/de** の完全な参照翻訳。

**フェーズ 1b（完了、`0.4.0`）：** 残りのインターフェース文字列にキーを付け、
**12 言語すべて**に翻訳しました（`CHANGES.md` の 0.4.0 を参照）。そのため、
`src/static/locales/*.json` のすべてのロケールが完全なキーセットを備えています（確認済み：
12 ファイル、それぞれ 6,991 キー、欠落なし）。正直さの姿勢は変わりません：名前は
固有名詞であり翻訳されず、部分的なロケールは引き続き UI を壊すことなく
英語にフォールバックします。

**フェーズ 2（完了 — 実際のブラウザでの確認待ち）：** `i18n.js` は
`index.html` に含まれています（2026-06-10 に Desk が廃止されるまでは `desk.html` にも含まれていました）。
**言語**ピッカー（`#oo-lang-select`）が設定にあり、自動的に接続されます。動的に描画される枠組みは、
デバウンスされた `MutationObserver` によって自動的に翻訳されます（`apply()` の呼び出しを散在させる必要はありません）。
英語に切り替えると元の文字列が復元されます。RTL は `<html dir>` で対応します。構造／構文は検証済みですが、
動作はやはりブラウザで目視確認する必要があります。

**フェーズ 3（次）：** `en.json` を文字列カタログの*全体*に拡張し（現在は
利用頻度の高い枠組みをカバーしています）、スタブのロケールを完成させ（コミュニティ）、
`ar`/`ur` の RTL レイアウトを磨き上げます。


## エクスポートの契約（バージョン管理）

機械可読なエクスポートは、安定した自己記述的な契約（スキーマ `oo-export-1`、
0.0.8 パート 2 / RM-15）を備えているため、下流のパイプラインが推測を強いられることはありません：

- **JSON**（`/api/articles/export?format=json`、`/api/links/export.json`）：エンベロープ —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`。
  `query` オブジェクトは、生成に使われた選択条件そのままです。来歴はデータとともに伝わります。
- **CSV**（`/api/articles/export?format=csv`）：コメント行はありません（素朴な読み取り処理を壊してしまうため）。
  同じエンベロープは HTTP ヘッダー（`X-OO-Export-Schema`、`X-OO-App-Version`、
  `X-OO-Generated-At`、`X-OO-Query`）として伝わります。列は順序を保ち、新しい列は常に末尾にのみ
  追加されます：`Fetched From Host`（キュー項目 61）は、リダイレクトを経た後にページを取得したホストで、
  記録されていない場合は空です。JSON エクスポートではこれを `fetched_host` として持ちます。
- **引用グラフ**（`/api/links/export.graphml`、`.json`）：誰が誰を引用しているかのグラフ
  （保存された記事 → 外部の登録可能ドメイン）。**件数のみ — 推定された信用度もスコアもありません**。
  注意書きはファイル自体に埋め込まれています。GraphML は
  Gephi/yEd/NetworkX で開けます。

スキーマの変更では `oo-export-N` を上げます。既存のフィールドが黙って別の用途に転用されることは決してありません。
既存のフィールドの横に追加されたフィールド（末尾の CSV 列、新しい JSON キー）は、既存のすべての読み取り処理の
フィールドを元の位置のままにするため、スキーマを上げることはありません。
