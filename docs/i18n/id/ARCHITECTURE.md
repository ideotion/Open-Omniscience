<!-- id: Translation of docs/ARCHITECTURE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 28 of 28 headings. Corrections are welcome as a pull request. -->

# Arsitektur & referensi teknis

Pendamping teknis untuk Panduan Pengguna: basis data/konfigurasi, peta API HTTP, dan internasionalisasi.

## Daftar isi
- [Konfigurasi Basis Data untuk Open Omniscience](#konfigurasi-basis-data-untuk-open-omniscience)
- [Referensi API](#referensi-api)
- [Internasionalisasi (i18n) — menjadikan aplikasi multibahasa](#internasionalisasi-i18n--menjadikan-aplikasi-multibahasa)


---

## Konfigurasi Basis Data untuk Open Omniscience

> **Status (diverifikasi dalam audit v0.0.7, `docs/archive/audits/00_BASELINE.md`):** lapisan basis data
> **berfungsi dan teruji** — server menyala, membuat/menggunakan penyimpanan SQLite, menerapkan migrasi
> Alembic, dan seluruh rangkaian uji (800+) lolos terhadapnya. Spanduk lama "konsep awal —
> tidak berfungsi" yang dulu ada di sini menggambarkan keadaan sebelum pembangunan ulang dan sudah lama
> usang.

### 🗃️ SQLite — penyimpanan yang didukung

SQLite adalah **backend bawaan dan satu-satunya yang didukung serta teruji**. Ia cocok dengan rancangan produk
yang lokal-dulu dan untuk satu operator.

- **Tanpa konfigurasi:** basis data dibuat secara otomatis saat pertama kali dijalankan, di
  `<data dir>/open_omniscience.db`. Direktori data adalah `OO_DATA_DIR` jika diatur, jika tidak `data/`
  repositori dalam checkout sumber, jika tidak `$XDG_DATA_HOME/open-omniscience` (lihat `src/paths.py`).
- **Disetel otomatis:** engine menerapkan mode jurnal `WAL`, `foreign_keys=ON`,
  `busy_timeout=30000` dan `synchronous=NORMAL` pada setiap koneksi
  (`src/database/session.py`) — Anda tidak perlu mengaturnya sendiri.
- **Pencarian teks penuh** menggunakan SQLite **FTS5** (`article_fts`, external-content, disinkronkan oleh
  trigger — `src/database/fts.py`).
- **Ganti lokasinya** dengan variabel lingkungan `DATABASE_URL` (**jangan** menyunting
  berkas sumber): `DATABASE_URL=sqlite:////absolute/path/to/your.db`
- **Pemeliharaan:** sesekali menjalankan `sqlite3 <db> "VACUUM;"` akan memulihkan ruang (audit v0.0.7
  juga menghapus indeks redundan yang mencapai ~63% ukuran berkas pada korpus besar; jalankan `make
  migrate` sekali setelah pembaruan untuk menghapusnya dari basis data yang sudah ada).

### 🐘 PostgreSQL — kerangka eksperimental, TIDAK didukung

Kejujuran di atas aspirasi (temuan audit ARCH-06): lapisan engine *mengenali*
`DATABASE_URL` PostgreSQL (connection pooling melalui `DB_POOL_SIZE`/`DB_MAX_OVERFLOW`), **tetapi**

- **pencarian teks penuh tidak ada di PostgreSQL** — penyiapan FTS5 sengaja tidak melakukan apa-apa pada
  engine non-SQLite, sehingga tab Pencarian akan mati;
- rangkaian uji tidak pernah dijalankan terhadap PostgreSQL, dan tidak ada CI yang mencakupnya;
- tidak ada deployment yang dipublikasikan yang pernah menggunakannya.

Perlakukan PostgreSQL sebagai **kerangka yang belum teruji untuk kemungkinan masa depan**, bukan pilihan yang dapat Anda
ambil hari ini. Jika skala multi-penulis suatu saat menjadi kebutuhan nyata, butir peta jalannya adalah
jalur pencarian `tsvector` ditambah matriks CI PostgreSQL — sampai itu terwujud, halaman ini tidak akan
berpura-pura.

### 🔄 Migrasi

Alembic dikonfigurasi di **akar repositori** (`alembic.ini`, `migrations/`). Alembic
terpasang bersama aplikasi (ia adalah dependensi inti — tidak perlu instalasi terpisah).

- **Basis data baru** dibuat lengkap (`create_all` + FTS) dan diberi cap head migrasi
  terkini secara otomatis saat startup.
- **Memperbarui basis data yang sudah ada:**
  ```bash
  make migrate          # = alembic upgrade head, from the repo root
  ```
- **Membuat migrasi** (kontributor): sunting `src/database/models.py`, lalu
  ```bash
  alembic revision --autogenerate -m "your message"
  alembic upgrade head
  ```
  dan periksa berkas yang dihasilkan — autogenerate melewatkan tabel virtual FTS (tabel-tabel itu berada di
  `src/database/fts.py`, diterapkan saat startup).
- **Mengembalikan (rollback):** `alembic downgrade -1`.

---

### 📊 Skema Basis Data

#### Tabel:

##### `sources`
| Kolom | Tipe | Deskripsi |
|--------|------|-------------|
| `id` | INTEGER | Kunci primer |
| `name` | STRING(100) | Nama sumber (misalnya "BBC News") |
| `domain` | STRING(255) | Domain sumber (misalnya "bbc.com") |
| `rss_url` | STRING(500) | URL umpan RSS (jika tersedia) |
| `rate_limit_ms` | INTEGER | Jeda antarpermintaan dalam milidetik |
| `enabled` | BOOLEAN | Apakah sumber aktif untuk scraping |
| `priority` | INTEGER | Tingkat prioritas (1 = tinggi, 3 = rendah) |
| `tags` | STRING(500) | Daftar tag yang dipisahkan koma |

##### `articles`
| Kolom | Tipe | Deskripsi |
|--------|------|-------------|
| `id` | INTEGER | Kunci primer |
| `url` | STRING(1000) | URL asli artikel |
| `canonical_url` | STRING(1000) | URL yang dikanonikalisasi (untuk deteksi duplikat) |
| `source_id` | INTEGER | Kunci asing ke `sources` |
| `title` | STRING(500) | Judul artikel |
| `content` | TEXT | Konten teks lengkap artikel |
| `published_at` | DATETIME | Tanggal/waktu publikasi (format ISO) |
| `language` | STRING(10) | Kode bahasa (misalnya "en", "fr") |
| `hash` | STRING(64) | Hash SHA-256 dari konten (untuk deteksi duplikat) |
| `created_at` | DATETIME | Stempel waktu saat artikel diserap |

> Kolom-kolom di atas adalah field inti; skema aktif (`src/database/models.py`)
> dan migrasi Alembic di bawah `migrations/versions/` adalah sumber kebenarannya.
> `articles` juga memuat field provenans/analisis (author, word_count, region,
> country, sentiment) dan sebuah kolom konten terkompresi.

##### Tabel lainnya (lihat model / migrasi untuk kolom lengkap)

| Tabel | Kegunaan |
|-------|---------|
| `source_groups`, `source_metadata`, `source_group_association` | Pengelompokan sumber + metadata geo/robots |
| `commodity_prices` | Titik harga yang teramati (simbol, tanggal, harga, mata uang, **satuan**, pasar, sumber) — grafik + korelasi harga↔berita |
| `market_extraction_rules` | Aturan per sumber (selector CSS / atribut / regex) yang menemukan harga satu instrumen pada satu halaman; kategori keuangan/saham/komoditas |
| `keywords` | Istilah kata kunci/entitas yang berbeda (dinormalisasi, bahasa, `is_entity`/`entity_type`, provenans **`extractor`**) |
| `keyword_mentions` | Satu per (artikel, kata kunci): jumlah + offset karakter pertama + `observed_on`/`country`/`city` yang didenormalisasi — menggerakkan tren, asosiasi, konteks, dan peta di Wawasan |
| `wiki_pages` | Halaman Wikipedia yang dilacak dalam satu edisi bahasa; menyimpan **satu** baseline teks penuh terkompresi |
| `wiki_revisions` | Satu suntingan yang dilacak: **diff + delta byte bertanda** + flag/tag (bukan salinan ulang), skor ORES opsional, flag suntingan besar yang jujur + alasannya |
| `article_analyses` | Hasil LLM turunan (ringkasan/terjemahan) dengan provenans model + prompt |
| `keyword_categories`, `external_sources`, `article_links`, … | Kategorisasi kata kunci + pelacakan tautan/hubungan sumber |

#### Indeks:
- `idx_article_hash`: Indeks unik pada `hash` (untuk deteksi duplikat).
- `idx_article_canonical_url`: Indeks pada `canonical_url` (untuk pencarian URL).
- `idx_article_source_id`: Indeks pada `source_id` (untuk kueri berbasis sumber).
- `idx_article_content`: Indeks pada `content` (untuk pencarian teks penuh).

---

### 🔍 Pencarian Teks Penuh

Pencarian teks penuh **sudah dibangun dan terhubung** — tidak ada yang perlu diaktifkan. Penyimpanan
memuat tabel external-content FTS5 (`article_fts`) yang disinkronkan oleh trigger; lihat
`src/database/fts.py` untuk skemanya dan `search_ids` di `src/api/main.py` untuk jalur
kuerinya (resolusi hanya-id dalam urutan akhir, baris lengkap dimuat hanya untuk halaman tersebut).

Bagian ini dulu menawarkan resep "pertimbangkan membuat tabel virtual" untuk SQLite dan resep
`to_tsvector` untuk PostgreSQL. Keduanya keliru: resep SQLite menjelaskan cara membangun secara
manual tabel yang sudah disertakan dan dipelihara oleh aplikasi (dengan nama yang *berbeda*, sehingga mengikutinya
akan menghasilkan indeks kedua yang tidak terpelihara), dan PostgreSQL sama sekali tidak memiliki jalur pencarian di sini,
yang dinyatakan bagian penyimpanan di atas sebagai alasan pertama mengapa ia bukan backend yang didukung.

---

### 📉 Pemantauan dan Pemeliharaan

- **Periksa ukuran basis data**:
  ```bash
  ls -lh data/open_omniscience.db
  ```
- **Periksa ukuran tabel**:
  ```bash
  sqlite3 data/open_omniscience.db "SELECT name, COUNT(*) FROM sqlite_master WHERE type='table';"
  ```
  Pada penyimpanan **terenkripsi**, CLI `sqlite3` sama sekali tidak dapat membuka berkas (memang itulah
  tujuannya) — gunakan permukaan Pengaturan → Diagnostik di dalam aplikasi, yang membaca penyimpanan
  melalui pabrik koneksi terjaga yang sama dengan yang digunakan aplikasi itu sendiri.

---

### 🚨 Pemecahan Masalah

#### Masalah Umum:

##### SQLite:
- **"Database is locked"**:
  - SQLite hanya mengizinkan satu penulis pada satu waktu. Mode WAL diaktifkan secara bawaan
    (`src/database/session.py`) dan gerbang penulis tunggal di seluruh proses
    (`src/database/writer.py`) menyerialkan penulisan di dalam aplikasi, sehingga penyerapan +
    impor yang bersamaan tidak lagi bertabrakan. Kunci yang terus-menerus berarti ada *proses* lain yang sedang menulis.

- **"Too many open files"**:
  - SQLite membuka koneksi baru untuk setiap thread. Batasi jumlah thread atau gunakan connection pooling.

- **"Relation does not exist" / "no such table"**:
  - Jalankan migrasi: `alembic upgrade head`.

---

### 📌 Praktik Terbaik

1. **Cadangkan melalui aplikasi, bukan dengan `cp`**:
   - Gunakan Pengaturan → Cadangan (atau `GET /api/database/backup` untuk snapshot yang konsisten).
     Menyalin `open_omniscience.db` secara manual **bukanlah** cadangan: penyimpanan berjalan dalam mode
     WAL, sehingga berkas aktif tidak memuat apa pun yang masih berada di `-wal`, dan pada penyimpanan bawaan yang
     **terenkripsi** berkas salinan tidak berguna tanpa frasa sandi dan tidak membawa
     komitmen integritas apa pun. Jalur milik aplikasi sendiri melakukan checkpoint, streaming, dan penandatanganan.

2. **Uji Migrasi**:
   - Selalu uji migrasi pada cadangan basis data Anda sebelum menerapkannya ke produksi.

3. **Pantau Kinerja**:
   - Pengaturan → Diagnostik memuat log kueri lambat, log latensi permintaan, dan
     laporan gerbang penulisan; CLI `sqlite3` berfungsi pada penyimpanan teks polos.

4. **Optimalkan Kueri**:
   - `EXPLAIN QUERY PLAN` adalah alatnya. Perhatikan bahwa SQLite menulis `SCAN` untuk pemindaian tabel
     biasa **maupun** pemindaian hanya-indeks — `SCAN <table> USING [COVERING] INDEX …` adalah
     sehat; yang patut dicurigai adalah `SCAN <table>` polos tanpa `USING`
     (`src/monitoring/slowquery.py` mengklasifikasikan tepat berdasarkan hal itu).

5. **Batasi Retensi Data**:
   - Arsipkan atau hapus artikel lama secara berkala agar basis data tetap terkelola.
   - Contoh: Hapus artikel yang lebih tua dari 1 tahun:
     ```python
     from datetime import datetime, timedelta
     one_year_ago = datetime.now(timezone.utc) - timedelta(days=365)
     session.query(Article).filter(Article.published_at < one_year_ago).delete()
     session.commit()
     ```

---
*Hak Cipta © 2026 Ideotion. Dilisensikan di bawah GNU General Public License v3.0
atau yang lebih baru (GPL-3.0-or-later) — lihat [LICENSE](../LICENSE). Ini adalah perangkat lunak bebas;
Anda boleh mendistribusikan ulang dan memodifikasinya berdasarkan ketentuan tersebut.*


---

## Referensi API

Referensi API yang aktif dan selalu akurat dihasilkan oleh aplikasi itu sendiri:

- **Swagger UI / ReDoc:** nonaktif secara bawaan (keduanya memuat aset dari host pihak ketiga); jalankan aplikasi dengan `OO_API_DOCS=1` untuk http://127.0.0.1:8000/docs dan `/redoc`
- **OpenAPI JSON:** http://127.0.0.1:8000/openapi.json

Aplikasi hanya terikat ke loopback dan (untuk satu pengguna lokal) tidak memerlukan autentikasi.

### Kelompok endpoint

Ini adalah **peta kelompok-kelompok utama, bukan daftar yang lengkap** — `/openapi.json`
yang aktif (di atas) selalu otoritatif. Router-router dihubungkan di
`src/api/main.py` melalui `include_router(...)`; kelompok yang ditandai **[analysis]** memerlukan
ekstra `[analysis]` (aplikasi tetap menyala tanpanya, dengan endpoint tersebut dinonaktifkan).

| Prefiks | Fungsinya |
|--------|--------------|
| `GET /api/health` | Keaktifan + versi |
| `GET /api/articles`, `/api/articles/export` | Pencarian teks penuh boolean (FTS5) + ekspor CSV/JSON |
| `POST /api/ingest`, `/api/sources/{id}/ingest`, `/api/sources/{id}/ingest-email` | Penyerapan yang etis: satu URL, umpan RSS, kotak surat IMAP |
| `… /api/sources`, `/api/sources/...` | Pengelolaan sumber + grup + metadata |
| `POST /api/sources/seed-defaults` | Mengisi katalog sumber yang dikurasi (berita + pasar + katalog dunia yang dihasilkan) |
| `GET /api/database/stats`, `/coverage`, `/countries` | Jumlah baris korpus + ukuran di disk; cakupan negara; jumlah sumber per negara + kata kunci topik |
| `GET /api/database/backup` | Unduhan snapshot SQLite yang konsisten (hanya penyimpanan SQLite teks polos; ditolak untuk permintaan dari situs lain atau Host yang tidak dilayani oleh penjaga DNS-rebinding, dan, pada nama selain loopback, untuk permintaan yang tidak menyebutkan halaman asalnya kecuali ia mengirim `X-OO-Download: 1`, satu per satu per proses, ditulis ke folder privat `.oo-backup-*` di samping basis data dan dihapus saat unduhan berakhir atau proses berhenti (proses yang dimatikan paksa meninggalkannya untuk penyapuan pada startup berikutnya, yang langsung menghapus folder milik pemilik yang sudah mati), 507 bila volume data tidak dapat menampungnya) |
| `POST /api/database/v2/restore/preview`, `/v2/restore/commit`, `/api/backup/v2/*` | Pemulihan **hanya-tambahan** melalui artefak `oo-backup-2` yang ditandatangani: pratinjau rencana penggabungan, lalu commit. Pemulihan **tidak pernah menimpa korpus Anda** — ia menggabungkan tanpa duplikat, mempertahankan nilai lokal bila terjadi konflik (jalur penggantian destruktif dihapus pada 2026-06-13) |
| `GET/PUT /api/settings` | Preferensi GUI (tema, batas hasil bawaan) |
| `… /api/scheduler/...` | Pengumpulan latar belakang: status, mulai, berhenti, jalankan sekarang, konfigurasi. Sejak siklus `0.4`, pengumpulan berjalan sebagai **jalur-jalur berdampingan** (`rss` / `crawl` / `markets` / `wiki` / `law`), bukan satu mode penjadwal — penyimpanan per jalur di bawah `… /api/storage/...`, dan tab **Sumber hidup** membaca `… /api/living/...` (apa yang berubah di Wikipedia, hukum, dan peta) |
| `… /api/markets/rules`, `/rules/{id}/run`, `/overview` | Aturan ekstraksi harga per sumber + jalankan "uji" + ikhtisar Pasar |
| `GET /api/markets/feeds`, `POST /feeds/{key}/import`, `/feeds/import-url` | Katalog umpan harga CSV resmi + impor (FRED/World Bank/EIA) + impor dari URL kustom |
| `GET /api/catalog/export.csv`, `/template.csv`, `/columns`, `POST /api/catalog/import` | Ekspor / templat / kolom CSV daftar sumber + impor upsert berdasarkan domain |
| `… /api/insights/...` | Analitik kata kunci & entitas: status, indeks ulang, teratas, tren naik, tren, asosiasi (PMI), konteks, peta |
| `GET /api/timemap`, `/timemap/range` | Sinyal ruang-waktu pada satu peta+sumbu waktu (jangkar + korpus tergeokode + bahaya/tanggal yang disebut, atas pilihan); `?kinds`, jendela tahun pecahan `?start`/`?end`, `?hazards`, `?articles`, `?mentions`, `?days` |
| `… /api/article-dates/...` | Tanggal yang diekstrak dari teks artikel sebagai tag per artikel yang dapat dikonfirmasi manusia: daftar/ekstrak per artikel, konfirmasi/tolak, indeks batch, filter korpus berdasarkan tanggal |
| `GET/POST /api/llm/...` | LLM lokal (Ollama): kesehatan, model, generate, meringkas artikel |
| `… /api/commodities/...` | Harga komoditas (impor / CSV / daftar) + korelasi harga↔berita yang jujur |
| `POST /api/analysis/...` | Statistik dengan ketelitian ilmiah: uji-t, korelasi, ANOVA, Mann-Whitney, CI |
| `GET /api/monitoring/...` | Kesehatan uptime sumber yang nyata + anomali volume korpus |
| `POST /api/verify/image-metadata` | Ekstraksi EXIF/metadata gambar yang jujur |
| `POST /api/reports/evidence`, `/evidence/verify` | Bundel bukti yang ditandatangani dan menunjukkan perusakan |
| `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`, `POST /api/custody/export`, `POST /api/custody/verify` | Log rantai kustodi yang hanya-tambahan, berantai hash, dan ditandatangani + verifikasi luring |
| `GET/PUT /api/custody/settings` | Preferensi kustodi saat runtime (penandatanganan pasca-kuantum, mode penambatan, pencatatan otomatis) — melaporkan keadaan *efektif* yang memperhitungkan ketersediaan |
| `POST /api/custody/anchor`, `GET /api/custody/providers` | Menambatkan akar Merkle (lokal / OpenTimestamps) + ketersediaan penyedia |
| `POST /api/custody/reconcile` | Menulis entri INGEST yang tertunggak akibat kegagalan, masing-masing ditandai terlambat dalam metadata yang ditandatangani; `scan` menghitung celah yang lebih lama, `record_gaps` mengantrekannya (2026-09-24, CUST-1) |
| `… /api/keywords/...`, `/api/analysis/articles/similarity` | **[analysis]** Ekstraksi kata kunci + kemiripan artikel |
| `GET /api/search/omni` | Omnibar terfederasi berbasis indeks (FTS5 artikel + kata kunci + sumber + wiki/hukum) |
| `… /api/jobs/...` | Agregasi pekerjaan task manager (putaran pengumpulan, pengambilan yang sedang berjalan, antrean dump wiki + penataan ulang) |
| `… /api/system/...` | Tanda vital sistem + keadaan/persetujuan jaringan (kill switch mode pesawat, IP antarmuka lokal) |
| `… /api/safety/...` | Kontrol keselamatan: kill switch, gerbang penemuan, pemulihan dari artefak terenkripsi |
| `… /api/briefing/...` | Produsen ringkasan Beranda (kartu bertingkat bukti; metode+caveat+n) |
| `… /api/insights/...`, `/api/insights/who`, `/where` | Analitik kata kunci/entitas + agregasi Siapa/Di mana di seluruh korpus |
| `… /api/links/...` (shared, preview) | Analisis tautan keluar bersama / graf sitasi + dialog pratinjau tautan lokal |
| `… /api/events/...`, `/api/events/astronomy`, `/climate` | Peristiwa Agenda termasuk astronomi yang dihitung secara lokal (Meeus) + tabel El Niño |
| `POST /api/weather/context` | Irisan reanalisis Open-Meteo yang terbatas dan atas persetujuan, untuk penguatan |
| `… /api/law/...` | Umpan perubahan legislasi/sumber primer yang dilacak |
| `… /api/integrity/...` | Sinyal gema / koordinasi / garis keturunan |
| `… /api/annotations/...` | Anotasi artikel lokal yang dapat ditandatangani secara opsional |
| `… /api/wiki/...` | Edisi Wikipedia, halaman yang dipantau, unduh/baca dump, sinkronisasi korpus |
| `… /api/hazards/...`, `/api/timemap` | Lapisan bahaya + peta ruang-waktu |
| `GET /unlock`, `POST /api/unlock`, `/create-db`, `/doctor`, `/encrypt-db` | Enkripsi saat tersimpan: layar buka kunci saat boot terkunci, membuat penyimpanan terenkripsi/teks polos, atestasi header, alat enkripsi satu arah |

Router yang ditandai **[analysis]** (komoditas, statistik, kata kunci, framing)
memerlukan ekstra `[analysis]`; tanpanya aplikasi tetap menyala dengan tulang punggung
inti dan endpoint tersebut dinonaktifkan.

Catatan perilaku:
- Penyerapan mengambil data hanya melalui fetcher etis (robots.txt gagal-tertutup, laju
  dibatasi); endpoint LLM mengembalikan **503** jika Ollama tidak tersedia (tidak pernah jawaban palsu).
- Verifikasi bukti: berikan kunci publik penanda tangan untuk membuktikan provenans, bukan hanya
  integritas (lihat [QUICKSTART](QUICKSTART.md) dan `scripts/verify_evidence.py`).
- Pengaturan kustodi adalah *preferensi*, bukan jaminan: `GET/PUT /api/custody/settings`
  selalu melaporkan keadaan **efektif** (preferensi **dan** ketersediaan pustaka), sehingga
  pasca-kuantum / OpenTimestamps tidak pernah tampak aktif ketika ekstra pendukungnya
  tidak ada. Penambatan secara bawaan menggunakan penyedia luring `local`; OpenTimestamps dan
  penambatan ke rantai publik membawa peringatan privasi (lihat
  [CHAIN_OF_CUSTODY](USER_MANUAL.md)).


---

## Internasionalisasi (i18n) — menjadikan aplikasi multibahasa

> Tujuan: **seluruh UI** (dan, seiring waktu, **dokumentasi**) tersedia dalam ~selusin
> bahasa, untuk memperluas akses terbuka menuju "hampir semua manusia." Dilakukan dengan
> cara proyek ini: **luring, tanpa CDN, tanpa API terjemahan saat runtime, tanpa telemetri**, dan
> **jujur** tentang kualitas terjemahan (kami tidak mengirimkan tebakan mesin seolah-olah
> otoritatif).

---

### Selusin bahasa (set Fase 1)

Dipilih berdasarkan jangkauan (penutur asli + penutur bahasa kedua) dan untuk secara sengaja menyertakan
Belahan Bumi Selatan (sesuai tujuan anti-bias `ROADMAP.md`):

| Kode | Bahasa | Nama asli | Aksara / arah | Status |
|---|---|---|---|---|
| `en` | Inggris | English | LTR | **sumber** (lengkap) |
| `fr` | Prancis | Français | LTR | **lengkap** (dijamin) |
| `es` | Spanyol | Español | LTR | **lengkap** (dijamin) |
| `de` | Jerman | Deutsch | LTR | **lengkap** (dijamin) |
| `zh` | Tionghoa (Mandarin) | 中文 | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `hi` | Hindi | हिन्दी | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `ar` | Arab | العربية | **RTL** | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `bn` | Bengali | বাংলা | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `ru` | Rusia | Русский | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `pt` | Portugis | Português | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `id` | Indonesia | Bahasa Indonesia | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |
| `ja` | Jepang | 日本語 | LTR | lengkap (diterjemahkan, siklus `0.4`; belum dijamin) |

Tambahan berikutnya yang mudah untuk jangkauan: **Swahili (`sw`)**, **Urdu (`ur`, RTL)**, Italia
(`it`), Turki (`tr`), Vietnam (`vi`).

**Sikap kejujuran.** Sebuah *stub* membuat suatu bahasa **dapat dipilih sekarang** dan kembali ke
bahasa Inggris untuk setiap string yang belum diterjemahkan — locale yang parsial tidak pernah merusak UI (inilah
mekanisme yang menjadi titik awal setiap locale masa depan — `it`, `tr`, `vi`, …). Kami menandai setiap locale `complete | draft | stub`. Pemelihara
hanya mengirimkan apa yang dapat ia jamin; selebihnya diisi oleh **kontribusi
komunitas** (beginilah tepatnya sumber terbuka memperluas akses).

---

### Arsitektur (luring, tanpa dependensi)

`src/static/i18n.js` + `src/static/locales/<code>.json`. Tanpa langkah build, tanpa jaringan.

- **Bahasa Inggris adalah kuncinya.** Berkas locale memetakan **string UI bahasa Inggris → terjemahannya**
  (misalnya `"Search the corpus": "Rechercher dans le corpus"`). Ini memungkinkan kami menyesuaikan
  UI yang ada tanpa menandai setiap elemen, dan mempertahankan bahasa Inggris sebagai sumber
  kanonis.
- **`OOI18N.setLang(code)`** memuat `locales/<code>.json`, menyimpan pilihan di
  `localStorage` (`oo.lang`), mengatur `document.documentElement.lang` dan `dir` (RTL untuk
  `ar`/`ur`), lalu **`apply()`** menelusuri DOM — menerjemahkan node teks yang teksnya setelah
  dipangkas cocok dengan sebuah kunci, ditambah atribut `placeholder`/`title`/`aria-label`. String yang tidak dikenal
  dibiarkan apa adanya (kembali ke bahasa Inggris) — tidak ada yang pernah rusak.
- **Konten dinamis** (data: judul artikel, nama sumber, jumlah) **tidak pernah**
  diterjemahkan — hanya kerangka antarmuka (chrome). Chrome yang dirender JS (palet perintah, laci)
  memanggil `OOI18N.apply()` setelah dirender.
- Setiap locale memuat `_meta` (`name`, `native`, `dir`, `status`).

#### Mengintegrasikannya (Fase 2 — sudah dikirim; Desk sejak itu telah dipensiunkan)

Dua baris di `index.html` (dan, sebelum dipensiunkan pada 2026-06-10, `desk.html`),
lalu pemilih bahasa:

```html
<script src="/static/i18n.js"></script>
<!-- after first render and on each view change: --> OOI18N.apply();
```

Pemilih **Bahasa** berada di Pengaturan dan memanggil `OOI18N.setLang(code)`,
disimpan bersama preferensi UI lokal lainnya.

---

### Dokumentasi dalam banyak bahasa

Dokumen itu panjang dan kualitas terjemahan lebih penting dibanding untuk string UI yang pendek, sehingga:

- Struktur: `docs/i18n/<code>/<DOC>.md` mencerminkan `docs/`.
- **Dokumen bahasa Inggris tetap kanonis**; terjemahan adalah pekerjaan komunitas/pemelihara,
  masing-masing ditandai dengan tanggal terjemahannya dan commit bahasa Inggris yang diikutinya.
- Kami **tidak** menerjemahkan dokumen secara otomatis dengan mesin lalu menyajikannya sebagai otoritatif — hal itu
  akan melanggar prinsip kejujuran proyek. Mulailah dari dokumen dengan nilai tertinggi dan paling pendek
  (QUICKSTART, tur "What you'll see first", ETHICS) untuk setiap bahasa.

---

### Alur kerja kontribusi (akses terbuka sejak rancangan)

1. Salin `locales/en.json` → `locales/<code>.json`, terjemahkan nilainya, atur `_meta.status`.
2. Untuk bahasa RTL, atur `_meta.dir: "rtl"`.
3. Jalankan pemeriksaan cakupan kunci (yang direncanakan): laporkan kunci yang hilang/berlebih dibandingkan `en.json`.
4. Kirimkan. Kunci yang belum diterjemahkan cukup kembali ke bahasa Inggris sampai diisi.

---

### Status

**Fase 1 (selesai):** engine i18n (`i18n.js`), kerangka locale untuk semua 12
bahasa, dan terjemahan rujukan lengkap untuk **en/fr/es/de**.

**Fase 1b (selesai, `0.4.0`):** string antarmuka yang tersisa diberi kunci dan
diterjemahkan ke **kedua belas** bahasa (lihat `CHANGES.md` 0.4.0), sehingga setiap
locale di `src/static/locales/*.json` kini memuat set kunci lengkap (terverifikasi:
12 berkas, masing-masing 6.991 kunci, tidak ada yang hilang). Kejujuran tidak berubah: nama adalah
nama diri dan tidak diterjemahkan, dan locale yang parsial tetap kembali ke
bahasa Inggris alih-alih rusak.

**Fase 2 (selesai — menunggu pengujian nyata di peramban):** `i18n.js` disertakan di
`index.html` (dan berada di `desk.html` sampai Desk dipensiunkan pada 2026-06-10); pemilih
**Bahasa** (`#oo-lang-select`) berada di Pengaturan dan terhubung otomatis; chrome yang dirender secara dinamis diterjemahkan otomatis oleh
`MutationObserver` dengan debounce (tanpa panggilan `apply()` yang tersebar); beralih ke bahasa Inggris
memulihkan teks aslinya; RTL melalui `<html dir>`. Struktur/sintaksis sudah divalidasi, tetapi
perilakunya tetap harus diperiksa dengan mata di peramban.

**Fase 3 (berikutnya):** perluas `en.json` ke katalog string *lengkap* (saat ini
mencakup chrome dengan lalu lintas tinggi), lengkapi locale stub (komunitas), dan rapikan
tata letak RTL untuk `ar`/`ur`.


## Kontrak ekspor (berversi)

Ekspor yang dapat dibaca mesin membawa kontrak yang stabil dan menjelaskan dirinya sendiri (skema `oo-export-1`,
0.0.8 bagian 2 / RM-15) sehingga pipeline hilir tidak pernah menebak:

- **JSON** (`/api/articles/export?format=json`, `/api/links/export.json`): sebuah amplop —
  `{export_schema, kind, app_version, generated_at, query, count, articles|data}`. Objek
  `query` adalah seleksi pembangkit apa adanya; provenans ikut bersama data.
- **CSV** (`/api/articles/export?format=csv`): tanpa baris komentar (itu akan merusak pembaca yang naif);
  amplop yang sama dibawa sebagai header HTTP (`X-OO-Export-Schema`, `X-OO-App-Version`,
  `X-OO-Generated-At`, `X-OO-Query`). Kolom-kolom mempertahankan urutannya, dan kolom baru hanya
  pernah ditambahkan di akhir: `Fetched From Host` (butir antrean 61), host tempat halaman diambil setelah
  pengalihannya, kosong bila tidak tercatat; ekspor JSON membawanya sebagai `fetched_host`.
- **Graf sitasi** (`/api/links/export.graphml`, `.json`): graf siapa-mengutip-siapa
  (artikel tersimpan → domain eksternal yang dapat didaftarkan). **Hanya jumlah — tanpa kredibilitas
  yang disimpulkan, tanpa skor**; catatan peringatannya tertanam dalam berkas itu sendiri. GraphML dapat dibuka di
  Gephi/yEd/NetworkX.

Perubahan skema menaikkan `oo-export-N`; field yang sudah ada tidak pernah dialihfungsikan secara diam-diam. Field yang
ditambahkan di sampingnya (kolom CSV di akhir, kunci JSON baru) membiarkan field setiap pembaca yang sudah ada
tetap di tempatnya, sehingga tidak menaikkan skema.
