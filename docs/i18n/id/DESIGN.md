<!-- id: Translation of docs/DESIGN.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 68 of 68 headings. Corrections are welcome as a pull request. -->

# Sintesis desain & produk

Apa aplikasi ini dan apa yang bukan, di mana setiap 'pilar' asli kini berada, alasan desain GUI, dan strategi analisis konten. Satu-satunya rujukan desain.

## Daftar isi
- [Open-Omniscience — Sintesis Produk (Apa yang Seharusnya Dilakukan Aplikasi)](#open-omniscience--sintesis-produk-apa-yang-seharusnya-dilakukan-aplikasi)
- [Peta Maksud Pilar — di mana tujuan setiap pilar kini berada](#peta-maksud-pilar--di-mana-tujuan-setiap-pilar-kini-berada)
- [Desain Ulang GUI — "0.05"](#desain-ulang-gui--005)
- [Dua antarmuka, satu argumen — "Console" vs "Desk"](#dua-antarmuka-satu-argumen--console-vs-desk)
- [Strategi analisis konten — tautan, keseragaman, dan sumber asli](#strategi-analisis-konten--tautan-keseragaman-dan-sumber-asli)


---

## Open-Omniscience — Sintesis Produk (Apa yang Seharusnya Dilakukan Aplikasi)

> **Status:** Draf untuk ditinjau. Dokumen ini menghimpun desain yang *dimaksudkan* dari seluruh
> dokumentasi repositori menjadi satu spesifikasi yang koheren dan bebas duplikasi. Dokumen ini dengan sengaja menghapus
> pergeseran versi, gembar-gembor pemasaran, dan klaim QA yang tidak dapat diverifikasi. Dokumen ini menggambarkan **produk sasaran**, bukan
> kode saat ini (yang sebagian besar tidak berfungsi).
>
> Penanda yang digunakan:
> - `⚠️ DECIDE:` titik di mana dokumen sumber ambigu atau saling bertentangan — keputusan ada di tangan Anda.
> - `(P0/P1/P2)` prioritas yang *disarankan* untuk kapabilitas tersebut (P0 = inti MVP, P1 = penting, P2 = nanti).

---

### 0. Konteks penerapan (TERSELESAIKAN — menentukan semua hal di bawah)

Build ini menyasar **satu lingkungan spesifik dan satu pengguna**. Jawaban-jawaban berikut kini sudah tetap dan menyelesaikan
beberapa titik `⚠️ DECIDE` sebelumnya.

- **Host:** Qubes OS, berjalan di dalam **Debian AppVM** (berbasis template).
- **Python:** **3.13 sebagai interpreter bawaan.**
- **Pengguna:** **satu pengguna utama (pemilik proyek)** — tanpa akun multi-tenant, tanpa RBAC.
- **Permukaan:** **UI web + REST API yang hanya terikat ke `127.0.0.1`** (loopback). Tanpa listener eksternal.
- **Postur jaringan:** local-first; lalu lintas keluar hanya saat scraping/penarikan LLM; **tanpa lalu lintas masuk** apa pun.

#### 0.1 Apa yang diubah Qubes pada desain

Qubes bukan "sekadar Debian." Model keamanan dan siklus hidup AppVM-nya memberlakukan batasan keras yang
**wajib** dihormati oleh installer dan runtime:

1. **Persistensi sistem berkas bersifat selektif.** Di dalam AppVM, hanya **`/home`, `/usr/local`, dan `/rw`**
   yang bertahan setelah reboot; sistem berkas root **diatur ulang dari TemplateVM setiap kali boot**. Karena itu:
   - Aplikasi, virtualenv-nya, basis data, data hasil scraping, log, jejak audit, dan model LLM apa pun yang diunduh
     **wajib berada di bawah `/home/user/...`** (disarankan: `/home/user/open-omniscience`).
   - **Paket `apt`/sistem *tidak* bertahan** jika dipasang di AppVM. Dependensi sistem wajib
     dipasang **di TemplateVM** (lalu AppVM di-reboot), atau ditarik melalui `bind-dirs` Qubes.
     Installer wajib **memisahkan**: "dependensi sistem → TemplateVM" vs "venv Python + aplikasi → `/home` AppVM."
2. **Tidak ada asumsi root yang persisten.** Perubahan root di AppVM lenyap saat reboot. Perlakukan AppVM sebagai:
   `/home` yang persisten, root yang efemeral.
3. **Jaringan melalui NetVM.** AppVM menjangkau internet hanya lewat qube jaringan/firewall
   yang ditetapkan untuknya. Aplikasi wajib **menurun secara rapi saat offline** dan tidak pernah mengasumsikan konektivitas.
4. **Tanpa GPU.** GPU passthrough tidak praktis pada penyiapan Qubes yang umum → **inferensi LLM hanya memakai CPU**.
   Bawaannya **model kecil** (mis. `gemma2:2b`, `llama3.2:3b`, `qwen2.5:1.5b`); model besar bersifat opt-in.
5. **Air-gap / split-VM adalah opsi *masa depan* kelas satu (bukan v1).** Qubes membuat pola "scrape secara etis di
   qube berjaringan, analisis/simpan di qube brankas offline" menjadi alami melalui **qrexec/qubes-rpc**. v1
   berjalan di **satu AppVM**; arsitekturnya wajib menjaga batas *fetch* tetap bersih agar pemisahan kelak menjadi
   perubahan penerapan, bukan penulisan ulang. (Repo sudah memuat sisa-sisa materi `src/qubes/rpc/` dan
   `docs/QUBES_*` — untuk ditinjau/diganti, bukan dipercaya.)

#### 0.2 Implikasi Python 3.13 (menyelesaikan konflik versi dependensi)

- **Stack inti bersih untuk 3.13:** FastAPI, uvicorn, SQLAlchemy 2.x, pydantic 2.x, requests, httpx,
  beautifulsoup4, feedparser, numpy, pandas, scipy, scikit-learn, statsmodels — semuanya menyediakan wheel 3.13.
- **LLM lokal TIDAK memerlukan ML Python yang berat.** Ollama adalah **biner native terpisah**; aplikasi berbicara
  dengannya **hanya lewat HTTP**. Kapabilitas LLM penuh bekerja di 3.13 hanya dengan `httpx`/`requests` — tanpa
  `torch`/`transformers` sama sekali di dalam aplikasi.
- **Pustaka ML berat dibuang dari inti.** `torch`, `onnx`/`onnxruntime`, `tensorflow`,
  `pyAudioAnalysis`, dan stack deepfake **dihapus** untuk v1 karena (a) saat ini
  **direkayasa** ("deepfake CNN" tidak pernah menjalankan inferensi), (b) berat dan **hanya CPU di sini**, dan
  (c) berisiko wheel 3.13 per paket (`pyAudioAnalysis` tidak dipelihara; `igraph`/`leidenalg`/`gensim`
  masing-masing harus diverifikasi sebelum dipakai). Fitur ML apa pun di masa depan harus membuktikan bobotnya layak dan membuktikan adanya wheel 3.13.
- **Satu manifes dependensi, dipatok ke 3.13.** Ganti enam berkas requirements yang saling tidak sepakat dengan satu
  `pyproject.toml` di root (`requires-python = ">=3.13"`) + extras opsional (`[llm]`, `[analysis]`, `[dev]`).
  Hapus komentar "korektif" buatan AI dan pin yang mustahil.

#### 0.3 Model keamanan untuk satu pengguna lokal (menyederhanakan P0)

Karena satu-satunya listener adalah loopback dan satu-satunya pengguna adalah Anda:
- **Autentikasi:** tidak diperlukan untuk v1 *asalkan* server terikat secara ketat ke `127.0.0.1` dan tidak pernah diekspos
  oleh aturan firewall Qubes. (Satu token API opsional dapat ditambahkan kelak bila diproksikan.) Ini **menyelesaikan**
  temuan "tanpa autentikasi pada endpoint" *untuk penerapan ini* — dengan menghilangkan paparan jaringan alih-alih
  menambahkan RBAC.
- **`/metrics`:** hanya loopback seperti yang lainnya.
- **Keamanan installer tetap wajib:** tanpa `rm -rf` yang tidak dikonfirmasi, tanpa `curl | sh` yang tidak diverifikasi, jangan pernah membuang
  stderr manajer paket — ini masalah kebenaran/keamanan terlepas dari satu pengguna atau tidak.
- **Aset front-end di-vendor secara lokal** (tanpa Google Fonts / React dari CDN) — diwajibkan untuk offline/Qubes dan
  untuk prinsip privasi.

---

### 1. Definisi satu kalimat

Open-Omniscience adalah **platform intelijen sumber terbuka yang local-first untuk jurnalis investigasi**
yang secara etis menghimpun banyak sumber data dari seluruh dunia ke dalam **satu korpus yang dapat dicari, dapat dirujuk silang,
dan terlacak asal-usulnya**, dengan **AI lokal** opsional untuk analisis — dan di mana setiap keluaran
dirancang agar **dapat dipertanggungjawabkan secara ilmiah dan hukum**.

### 2. Untuk siapa, dan pekerjaan apa yang mereka percayakan kepadanya

**Pengguna utama:** jurnalis investigasi, peneliti, atau analis — kemungkinan bekerja sendiri atau di
ruang redaksi kecil, sering kali peka privasi (ada narasumber yang harus dilindungi), kadang di lingkungan
terbatas/terisolasi (air-gapped).

**Pekerjaan inti yang harus diselesaikan:**
1. *"Kumpulkan semua yang relevan dengan investigasi saya dari banyak sumber, di satu tempat, secara otomatis."*
2. *"Cari dan rujuk silang semuanya bersama-sama — artikel, pasar, email — untuk menemukan keterkaitan."*
3. *"Bantu saya memahami teks dalam volume besar"* (meringkas, menerjemahkan, mengekstrak entitas) — **tanpa
   mengirim data saya ke siapa pun.**
4. *"Beri tahu saya kapan sesuatu bisa saya percaya — atau tidak"* (memverifikasi media, menandai manipulasi).
5. *"Buktikan dari mana ini berasal dan bahwa saya tidak merusaknya"* (asal-usul untuk publikasi/hukum).
6. *"Peringatkan saya saat ada yang berubah"* (sumber menghilang, harga melonjak, narasi muncul).

### 3. Prinsip panduan (hal-hal yang tidak dapat ditawar)

Ini adalah inti dari maksud proyek dan wajib membatasi setiap fitur. Di mana kode hari ini melanggar salah satunya,
itu adalah cacat, bukan kompromi.

1. **Local-first & mampu offline.** Berjalan sepenuhnya di mesin/server pengguna. Wajib berfungsi
   tanpa internet kecuali selama scraping itu sendiri. Cocok untuk penggunaan air-gapped (dengan data/model yang disiapkan sebelumnya).
2. **Menjaga privasi.** Tanpa telemetri. **Tidak ada data pengguna yang pernah meninggalkan mesin** — terutama pemrosesan
   LLM (hanya lokal melalui Ollama). ✅ TERSELESAIKAN (§0): semua aset front-end (font, pustaka JS) **di-vendor
   secara lokal** — tanpa panggilan CDN — diwajibkan untuk postur Qubes/offline.
3. **100% FOSS.** Semua kode dan model bersumber terbuka. ⚠️ DECIDE: Lisensinya **GPLv3** di root tetapi
   **AGPL-3.0** di Pilar 3 — pilih satu untuk seluruh proyek (AGPL lebih ketat untuk penggunaan lewat jaringan).
4. **Etis secara konstruksi.** Hormati `robots.txt`, batas laju, identifikasi bot, hanya data publik,
   jangan pernah melewati paywall atau memakai kredensial untuk scraping. **Gagal *tertutup*** — jika kepatuhan tidak dapat
   diverifikasi, jangan lakukan scraping.
5. **Keluaran yang dapat dipertanggungjawabkan (ilmiah + hukum).** Setiap hasil analitis membawa ketidakpastian yang jujur dan
   asal-usul yang dapat dilacak. **Tanpa angka rekaan.** Skor keyakinan harus berasal dari metode yang nyata, atau
   tidak ada sama sekali. Rantai pengawasan (chain-of-custody) harus nyata (bertanda tangan, menunjukkan bukti perusakan), bukan sekadar berkas log biasa.
6. **Korpus terpadu.** Semua yang diserap — berita, data keuangan, komoditas, email — berada di **satu
   basis data** dan **dapat dirujuk silang dalam satu kueri**. Inilah alasan produk ini ada.
7. **Transparansi di atas kegagalan yang anggun.** Sistem tidak boleh diam-diam menurun menjadi keluaran yang tidak valid.
   Model hilang, sumber diblokir, dependensi tidak tersedia → **status yang terlihat dan eksplisit**, tidak pernah
   placeholder yang diam.

### 4. Model mental inti

```
        ┌─────────────────────────── INGESTION ───────────────────────────┐
        │  Web articles · RSS · Financial · Commodities · Email/Newsletters │
        │            (all ethically scraped / retrieved)                    │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
        ┌──────────────────── ONE UNIFIED, PROVENANCE-TRACKED STORE ────────┐
        │  articles · financial_data · commodity_data · emails · entities    │
        │  + links between them (article ↔ price move ↔ email ↔ entity)      │
        └───────────────────────────────┬───────────────────────────────────┘
                                         ▼
   ┌──────────── RETRIEVAL ────────────┐   ┌──────────── ANALYSIS (opt-in) ───────────┐
   │ Boolean / full-text search        │   │ Local LLM · verification · stats ·        │
   │ filters · cross-source correlation│   │ monitoring/alerts · correlation engines   │
   │ export (CSV/JSON) · reports       │   │ (every result: method + uncertainty)      │
   └───────────────────────────────────┘   └───────────────────────────────────────────┘
                                         ▼
                         GUI (search, dashboards, source mgmt, reports)
                         + REST API (everything available programmatically)
```

**Tulang punggungnya (serap → penyimpanan terpadu → cari → ekspor) wajib kokoh sebelum pilar mana pun.**
Pilar adalah *pengaya* yang membaca dari dan menulis kembali ke penyimpanan bersama.

---

### 5. Lingkup fungsional, per area kapabilitas

#### 5.1 Penyerapan Data (P0)
- **Jenis sumber:** situs berita (HTML), feed RSS/Atom. Kelak: API, platform sosial, kiriman berkas.
  ⚠️ DECIDE: Pilar 4 mencantumkan Twitter/X, Reddit, Telegram, Mastodon, S3/SFTP — pastikan mana (jika ada)
  yang benar-benar dalam lingkup vs sekadar aspirasi.
- **Scraper etis (satu implementasi bersama):** pemeriksaan robots.txt (di-cache, sadar http+https,
  **gagal tertutup** bila ragu), pembatasan laju per sumber, User-Agent yang mengidentifikasi diri, coba ulang/backoff.
  **Satu fetch per URL** — tanpa fetch ganda, tanpa jalur pintas mentah.
- **Deduplikasi:** berbasis hash konten + URL kanonis; jangan pernah menyimpan artikel yang sama dua kali.
- **Normalisasi:** ekstrak judul, penulis, tanggal terbit, bahasa, URL kanonis, teks isi secara andal.
  ⚠️ DECIDE: ekstraksi berita yang nyata memerlukan aturan per situs atau pustaka (mis. bergaya trafilatura); pendekatan
  CSS generik saat ini diam-diam menghasilkan "No Title/No Content." Pastikan kita mengadopsi ekstraksi yang tangguh.
- **Penjadwalan & pembaruan inkremental:** scraping ulang berkala, hanya mengambil konten baru/berubah, melanjutkan
  proses yang terputus.

#### 5.2 Penyimpanan Data Terpadu (P0)
- **Satu basis data** yang memuat semua jenis entitas, dengan **tabel tautan** eksplisit yang menghubungkannya
  (artikel ↔ instrumen keuangan, artikel ↔ komoditas, artikel ↔ email, artikel ↔ entitas bernama).
- **Kolom asal-usul pada setiap rekaman:** sumber, stempel waktu pengambilan, URL asli, hash konten,
  pemisahan mentah-vs-terolah.
- **Backend:** SQLite untuk satu pengguna/desktop; PostgreSQL untuk server/penggunaan bersamaan.
  ⚠️ DECIDE: pastikan SQLite sebagai bawaan + Postgres opsional (dokumen menyebut keduanya; juga Redis untuk caching —
  masuk atau tidak?).
- **Log audit:** rekaman append-only dan **menunjukkan bukti perusakan** atas setiap penyerapan dan mutasi.

#### 5.3 Pencarian & Pengambilan (P0)
- **Pencarian teks lengkap** di seluruh korpus.
- **Operator Boolean** (`AND`/`OR`/`NOT`), **frasa berkutip**, dan **tanda kurung dengan presedensi
  yang benar** — diimplementasikan dengan tata bahasa yang nyata atau FTS bawaan DB, bukan akal-akalan string.
- **Filter terstruktur:** sumber, rentang tanggal, bahasa, tag/kategori, entitas, jenis data.
- **Paginasi**, peringkat hasil, cuplikan/sorotan.
- **Ekspor:** CSV dan JSON (dan ⚠️ DECIDE: format PDF/laporan?), setia pada himpunan hasil yang difilter.

#### 5.4 Rujukan Silang & Korelasi (P1 — pembedanya)
- Berpindah dari rekaman mana pun ke rekaman terkait lintas jenis (artikel → perusahaan yang disebut → pergerakan harga
  di sekitar tanggal terbit → email terkait).
- **Mesin korelasi** (keuangan/komoditas ↔ berita) yang memunculkan hubungan *kandidat* dengan
  **ukuran yang jujur dan terdefinisi** (dan dengan jelas menandai korelasi ≠ kausalitas). Tanpa nilai-p rekaan.
- Tampilan berpusat entitas: semua yang diketahui korpus tentang seseorang/organisasi/tempat/instrumen.

#### 5.5 Analisis LLM Lokal (P1)
- **Runtime:** Ollama, sepenuhnya lokal. Model dapat dipasang-ganti; sertakan bawaan kecil yang masuk akal dan *benar-benar
  ada*. ⚠️ DECIDE: bawaan saat ini `gemma4:e2b` dan sebagian besar model yang tercantum (Gemma 4, Llama 4, Qwen 3.5)
  adalah halusinasi — ganti katalognya dengan tag yang nyata (mis. `gemma2:2b`, `llama3.2:3b`, `qwen2.5`,
  `phi3`).
- **Kapabilitas:** generate, chat (dengan konteks), ekstrak (entitas/kata kunci/ringkasan/kutipan/tautan),
  terjemahkan (multibahasa), analisis (sentimen/nada/keterbacaan; bias hanya jika dibatasi secara jujur),
  sintesis (ringkasan, perbandingan, linimasa, laporan), batch.
- **Menurun dengan lantang:** jika Ollama atau modelnya tidak ada, katakan demikian — jangan pernah mengembalikan analisis palsu.

#### 5.6 Verifikasi & Pertahanan terhadap Penipuan — *Pilar 3* (P2, lingkup belum ditentukan)
- **Maksud:** mendeteksi media yang dimanipulasi (deepfake gambar/video/audio), teknik propaganda, bias
  kognitif, bot, dan kampanye terkoordinasi; memvalidasi metadata (EXIF/ID3) dan konsistensi lintas modal.
- ⚠️ DECIDE (penting): Saat ini ini **direkayasa** — "deepfake CNN" tidak pernah menjalankan inferensi; skornya
  adalah heuristik keburaman; cakupan bias/propaganda sebagian besar tidak terjangkau; "akurasi >95%" hanyalah aspirasi.
  Pilih salah satu:
  - **(a) Pangkas** forensik media untuk saat ini dan kirimkan hanya yang jujur (validasi metadata/EXIF itu nyata
    dan berguna); **(b) Bangun ulang** dengan model FOSS yang asli, telah dievaluasi, dan akurasinya dipublikasikan; atau
    **(c) Pertahankan** tetapi **beri label jelas "heuristik eksperimental, bukan bukti."**
  Rekomendasi saya: (a) sekarang, (b) nanti. Forensik rekaan adalah satu-satunya liabilitas terbesar bagi alat
  jurnalisme/hukum.

#### 5.7 Ketelitian Ilmiah — *Pilar 2* (P1)
- **Maksud:** membuat klaim kuantitatif platform dapat dipertanggungjawabkan — uji statistik nyata, interval
  kepercayaan, penilaian reproduktibilitas/garis keturunan data, dan "tinjauan sejawat" melalui beberapa LLM lokal yang saling memeriksa.
- Pilar ini adalah yang paling sungguh-sungguh terimplementasi (scipy/statsmodels yang nyata). Pertahankan, perkuat, dan jadikan
  **penjaga gerbang**: angka apa pun yang ditampilkan aplikasi kepada pengguna harus melewati pelaporan ketidakpastian yang jujur.

#### 5.8 Pemantauan & Peringatan Waktu Nyata — *Pilar 4* (P2)
- **Maksud:** pengawasan sumber secara berkelanjutan; deteksi anomali/tren/pola; pengayaan intelijen ancaman;
  peringatan multikanal (email/webhook/chat) dengan aturan dan eskalasi.
- ⚠️ DECIDE: pemeriksaan kesehatan saat ini disimulasikan (`sleep; return HEALTHY`) dan intelijen ancaman/STIX-TAXII
  tidak ada. Pastikan lingkupnya: pemantauan uptime sumber yang nyata + peringatan anomali pada korpus itu
  dapat dicapai dan bernilai; STIX/TAXII, SMS/Twilio, Slack/Teams itu berat — masuk atau tidak?

#### 5.9 Intelijen Keuangan — *Pilar 5* (P2, ditandai 0% di dokumen)
- **Maksud:** melakukan scraping bursa global (OHLC + fundamental) dari sumber web terbuka (tanpa API/paywall),
  mendeteksi fluktuasi/pola/anomali, dan **mengorelasikan pergerakan harga dengan berita** di DB bersama.
- ⚠️ DECIDE: Ini **hanya desain (0% dibangun)** meskipun ada kode kerangka yang sudah di-commit. Pastikan ini sasaran
  yang nyata dan, jika ya, lingkup pertamanya yang realistis (mis. segelintir bursa, OHLC harian, korelasi dengan
  artikel) alih-alih "50+ bursa / 10.000+ perusahaan" sejak hari pertama. Catatan: scraping multi-bursa yang tangguh
  tanpa API adalah pekerjaan besar dan rapuh.

#### 5.10 Intelijen Logam Tanah Jarang / Komoditas — *Pilar 6* (P2, ditandai 0% di dokumen)
- **Maksud:** pola yang sama dengan Pilar 5 untuk 17 unsur tanah jarang — harga, produksi, persediaan,
  dikorelasikan dengan peristiwa geopolitik/berita; dengan peramalan.
- ⚠️ DECIDE: Juga **hanya desain (0% dibangun)**. Pastikan lingkup dan prioritasnya dibandingkan Pilar 5. (Perlu perbaikan: perhitungan
  satuan untuk normalisasi harga saat ini meleset sekitar ~1000×, dan mata uang tidak dikonversi.)
  ⚠️ DECIDE: Apakah "peramalan" termasuk dalam lingkup? Peramalan yang jujur dengan ketidakpastian itu sulit; disarankan untuk ditunda.

#### 5.11 Intelijen Email & Newsletter (P1/P2)
- **Maksud:** mengambil dari IMAP/POP3 dan sumber newsletter (Substack/Mailchimp/RSS-ke-email), mengurai +
  membersihkan, menangani lampiran (PDF/Office/gambar dengan OCR), mengekstrak entitas dan jaringan komunikasi,
  dan **memasukkannya ke korpus yang sama yang dapat dicari**.
- **Privasi/persetujuan adalah yang terpenting di sini** (komunikasi pribadi): otorisasi eksplisit, penyimpanan
  kredensial terenkripsi, minimisasi data, retensi/hak untuk dilupakan.
- ⚠️ DECIDE: Integrasi API newsletter (Substack/Mailchimp/dll.) vs. hanya IMAP + RSS-ke-email untuk v1?

#### 5.12 GUI / UX (P0 untuk inti, P1+ untuk dasbor pilar)
- **GUI inti:** antarmuka pencarian, penelusuran hasil, pengelolaan sumber, ekspor, dasbor dasar.
- **Dasbor pilar (nanti):** peta panas/grafik keuangan, tampilan komoditas, pemantauan/peringatan, kotak masuk
  email, penjelajah korelasi.
- ✅ TERSELESAIKAN (§0): **UI web dilayani oleh FastAPI di `127.0.0.1:8000`; aplikasi desktop Tkinter dibuang**
  (hapus `python3-tk`). Buka di peramban AppVM.
- ✅ TERSELESAIKAN (§0): front-end adalah **JS vanilla + pustaka yang di-vendor (dilayani dari `/static`)** — tanpa CDN.
  ⚠️ DECIDE (minor): grafik tetap ringan (mis. pustaka grafik kecil yang di-vendor) vs tanpa grafik di v1.

#### 5.13 Pelaporan & Keluaran yang Dapat Dipertanggungjawabkan (P1)
- Menghasilkan laporan investigasi yang menggabungkan temuan **beserta asal-usulnya** (sumber, stempel waktu,
  hash, metode, ketidakpastian).
- **Rantai pengawasan / integritas:** penandatanganan kriptografis + bukti perusakan pada bukti yang diekspor
  (modul kripto sudah ada tetapi belum disambungkan). Inilah yang membuat klaim "dapat diterima secara hukum"
  nyata alih-alih sekadar hiasan.

---

### 6. Persyaratan non-fungsional

- **Platform:** ✅ TERSELESAIKAN (§0) — **Qubes OS Debian AppVM** adalah *satu-satunya* sasaran yang didukung untuk v1
  (dibangun dan diuji di sana). Debian 13 biasa mungkin berfungsi tetapi bukan tujuan; tidak ada komitmen lintas platform.
- **Python:** ✅ TERSELESAIKAN (§0) — **3.13**, konsisten di `pyproject.toml`, `.python-version`, dan
  CI mana pun. Buang dependensi yang tidak memiliki wheel 3.13 (lihat §0.2).
- **Jejak instalasi:** **inti minimal** yang sesungguhnya (web + DB + pencarian, ringan) yang dapat dipisahkan dari extras
  opsional (`[llm]`, `[analysis]`). **Satu** `pyproject.toml` — bukan enam manifes yang saling tidak sepakat. Installer
  menghormati persistensi Qubes (§0.1): dependensi sistem di TemplateVM, venv+data di `/home`.
- **Keamanan:** ✅ TERSELESAIKAN (§0) — satu pengguna lokal, **hanya loopback**, sehingga tanpa RBAC. Tetap wajib:
  hanya akses DB terparameterisasi (hapus "sanitizer" berbasis daftar blokir), tanpa rahasia di dalam kode, `/metrics` loopback,
  dan **installer yang aman** (tanpa `rm -rf` yang tidak dikonfirmasi, tanpa `curl | sh` yang tidak diverifikasi, jangan pernah membuang stderr paket).
- **Kinerja:** I/O non-blocking untuk pekerjaan jaringan/LLM; konkurensi terbatas; aplikasi tetap responsif selama
  scraping/inferensi. Asumsi **hanya CPU** (tanpa GPU di Qubes). Target ditetapkan berdasarkan sumber daya AppVM
  yang realistis, bukan aspirasi.
- **Offline:** semua aset, font, dan model (yang sudah ditarik sebelumnya) bersifat lokal; prosedur terdokumentasi untuk beroperasi dengan
  NetVM dilepas setelah data/model diambil.
- **Keteramatan (observability):** log terstruktur (di bawah `/home`), pemeriksaan kesehatan yang jujur, metrik Prometheus loopback —
  mencerminkan keadaan nyata.

### 7. Hal yang secara eksplisit bukan tujuan / di luar lingkup (usulan — silakan sesuaikan)

- Bukan crawler/mirror web serbaguna (garis keturunan HTTrack hanyalah sisa; buang pembingkaian itu).
- Bukan scraper untuk menembus paywall, credential-stuffing, atau yang melanggar ToS.
- Bukan produk cloud/SaaS; tanpa API AI eksternal.
- ⚠️ DECIDE: Apakah peramalan (5.10), penyerapan media sosial (5.8), dan forensik media (5.6) masuk atau tidak
  untuk rilis nyata pertama?

### 8. Model data, asal-usul & ketahanan hukum (lintas bagian)

- Setiap item yang disimpan: `{source, original_url, fetched_at, content_hash, raw_payload_ref, processing_log}`.
- Setiap hasil turunan/analitis: `{method, version, inputs_ref, uncertainty/confidence_basis,
  computed_at}` — **keyakinan tidak pernah berupa konstanta yang di-hardcode.**
- Bukti yang diekspor: opsional **ditandatangani**, dengan manifes yang dapat diverifikasi (hash + Merkle/GPG) sehingga pihak
  ketiga dapat memastikan integritasnya. Inilah makna konkret dari "Pilar 4: Dapat Diterima secara Hukum."

### 9. Keputusan (terhimpun)

**✅ Terselesaikan oleh konteks penerapan (§0):**
- **3. Penerapan & model ancaman** → satu pengguna lokal, Qubes Debian AppVM, hanya loopback, tanpa RBAC.
- **7. GUI** → UI web di `127.0.0.1:8000`, JS vanilla, aset di-vendor secara lokal; Tkinter dibuang.
- **8. Platform/Python** → Qubes Debian AppVM, Python 3.13, SQLite sebagai bawaan (Postgres/Redis **tidak masuk** untuk v1).

**⚠️ Masih terbuka (keputusan Anda — bawaan yang masuk akal diusulkan):**
1. **Lingkup MVP:** *usulan* — hanya Inti Tepercaya dahulu (Fase 1), lalu LLM. Mohon konfirmasi.
2. **Strategi pembangunan ulang:** *usulan* — selamatkan bagian tipis yang baik (model DB, `ethical_scraper`,
   `async_db`, kerangka FastAPI), hapus pilar-pilar rekaan, bangun ulang inti di sekitarnya. Konfirmasi vs.
   greenfield penuh.
4. **Forensik media (Pilar 3):** *usulan* — **(a) pangkas** deepfake/propaganda/bias untuk v1 (juga
   tidak bersahabat dengan 3.13/CPU), **pertahankan** validasi metadata/EXIF yang nyata. Mohon konfirmasi.
5. **Keuangan (5) & komoditas (6):** *usulan* — tunda ke Fase 3, lalu bangun **satu** vertikal tipis.
   Yang mana dahulu?
6. **Email:** *usulan* — hanya IMAP + RSS-ke-email untuk v1; tunda integrasi API newsletter. Mohon konfirmasi.
9. **Lisensi:** GPLv3 vs AGPL-3.0 untuk seluruh proyek — masih memerlukan keputusan.
10. **Konfirmasi di luar lingkup:** peramalan, penyerapan media sosial, STIX/TAXII, peringatan SMS/chat —
    *usulan* tidak masuk untuk v1.

### 10. Pentahapan yang disarankan (usulan, bukan komitmen)

- **Fase 1 — Inti Tepercaya:** penyerapan etis → penyimpanan terpadu (dengan asal-usul) → pencarian Boolean/
  teks lengkap yang benar → ekspor → GUI web minimal → pengujian nyata. *Semua yang lain dimatikan sampai ini hijau.*
- **Fase 2 — LLM Lokal + Ketelitian Ilmiah:** sambungkan Ollama (model nyata, penurunan yang lantang); jadikan Pilar 2
  gerbang kejujuran bagi angka apa pun yang ditampilkan.
- **Fase 3 — Satu vertikal + korelasi:** pilih **antara** keuangan **atau** komoditas, bangun irisan yang tipis tetapi
  nyata, buktikan pengalaman korelasi artikel↔data dari ujung ke ujung.
- **Fase 4 — Pemantauan/peringatan, email, verifikasi (metadata dahulu):** tambahkan pengaya satu per satu,
  masing-masing sungguh berfungsi dan teruji.
- **Fase 5 — Pelaporan yang dapat dipertanggungjawabkan:** sambungkan penandatanganan/rantai pengawasan yang nyata ke dalam ekspor.

---

### 11. Status implementasi (saat ini)

Apa yang sudah dibangun dan diuji hari ini, dipetakan ke lingkup di atas (maksud tidak berubah; catatan ini
menunjukkan di mana kenyataan kini berada). Lihat dokumen fitur yang ditautkan untuk rinciannya.

- **Inti tepercaya (5.1–5.3, 5.13):** ✅ penyerapan etis, penyimpanan asal-usul terpadu,
  pencarian Boolean FTS5, ekspor CSV/JSON, rantai pengawasan yang ditandatangani.
- **Penyerapan berskala (5.1):** ✅ **penjadwal** di dalam aplikasi (mulai/berhenti, interval, mode
  rss/crawl/markets) dan **crawler rekursif terbatas** (*penemuan* domain yang sama,
  robots gagal tertutup, batas kedalaman/halaman) — bukan mirror serbaguna (§7 dihormati).
- **GUI (5.12):** ✅ UI web bertab — Pencarian · Ingest · **Sources & Database** (statistik,
  pengelolaan sumber, **cakupan dunia**) · **Pasar** · **Wawasan** · Rantai
  pengawasan · **Pengaturan** (tema + cadangan/pemulihan SQLite). Tanpa dependensi, offline.
- **Keuangan & komoditas (5.9, 5.10):** ✅ vertikal nyata yang tipis — **aturan ekstraksi**
  harga per sumber, **feed CSV resmi** (FRED→World Bank/EIA), grafik, dan
  korelasi harga↔berita yang jujur. Perhitungan satuan diperbaiki; angka hanya berasal dari aturan yang terverifikasi
  atau CSV yang diimpor. Lihat [USER_MANUAL.md](USER_MANUAL.md).
- **Cakupan sumber sedunia:** ✅ katalog pasar yang dipaketkan + **generator berbasis
  data** (Wikidata CC0) untuk media berita **dan** institusi per negara, dengan
  laporan cakupan. Impor/ekspor CSV untuk daftar sumber. Lihat
  [ROADMAP.md](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).
- **Rujukan silang & korelasi (5.4):** ✅ **analitik kata kunci & entitas** —
  ekstraksi saat penyerapan, penyimpanan penyebutan beserta konteksnya, tren, asosiasi PMI
  ("peta pikiran"), dan peta per negara/kota. Lihat [USER_MANUAL.md](USER_MANUAL.md).
- **Wikipedia sebagai sumber yang dilacak (baru):** 🚧 fondasi pelacakan perubahan (edisi per
  bahasa, penyimpanan delta, penandaan suntingan besar/revisionisme termasuk ORES) — skema +
  parser + penandaan selesai; polling langsung, tab, dan pengunduh offline menyusul. Lihat
  [USER_MANUAL.md](USER_MANUAL.md).
- **Verifikasi (5.6):** ✅ hanya EXIF/metadata gambar yang jujur (forensik rekaan
  tetap dikarantina). **LLM (5.5)**, **pemantauan/peringatan (5.8)**, **email (5.11)**:
  sebagian/dalam antrean.

---


---

## Peta Maksud Pilar — di mana tujuan setiap pilar kini berada

Desain awal menata platform ke dalam enam "pilar". Pohon-pohon pilar tersebut
berisi ~50 ribu baris yang tidak pernah diimpor oleh aplikasi yang berjalan — sebagian besar hanya desain atau
rekaan. **Adapun *maksud*-nya, telah dipertahankan**: tujuan sejati setiap pilar
kini menjadi modul kecil yang jujur dan teruji di dalam `src/` (atau secara eksplisit ditunda).
Pohon-pohon pilar asli disimpan di bawah `quarantine/pillars/` sebagai rujukan dan
sejarah; tidak ada yang dihapus.

| Pilar (maksud) | Di mana maksudnya kini berada | Status |
|---|---|---|
| **1 — Penyerapan data** (scraping etis → penyimpanan terpadu) | `src/ingest/` (fetcher, extract, pipeline, email) + `src/database/` | ✅ Nyata, teruji |
| **2 — Ketelitian ilmiah** (statistik yang jujur, ketidakpastian) | `src/analysis/` (`statistical_tests`, `confidence_intervals`) + `POST /api/analysis/*` | ✅ **Kode scipy/statsmodels yang asli diselamatkan** + 60 pengujiannya |
| **3 — Pertahanan terhadap penipuan** (verifikasi media) | `src/verification/metadata.py` (EXIF/metadata yang jujur) + `POST /api/verify/image-metadata` | ✅ Lingkup yang jujur. Detektor deepfake/propaganda/bias adalah rekaan → `quarantine/pillar3_analysis/` |
| **4 — Pemantauan + dapat diterima secara hukum** | `src/monitoring/` (uptime + anomali yang nyata) dan `src/reporting/` + `src/crypto/` (bukti bertanda tangan Merkle + Ed25519) | ✅ Nyata, teruji |
| **5 — Intelijen keuangan** | *Ditunda.* Polanya telah dibuktikan oleh implementasi ulang Pilar 6; vertikal keuangan dapat memakai ulang `src/commodity` + `src/analysis`. | ⏸ Awalnya hanya desain (0%); belum dibangun |
| **6 — Logam tanah jarang / komoditas** | `src/commodity/` (harga, konversi satuan yang benar, korelasi scipy yang **nyata**, impor CSV) + `POST /api/commodities/*` | ✅ Nyata, teruji |

### Apa yang diselamatkan pada langkah ini (Pilar 2)
- `src/analysis/statistical_tests.py` — uji-t, ANOVA, chi-kuadrat, Pearson/Spearman,
  Mann-Whitney, Wilcoxon, regresi, Tukey HSD (scipy/statsmodels). Setiap hasil
  membawa statistik, nilai-p, derajat kebebasan, ukuran efek, ukuran sampel.
- `src/analysis/confidence_intervals.py` — rata-rata dan proporsi (t/normal/Wilson/
  Clopper-Pearson/Agresti-Coull).
- Diekspos di `POST /api/analysis/{t-test,correlation,anova,mann-whitney,confidence-interval}`
  sehingga jurnalis dapat memeriksa apakah suatu pola dalam datanya memang signifikan.
- Rangkaian pengujian Pilar 2 yang asli ikut pindah bersama kodenya (`tests/test_statistical_tests.py`,
  `tests/test_confidence_intervals.py`).

### Apa yang TIDAK diselamatkan (dan mengapa)
- `peer_review` / `consensus` / `reproducibility` dari Pilar 2 — spekulatif atau dangkal
  (mis. reproduktibilitas berupa rubrik rata-rata boolean). Diparkir; hidupkan kembali dengan metode
  yang nyata bila diperlukan.
- Detektor forensik Pilar 3, pemantauan/intelijen ancaman simulasi Pilar 4, kerangka Pilar
  5/6 — rekaan atau hanya desain; bagian yang jujur sudah ada di `src/`.

### Dampak bersih
Repositori kini mencerminkan apa yang benar-benar berjalan: inti hidup ~16 ribu baris (ditambah
statistik yang diselamatkan), dengan ~50 ribu baris pilar yang aspiratif/rekaan diparkir di
`quarantine/pillars/` alih-alih menyamar sebagai fitur yang berfungsi.


---

## Desain Ulang GUI — "0.05"

> Desain ulang menyeluruh antarmuka Open Omniscience, dinalar dari pengguna
> ke luar. Dokumen ini adalah *mengapa*-nya; `src/static/index.html` adalah *apa*-nya.
> Baca ini dahulu jika Anda ingin memahami (atau memperdebatkan) keputusan-keputusannya.

---

### 0. Ringkasan tugas, dinyatakan ulang

Rancang ulang seluruh GUI untuk orang tertentu: **seorang pencari kebenaran — penyelidik/jurnalis
yang *tidak* menyukai komputer**, yang ingin memahami
dunia sebagaimana adanya dan menyampaikan temuan secara kredibel. Hasilnya harus
apik, indah, adaptif, sangat dapat disesuaikan, sederhana *sekaligus* mendalam, dan cukup baik
sehingga rekan yang melirik dari balik bahu berkata *"ini apa — boleh saya punya
juga?"* Ia harus menghormati apa yang sudah menjadi jati diri proyek: **satu pengguna, hanya loopback,
offline-first, tanpa dependensi, tanpa telemetri**, diatur oleh **Piagam München (Munich Charter)**
(kebenaran, verifikasi sumber, privasi, tanpa propaganda).

#### Sikap rekayasa (dan kompromi yang jujur)

UI sebelumnya adalah satu `index.html` berisi 2.200 baris yang menyambungkan ~110 fungsi ke ~150
endpoint API. Fungsi-fungsi itu *berfungsi dan teruji*. Penulisan ulang dari nol akan
menghasilkan cangkang yang lebih cantik dengan peluang tinggi tombol-tombolnya diam-diam rusak — justru
kebalikan dari alat yang seluruh nilai jualnya adalah **kejujuran**. Maka ini adalah
**desain ulang total atas segala yang dilihat dan disentuh pengguna** — bahasa visual,
tata letak, model navigasi, arsitektur informasi, penamaan, orientasi pengguna baru,
kustomisasi, dan dua permukaan yang sama sekali baru (dasbor Beranda dan pembaca Docs
di dalam aplikasi) — dibangun *di atas lapisan data yang sudah terbukti*, dengan setiap ID elemen asli
dipertahankan agar tidak ada yang mundur. Tanpa dependensi tetap mutlak: **tanpa CDN, tanpa font
web, tanpa framework** — satu berkas mandiri yang berjalan dengan NetVM dilepas.

---

### 1. Persona (siapa yang sebenarnya kita layani)

**Amara — jurnalis investigasi, 44 tahun. Persona utama.**
Meliput korupsi pengadaan. Reporter cemerlang, pengguna komputer yang enggan. Menangani
liputan sensitif dan (wajar saja) waspada terhadap pengawasan dan kehilangan data.
*Kebutuhan:* menemukan sesuatu dengan cepat di korpusnya sendiri; membuktikan bahwa sebuah dokumen autentik dan
tidak diubah; mengekspor sesuatu yang bisa ia serahkan kepada editor atau pengadilan; tidak pernah merasa bodoh.
*Ketakutan:* kehilangan pekerjaan, dilacak, jargon, terlihat amatir di samping rekan yang "melek teknologi".
*Kondisi menang:* ia membuka aplikasi dan langsung tahu apa yang harus dilakukan, dan apa yang ia
hasilkan terlihat tepercaya dan *memang* tepercaya.

**Daniel — peneliti OSINT lepas, 29 tahun. Persona pengguna mahir.**
Semi-teknis, cepat, mengandalkan papan ketik, menjalankan banyak sumber. *Kebutuhan:* kepadatan, operasi
batch, tren/asosiasi, korelasi pasar, pintasan papan ketik, palet
perintah. *Ketakutan:* tuntunan berlebihan yang memperlambatnya; fitur yang tersembunyi.
*Kondisi menang:* ia tidak pernah harus menyentuh tetikus dan menemukan kemampuan lanjutan yang siap pakai.

**Saudari seperjuangan — sang "operatif", usia 50-an. Persona nilai.**
Tidak memercayai Big Tech; menginginkan kedaulatan. *Kebutuhan:* bukti bahwa tidak ada yang "menelepon pulang"; operasi
offline; penjelasan sederhana tentang apa dampak setiap tindakan terhadap keterpaparan jaringannya.
*Kondisi menang:* ia dapat membaca, di dalam aplikasi, persis apa yang akan dan tidak akan dilakukannya.

**Elliot — editor, 38 tahun. Persona penerima.**
Tidak pernah membuka aplikasi; ia *menerima* keluarannya. *Kebutuhan:* ekspor yang terbaca dan
dapat diverifikasi dengan sendirinya. UI melayaninya secara tidak langsung: bundel bukti, kustodi
bertanda tangan, CSV/JSON yang rapi.

**Implikasi desain:** utamakan Amara (kejelasan, tuntunan, kepercayaan), lapiskan kedalaman Daniel
sehingga tidak pernah menghalanginya (pengungkapan bertahap + palet perintah),
hormati kedaulatan sang operatif dalam teks dan perilaku, dan jadikan
artefak Elliot sebagai warga kelas satu.

---

### 2. Prinsip desain (diturunkan, bukan dipinjam)

1. **Kejelasan di atas kecerdikan.** Kata kerja sederhana, label yang manusiawi, satu tindakan utama yang jelas
   per layar. Jargon ("ingest", "korpus", "akar Merkle") diterjemahkan atau
   dijelaskan di tempat, tidak pernah diasumsikan.
2. **Kepercayaan adalah produknya.** Keterverifikasian, asal-usul, dan "angka ini nyata,
   bukan perkiraan" ditampilkan ke permukaan, bukan dikubur. Estetikanya harus *terasa* seperti
   instrumen, bukan mainan.
3. **Pengungkapan bertahap.** Sederhana secara bawaan; kedalaman hanya sejauh satu klik. Panel
   lanjutan dapat dilipat; modul yang jarang dipakai dapat disembunyikan sepenuhnya.
4. **Dapat disesuaikan, karena kepercayaan itu personal.** Tema, aksen, kepadatan, ukuran font,
   tata letak, dan *alat mana yang bahkan muncul* ditentukan oleh pengguna — dan hanya disimpan
   secara lokal.
5. **Kejujuran di antarmuka.** Jika suatu kapabilitas bergantung pada extra opsional,
   UI mengatakannya alih-alih berpura-pura. Tidak ada yang memalsukan keberhasilan.
6. **Berdaulat secara konstruksi.** Tanpa permintaan eksternal dalam bentuk apa pun. Tampilannya
   dicapai dengan font sistem dan ikon SVG buatan tangan.
7. **Mengutamakan papan ketik juga berarti mengutamakan aksesibilitas.** Palet perintah dan pintasan
   melayani Daniel *dan* membuat seluruh aplikasi dapat dijangkau tanpa ketepatan tetikus.

---

### 3. Analisis per alat — kelebihan, kekurangan, keputusan

Kumpulan tab atas yang lama: *Pencarian · Ingest · Sumber · Basis data · Pasar · Wawasan ·
Wikipedia · Rantai pengawasan · Pengaturan.* Dievaluasi satu per satu untuk persona-persona kita.

| Tab lama | Kelebihan | Kekurangan | **Keputusan** |
|---|---|---|---|
| **Pencarian** | Tindakan inti. Semua orang membutuhkannya. | Terkubur sebagai satu tab di antara sembilan; tidak ada orientasi bagi pengguna baru. | **Pertahankan & angkat.** Menjadi jantungnya, dapat dijangkau seketika; **Beranda** yang baru memberi orientasi di sekelilingnya. |
| **Ingest** | Diperlukan untuk menarik data masuk. | "Ingest" adalah jargon insinyur; mengintimidasi; mencampuradukkan penjadwal + pengambilan manual. | **Pertahankan, ganti nama → "Kumpulkan."** Dahulukan tindakan manual yang sederhana; penjadwal menjadi "Pengumpulan otomatis," dibingkai sebagai atur-lalu-lupakan. |
| **Sumber** | Kredibilitas berada di sini; asal-usul dimulai dari *di mana*. | Tabel padat; terasa seperti administrasi, bukan jurnalisme. | **Pertahankan, bingkai ulang sebagai "Sumber" (daftar liputan ruang redaksi Anda).** Ditata ulang agar terbaca seperti perpustakaan, bukan konsol basis data. |
| **Basis data** | Hitungan langsung yang jujur; cadangan/pemulihan. | "Basis data" tidak berarti apa-apa bagi Amara; ia punya *perpustakaan/arsip*, bukan DB. | **Pertahankan, ganti nama → "Pustaka."** Hitungan nyata dan cakupan dunia yang sama, dibingkai sebagai "apa yang telah Anda kumpulkan." |
| **Pasar** | Ampuh untuk investigasi "ikuti aliran uang". | Tidak relevan bagi sebagian besar liputan; berat, ceruk; mengacaukan tampilan bagi Amara. | **Pertahankan, tandai Lanjutan, dapat disembunyikan.** Di luar jalur kritis; satu sakelar menghapusnya bagi pengguna yang tidak bekerja di bidang keuangan. |
| **Wawasan** | Etalase visual — tren, asosiasi, peta. Sang "wow." | Dulu tab tengah yang sepi; kurang ditonjolkan. | **Pertahankan & promosikan.** Ini fitur utama; diberi keunggulan dan polesan. |
| **Wikipedia** | Sangat cocok: "dunia sebagaimana adanya," pengetahuan offline, deteksi perang suntingan. | Dua hal yang berbeda (pelacakan langsung vs dump offline yang berat) terbagi di beberapa tab secara membingungkan. | **Pertahankan.** Pelacakan tetap di sini; dump berat tetap di Pengaturan, dengan tautan silang yang jelas (sudah dilakukan dalam pekerjaan sebelumnya). |
| **Rantai pengawasan** | Pembeda dalam hal kepercayaan. Inilah yang membuat Elliot memercayai keluarannya dan Amara terlihat profesional. | Dinamai dengan bahasa hukum; terasa seperti brankas yang jarang dibuka. | **Pertahankan, ganti nama → "Bukti & kustodi," promosikan.** Bagian dari momen "ini apa?!". |
| **Pengaturan** | Diperlukan. | Dulu menjadi laci serba ada (preferensi + filter kata kunci + dump + cadangan). | **Pertahankan, susun ulang** menjadi beberapa bagian (Tampilan · Umum · Wikipedia · Data & cadangan · Keamanan). *(0.07: laci Sesuaikan yang berdiri sendiri dilebur sebagai bagian **Tampilan** — satu rumah untuk tampilan dan nuansa, lebih sedikit elemen yang mengambang.)* |

#### Permukaan baru yang ditambahkan

- **Beranda (dasbor).** *Alasan:* Amara membutuhkan orientasi, bukan kotak pencarian kosong.
  Status sekilas (ukuran korpus, sumber, penjadwal, aktivitas terakhir), tindakan cepat
  yang besar ("Pencarian," "Kumpulkan sekarang," "Verifikasi dokumen"), dan keadaan kosong yang
  mengajari. Ini adalah satu-satunya kemenangan kegunaan terbesar bagi persona utama.
- **Bantuan / pembaca Docs.** Pengguna secara eksplisit meminta akses langsung ke manual
  yang terperinci. Permukaan **Bantuan** kelas satu menampilkan User Manual (dan dokumen lain)
  *di dalam* aplikasi — dapat dicari, offline, tanpa meninggalkan alat. Juga dapat dijangkau dari
  bilah atas (`?`) dan palet perintah.

#### Arsitektur informasi yang dihasilkan

Deretan 9 tab yang datar menjadi **bilah samping berkelompok** (dapat dilipat menjadi ikon), diurutkan
menurut alur kerja yang sebenarnya:

- **Investigasi** — Beranda · Pencarian · Wawasan · Peta temporal · Wikipedia · *Pasar (lanjutan)*
- **Kumpulkan** — Kumpulkan · Sumber · Pustaka
- **Kepercayaan** — Bukti & kustodi
- **Sistem** — Pengaturan · Bantuan

Pengelompokan mengubah "sembilan orang asing yang setara" menjadi "empat niat," sesuai cara Amara
berpikir ("Saya ingin *menemukan* sesuatu" / "Saya ingin *mengumpulkan*" / "Saya ingin *membuktikan*").

---

### 4. Sang "wow" — apa yang membuat jurnalis tertarik mendekat

- **Sistem visual yang koheren.** Tema gelap "tinta" yang pekat sebagai bawaan dengan satu
  aksen yang percaya diri, ritme jarak yang lapang, hierarki tipografi yang nyata, monospace untuk
  data/hash, kedalaman yang lembut, dan gerak yang terkendali. Ia terbaca sebagai *instrumen*, bukan
  *templat dasbor*.
- **Palet perintah (Ctrl/⌘-K).** Ketik untuk melompat ke mana saja, menjalankan tindakan apa pun, atau membuka
  dokumen apa pun. Kekuatan bagi Daniel; peta "apa yang sebenarnya bisa saya lakukan di sini?" bagi Amara.
- **Kontrol tampilan** (Pengaturan → Tampilan; laci langsung hingga 0.06, dilebur
  ke Pengaturan di 0.07). Preset tema (Ink, Slate, Midnight, Paper, Sepia,
  Terminal, High-contrast), contoh warna aksen, kepadatan, ukuran font, pelipatan bilah samping,
  dan **visibilitas modul** — semuanya instan, semuanya lokal, semuanya persisten.
- **Beranda yang memberi orientasi**, orientasi pengguna baru yang mengajari, dan keadaan kosong yang menuntun.
- **Kepercayaan, dibuat terlihat.** Kustodi/verifikasi dan pembingkaian "diukur, bukan diperkirakan"
  adalah bagian dari estetika, bukan cetakan kecil.
- **Integritas offline total.** Tanpa panggilan jaringan untuk elemen antarmuka — yang dengan sendirinya merupakan
  fitur yang bisa Anda *tunjukkan* kepada rekan yang sadar keamanan.

---

### 5. Model kustomisasi

Tampilan dan nuansa disimpan di `localStorage` (`oo.ui`) — tidak pernah dikirim ke mana pun — sehingga
instan dan bertahan saat offline. Preferensi fungsional (batas hasil bawaan, tema
dasar) tetap disimpan di sisi server melalui `/api/settings`. Yang dapat disesuaikan: preset
tema, warna aksen, kepadatan, skala font, keadaan bilah samping, dan himpunan modul
yang terlihat. Bawaan yang masuk akal berarti pengguna yang baru pertama kali menjalankan tidak perlu menyentuh satu pun.

---

### 6. Apa yang dengan sengaja **tidak** saya lakukan (kejujuran)

- **Tanpa framework / langkah build / CDN.** Itu akan merusak etos offline, dapat diaudit, dan berdaulat
  demi keuntungan kosmetik. Vanilla, satu berkas, font sistem, SVG yang digambar tangan.
- **Tanpa fitur rekaan.** Setiap tombol terhubung ke endpoint nyata yang berfungsi. Kapabilitas
  yang bergantung pada extra opsional tetap mengatakannya.
- **Tanpa perubahan backend diam-diam** selain endpoint docs yang aditif, hanya-baca, dan berbasis daftar izin
  (`/api/docs`) untuk menjalankan pembaca Bantuan.
- **Input bahasa teks bebas tetap berupa teks bebas** (sudah dicatat di OPEN_QUESTIONS);
  desain ulang tidak mengarang dropdown yang tidak dapat didukung backend.

---

### 7. Status

`0.05` kini menjadi **cabang bawaan** repositori (mainline); jalur sebelumnya (0.04
dan sebelumnya) tetap ada di riwayat git. Paritas fungsional dipertahankan (ID elemen
yang sama, sambungan yang sama); perubahannya adalah segala sesuatu *di sekitar* mesin itu. Bawaannya menyertakan
**dua** antarmuka — Console (`/`) dan Desk (`/desk`) — yang dibandingkan di
[`DESIGN.md`](DESIGN.md).


---

## Dua antarmuka, satu argumen — "Console" vs "Desk"

> Anda meminta argumen yang *kontradiktif*: bukan pembelaan atas desain ulang 0.05, melainkan
> argumen jujur bahwa itu mungkin antarmuka yang **salah** untuk aplikasi ini — beserta
> alternatif konkret untuk mengujinya. Dokumen ini adalah argumen tersebut. Kedua
> antarmuka disertakan berdampingan sehingga Anda dapat menjalankan keduanya pada data yang sama dan menilai
> sendiri.

---

### 0. Pertama, kembali berpijak pada apa sebenarnya aplikasi ini

Sebelum memperdebatkan elemen antarmuka, hal-hal yang tidak dapat ditawar (dari `ETHICS.md`,
`DESIGN.md`, Piagam München):

- **Satu pengguna, satu mesin, hanya loopback, offline-first.** Tanpa akun, tanpa cloud,
  tanpa telemetri. Sering dijalankan di Qubes AppVM dengan qube jaringan *dilepas*.
- **Pencari kebenaran yang tidak menyukai komputer.** Seorang penyelidik /
  jurnalis yang tugasnya adalah *memahami kenyataan dan menyampaikannya secara kredibel*.
- **Produknya adalah kepercayaan.** Asal-usul, verifikasi sumber, "diukur, bukan
  diperkirakan," bukti perusakan. Piagam München (kebenaran, verifikasi sumber, lindungi
  narasumber, lawan propaganda) adalah tulang punggungnya.
- **Kedaulatan sebagai estetika.** Alat ini harus *terasa* milik penggunanya,
  bukan milik sebuah platform.

Antarmuka apa pun harus dinilai terhadap *hal-hal itu*, bukan terhadap "apakah ini terlihat seperti
produk SaaS tahun 2025."

---

### 1. Daftar dakwaan terhadap "Console" (desain ulang 0.05)

Menyusun versi terkuat dari argumen bahwa 0.05 adalah arah yang salah:

1. **Ia membalut alat yang berdaulat dengan pakaian kapitalisme pengawasan.** Bilah samping kiri
   yang persisten, pil status, palet perintah, laci kustomisasi dengan delapan
   tema — inilah tata bahasa visual Slack, Linear, Notion: *SaaS cloud*. Bagi
   pengguna yang tidak memercayai Big Tech dan menangani liputan sensitif, tata bahasa itu dapat
   terbaca sebagai "satu lagi aplikasi yang mengawasi saya," merongrong satu hal yang paling penting
   di sini: kepercayaan. Tampilannya melawan nilai-nilainya.

2. **Ia dioptimalkan untuk demo, bukan untuk pekerjaan.** Ringkasan tugasnya mencakup "membuat
   jurnalis berkata *boleh saya punya juga?*" — reaksi lima detik dari balik bahu.
   Mendesain untuk itu menarik ke arah kemilau dasbor (gradien, hitungan beranimasi,
   kebun binatang tema) dan menjauh dari kenyataan investigasi yang tenang, sarat membaca, dan berpusat pada
   dokumen. Alat terbaik untuk kerja mendalam (penyunting teks, buku catatan) itu
   *polos*. Console mungkin mengesankan namun dangkal.

3. **Kustomisasi adalah pajak yang menyamar sebagai hadiah.** Delapan tema, contoh warna aksen,
   kepadatan, skala font, penyembunyian per modul. Bagi *Amara* (yang tidak menyukai komputer) setiap
   satu dari hal ini adalah keputusan yang tidak ia inginkan dan cara untuk salah mengonfigurasi alatnya.
   "Sangat dapat disesuaikan" melayani kata-kata ringkasan tugas dan gagasan *perancang* tentang
   kemurahan hati — tetapi alat yang sungguh sederhana itu **beropini**: ia membuat keputusan yang tepat
   agar pengguna tidak perlu. Pilihan adalah beban kognitif.

4. **Arsitektur informasinya masih milik perangkat lunak, bukan milik pengguna.** Console
   mengganti nama dan mengelompokkan ulang tab, tetapi menunya tetap daftar *modul*
   (Pencarian, Sumber, Wawasan, Pasar, Kustodi…). Amara tidak berpikir dalam modul;
   ia berpikir dalam **kasus**: "Saya sedang mengejar liputan ini — kumpulkan, baca, hubungkan, buktikan,
   terbitkan." Baik 0.04 maupun 0.05 membuat pengguna menerjemahkan *pekerjaannya* ke dalam *fitur*
   aplikasi. Navigasi persisten berisi sembilan tujuan adalah peta basis kode.

5. **Elemen antarmuka bersaing dengan konten.** Bilah samping tetap + bilah atas secara permanen menghabiskan
   ~250px dan sebuah pita horizontal untuk *navigasi yang dipakai pengguna selama dua detik per
   sesi*. Hal yang benar-benar mereka lakukan — membaca artikel, memindai hasil, membandingkan
   diff — mendapat sisa-sisanya. Investigasi adalah membaca; Console kurang melayani
   kegiatan membaca.

6. **"Wow"-nya dipinjam, bukan diperoleh.** Palet dan tema adalah *syarat minimum*
   di aplikasi modern — mengesankan justru karena sudah akrab. Fitur yang sungguh
   membedakan, yang membuat orang berkata "saya belum pernah melihat itu", di sini adalah *substansinya*:
   deteksi perang suntingan Wikipedia secara offline, kustodi yang menunjukkan bukti perusakan, "setiap angka adalah
   COUNT(\*) yang nyata". Console menghias; ia tidak mendramatisasi apa yang sebenarnya unik.

Itu dakwaan yang serius. Ia layak mendapat alternatif nyata, bukan sanggahan.

---

### 2. Pembelaan untuk Console (agar argumennya adil)

- Navigasi persisten itu **mudah ditemukan**: tidak ada yang tersembunyi, yang penting bagi
  pemula yang belum tahu apa yang dapat dilakukan alat ini. Model hub-and-spoke menyembunyikan
  kemampuan di balik satu klik dan tebakan.
- Kustomisasi bersifat **opt-out**: bawaannya waras; pengguna yang mengabaikan laci
  tidak kehilangan apa pun. Dan pemakaian tema sungguh membantu kenyataan mata lelah/larut malam dalam
  pekerjaan ini, serta aksesibilitas (kontras tinggi, ukuran teks) bagi pengguna *nyata*.
- "Tata bahasa SaaS" juga sekadar **konvensi kegunaan saat ini** — orang tahu cara
  memakainya sejak hari pertama. Kebaruan demi kebaruan punya pajaknya sendiri.
- Ia tetap **100% offline dan tanpa dependensi**. Tata bahasanya dipinjam;
  substansinya (tanpa jaringan, tanpa telemetri) tidak.

Kedua posisi itu sah. Cara menyelesaikannya bukan dengan berdebat lebih lama — melainkan
**membangun antitesisnya dan memakai keduanya**.

---

### 3. Antitesisnya: "Desk"

Jika Console adalah **konsol operasi yang luas** (semuanya selalu sejauh satu klik,
sefleksibel mungkin, tata bahasa aplikasi modern), maka **Desk** adalah tesis kebalikannya:

> **Meja seorang penyelidik: tenang, beropini, mengutamakan konten, dan dibingkai oleh tugas.
> Nyaris tanpa elemen antarmuka. Satu pekerjaan dalam satu waktu. Antarmuka menyingkir dari jalan kegiatan membaca
> dan berpikir.**

Komitmen konkret di mana Desk dengan sengaja *tidak sependapat* dengan Console:

| Dimensi | Console (tesis) | Desk (antitesis) |
|---|---|---|
| Navigasi | Bilah samping kiri yang persisten (selalu terlihat) | **Tanpa navigasi persisten.** Navigasi tersedia *sesuai permintaan* — beranda yang tenang, lapisan "Pergi ke…", dan ⌘K. Elemen antarmuka muncul hanya saat dipanggil. |
| Titik masuk | Dasbor status | **Beranda yang dibingkai oleh pekerjaan:** "Apa yang sedang Anda kerjakan?" → Kumpulkan · Temukan & baca · Hubungkan · Verifikasi & bagikan. Dibingkai oleh tugas pengguna, bukan oleh modul aplikasi. |
| Kustomisasi | 8 tema, aksen, kepadatan, font, sakelar modul | **Hanya dua tema** (Paper / Ink), tanpa kenop. Beropini. Alat yang memutuskan agar Anda tidak perlu. |
| Estetika | Konsol aplikasi modern (sans, pil, gradien) | **Editorial / cetak:** judul serif, kehangatan kertas, margin lapang, lebar baris yang nyaman dibaca. Terasa seperti ruang redaksi, bukan SaaS. |
| Apa yang mendapat ruang | Navigasi + status, lalu konten | **Konten.** Satu kolom baca di tengah; tabel dan pembaca artikel mendapat ruang. |
| Sinyal kepercayaan | Pil status | Baris yang persisten dan tenang **"Lokal · Offline · Tidak ada yang meninggalkan mesin ini"** — kedaulatan dinyatakan, bukan disiratkan. |
| Reaksi demo | "Apik!" | "…oh, ini *tenang*. Dan semuanya milik saya." Jenis wow yang lebih lambat dan lebih dalam. |

Apa yang **dipertahankan** Desk (karena itulah inti aplikasi, bukan elemen antarmuka): setiap fitur
dan setiap endpoint yang berfungsi. Desk dan Console berbagi mesin yang persis sama dan
panel konten yang sama — keduanya *hanya* berbeda dalam cangkang, model navigasi, pembingkaian arsitektur informasi,
dan estetika. Itu disengaja: hal ini menjaga eksperimen tetap terkendali, sehingga yang Anda
bandingkan adalah **filosofinya**, bukan mana yang kebetulan saya sambungkan dengan lebih cermat.

---

### 4. Cara menilai keduanya (rubrik)

Nilai masing-masing terhadap nilai-nilainya — bukan terhadap naluri Anda tentang "mana yang terlihat lebih bagus":

1. **Kepercayaan** — mana yang *terasa* milik Anda dan tidak akan mengkhianati Anda?
2. **Ketenangan vs kapabilitas** — mana yang membiarkan Anda berpikir? mana yang membuat kemampuan mudah ditemukan?
3. **Jalur pemula** — lepaskan *Amara* tanpa persiapan: mana yang membawanya ke hasil lebih cepat, dengan
   lebih sedikit rasa takut?
4. **Jalur pengguna mahir** — *Daniel* di papan ketik: mana yang menyingkir dari jalannya?
5. **Membaca** — buka artikel panjang / diff Wikipedia di masing-masing. Mana tempat yang lebih baik
   untuk *membaca*?
6. **Uji 5 detik** — tunjukkan masing-masing kepada rekan. Mana yang memancing "boleh saya punya juga?" —
   dan apakah itu reaksi yang sebenarnya ingin Anda optimalkan?
7. **Kecocokan dengan etos** — mana yang Anda percayai untuk dijalankan dengan jaringan dilepas di
   brankas Qubes?

---

### 5. Prediksi kelebihan / kekurangan (taruhan jujur saya, untuk diuji)

**Console** — *Kelebihan:* mudah ditemukan, konvensional, fleksibel, kenop aksesibilitas, kilau
demo. *Kekurangan:* berat elemen antarmuka, beban keputusan, nuansa SaaS generik yang dapat mengikis kepercayaan,
arsitektur informasi masih berpusat pada modul.

**Desk** — *Kelebihan:* tenang, mengutamakan konten/membaca, beropini (tanpa pajak konfigurasi),
titik masuk yang dibingkai oleh tugas, estetika yang *memperkuat* kedaulatan dan kepercayaan. *Kekurangan:*
kemampuan berada sejauh satu panggilan (satu klik/tombol), lebih sedikit kenop aksesibilitas, kurang
"mengesankan" secara langsung, kebaruan menuntut sedikit biaya belajar.

---

### 6. Rekomendasi saya (sintesis — sementara, menunggu pengujian Anda)

Saya memperkirakan jawaban yang tepat adalah **bukan Console murni maupun Desk murni**, melainkan sintesis
yang bersandar pada *kecocokan nilai* Desk dan *kemudahan ditemukan* Console:

- **Adopsi beranda Desk yang dibingkai oleh tugas dan ketenangan editorialnya** sebagai suasana bawaan. Pembingkaian
  pekerjaan ("kumpulkan / baca / hubungkan / verifikasi") adalah satu-satunya perbaikan terbesar atas kritik
  "arsitektur informasi adalah basis kode".
- **Adopsi pengekangan Desk dalam kustomisasi:** sertakan dua tema yang sangat baik
  (Paper/Ink) + kontrol ukuran teks untuk aksesibilitas, dan **pangkas** keberlimpahan aksen /
  kepadatan / penyembunyian modul. Beropini mengalahkan dapat dikonfigurasi di sini.
- **Pertahankan navigasi yang *tenang dan dapat dilipat* dari Console** demi kemudahan ditemukan — tetapi
  terlipat secara bawaan, sehingga konten memimpin dan navigasi ada saat dibutuhkan.
- **Pertahankan ⌘K** (melayani pemula maupun pengguna mahir dan sungguh berguna).
- **Dramatisasi substansinya, bukan elemen antarmukanya:** jadikan kustodi, Wikipedia offline, dan
  "hitungan nyata" sebagai pahlawan visual — itulah wow yang diperoleh.
- **Kedepankan baris kepercayaan di mana-mana** ("tidak ada yang meninggalkan mesin ini"). Itulah
  mereknya.

Tetapi itu hipotesis. Jalankan keduanya, nilai terhadap §4, dan beri tahu saya di mana kenyataan
menyimpang dari taruhan saya — lalu saya akan meleburkan putusannya ke dalam satu 0.06.

> **PUTUSAN AKHIR (pemelihara, 2026-06-10, setelah pemakaian langsung):** dialektikanya
> selesai — **Desk dipensiunkan sepenuhnya. Satu antarmuka: Console** (`/`).
> Dua ikon lebih banyak membingungkan daripada membantu; perangkat alat Desk yang dikurangi membuat
> fitur yang sudah dikirim (Peta temporal, Agenda) tampak tersesat; dan Console sudah
> beradaptasi dengan mulus terhadap ukuran jendela (bilah samping menyusut menjadi rel ikon). Berkas
> `desk.html` telah dihapus (ia tersimpan di riwayat git); `/desk` kini
> dialihkan ke `/`. Gagasan terbaik Desk — beranda yang dibingkai oleh tugas, ⌘K, ketenangan
> editorial — sebaiknya dilebur ke dalam Console seiring waktu, sesuai §6 di atas.

---

### 7. Menjalankan keduanya sekaligus

Kedua antarmuka dilayani oleh backend lokal yang sama atas data yang sama:

- **Console** → `http://127.0.0.1:8000/`  (bawaan)
- **Desk** → `http://127.0.0.1:8000/desk`

Installer membuat **dua ikon desktop** — *Open Omniscience* (Console) dan
*Open Omniscience — Desk* — sehingga Anda dapat meluncurkan salah satunya, atau membuka kedua jendela bersamaan
dan membandingkannya tab demi tab pada data yang identik. Pilih pemenang (atau minta
sintesisnya) dan kita kembali menjadi satu di 0.06.


---

## Strategi analisis konten — tautan, keseragaman, dan sumber asli

> Strategi konkret dan bertahap untuk visi dalam [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md):
> memakai **tautan** artikel untuk menghimpun apa saja yang membicarakan hal yang sama, memunculkan
> **keseragaman** media, dan menelusuri informasi kembali ke **sumber aslinya** — sambil
> menjaga **pengguna tetap memegang kendali**, analisis tetap **transparan dan lokal**, dan tidak pernah
> membiarkan alat ini menjadi penentu kebenaran (Piagam München). Sumber terbuka dan
> offline di sepanjang prosesnya.

---

### 0. Di mana kita berada (status jujur)

Deteksi tautan artikel **sudah berkerangka tetapi belum disambungkan**:

- ✅ **`src/services/link_analyzer/extractor.py`** (`LinkExtractor`) — mengekstrak tautan
  dari HTML, menormalkan URL, melacak teks jangkar + posisi, mengklasifikasikan *jenis* tautan
  (internal/eksternal/gambar/…), dan menghasilkan statistik tautan. ~500 baris, berbentuk unit.
- ✅ **Skema DB** — `ArticleLink` (url, normalized_url, link_text, position,
  link_type, **classification** = source/reference/ad/social/navigation,
  `external_source_id`, `source_article_id`, is_working, http_status…),
  `ExternalSource`, dan `LinkClassificationRule`. Relasinya sudah ada
  (`Article.links`, `ExternalSource.links`).
- ✅ **Dipanggil saat penyerapan** *(selesai — P0)* — `src/ingest/pipeline.py:_maybe_index_links`
  mengisi `article_links` dengan tautan keluar **eksternal** (upaya terbaik, gagal terbuka;
  internal/gambar/iklan/sosial/pelacak dikecualikan sesuai `ROADMAP.md`; dihapus duplikatnya + dibatasi).
- ✅ **API** *(selesai — P1)* — `src/api/link_analysis.py` (`/api/links`): `stats`,
  `top-cited` (berdasarkan url|domain, dalam jendela waktu), `articles-by-link` (berdasarkan url|domain). Hanya
  hitungan; tidak ada yang diberi skor atau dinilai.
- ❌ **Belum ada UI** — belum ada tampilan Wawasan atas graf tautan (P2, di bawah).

Jadi P0/P1 sudah tersambung; pekerjaan yang tersisa adalah UI dan analisis yang lebih dalam (P3/P4).

---

### 1. Gagasan inti: tautan adalah graf sitasi

Perlakukan setiap artikel sebagai simpul dan setiap tautan keluar sebagai sisi berarah ke sebuah URL (dan
ke domainnya). Graf itu menjawab persis apa yang Anda tanyakan:

- **"Himpun semua artikel yang membicarakan tautan yang sama."** = kelompokkan artikel menurut
  URL eksternal yang mereka kutip → **derajat masuk** URL tersebut adalah "berapa banyak artikel saya yang menunjuk
  ke sini." Derajat masuk tinggi = sebuah **hub**: sering kali dokumen primer, berita kantor berita, atau
  rujukan yang banyak dibicarakan.
- **"Temukan tren melalui tautan internal."** = amati derajat masuk dari waktu ke waktu; URL atau
  domain yang sitasinya melonjak adalah *tren* yang berpijak pada apa yang benar-benar dikutip para reporter,
  bukan sekadar frekuensi kata kunci.
- **"Telusuri sumber asli / sumber primer."** = di dalam klaster artikel tentang satu
  liputan, sumber aslinya adalah simpul yang **ditautkan** oleh yang lain, dan/atau yang paling awal, dan/atau
  yang mengutip **dokumen primer** (pengadilan/pemerintah/dataset). Tautan + stempel waktu + atribusi kantor
  berita melakukan triangulasi terhadapnya.

Inilah *analisis ko-sitasi* — murah, transparan, dan dapat dijelaskan. Tanpa kotak hitam.

---

### 2. Strategi bertahap (masing-masing dapat dikirim secara mandiri)

#### P0 — Sambungkan extractor ke penyerapan (membuat grafnya ada)
- Panggil `LinkExtractor` selama penyerapan pada HTML yang diambil; simpan tautan keluar
  **eksternal** ke `article_links` (lewati navigasi internal, iklan, dan — sesuai
  `ROADMAP.md` — tautan gambar/biner). Simpan normalized_url + teks jangkar + jenis.
- Petakan domain setiap tautan eksternal ke `Source`/`ExternalSource` yang dikenal bila
  memungkinkan (sehingga "siapa mengutip siapa" dapat diringkas ke tingkat media dan **pemiliknya**).
- Murah, deterministik, offline. Tidak ada yang diambil di luar apa yang sudah diambil oleh penyerapan.

#### P1 — Agregasi + API (menjawab pertanyaan pengguna)
Endpoint hanya-baca atas graf:
- **`top-cited`** — URL/domain yang paling banyak dikutip dalam suatu jendela waktu (sinyal tren).
- **`articles-by-link`** — untuk URL/domain tertentu, setiap artikel di korpus yang mengutipnya
  ("himpun semua artikel yang membicarakan tautan yang sama").
- **`link-graph`** — simpul/sisi untuk suatu topik atau jendela waktu, untuk visualisasi.
- **`co-citation`** — artikel yang mengutip sumber eksternal yang *sama* (klaster kandidat
  "liputan yang sama"), dengan hitungan tumpang-tindih.

#### P2 — UI: tampilan "Tautan & sumber" di Wawasan
- Daftar berperingkat **tautan/domain yang paling banyak dikutip** (klik → semua artikel yang mengutip).
- **Graf sitasi** kecil yang dapat diperbesar (memakai ulang pendekatan SVG yang sudah dipakai untuk
  peta Wawasan — tanpa dependensi baru).
- Selalu menampilkan **ukuran sampel** ("dikutip oleh 14 artikel Anda") — diukur, bukan
  ditebak. Pengguna mengeklik, menjelajah, memutuskan.

#### P3 — Garis keturunan sumber asli
Untuk klaster artikel tentang satu liputan, tampilkan **garis keturunan**, diperingkat berdasarkan sinyal
(masing-masing ditampilkan, tidak ada yang menentukan sendiri):
- derajat masuk (siapa yang ditautkan oleh yang lain),
- stempel waktu publikasi paling awal,
- atribusi kantor berita (AFP/Reuters/AP — kita sudah memberi tag `wire-agency`),
- keberadaan tautan **dokumen primer** (pemerintah/pengadilan/dataset/pracetak).
Keluaran: "dokumen primer → laporan pertama → gema," sebagai rantai yang dibaca pengguna.

#### P4 — Keseragaman & gema (terkait dengan konsentrasi media)
- **Deteksi hampir-duplikat** (MinHash/SimHash yang murah) untuk menandai teks sindikasi/salinan
  lintas media — dibangun di atas `src/ingestor/duplicate_detector.py`.
- **Skor gema**: klaster di mana banyak media mengutip **satu** sumber (atau saling mengutip dalam
  lingkaran sempit) dan hanya menambah sedikit tautan orisinal = gema tinggi. Sitasi sumber primer yang
  beragam = peliputan independen.
- **Lapisan konsentrasi**: bobotkan gema menurut **kepemilikan** — jika klaster yang menggema terpetakan
  ke satu pemilik/blok (kasus "~7 miliarder memiliki ~90%"), munculkan hal itu. Memerlukan
  graf kepemilikan (Wikidata P127/P749 + manual), sesuai `ROADMAP.md`.

---

### 3. Menjaga pengguna tetap memegang kendali (tidak dapat ditawar)

- **Munculkan, jangan pernah tekan.** Skor gema/garis keturunan *ditampilkan dan dapat diurutkan*; alat ini
  tidak pernah menyembunyikan atau otomatis menurunkan peringkat suatu sumber. Penurunan bobot apa pun adalah kontrol pengguna
  yang eksplisit dan dapat dibalik, **nonaktif secara bawaan**.
- **Tanpa label kebenaran.** "Paling awal yang kami lihat" / "paling banyak dikutip" ≠ "benar." Kami menampilkan struktur
  (siapa yang mengatakannya pertama, siapa mengutip siapa, siapa memiliki siapa) lalu berhenti.
- **Semuanya dapat dijelaskan & lokal.** Setiap angka dapat ditelusuri ke baris yang dapat diperiksa pengguna;
  tanpa panggilan eksternal, tanpa kotak hitam ML (hashing + penghitungan + derajat graf).
- **Sumber terbuka & dapat diaudit.** Fungsi murni, dapat diuji per unit, aturan klasifikasi dalam bentuk
  data (`LinkClassificationRule`) yang dapat disunting pengguna.

---

### 4. Risiko & batasan yang jujur

- Ekstraksi tautan hanya sebaik HTML yang diambil (paywall/JS membatasinya).
- Konvensi jangkar/sitasi bervariasi; "menurut X" tanpa tautan akan terlewat (proses
  NLP di kemudian hari dapat membantu, tetapi dimulai dengan sederhana).
- Data kepemilikan tidak lengkap dan sudah usang — harus dapat diatribusikan, bukan ditebak.
- Hampir-duplikat pada skala korpus memerlukan kehati-hatian agar tetap murah di satu mesin (hashing, perbandingan
  dalam jendela), bukan perbandingan teks lengkap O(n²).

### 5. Commit pertama yang disarankan

Sambungkan **P0** (mengisi `article_links` saat penyerapan) di balik sebuah pengaturan, tambahkan endpoint **P1
`articles-by-link`** dan **`top-cited`**, serta daftar Wawasan yang minimal. Itu
saja sudah menghadirkan "himpun semua artikel yang mengutip tautan yang sama" dan tren berbasis
sitasi — irisan terkecil dari nilai nyata, sepenuhnya selaras dengan etosnya.
