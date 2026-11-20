<!-- id: Translation of docs/ETHICS.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 50 of 50 headings. Corrections are welcome as a pull request. -->

# Pedoman Etika untuk Open Omniscience

> **Status (diperiksa ulang 2026-10-08):** perangkat lunak ini adalah **alfa** yang berfungsi dan teruji
> (`v0.5.0` — lihat README repositori untuk apa yang sudah berfungsi saat ini; kata-kata era 0.0.9 di bawah
> dipertahankan sebagai catatan sejarah tentang kapan pedoman ini mulai berlaku). Rilis-rilis awal memuat
> spanduk "tidak berfungsi" di sini; hal itu sudah tidak benar lagi dan telah dihapus —
> pedoman ini **berlaku sekarang**, bukan sekadar rujukan untuk masa depan.
> *Catatan sejarah:* rilis konsep paling awal (sebelum 0.0.4) berangkat dari
> penyalin situs web HTTrack; basis kode saat ini adalah penulisan ulang total dan
> tidak berbagi kode apa pun dengannya.

Dokumen ini menguraikan **prinsip etika, persyaratan kepatuhan, dan praktik terbaik** untuk menggunakan dan berkontribusi pada Open Omniscience. Kepatuhan terhadap pedoman ini **wajib** bagi semua pengguna dan pengembang.

Open Omniscience selaras dengan **Piagam München** (Munich Charter), seperangkat prinsip dasar bagi jurnalis yang diadopsi pada tahun 1971. Prinsip-prinsip ini diintegrasikan di bawah untuk memandu penggunaan platform ini secara etis.

---

## 📜 Piagam München: Deklarasi Kewajiban dan Hak

### Pembukaan
Hak atas informasi, atas kebebasan berekspresi dan mengkritik adalah salah satu hak fundamental umat manusia. Semua hak dan kewajiban mereka yang menggunakan Open Omniscience bersumber dari hak publik untuk mendapatkan informasi tentang peristiwa dan pendapat. Tanggung jawab pengguna terhadap publik melampaui tanggung jawab lainnya, khususnya terhadap pemberi kerja dan otoritas publik. Misi informasi dengan sendirinya mencakup batasan-batasan yang harus secara sukarela diterapkan pengguna pada diri mereka sendiri. Inilah tujuan deklarasi kewajiban yang dirumuskan di bawah.

Seorang pengguna Open Omniscience hanya dapat menghormati kewajiban-kewajiban ini dalam menjalankan penggunaannya apabila kondisi independensi dan martabat profesional benar-benar ada. Inilah tujuan deklarasi hak berikut.

---

### 📋 Deklarasi Kewajiban
Kewajiban pokok pengguna Open Omniscience yang terlibat dalam mengumpulkan, menyunting, dan menganalisis informasi adalah:

1. **Menghormati Kebenaran:**
   Menghormati kebenaran apa pun konsekuensinya bagi diri sendiri, karena hak publik untuk mengetahui kebenaran.

2. **Membela Kebebasan Informasi:**
   Membela kebebasan informasi, berkomentar, dan mengkritik.

3. **Memverifikasi Sumber:**
   Hanya melaporkan fakta yang asal-usulnya diketahui; tidak menyembunyikan informasi penting dan tidak mengubah teks maupun dokumen.

4. **Metode yang Jujur:**
   Tidak menggunakan metode yang tidak jujur untuk memperoleh informasi, foto, atau dokumen.

5. **Menghormati Privasi:**
   Membatasi diri pada penghormatan terhadap privasi.

6. **Mengoreksi Ketidakakuratan:**
   Meralat setiap informasi yang telah dipublikasikan yang ternyata tidak akurat.

7. **Kerahasiaan Profesional:**
   Menjaga kerahasiaan profesional dan tidak mengungkapkan sumber informasi yang diperoleh secara rahasia.

8. **Menghindari Pelanggaran Profesional:**
   Menganggap sebagai pelanggaran profesional berat:
   - Plagiarisme
   - Fitnah, pencemaran nama baik lisan maupun tertulis, dan tuduhan tanpa dasar
   - Penerimaan suap dalam bentuk apa pun sebagai imbalan atas publikasi maupun penyembunyian informasi

9. **Pemisahan dari Iklan/Propaganda:**
   Tidak pernah mencampuradukkan penggunaan Open Omniscience dengan kegiatan penjualan iklan atau propaganda, dan menolak setiap perintah langsung maupun tidak langsung dari pengiklan.

10. **Menolak Tekanan:**
    Menolak setiap tekanan dan hanya menerima perintah dari pihak yang bertanggung jawab yang selaras dengan penggunaan platform secara etis.

---

### 📜 Deklarasi Hak

Pengguna Open Omniscience menuntut:

1. **Akses Bebas terhadap Informasi:**
   Akses bebas ke semua sumber informasi, dan hak untuk menyelidiki secara bebas semua peristiwa yang memengaruhi kehidupan publik. Oleh karena itu, kerahasiaan urusan publik maupun pribadi hanya dapat diajukan kepada pengguna dalam kasus-kasus luar biasa dan dengan alasan yang dinyatakan secara jelas.

2. **Menolak Subordinasi yang Tidak Etis:**
   Hak untuk menolak tunduk pada apa pun yang bertentangan dengan kebijakan umum Open Omniscience, serta segala bentuk subordinasi yang tidak secara jelas tersirat dalam kebijakan ini.

3. **Hati Nurani dan Keyakinan:**
   Seorang pengguna tidak dapat dipaksa melakukan suatu tindakan atau menyatakan suatu pendapat yang bertentangan dengan keyakinan atau hati nuraninya.

4. **Transparansi dalam Pengambilan Keputusan:**
   Komunitas harus diberi tahu tentang semua keputusan penting yang dapat memengaruhi proyek. Komunitas setidaknya harus dimintai pendapat sebelum keputusan definitif diambil atas semua hal yang berkaitan dengan arah proyek.

5. **Kompensasi yang Adil dan Independensi:**
   Dengan memperhitungkan fungsi dan tanggung jawab mereka, kontributor berhak atas pengakuan dan kondisi yang menjamin keamanan material dan moral atas pekerjaan mereka, serta independensi ekonomi.

---

## 🌍 Prinsip Inti Open Omniscience

1. **Menghormati Ketentuan Sumber:** Selalu patuhi arahan `robots.txt` dan ketentuan layanan situs web yang di-scrape.
2. **Pembatasan Laju:** Jalur pengambilan tunggal (`EthicalFetcher`) memberlakukan interval
   permintaan minimum per host dan mengambil kunci per host sehingga hanya satu permintaan ke host
   tertentu yang berjalan pada satu waktu.
   - Bawaan: **1 permintaan per detik per host** — `min_interval_s` di
     `EthicalFetcher`, diatur dari variabel lingkungan `OO_FETCH_MIN_INTERVAL`.
   - Apabila `robots.txt` suatu host memublikasikan **`Crawl-delay`**, nilai itu dihormati:
     interval efektifnya adalah `max(min_interval, Crawl-delay)`.
   - (`rate_limit_ms` per sumber di `sources.yml` adalah sebuah kolom data, **tidak** terhubung ke
     interval fetcher; dua tuas di atas itulah yang benar-benar membatasi laju.)
3. **Transparansi:** Aktivitas pengambilan dicatat secara lokal untuk ditinjau sendiri oleh
   operator — putusan per sumber/umpan di `data/source_preflight.jsonl` dan
   `data/feed_preflight.jsonl`, hasil uji lapangan di `data/field_test.jsonl`, dan
   galat aplikasi di `data/app_errors.jsonl`. Semua ini tetap berada di mesin dan dibundel,
   **hanya saat diklik**, ke dalam **bundel debug** di Pengaturan → diagnostik — tidak pernah
   dikirim secara otomatis. (Tidak ada `audit/scrape_log.csv`; itu adalah rancangan awal
   yang digantikan oleh sikap lokal-dulu tanpa telemetri.)
4. **Minimisasi Data:** Hanya kumpulkan dan simpan data yang diperlukan untuk fungsi inti platform (URL, judul, konten, metadata).
5. **Penggunaan yang Tidak Berbahaya:** Open Omniscience tidak boleh digunakan untuk:
   - Spam atau pelecehan.
   - Kegiatan ilegal (misalnya peretasan, pelanggaran hak cipta).
   - Eksploitasi komersial tanpa izin.
6. **Identifikasi User-Agent:** Gunakan string User-Agent yang jelas dan dapat diidentifikasi. Bot
   mengirim `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`
   (pengambilan yang dilindungi/dirutekan lewat Tor mengirim UA peramban generik, agar tidak mencolok).
7. **Pembatasan per IP:** Hindari permintaan beruntun yang cepat dari satu IP. Hormati penggunaan wajar server.

---

## ✅ Daftar Periksa Kepatuhan

Sebelum melakukan scraping pada sumber baru, verifikasi hal-hal berikut:
- [ ] Domain tersebut **tidak** ada dalam [Daftar Jangan Di-scrape](#daftar-jangan-di-scrape).
- [ ] Berkas `robots.txt` mengizinkan scraping (periksa [https://{domain}/robots.txt](https://{domain}/robots.txt)).
- [ ] Sumber tersebut **tidak** memerlukan autentikasi atau melanggar paywall.
- [ ] Batas laju dikonfigurasi untuk menghindari **>1 permintaan per detik** secara bawaan (sesuaikan untuk domain yang sensitif).
- [ ] String User-Agent mengidentifikasi Open Omniscience (`OpenOmniscienceBot/{version}`).
- [x] Putusan pengambilan dicatat secara lokal (`data/*_preflight.jsonl`), ditampilkan
  saat diklik melalui bundel debug di Pengaturan — tidak pernah dikirim secara otomatis.

---

## 🚫 Daftar Jangan Di-scrape

Daftar ini adalah **panduan bagi operator**, bukan daftar larangan yang ditegakkan secara mekanis: aplikasi
tidak menyertakan blokir yang ditanam dalam kode untuk domain-domain ini. Penjaga di tingkat kode adalah **robots.txt
gagal-tertutup** (fail-closed) dalam jalur tunggal `EthicalFetcher` — sumber yang `robots.txt`-nya tidak dapat
diambil atau tidak secara jelas mengizinkan URL tersebut akan ditolak, bukan di-scrape. Operator tetap
harus menggunakan pertimbangan dan menghindari kategori di bawah saat menambahkan sumber:

### Konten Berbayar (Paywall)


### Platform Media Sosial


### Data Pribadi atau Sensitif
- Basis data pemerintah (misalnya `*.gov`, `*.mil` kecuali secara eksplisit publik)
- Rekam medis (misalnya `*.health`, `*.medical`)
- Catatan keuangan (misalnya `*.bank`, `*.finance` kecuali publik)
- Repositori data pribadi (misalnya `*.personal`, `*.private`)

### Pembatasan Teknis
- Domain dengan **pembatasan laju yang agresif** (misalnya `github.com`, `stackoverflow.com`).
- Domain yang **memblokir scraper** (misalnya situs yang dilindungi `cloudflare.com` tanpa jalan pintas).
- **Sumber khusus API** (misalnya `twitter.com/api`, `reddit.com/api` - gunakan API resmi sebagai gantinya).

> **Catatan:** Daftar ini tidak lengkap. Pengguna harus menjalankan **uji tuntas** dan **penilaian kritis** saat menambahkan sumber baru. Jika ragu, **jangan lakukan scraping**. 

---

## 📊 Audit dan Akuntabilitas

Aktivitas pengambilan dicatat **secara lokal**, untuk ditinjau sendiri oleh operator, dan dibagikan
**hanya saat diklik** — tidak pernah dikirim secara otomatis (tanpa telemetri; lokal-dulu sejak rancangan). Mekanisme
yang sebenarnya (rancangan awal `audit/scrape_log.csv` digantikan oleh ini):

- **Putusan preflight** — hasil keterjangkauan/robots/transport per sumber dan per umpan
  ditambahkan ke `data/source_preflight.jsonl` dan
  `data/feed_preflight.jsonl` (setiap baris: stempel waktu, sumber/domain, putusan yang
  memperhitungkan transport, dan alasan yang jujur). Data ini menggerakkan UX "Coba lagi umpan yang gagal" dan
  putusan per umpan di Indeks/pasar.
- **Hasil uji lapangan** — saat mode uji lapangan aktif, latihan terhadap permukaan pengambilan
  ditulis apa adanya ke `data/field_test.jsonl`.
- **Galat aplikasi** — dibatasi ke `data/app_errors.jsonl` (baris terbaru yang disimpan).

### Berbagi untuk dukungan

Tidak ada CSV/`errors.log` yang diunggah secara otomatis. Operator dapat membuat satu **bundel debug**
(Pengaturan → diagnostik) yang menggabungkan log JSONL di atas beserta diagnostik kata kunci/jaringan;
bundel itu ditulis ke disk dan dibagikan hanya melalui tindakan eksplisit operator.
Inilah protokol pemelihara: klik-telusuri aplikasi, lalu serahkan bundelnya.

---

## 🔒 Privasi dan Perlindungan Data

- **Tanpa Pelacakan Pengguna:** Open Omniscience **tidak** mengumpulkan atau menyimpan:
  - IP pengguna
  - Riwayat pencarian
  - Data pribadi
- **Hanya Lokal:** Semua data tetap berada di mesin pengguna. Tanpa ketergantungan pada cloud secara bawaan.
- **Enkripsi saat tersimpan (aktif secara bawaan):** Korpus baru dibuat dalam keadaan **terenkripsi** dengan
  SQLCipher, dilindungi oleh frasa sandi yang dipilih pengguna saat peluncuran pertama. Menjalankan
  basis data **teks polos** (plaintext) adalah pilihan keluar eksplisit yang memerlukan konfirmasi tertulis atas
  risiko yang dinyatakan. **Tidak ada pemulihan** untuk frasa sandi yang terlupa (korpus dapat
  disusun kembali dengan scraping ulang, sehingga tidak ditambahkan kunci pemulihan / permukaan dekripsi kedua).
  Model ancamannya adalah mesin yang disita atau disalin dalam keadaan **mati** — bukan sesi yang
  sudah berjalan dan telah disusupi (lihat `SECURITY.md`).
- **Kepatuhan GDPR:** Jika melakukan scraping pada sumber yang berbasis di UE:
  - Anonimkan data pribadi (misalnya nama, email) dalam konten yang disimpan.
  - Hormati hak untuk dihapus (hapus data atas permintaan).

---

## 🌍 Pertimbangan Hukum

- **Hak Cipta:** Hormati undang-undang hak cipta. Hanya lakukan scraping dan simpan konten untuk:
  - Analisis **pribadi, non-komersial**.
  - **Penggunaan wajar** (fair use) (misalnya kritik, komentar, penelitian).
  - **Tujuan transformatif** (misalnya agregasi untuk jurnalisme investigasi).
- **Kepatuhan GDPR:** Jika memproses data warga UE:
  - Minimalkan pengumpulan data pribadi.
  - Sediakan cara bagi individu untuk meminta penghapusan data mereka.
- **Yurisdiksi:** Pengguna bertanggung jawab untuk mematuhi hukum di yurisdiksi mereka, termasuk:
  - **Computer Fraud and Abuse Act (CFAA)** (AS)
  - **General Data Protection Regulation (GDPR)** (UE)
  - **Undang-Undang Hak Cipta** (berbagai negara)

---

## 🛡️ Pengamanan Teknis

Untuk mencegah penyalahgunaan dan memastikan scraping yang etis, Open Omniscience menerapkan pengamanan berikut:

1. **Pembatasan Laju:**
   - Bawaan: 1 permintaan per detik per host (`min_interval_s`, dari `OO_FETCH_MIN_INTERVAL`).
   - `Crawl-delay` robots suatu host dihormati bila lebih besar; satu permintaan per host pada satu waktu.

2. **Kepatuhan Robots.txt:**
   - Secara otomatis memeriksa `robots.txt` sebelum scraping.
   - Menghormati arahan `Disallow`.

3. **Identifikasi User-Agent:**
   - Mengirim `OpenOmniscienceBot/{version} (+https://github.com/ideotion/Open-Omniscience; ethical research crawler)`.
   - Pengambilan yang dilindungi (dirutekan lewat Tor) mengirim UA peramban generik agar tidak menonjol.

4. **Penanganan Galat:**
   - Mencoba ulang permintaan yang gagal dengan backoff eksponensial.
   - Mencatat semua galat untuk ditinjau.

5. **Deteksi Duplikat:**
   - Menggunakan kanonikalisasi URL dan hashing konten untuk menghindari scraping yang berulang.

6. **Jejak Audit:**
   - Mencatat semua aktivitas scraping demi transparansi dan akuntabilitas.

---

## 📐 Metrik yang jujur — tanpa skor rekaan

Kejujuran sejak konstruksi: aplikasi tidak pernah menyajikan **skor gabungan kepercayaan / kualitas /
kredibilitas**. Setiap sinyal yang dihitungnya membawa metode, catatan peringatan (caveat), dan
*n*-nya; kartu yang mencoba menyertakan skor campuran akan ditolak secara mekanis oleh skema
kartu. Kolom skor yang tidak aktif (`credibility_score`, `political_bias`) tetap
NULL dan tidak pernah diserialisasi ke respons API mana pun.

**Satu pengecualian yang disengaja dan sempit — `reliability_score`.** Kolom `1–10` per sumber ini
adalah **metadata provenans yang dinyatakan operator**: angka yang *Anda* (operator)
tetapkan per sumber melalui konfigurasi atau impor CSV. Nilai ini **tidak pernah dihitung, tidak pernah diberi nilai bawaan,
dan tidak pernah diturunkan dari data artikel** oleh aplikasi — nilai bawaan rekaan `=5`
sebelumnya telah dihapus (di-NULL-kan oleh migrasi `f4b5c6d7e8a9`). Karena ini adalah pernyataan
Anda sendiri (bukan putusan yang dibuat oleh alat), nilai ini ditampilkan dalam daftar sumber
dan diberi label **"ditetapkan operator, tidak dihitung"** di mana pun ia muncul; kartu ringkasan
tetap tidak pernah dapat menyajikannya sebagai skor. Sebuah invarian repositori
(`tests/test_repo_invariants.py::test_reliability_score_is_operator_set_never_computed`)
menjaganya tetap demikian, sehingga ia tidak dapat diam-diam berubah menjadi putusan kualitas yang dihitung.

---

## 📢 Melaporkan Pelanggaran

Jika Anda menemukan atau mencurigai penggunaan Open Omniscience yang tidak etis:
1. **Hentikan** aktivitas yang melanggar tersebut segera.
2. **Dokumentasikan** insidennya (misalnya tangkapan layar, log, stempel waktu).
3. **Laporkan** kepada pemelihara melalui:
   - [GitHub Issues](https://github.com/ideotion/Open-Omniscience/issues) (untuk laporan publik)
   - Email: `open-omniscience@ideotion.com` (untuk laporan sensitif)

---

## 📅 Tinjauan dan Pembaruan

Dokumen ini akan **ditinjau dan diperbarui secara berkala** untuk mencerminkan:
- Tantangan etika baru (misalnya konten buatan AI, deepfake).
- Persyaratan hukum (misalnya perubahan undang-undang hak cipta atau perlindungan data).
- Masukan komunitas (misalnya laporan penyalahgunaan atau saran perbaikan).

### Riwayat Versi
| Versi | Tanggal    | Perubahan                                                               |
|-------|------------|-------------------------------------------------------------------------|
| 1.0   | 2026-05-07 | Versi awal. Menambahkan Daftar Jangan Di-scrape, pencatatan audit, dan catatan GDPR. |
| 1.1   | 2026-05-07 | Menambahkan identifikasi User-Agent, pembatasan per IP, dan pengamanan teknis. |

---

## 📌 Praktik Terbaik bagi Kontributor

1. **Uji Secara Etis:**
   - Selalu uji scraping dalam skala kecil sebelum memperbesar skalanya.
   - Gunakan `localhost` atau lingkungan staging bila memungkinkan.

2. **Dokumentasikan Sumber:**
   - Tambahkan komentar di `sources.yml` yang menjelaskan mengapa suatu sumber dimasukkan/dikecualikan.
   - Catat setiap persyaratan scraping khusus (misalnya selector kustom).

3. **Hormati Permintaan Keluar:**
   - Jika suatu sumber meminta untuk dihapus, patuhi segera.
   - Tambahkan domain tersebut ke Daftar Jangan Di-scrape.

4. **Minimalkan Dampak:**
   - Lakukan scraping di luar jam sibuk bila memungkinkan.
   - Simpan respons dalam cache untuk menghindari permintaan berulang atas konten yang sama.

5. **Tetap Mutakhir:**
   - Periksa `robots.txt` secara berkala untuk melihat perubahan.
   - Pantau pembaruan hukum (misalnya undang-undang hak cipta baru).

---
**Ingat:** Scraping yang etis bukan sekadar kewajiban hukum—melainkan **tanggung jawab moral**. Dengan menggunakan Open Omniscience, Anda berkomitmen untuk menjunjung prinsip-prinsip ini.

---

# Kepatuhan, lisensi & pemberitahuan pihak ketiga

Pendamping hukum dan atribusi untuk prinsip-prinsip etika di atas.

**Di bagian ini:**
- [Panduan Kepatuhan GPLv3](#panduan-kepatuhan-gplv3)
- [Pemberitahuan dan Atribusi Pihak Ketiga](#pemberitahuan-dan-atribusi-pihak-ketiga)


---

## Panduan Kepatuhan GPLv3

Bagian ini menguraikan kepatuhan Open Omniscience terhadap GNU General
Public License Versi 3 (GPLv3). Bagian ini berlaku untuk perangkat lunak yang berfungsi sebagaimana dikirimkan.

---

### 📜 Lisensi Open Omniscience

**Lisensi:** GNU General Public License Versi 3 (GPLv3)  
**Hak Cipta:** © 2026 Ideotion  
**Berkas Lisensi:** [LICENSE](../LICENSE)

Open Omniscience sepenuhnya dilisensikan di bawah GPLv3, yang memberikan kepada pengguna
kebebasan-kebebasan berikut (perangkat lunak ini adalah pra-alfa yang berfungsi dan teruji — kebebasan ini berlaku sekarang):

1. **Kebebasan 0:** Kebebasan untuk menjalankan program untuk tujuan apa pun
2. **Kebebasan 1:** Kebebasan untuk mempelajari cara kerja program dan mengubahnya
3. **Kebebasan 2:** Kebebasan untuk mendistribusikan ulang salinan
4. **Kebebasan 3:** Kebebasan untuk mendistribusikan versi yang telah dimodifikasi

---

### ✅ Daftar Periksa Kepatuhan GPLv3

#### Untuk Proyek Open Omniscience

- [x] **Berkas Lisensi**: Teks lengkap GPLv3 disertakan dalam [LICENSE](../LICENSE)
- [x] **Ketersediaan Kode Sumber**: Semua kode sumber tersedia untuk publik di repositori ini
- [x] **Pemberitahuan Hak Cipta**: Modul sumber memuat pemberitahuan `Copyright (C) 2026 Ideotion`;
  [LICENSE](../LICENSE) proyek mengatur karya secara keseluruhan
- [x] **Header Lisensi**: Sebagian besar modul sumber memuat header bergaya SPDX `GPL-3.0-or-later`
  (beberapa penanda paket `__init__.py` yang kosong dan beberapa modul kecil tidak
  memuatnya). GPLv3 **tidak** mewajibkan header per berkas — berkas [LICENSE](../LICENSE)
  berlaku otoritatif untuk seluruh karya; pemberitahuan per modul adalah bentuk kesopanan, bukan klaim
  bahwa setiap berkas memuatnya
- [x] **Tanpa Pembatasan Tambahan**: Tidak ada pembatasan lebih lanjut di luar GPLv3 yang diberlakukan
- [x] **Versi yang Dimodifikasi**: Semua modifikasi memuat pemberitahuan yang mencolok (Bagian 5a)
- [x] **Informasi Instalasi**: Tidak berlaku (bukan Produk Pengguna sebagaimana didefinisikan dalam GPLv3)

---

### 📦 Kepatuhan Distribusi

#### Distribusi Kode Sumber

Saat mendistribusikan kode sumber Open Omniscience:

1. ✅ **Sertakan berkas LICENSE**: Teks lengkap lisensi GPLv3 harus disertakan
2. ✅ **Sertakan ETHICS.md**: Atribusi pihak ketiga harus disertakan
3. ✅ **Pertahankan Header**: Semua berkas sumber harus mempertahankan header GPLv3-nya
4. ✅ **Pertahankan Hak Cipta**: Semua pemberitahuan hak cipta harus dipertahankan
5. ✅ **Dokumentasikan Perubahan**: Setiap modifikasi harus didokumentasikan

#### Distribusi Biner

Saat mendistribusikan Open Omniscience dalam bentuk biner:

1. ✅ **Sertakan Kode Sumber**: Wajib menyediakan Sumber Terkait (Corresponding Source) (Bagian 6)
2. ✅ **Sertakan LICENSE**: Teks lengkap GPLv3 harus disertakan
3. ✅ **Sertakan ETHICS.md**: Atribusi pihak ketiga harus disertakan
4. ✅ **Dokumentasikan Perubahan**: Setiap modifikasi harus didokumentasikan
5. ✅ **Tanpa Pembatasan Tambahan**: Tidak boleh menambahkan pembatasan di luar GPLv3

#### Kepatuhan Produk Pengguna

Jika Open Omniscience didistribusikan sebagai bagian dari Produk Pengguna (perangkat konsumen):

1. ✅ **Informasi Instalasi**: Wajib menyediakan informasi untuk memasang versi yang dimodifikasi (Bagian 6)
2. ✅ **Ketersediaan Kode Sumber**: Wajib menyediakan Sumber Terkait
3. ✅ **Tanpa Tivoisasi**: Tidak boleh mencegah pengguna memasang versi yang dimodifikasi

**Catatan:** Open Omniscience sendiri bukan Produk Pengguna, tetapi jika Anda menanamkannya ke dalam salah satunya, persyaratan ini berlaku.

---

### 🔍 Langkah Verifikasi

#### Untuk Pengembang

1. **Periksa Header Lisensi**
   ```bash
   grep -r "GNU General Public License" src/ tests/ package/ scripts/
   ```

2. **Verifikasi Berkas LICENSE**
   ```bash
   head -5 LICENSE
   ```

3. **Periksa Berkas NOTICES**
   ```bash
   cat ETHICS.md
   ```

4. **Verifikasi Tidak Ada Kode Proprietary**
   ```bash
   # Check for any non-GPLv3 licensed code in active project
   find . -path "./.git" -prune -o -path "./archive" -prune -o -type f -print
   ```

#### Untuk Pengguna

1. **Periksa Lisensi**
   ```bash
   cat LICENSE | head -5
   ```

2. **Tinjau Atribusi**
   ```bash
   cat ETHICS.md
   ```

---

### 📝 Pertanyaan Umum tentang Kepatuhan

#### T: Bolehkah saya menggunakan Open Omniscience untuk tujuan komersial?
**J:** Ya! GPLv3 mengizinkan penggunaan komersial. Namun, setiap versi modifikasi yang Anda distribusikan juga harus dilisensikan di bawah GPLv3, dan Anda wajib menyediakan kode sumbernya.

#### T: Bolehkah saya menggunakan Open Omniscience dalam perangkat lunak proprietary?
**J:** Tidak. GPLv3 mewajibkan karya turunan juga dilisensikan di bawah GPLv3. Anda tidak dapat memasukkan Open Omniscience ke dalam aplikasi proprietary bersumber tertutup.

#### T: Apakah saya perlu merilis modifikasi saya?
**J:** Hanya jika Anda mendistribusikannya. Jika Anda memodifikasi Open Omniscience untuk penggunaan Anda sendiri dan tidak mendistribusikannya, Anda tidak perlu merilis modifikasi Anda.

#### T: Bagaimana dengan dependensi Python?
**J:** Dependensi Python (FastAPI, SQLAlchemy, dll.) adalah karya terpisah dengan lisensinya sendiri. Lisensi GPLv3 Open Omniscience tidak memengaruhinya. Lihat [ETHICS.md](ETHICS.md) untuk detailnya.

#### T: Bagaimana dengan data yang saya scrape?
**J:** Lisensi GPLv3 hanya berlaku untuk perangkat lunak Open Omniscience itu sendiri, bukan untuk data yang Anda kumpulkan. Anda bertanggung jawab untuk mematuhi hak cipta dan ketentuan layanan situs web yang Anda scrape.

---

### 📞 Melaporkan Masalah Kepatuhan

Jika Anda memiliki pertanyaan atau kekhawatiran tentang kepatuhan GPLv3:

- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience
- **GitHub Issues:** https://github.com/ideotion/Open-Omniscience/issues

---

### 📚 Sumber Daya

- [Teks Lengkap Lisensi GPLv3](../LICENSE)
- [Situs Web Resmi GNU GPLv3](https://www.gnu.org/licenses/gpl-3.0.html)
- [FAQ GNU GPLv3](https://www.gnu.org/licenses/gpl-faq.html)
- [Pemberitahuan Pihak Ketiga](ETHICS.md)

---

**Terakhir Diperbarui:** 2026-06-14


---

## Pemberitahuan dan Atribusi Pihak Ketiga

Bagian ini berisi pemberitahuan dan atribusi untuk perangkat lunak dan
pustaka pihak ketiga yang digunakan oleh Open Omniscience. (*Catatan sejarah:* rilis konsep
sebelum 0.0.4 berangkat dari HTTrack; basis kode saat ini adalah penulisan ulang total dan
tidak ada kode HTTrack yang tersisa.)

---

### 📦 Dependensi Python

Open Omniscience **menggunakan** paket-paket Python berikut, masing-masing di bawah
lisensinya sendiri. Daftar otoritatif yang bersumber tunggal adalah [`pyproject.toml`](../pyproject.toml);
jalankan `pip show <package>` (atau `pip-licenses`) untuk memastikan lisensi versi mana pun
yang terpasang. **Setiap dependensi adalah FOSS dan kompatibel dengan GPLv3** — itu adalah
persyaratan untuk dimasukkan (lihat invarian khusus-FOSS di `docs/DESIGN.md`).

**Inti (selalu terpasang):**

| Paket | Lisensi | Kegunaan |
|---------|---------|---------|
| FastAPI | MIT | Kerangka kerja API web |
| Uvicorn | BSD-3-Clause | Server ASGI |
| Jinja2 | BSD-3-Clause | Templating sisi server |
| SlowAPI | MIT | Pembatasan laju |
| Prometheus Client | Apache-2.0 | Endpoint metrik |
| SQLAlchemy | MIT | ORM basis data |
| Alembic | MIT | Migrasi skema |
| sqlcipher3 | Zlib/BSD-style | Enkripsi SQLCipher saat tersimpan |
| Requests | Apache-2.0 | Klien HTTP (fetcher etis) |
| httpx | BSD-3-Clause | Klien HTTP |
| BeautifulSoup4 | MIT | Parsing HTML |
| lxml | BSD-3-Clause | Parsing XML/HTML |
| feedparser | BSD-2-Clause | Parsing RSS/Atom |
| trafilatura | Apache-2.0 | Ekstraksi artikel |
| Pydantic | MIT | Validasi data |
| PyYAML | MIT | Parsing konfigurasi |
| Bleach | Apache-2.0 | Sanitasi HTML |
| bcrypt | Apache-2.0 | Primitif hashing kata sandi |
| defusedxml | PSF-2.0 | Pengerasan XML tak tepercaya (dump Wikipedia) |
| cryptography | Apache-2.0 OR BSD-3-Clause | Tanda tangan Ed25519 + pohon Merkle |
| Pillow | HPND (MIT-CMU) | EXIF / metadata gambar |
| python-dateutil | Apache-2.0 / BSD | Parsing tanggal |
| tenacity | Apache-2.0 | Coba ulang / backoff |
| cachetools | MIT | Cache dalam memori |
| orjson | Apache-2.0 OR MIT (dengan komponen MPL-2.0) | JSON cepat |
| psutil | BSD-3-Clause | Tanda vital perangkat keras |

**Ekstra opsional (dipasang sesuai kebutuhan):**

| Ekstra | Paket | Lisensi | Kegunaan |
|---|---|---|---|
| `analysis` | numpy, pandas, scipy, scikit-learn, statsmodels, networkx | BSD-3-Clause | Statistik / graf |
| `analysis` | nltk | Apache-2.0 | Tokenisasi |
| `analysis` | vaderSentiment | MIT | Sentimen berbasis leksikon (hanya bahasa Inggris) |
| `nlp` | spaCy | MIT | Pipeline NLP |
| `crypto` | python-gnupg | LGPL-3.0 | Integrasi GPG |
| `pqc` | pqcrypto | MIT | Tanda tangan pasca-kuantum (ML-DSA) |
| `timestamping` | opentimestamps | LGPL-3.0 | Stempel waktu yang ditambatkan ke Bitcoin |
| `compression` | zstandard, lz4 | BSD | Kompresi cadangan |

LLM lokal adalah biner **Ollama eksternal** (MIT), dijangkau melalui HTTP
loopback — tidak ada bobot model atau pustaka inferensi yang dibundel atau dikirimkan.

#### Catatan Kepatuhan

- Setiap dependensi adalah **karya terpisah** di bawah lisensinya sendiri; GPLv3 Open
  Omniscience tidak meluas kepadanya, dan lisensinya tidak membatasi
  Open Omniscience.
- Semua lisensi yang tercantum bersifat **permisif atau copyleft lemah dan kompatibel dengan GPLv3**
  (ekstra LGPL-3.0 `python-gnupg`/`opentimestamps`, dan komponen MPL-2.0
  dari `orjson`, masing-masing kompatibel dengan GPL-3.0). FOSS + kompatibilitas GPLv3 adalah
  persyaratan mutlak untuk dimasukkan.
- Pengguna harus mematuhi lisensi masing-masing dependensi; `pip show <pkg>`
  menampilkannya.

---

### 📄 Fon dan Ikon

| Sumber Daya | Lisensi | Sumber |
|----------|---------|--------|
| Ikon Proyek | MIT (asli) | Disertakan dalam proyek |
| Fon yang dibundel — Inter, Outfit, Manrope, JetBrains Mono, Source Serif 4, Cantarell | SIL Open Font License 1.1 | `src/static/fonts/` (masing-masing dengan `OFL-*.txt`-nya) |

### 📦 Data & aset yang dibundel

Aset non-kode ini disertakan (vendored) ke dalam repositori di bawah lisensinya sendiri.
Terdaftar di `configs/external_artifacts.yml` (kemutakhiran/atribusi dilacak di sana).

| Aset | Lisensi | Atribusi / catatan |
|-------|---------|---------------------|
| Fon (Inter · Outfit · Manrope · JetBrains Mono · Source Serif 4 · Cantarell) | SIL OFL 1.1 | `src/static/fonts/*.woff2`, teks lisensi di `src/static/fonts/OFL-*.txt` |
| Alpine.js v3.14.1 (galeri GUI) | MIT | Disertakan secara lokal, disematkan dengan sha256, tanpa CDN — `src/static/guis/vendor/alpine.min.js` |
| vaderSentiment 3.3.2 — tiga metode penganalisis yang diadaptasi untuk waktu linear | MIT | **Copyright (c) 2016 C.J. Hutto**; pemberitahuannya direproduksi di `src/analytics/vader_linear.py`, yang hanya berjalan pada berkas persis yang telah diperiksa (disematkan dengan sha256) |
| DB-IP IP-to-Country Lite (geolokasi luring) | CC BY 4.0 | **Atribusi wajib:** "IP geolocation by DB-IP (https://db-ip.com) — CC BY 4.0" — `src/geo/data/dbip_country_lite.csv.gz` |
| stopwords-iso (daftar kata henti multibahasa) | MIT | `configs/stopwords_iso/*.txt` |
| Natural Earth (garis pantai + poligon negara) | Domain publik | `src/static/world_outline.json`, `src/static/world_countries.json` |

---

### 📝 Sumber Data

Open Omniscience mengagregasi data dari berbagai sumber berita. Pengguna bertanggung jawab untuk:

1. Menghormati **hak cipta** konten yang di-scrape
2. Mematuhi **ketentuan layanan** setiap situs web
3. Mengikuti arahan **robots.txt**
4. Mematuhi pedoman **scraping yang etis** (lihat [ETHICS.md](ETHICS.md))

**Catatan:** Lisensi GPLv3 Open Omniscience **tidak** berlaku untuk data yang di-scrape menggunakan perangkat lunak ini. Pengguna sepenuhnya bertanggung jawab untuk memastikan penggunaan data hasil scraping mereka mematuhi semua hukum dan peraturan yang berlaku.

---

### 🔍 Verifikasi

Untuk memverifikasi kepatuhan terhadap lisensi pihak ketiga:

1. **Dependensi Python**: Jalankan `pip list` untuk melihat semua paket yang terpasang beserta lisensinya
2. **Kode Sumber**: Semua kode sumber Open Omniscience tersedia di repositori ini

---

### 📞 Kontak

Untuk pertanyaan tentang lisensi pihak ketiga atau kepatuhan:
- **Email:** open-omniscience@ideotion.com
- **GitHub:** https://github.com/ideotion/Open-Omniscience

---

**Terakhir Diperbarui:** 2026-06-14
