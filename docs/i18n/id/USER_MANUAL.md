<!-- id: AI-drafted translation of docs/USER_MANUAL.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 124 of 124 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Open Omniscience — Panduan Pengguna

*Platform intelijen sumber terbuka, etis, dan mengutamakan lokal untuk jurnalisme
investigasi.* Panduan ini adalah pemandu ramah dari awal sampai akhir: apa itu aplikasi ini, cara
memasang dan menjalankannya, serta tur ke **setiap tab, kontrol, pengaturan, dan alur kerja**,
diikuti referensi teknis (lokasi data, variabel lingkungan, API HTTP
lengkap) dan pemecahan masalah.

> **Dalam satu kalimat:** Open Omniscience mengumpulkan berita secara etis (juga suntingan
> Wikipedia dan harga pasar) ke dalam satu basis data SQLite di mesin *Anda* yang dapat dicari,
> bebas duplikat, dan asal-usulnya terlacak; memungkinkan Anda menganalisisnya (pencarian, tren, peta,
> pembingkaian, ringkasan LLM lokal); dan dapat menghasilkan **bukti bertanda tangan kriptografis
> yang dapat diverifikasi secara offline** tentang apa yang disimpannya dan kapan.

**Janji desain yang membentuk semua hal di bawah ini:**

- **Mengutamakan lokal & privat.** Semuanya berjalan di `127.0.0.1` (hanya loopback). Tanpa
  akun, tanpa telemetri, tidak ada yang keluar dari mesin Anda — satu-satunya lalu lintas keluar
  adalah pengikis (scraper) etis yang mengambil sumber yang Anda tunjuk (dan, jika Anda memilih ikut,
  Wikipedia/OpenTimestamps/Ollama).
- **Hanya angka yang jujur.** Setiap angka adalah `COUNT(*)` nyata, ukuran byte nyata di disk,
  atau agregat statistik nyata beserta ukuran sampel dan catatan kehati-hatiannya. Aplikasi
  lebih memilih menampilkan galat daripada mengarang nilai. (Beberapa fitur "deteksi AI" lama
  yang memalsukan skor telah dihapus — lihat `docs/HISTORY.md`.)
- **Pengambilan data yang etis.** Satu jalur pengambilan. `robots.txt` dihormati secara **gagal-tertutup**
  (jika ragu, aplikasi *tidak* mengambil), setiap host dibatasi lajunya, dan tidak ada yang
  disimpan kecuali isi artikel yang nyata berhasil diekstrak.

---

## Daftar isi

1. [Pemasangan & peluncuran pertama](#1-pemasangan--peluncuran-pertama)
2. [Tur 60 detik](#2-tur-60-detik)
3. [Alat-alat, satu per satu](#3-alat-alat-satu-per-satu)
   - [Beranda](#30-beranda) · [Aktivitas & Pengelola tugas](#30a-aktivitas--pengelola-tugas) ·
     [Feed](#30b-feed) ·
     [Jelajahi: pencarian](#31-pencarian) · [Jelajahi: analisis](#31a-analisis--jendela-korpus) · [Kumpulkan](#32-kumpulkan-di-pengaturan--lanjutan--pengumpulan) ·
     [Sumber](#33-sumber-di-pengaturan--lanjutan--sumber) · [Pustaka](#34-pustaka) · [Pasar](#35-pasar) ·
     [Indeks](#35a-indeks) · [Wawasan](#36-wawasan) ·
     [Peta dunia](#36a-peta-dunia) · [Agenda](#36b-agenda) ·
     [Sumber hidup](#36b-sumber-hidup) · [Iklim](#36c-iklim) · [Observatorium](#36d-observatorium) ·
     [Wikipedia](#37-wikipedia-di-pengaturan--wikipedia) ·
     [Bukti & kustodi](#38-bukti--pengawasan) · [Pengaturan](#39-pengaturan) ·
     [Bantuan & dokumen](#310-bantuan--dokumen)
4. [Alur kerja umum (cara melakukan)](#4-alur-kerja-umum-panduan-langkah-demi-langkah)
5. [Referensi teknis](#5-referensi-teknis)
   - [Di mana data Anda disimpan](#51-lokasi-data-anda) ·
     [Variabel lingkungan](#52-variabel-lingkungan) ·
     [Komponen tambahan opsional](#53-ekstra-opsional) ·
     [API HTTP](#54-api-http) ·
     [Memori pada mesin kecil](#55a-memori-pada-mesin-kecil--satu-satunya-batas-nyata)
6. [Pemecahan masalah](#6-pemecahan-masalah)
7. [Glosarium](#7-glosarium)

---

## 1. Pemasangan & peluncuran pertama

Open Omniscience ditujukan untuk **Python 3.13** di Linux berbasis Debian (dirancang untuk
AppVM Debian di **Qubes OS**, tetapi berjalan di Linux modern mana pun). Ini adalah aplikasi
satu pengguna yang mengutamakan lokal.

### Cara termudah: pemasang satu baris

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

Perintah ini mengkloning repositori dan menjalankan `./install.sh`, yang **mulus — tidak menanyakan apa pun**.
Ia memasang set bawaan — **Core** (mengikis, menyimpan, mencari, mengekspor) ditambah komponen tambahan
**Analysis** (statistik, analitik kata kunci/entitas, korelasi pasar melalui
scipy/scikit-learn; spaCy opsional untuk pengenalan entitas bernama yang sesungguhnya) ditambah kompresi —
lalu membuat peluncur **Open Omniscience** di menu aplikasi Anda dan di Desktop, serta
**membuka aplikasi secara otomatis** di peramban Anda pada `http://127.0.0.1:8000`. (Setel
`OO_COMPONENTS` untuk mengganti set komponen.) Meringkas/menerjemahkan di perangkat memerlukan
model lokal — pasang **Ollama** dari **Pengaturan → AI** (pemasang terverifikasi di dalam aplikasi) atau
dari ollama.com. Jalankan ulang `install.sh` kapan saja.

> Selalu periksa sebuah skrip sebelum menyalurkannya (pipe) ke shell.
> [`bootstrap.sh`](../scripts/bootstrap.sh) sangat kecil; Anda juga bisa mengkloning repositori
> dan menjalankan `./install.sh` sendiri.

**Di Qubes:** jalankan `sudo ./install.sh --template` di dalam TemplateVM, mulai ulang
AppVM, lalu jalankan `./install.sh` di AppVM.

### Pemasangan untuk pengembang / manual

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"     # core + analysis + test tooling
pytest -q                            # full suite should be green
open-omniscience                     # serves http://127.0.0.1:8000
```

Pada peluncuran pertama, aplikasi **secara otomatis mengisi katalog sedunia (~3.400 domain unik
yang mencakup berita, pasar, set spektrum politik, dan portal resmi hukum/HKI)** sehingga Anda
langsung punya sesuatu untuk diambil, menginisialisasi basis data SQLite dan indeks
FTS, dan (jika diaktifkan) memulai penjadwal latar belakang.

### Halaman peluncuran pertama (bahasa → ketentuan → frasa sandi)

Pada **pemasangan baru**, hal pertama yang Anda lihat adalah halaman penyiapan
mandiri yang berjalan offline di `/unlock`, dalam tiga langkah **sebelum aplikasi terbuka**:

1. **Pilih bahasa Anda** — pilih dari 12 bahasa antarmuka; seluruh halaman
   langsung berganti bahasa dan pilihan Anda terbawa ke dalam aplikasi.
2. **Baca dan terima dokumen hukum** (ditampilkan dalam bahasa Anda; versi bahasa Prancis
   yang berlaku). **Terima dan lanjutkan (Accept and continue)** untuk meneruskan, atau **Tolak (Decline)** — menolak
   **mencopot pemasangan aplikasi** (sub-panel konfirmasi yang harus diketik memastikan klik
   tak sengaja tidak pernah menghapus apa pun).
3. **Buat frasa sandi korpus Anda.** Basis data baru **dienkripsi SQLCipher di disk
   secara bawaan**, jadi di sini Anda memilih **SATU frasa sandi itu** (dimasukkan dua kali untuk konfirmasi). Ini
   adalah satu rahasia tetap, seperti ID pengguna, **tanpa pemulihan dan tanpa alternatif
   dekripsi** — frasa sandi yang hilang berarti Anda harus mengumpulkan ulang, karena korpus
   dibangun kembali dari web. Alasan lengkap dan model ancaman yang jujur ada di
   [Pengaturan → Lanjutan → Keamanan](#39-pengaturan).

Pada **peluncuran berikutnya**, penyimpanan sudah dibuat, jadi Anda langsung menuju satu
permintaan **buka kunci** untuk frasa sandi yang sama. Jalankan tanpa antarmuka/terskrip memberikannya melalui
`OO_DB_PASSPHRASE`; operasi tanpa enkripsi (plaintext) tetap merupakan pilihan eksplisit (`OO_DB_PLAINTEXT=1`).

### Penyiapan terpandu & layar Beranda

Setelah Anda masuk, **penyiapan terpandu** satu kali di dalam aplikasi (dialog bertahap) dapat memandu Anda
melalui pilihan pertama Anda: dimulai dengan langkah **Bahasa** dan diakhiri dengan langkah **Selesai**
yang menyatakan bahwa aplikasi **dimulai dalam keadaan offline** dan menawarkan tombol *"Online dan mulai
mengumpulkan"*. Beralih online selalu melewati popup persetujuan jaringan (di bawah) —
panduan hanya mengajak Anda; ia tidak pernah tersambung dengan sendirinya. Anda dapat menjalankannya ulang kapan saja
dari **Pengaturan → Umum → "Jalankan kembali panduan peluncuran pertama."**

Setelah itu, aplikasi terbuka di **Beranda**, yang diawali dengan **Ringkasan** Anda — umpan berisi
**Petunjuk** yang jujur (lihat [3.0 Beranda](#30-beranda)) — di atas strip **sekilas pandang** yang ringkas berisi
hitungan langsung. Anda tidak perlu mengisi apa pun secara manual: katalog kurasi **terisi otomatis
saat aplikasi dimulai**, dan beralih online **otomatis memulai pengumpulan**, setelah itu **Pencarian**
sudah berisi artikel nyata.

**Kerangka antarmuka.** Navigasi ada di **bilah sisi kiri** — **daftar datar** alat-alat
data: **Beranda · Feed · Jelajahi · Wawasan · Observatorium · Peta dunia · Pemerintah ·
Agenda · Iklim · Indeks · Komoditas *(lanjutan)* · Sumber hidup · Pustaka** (pada kedalaman antarmuka
**Esensial**, hanya Beranda dan Feed yang disematkan dan sisanya ada di balik baris
berlabel **Tampilkan lebih banyak**; lihat [3.](#3-alat-alat-satu-per-satu)) (bilah ini menciut menjadi deret ikon pada jendela sempit tetapi tidak pernah
menghilang). Tombol **Pengaturan** berada di **bagian bawah bilah sisi** (bersama
tombol penciut), dan **bilah atas minimal** di atas konten memuat:

- **Bilah pencarian / perintah (⌘K / Ctrl-K).** Ketik untuk melompat ke alat mana pun, menjalankan
  tindakan umum, membuka dokumen apa pun — atau melakukan pencarian gabungan atas data Anda (lihat [3.1 Pencarian](#31-pencarian)).
  Pencarian lengkap, beserta analisisnya, ada di tab **Jelajahi**.
- **Status langsung** — titik kesehatan backend dan pil **LLM** (klik untuk membuka
  Pengaturan → AI).
- **Pengelola tugas** — tombol yang membuka [jendela pengelola tugas](#30a-aktivitas--pengelola-tugas).
- **Mode pesawat** — satu-satunya sakelar jaringan hidup/mati (ikon pesawat yang *isian*-nya menunjukkan
  keadaan; terisi = offline). Pada peluncuran pertama, selama offline, sebuah penanda petunjuk kecil menunjuk
  ke sana dan mengajak Anda untuk online ketika siap.
- **Pengalih bahasa** — ke-12 bahasa dalam satu menu (bendera hanyalah isyarat; nama
  asli bahasanya adalah penanda). Satu klik menerjemahkan ulang seluruh antarmuka.
- **Bantuan (?)** — membuka pembaca dokumentasi di dalam aplikasi (panduan ini dan
  panduan lainnya), dapat dicari dan sepenuhnya offline. (Halaman interaktif Swagger/ReDoc nonaktif secara bawaan, lihat §5.4.)
- **Matikan (ikon daya)** — menghentikan server dengan rapi; data Anda tidak tersentuh, dan antarmuka
  diganti dengan lapisan "Anda dapat menutup tab ini". (Ini *bukan* pencopotan pemasangan atau
  penghapusan data.)

**Pengaturan** dibuka dari **tombol Pengaturan di bagian bawah bilah sisi** (palet
perintah juga dapat langsung melompat ke sana); lihat [3.9 Pengaturan](#39-pengaturan).
**Tampilan** (**Pengaturan → Grafis**) menawarkan **14 tema warna + Sistem**, warna aksen,
kepadatan, pemilih jenis huruf bawaan, dan penciutan bilah sisi. Semuanya
disimpan secara lokal; tidak ada yang dikirim.

### Tambahan terbaru (siklus uji langsung 0.0.8, Juni 2026)

> **Cuplikan historis.** Bagian ini menggambarkan aplikasi pada siklus 0.0.8
> (Juni 2026); aplikasi sudah berkembang sejak itu. `CLAUDE.md` adalah sumber kebenaran terkini
> tentang apa yang dirilis sesudahnya — lihat `docs/ledger/shipped.csv` untuk indeksnya.

- **Sakelar jaringan adalah tombol mode pesawat (bilah atas):** satu ikon pesawat
  tetap yang **isiannya menunjukkan keadaan** — terisi berarti offline aktif
  (setiap permintaan jaringan baru langsung ditolak; satu permintaan yang sedang berjalan mungkin
  selesai). **Setiap peralihan kembali ke online selalu bertanya dulu**: satu popup
  persetujuan menyebutkan tindakan mana yang memerlukan jaringan dan mencantumkan **alamat antarmuka
  lokal** mesin Anda (dibaca dari tabel milik kernel sendiri — tidak pernah lewat panggilan
  jaringan; aplikasi sengaja tidak mengambil layanan pemantul "berapa IP saya", karena
  itu sendiri merupakan lalu lintas). Di luar alamat lokal tersebut, internet
  melihat alamat publik apa pun yang ditampilkan ISP atau VPN Anda. Memulai putaran
  pengumpulan, mengimpor feed pasar, menambahkan halaman Wikipedia yang dipantau, atau mengunduh
  dump semuanya melewati persetujuan yang sama saat offline, dan tombol tersebut
  diperbarui seketika pada setiap peralihan — tidak pernah menunggu polling berikutnya.

  **Mode pesawat adalah jaminan di tingkat soket, bukan sekadar konvensi per panggilan.** Sebagai
  persetujuan berdasarkan informasi tentang perlindungan *milik aplikasi sendiri*: selama mode pesawat aktif,
  aplikasi memasang **pengaman di seluruh proses** atas panggilan soket tingkat rendah
  (`getaddrinfo` / `create_connection` / `connect`), sehingga **setiap** upaya menjangkau
  alamat non-loopback — dari jalur kode mana pun, pustaka pihak ketiga, atau prefetch DNS —
  gagal sebelum soket yang sebenarnya digunakan. Loopback (127/8, ::1, `localhost`) dan soket
  Unix selalu diloloskan, sehingga server aplikasi itu sendiri, Ollama lokal, dan basis data
  berkas tetap berfungsi. Pengaman ini transparan saat Anda online (tanpa biaya selama
  pengumpulan). Setel `OO_AIRPLANE_SOCKET_GUARD=0` untuk menonaktifkannya (untuk penerapan
  tidak lazim yang meneruskan loopback ke tempat lain).
- **Peta pikiran berlapis & awan kata (Wawasan):** peta pikiran radial sejati (pusat →
  lengan → daun ke arah luar) dalam tiga lapis zoom (kata kunci ↔ keluarga ↔
  supergrup), dengan tampilan kedua berupa awan kata, kontrol spektrum tanggal,
  penggeser ukuran teks, dan ⛶ Perbesar (Enlarge). Ukuran huruf selalu mewakili volume artikel bersama.
- **Supergrup yang sudah dibuat sebelumnya:** set awal bawaan (disusun dari log lapangan
  nyata) diisi saat aplikasi dimulai; suntingan dan penghapusan Anda sendiri selalu diutamakan.
- **Peta dunia kini berupa koroplet (ooMap):** tab ini mewarnai negara menurut dimensi
  terukur (sumber · artikel · sebutan kata kunci · nada), dengan kontrol di dalam peta untuk
  ukuran, granularitas negara↔benua, lapisan Tempat, lapisan Sinyal dengan
  penggeser momen-dalam-fokus, lapisan IP server, zoom roda, geser-seret, dan ⛶ Perbesar. Lihat
  [3.6a](#36a-peta-dunia).
- **Tanggal peristiwa, tempat, orang, dan organisasi yang diekstrak dari teks:**
  pengekstrak tanggal membaca enam bahasa, format angka, dan ungkapan berjangkar
  ("kemarin", nama hari saja, "11 Juni"); pengekstrak lokasi menemukan
  kota dari gazetir dan nama negara; pengekstrak entitas menampilkan **orang**
  dan **organisasi** sebagai dua kelas yang sengaja dipisahkan (nama yang diawali gelar
  kehormatan dan akronim yang berulang menjawab pertanyaan berbeda — setiap entri mencatat
  aturan mana yang menemukannya). Semuanya mengisi kepala metadata pembaca artikel, yang
  memisahkan **"Dari sumber"** dari **"Disimpulkan oleh aplikasi ini — kurang andal"**
  (kotak bergaris putus-putus): hasil ekstraksi adalah kandidat leksikal dengan asal-usul cuplikan,
  bukan fakta yang terkonfirmasi.
- **Ekspor kata kunci per bahasa:** log kata kunci diagnostik dibatasi 5.000
  kata kunci *per bahasa dominan*, sehingga kosakata bahasa minoritas tidak pernah
  tersingkir dari analisis oleh volume bahasa Inggris.
- **Dump Wikipedia offline:** daftar edisi kembali dimuat dengan benar dan dapat
  dipilih lebih dari satu — unduh beberapa edisi bahasa dalam satu proses antrean.
- **17 tema dan fon sumber terbuka bawaan:** sembilan paduan warna baru (Arctic,
  Solar, Forest, Aubergine, Garnet, Cyber, Mist, Dawn, Mint) bergabung dengan set
  asli, dan enam jenis huruf SIL-OFL kini disertakan **di dalam aplikasi** (Cantarell, Inter,
  Outfit, Manrope, JetBrains Mono, Source Serif 4 — lihat
  `src/static/fonts/README.md`): tidak ada yang perlu diunduh, tidak ada permintaan fon yang pernah
  keluar dari mesin Anda. Beberapa tema dipasangkan dengan fon (Arctic→Inter,
  Cyber→Outfit, Sepia/Paper→Source Serif); pemilih **Jenis huruf** yang baru di
  Pengaturan → Grafis dapat menimpa semuanya, dan pembaca artikel menggunakan
  fon serif bawaan. Widget formulir (penggeser, kotak centang, menu tarik-turun bawaan) kini
  juga mengikuti tema.

**Catatan tentang “FOOS”.** Tab peramban yang dibuka aplikasi (investigasi Petunjuk, pembaca
artikel lokal) diberi akhiran **“· FOOS” — Free Open OmniScience**: cukup pendek
untuk deretan tab yang sempit sambil tetap membuat aplikasi mudah dikenali. Ini adalah
nama kerja tahap alfa; nama yang lebih tepat mungkin menyusul nanti.

**Satu ikon, satu antarmuka.** Pemasang membuat **satu peluncur** — **Open
Omniscience** → `http://127.0.0.1:8000/` — aplikasi bilah sisi yang mudah dijelajahi dan dapat disesuaikan,
yang menyesuaikan diri dengan mulus terhadap ukuran jendela Anda (bilah sisi menyusut menjadi deret
ikon pada jendela yang lebih sempit). Antarmuka kedua yang eksperimental ("Desk") pernah ada
pada siklus-siklus sebelumnya dan dipensiunkan di 0.0.8; riwayatnya ada di
[`DESIGN.md`](DESIGN.md).

**Berjalan di latar belakang, dengan peramban tertutup.** Aplikasi hidup di jendela
peluncurnya, bukan di tab peramban. Anda dapat menutup peramban kapan saja: pengumpulan,
unduhan Wikipedia dan peta, pencadangan ke folder atau drive, impor, tugas-tugas AI (unduhan
model, deteksi bahasa, pemeriksaan AI), dan arsip diagnostik semuanya tetap
berjalan. Inilah cara membiarkan mesin mengumpulkan selama berhari-hari sambil menghemat memori yang
dipakai peramban (sering 0,5 hingga 1 GB, yang berarti besar pada VM kecil).

Selama aplikasi berjalan, jendela peluncur menampilkan sebuah **panel**, dan panel itu tetap ada selama
aplikasi berjalan: hanya ada satu jendela, sama di Linux, macOS, dan Windows. Di bagian atas, panel menunjukkan
apakah aplikasi terkunci, keadaan jaringan dan pengumpulan, memori dan CPU server,
serta apa yang sedang berjalan sekarang. Di bawahnya ada **log aktivitas**: satu baris bertanda waktu untuk setiap hal
yang terjadi (pengumpulan dimulai atau berhenti, unduhan mencapai 40 %, pencadangan selesai,
jaringan menjadi offline, aplikasi berhenti merespons lalu merespons lagi), ditambahkan satu demi satu
selama aplikasi berjalan, dengan yang terbaru di bawah. Gulir kembali dengan tombol panah, PgUp dan
PgDn, atau roda tetikus; End kembali ke baris terbaru. Klik tombolnya, atau tekan
tombol keyboard yang tertera pada masing-masing:

- **Buka UI (Open UI) (o)** membuka aplikasi lagi di peramban Anda.
- **Jeda pengumpulan (Pause collection) (p)** menghentikan pengumpulan dan memasukkan aplikasi ke mode pesawat. Untuk melanjutkan,
  buka UI: beralih online selalu melewati jendela persetujuannya, tidak pernah lewat terminal.
- **Pesan server (Server messages) (l)** menampilkan pesan milik server itu sendiri (tidak tersedia di Windows); tekan tombol apa saja
  untuk kembali.
- **Hentikan aplikasi (Stop app) (s)** menghentikan aplikasi, setelah ditekan kedua kalinya. Ia menyebutkan tugas-tugas yang akan berakhir.

Panel tidak tertutup dengan sendirinya selama aplikasi berjalan, bahkan saat aplikasi sibuk atau
komputer sempat tertidur dan aplikasi butuh waktu untuk merespons: panel menyebutkan sudah berapa lama aplikasi
diam dan terus mencoba. Panel berakhir ketika aplikasi berakhir.
Panel tidak pernah meminta frasa sandi Anda: jika aplikasi terkunci, panel memberitahukannya, dan Anda membukanya
di peramban. Menutup jendela peluncur atau menekan Ctrl-C tetap menghentikan aplikasi, seperti
sebelumnya. Setel `OO_PANEL=0` untuk memulai tanpa panel. Alat-alat AI yang menjawab di halaman
(meringkas atau menerjemahkan massal, ekstraksi kata kunci dengan AI, menjalankan prompt) juga tetap berjalan setelah
tab ditutup, dan tampil di panel. Untuk menghentikan salah satunya, buka UI dan tekan **Hentikan**
pada barisnya di pengelola tugas, atau **Batal** di halaman (tombol Hentikan aplikasi milik panel menghentikan
seluruh aplikasi): ia berhenti setelah artikel yang sedang diproses, dan artikel yang sudah selesai tetap
tersimpan. Indeks kata kunci untuk artikel yang belum diindeks oleh Wawasan juga menyusul dengan
sendirinya saat aplikasi menganggur. Hanya dua hal yang memerlukan tab tetap terbuka: unggahan yang sedang Anda
kirim dari peramban, dan berkas yang sedang diunduh peramban. Di
Windows, panel terbuka di jendelanya sendiri (menutupnya tidak menghentikan aplikasi). Panel memerlukan
modul curses milik Python, yang di Windows diperoleh dari paket windows-curses: pemasang
menambahkannya di PC Intel dan AMD, dan pada pemasangan yang dibuat sebelum versi ini Anda dapat menambahkannya dengan
`.venv\Scripts\python -m pip install windows-curses` di folder aplikasi. Windows di ARM belum
memiliki build untuk modul itu, jadi di sana aplikasi dimulai tanpa panel.

---

## 2. Tur 60 detik

Siklus intinya adalah:

> **Pilih/tambah sumber → Kumpulkan → Jelajahi (cari dan analisis) → Ekspor / tanda tangani.**

1. **Pengaturan → Lanjutan → Sumber** — katalog sedunia sudah terisi; tambahkan sumber Anda sendiri jika mau.
2. **Pengaturan → Lanjutan → Pengumpulan** — ambil feed RSS suatu sumber atau tempelkan URL satu artikel.
   Atau biarkan **penjadwal** melakukannya secara otomatis pada selang waktu tertentu. Pengumpulan memerlukan
   jaringan: tombol pesawat di bilah atas harus mati, dan mematikannya akan meminta persetujuan Anda
   terlebih dahulu.
3. **Beranda** dan **Feed** — baca apa yang masuk: Beranda sebagai sinyal terukur (Petunjuk), Feed sebagai
   aliran artikel biasa.
4. **Jelajahi** — pencarian teks lengkap Boolean di semua yang telah Anda kumpulkan;
   analisis artikel yang cocok muncul di bawah hasil.
5. **Wawasan / Observatorium / Peta dunia / Pemerintah / Agenda / Iklim / Indeks /
   Komoditas / Sumber hidup** — tampilan opsional di atas korpus dan data
   publik (pola, ruang-waktu, hukum, tanggal, catatan iklim, harga, apa yang berubah).
6. **Ekspor** — CSV/JSON, atau **paket bukti bertanda tangan** yang dapat diverifikasi siapa pun
   secara offline.

Pilih alat mana pun dari bilah sisi, atau cukup tekan **⌘K / Ctrl-K** dan ketik tujuan
Anda. Untuk jalan-jalan singkat melalui tab-tab bilah sisi pada kedalaman antarmuka Anda,
pilih **Ikuti tur** (Pengaturan → Umum, Bantuan & dokumen, atau palet perintah).
Tur hanya dimulai jika Anda memintanya, tidak mengubah apa pun, dan tidak menyimpan catatan bahwa tur pernah dijalankan. Tampilan aktif menyegarkan dirinya secara langsung (setiap beberapa detik) selama tampil di
layar, dan tindakan dikonfirmasi dengan notifikasi toast kecil di sudut.
Tindakan yang merusak/menghapus selalu meminta persetujuan terlebih dahulu.

---

## 3. Alat-alat, satu per satu

Bilah sisi adalah **daftar datar** alat-alat data (dari atas ke bawah):

- **Beranda · Feed · Jelajahi · Wawasan · Observatorium · Peta dunia · Pemerintah · Agenda ·
  Iklim · Indeks · Komoditas *(lanjutan)* · Sumber hidup · Pustaka** — ditambah tombol **Pengaturan**
  di bagian bawah bilah sisi. Bantuan dibuka dari tombol **?** di bilah atas.
  Tidak ada tab "Kumpulkan": pengumpulan berada di Pengaturan.
- **Jelajahi** adalah satu halaman: kotak pencarian di atas, dan analisis artikel yang
  cocok di bawah hasil segera setelah pencarian selesai (lihat [3.1](#31-pencarian) dan
  [3.1a](#31a-analisis--jendela-korpus)). Kata kunci
  yang diklik di dalam aplikasi membuka analisisnya di halaman ini; kata kunci di pembaca artikel,
  **Buka korpus ↗** pada Petunjuk Beranda, dan Enter di omnibar membukanya di Jelajahi pada
  **tab peramban baru**.
- **Kedalaman antarmuka** (Pengaturan → Umum) mengubah apa yang *disematkan* bilah sisi, tidak pernah apa yang
  dapat Anda jangkau. Pada **Esensial**, hanya Beranda dan Feed yang disematkan dan tab-tab lain berada
  di balik baris berlabel **Tampilkan lebih banyak**; **Standar** dan **Lengkap** mencantumkan setiap tab. Palet
  perintah (Ctrl/⌘-K) menjangkau setiap tab pada setiap kedalaman.

**Konten diutamakan.** Bilah sisi menampilkan *data*; permukaan untuk akuisisi dan pemeliharaan
berada di **Pengaturan**: **Kumpulkan** (penjadwal + pengambilan manual), **Sumber**
(katalog), **Wikipedia** (pelacakan perubahan + dump offline), **Bukti & kustodi**,
dan **meja integritas sumber** semuanya dijangkau dari Pengaturan (didokumentasikan dalam
subbagiannya masing-masing di bawah). Pengaturan dibuka dari **tombol di bagian bawah bilah sisi**; palet
perintah juga dapat langsung melompat ke sana.

Beberapa nama diubah agar lebih sederhana (kontrolnya tetap sama): **Ingest → Kumpulkan**,
**Basis data → Pustaka**, **Hukum dunia → Pemerintah** (kini dengan subtab **Negara · Peta · Hukum**),
**Pasar → Komoditas** (dengan **Indeks** dipisahkan). Lompat ke alat mana pun dengan
palet perintah (Ctrl/⌘-K).

### 3.0 Beranda

**Kegunaannya:** **ringkasan** (briefing) Anda — umpan triase sekaligus orientasi.

- **Ringkasan (umpan):** aplikasi mengumpulkan dan mengukur di latar belakang, lalu
  menampilkan calon berita sebagai **Petunjuk** (nama di layar untuk kartu-kartu ringkasan)
  yang dikelompokkan ke dalam keranjang editorial (*naik, terlalu banyak diberitakan, kurang diberitakan, selidiki,
  periksa-pembingkaian, pantau, konteks, integritas data*). Setiap Petunjuk adalah **satu sinyal
  terukur + tautan bukti + catatan kehati-hatian** — tidak pernah vonis, dan **tidak ada "skor
  kepercayaan"** (dilarang di dalam kode).
- **Kartu bolak-balik — peringatannya ada di sisi belakang.** Petunjuk adalah **kartu bolak-balik dua sisi**:
  **depan** adalah petunjuk sekilas pandang; **klik (atau tekan Enter)** dan kartu berbalik ke
  sisi **belakang** yang memuat **catatan kehati-hatian, metode, alasan munculnya, bukti, dan tombol
  "Buka korpus ↗"** (yang membuka set artikel persis milik Petunjuk itu di jendela analisis
  baru). Catatan kehati-hatian ada di DOM secara bawaan, tepat di samping tombol tindakan — tidak pernah
  disembunyikan di balik sakelar tampilan tenang. **+ Tambah ke draf** menyematkan Petunjuk; **Abaikan** menyembunyikannya
  (dapat dibatalkan). Umpan disimpan di cache (instan) dan **memperbarui dirinya sendiri** — ia menghitung ulang di
  latar belakang setelah setiap putaran pengikisan dan melakukan polling ulang sendiri; tidak ada tombol Segarkan.
- **Draf nawala:** Petunjuk yang disematkan + catatan Anda, diekspor sebagai **Markdown** di mana
  setiap klaim sudah membawa tautan sumber, metode, dan catatan kehati-hatiannya — jurnalisme
  yang dapat direproduksi. Untuk salinan bertanda tangan dari artikel-artikel yang mendasarinya, gunakan Bukti & kustodi.
- **Tata letak yang mengutamakan konten:** strip **sekilas pandang** yang ringkas disematkan di atas (hitungan
  langsung + apakah pengumpulan otomatis sedang berjalan), dan Petunjuk di bawahnya dapat disaring
  menurut **keluarga** melalui subtab vertikal (lensa bawaan **"Semua petunjuk"**, ditambah satu tab per
  keranjang dengan warnanya sendiri). Katalog kurasi terisi otomatis dan pengumpulan dimulai ketika Anda
  online, jadi Beranda yang kosong cukup menampilkan keadaan kosong yang jujur — tanpa kartu sambutan. *(Sapaan
  besar lama dan baris "Tindakan cepat" telah dihapus — Beranda langsung terbuka pada
  Ringkasan.)*

### 3.0a Aktivitas & Pengelola tugas

**Kegunaannya:** melihat — dan mengarahkan — semua yang dikerjakan aplikasi di
latar belakang, dari tab mana pun.

- **Cip aktivitas** di bilah atas menyala selama ada pekerjaan berjalan (putaran pengumpulan,
  dump Wikipedia, impor pasar); tombol **pengelola tugas** yang permanen berada di sampingnya
  (tetap dapat dijangkau bahkan saat aplikasi menganggur).
- Buka **Pengelola tugas** — sebuah jendela sungguhan (bukan popover) dengan lima subtab:
  - **Aktif** — setiap tugas yang sedang berjalan: putaran pengumpulan, setiap dump Wikipedia yang sedang diunduh,
    pengambilan yang sedang berlangsung (hanya ditampilkan sebagai DOMAIN), loop menganggur, dan setiap unduhan
    yang dijeda/gagal. Setiap tugas menampilkan kemajuan nyatanya dan kontrol yang berlaku — **Hentikan**
    putaran pengumpulan (ini juga mengaktifkan sakelar pemutus jaringan, sehingga Anda menjadi offline; tombolnya
    menyebutkan hal itu) dan **Jeda/Batal** untuk dump. Tidak ada perkiraan waktu atau laju yang dikarang — hanya
    kemajuan byte nyata yang dilaporkan pemilik tugas.
  - **Antrean** — tugas yang menunggu giliran: antrean dump Wikipedia yang diunduh satu per satu, sesuai
    urutan, dengan kontrol **↑ / ↓** untuk mengubah urutannya (dahulukan dump bahasa Prancis yang kecil di depan
    dump bahasa Inggris yang besar).
  - **Jadwal** — fakta nyata penjadwal: keadaan (berjalan / menganggur / berhenti),
    kemajuan putaran saat ini (hanya domain), irama, proses terakhir, dan waktu proses
    berikutnya milik backend sendiri yang ditampilkan sebagai waktu relatif yang jujur (metodenya ada di gelembung
    arahkan-kursor — tidak pernah hitung mundur yang dikarang).
  - **Cakupan** — jangkauan dan kesegaran pengikisan per tag (seberapa banyak setiap topik/tag yang
    benar-benar tersentuh oleh pengumpulan Anda, dan seberapa segar), sehingga Anda dapat melihat celahnya.
  - **Sistem** — tanda vital proses secara langsung (CPU, RAM, laju unduh). *(Tanda vital dipindahkan ke sini
    dari bilah atas.)*
- Jendela ini membaca **secara langsung dari sistem yang memiliki pekerjaan itu**, sehingga tidak pernah dapat
  berbeda dengan apa yang sebenarnya terjadi — tanpa keadaan bayangan.

### 3.0b Feed

**Kegunaannya:** membaca korpus Anda sebagai **aliran**, bukan sebagai kumpulan sinyal
terukur. Beranda memberi tahu Anda apa yang menonjol; Feed hanya menyodorkan artikel, satu demi
satu, dan membiarkan Anda menggulir.

- **Dua urutan, keduanya dinyatakan.** **Terbaru dahulu** adalah tanggal terbit, yang terbaru di atas.
  **Diacak** adalah urutan tetap yang ditentukan oleh sebuah **benih (seed)**: posisi sebuah artikel bergantung
  pada id-nya dan benih itu, **dan tidak ada yang lain**. Setiap halaman membawa baris metodenya sendiri
  yang menyebutkan urutan mana dari keduanya yang sedang Anda baca.
- **Pengacakan adalah alat bantu menjelajah, bukan sistem rekomendasi.** **Tidak ada penilaian
  keterlibatan dalam bentuk apa pun** — tidak ada yang mengukur apa yang Anda buka, berapa lama Anda bertahan, atau apa yang Anda
  lewati, dan **tidak ada riwayat baca yang disimpan atau dirujuk**. Dua orang dengan benih
  yang sama dan korpus yang sama melihat urutan yang sama. Kalimat itu adalah bagian dari teks metode
  yang dicetak halaman, sehingga tidak bisa diam-diam berhenti menjadi benar.
- **Apa yang tidak ditampilkan, dihitung.** Feed menampilkan artikel yang **tidak dikarantina**
  dan yang **sumbernya sudah dikualifikasi**. Kedua pengecualian itu **dihitung dengan tepat** dan
  ditampilkan di halaman pertama, sehingga feed yang pendek pada korpus yang penuh terbaca sebagai *"sumber Anda
  belum dikualifikasi"* — yang dapat ditindaklanjuti — bukan sebagai *"Anda tidak punya apa-apa"*,
  yang keliru. Kedua hitungan itu menggambarkan korpus, bukan halaman, sehingga
  dihitung sekali dan tidak berubah saat Anda menggulir.
- **Di mana Anda berhenti.** Guliran mempertahankan posisinya antarsesi dengan menyimpan **satu
  penanda posisi** di peramban Anda — sebuah benih dan satu kursor, tidak pernah daftar apa yang
  Anda baca. **Pengaturan → Umum → Riwayat gulir Feed** memuat dua kontrolnya:
  **Acak ulang** (benih baru, urutan baru, kembali ke awal) dan **Mulai dari atas**
  (urutan sama, posisi dihapus).
- **Celah jujur dalam setiap urutan.** Pengumpulan terus berjalan selagi Anda menggulir, dan setiap
  urutan melewatkan artikel yang baru masuk dengan cara berbeda: pada **Diacak**, artikel baru dapat jatuh *di bawah*
  titik yang telah Anda capai (mengacak ulang menjangkaunya), dan pada **Terbaru dahulu** artikel baru
  muncul *di atasnya* (kembali ke atas menjangkaunya). Halaman menyebutkan mana yang berlaku.
- **Setiap kartu** menampilkan judul, sumber, tanggal, dan **tiga kata kunci teratas milik artikel itu
  sendiri** — kata kunci artikel tersebut, bukan kata kunci dari apa pun yang Anda cari. **Baca selengkapnya**
  membentangkan ringkasan **di tempat**; judul membuka artikel di pembaca lokal.

### 3.1 Pencarian

**Kegunaannya:** menemukan artikel di korpus Anda. Pencarian adalah bagian atas
tab **Jelajahi** di bilah sisi; analisis artikel yang cocok
([3.1a](#31a-analisis--jendela-korpus)) muncul tepat di bawah hasil, tanpa
tombol yang perlu ditekan. Pencarian tanpa kata dan tanpa filter cukup mencantumkan setiap artikel dan
tidak menganalisis apa pun.

- **Kueri Boolean** — mendukung `AND` / `OR` / `NOT`, `"exact phrases"`, dan
  tanda kurung dengan urutan prioritas yang benar, mis.
  `(climate OR energy) AND policy NOT opinion`. Didukung oleh SQLite FTS5 dan sepenuhnya
  terparameterisasi (tanpa injeksi).
- **Kata dalam bahasa Arab, Tionghoa, dan Jepang ditemukan bagaimanapun cara penulisannya.** Kata
  Arab cocok dengan atau tanpa tanda vokal dan apa pun ejaan alef, teh
  marbuta, atau alef maksura-nya (أحمد menemukan احمد, مدرسة menemukan مدرسه), dan kata Tionghoa atau Jepang
  ditemukan di dalam rangkaian teks yang lebih panjang (东京 menemukan artikel yang menyebut 东京大学).
  Bahasa Tionghoa dipecah menjadi kata oleh jieba di setiap pemasangan; bahasa Jepang oleh sudachipy, yang
  disertakan bersama komponen tambahan opsional `[segmentation]`. Artikel yang diindeks sebelum versi ini
  tetap ditemukan seperti biasanya, dan juga ditemukan per kata setelah **Indeks ulang
  pencarian** (Re-index search) (Pengaturan → Lanjutan → Diagnostik) dijalankan.
- **Filter:** Sumber (nama persis), Bahasa (kode seperti `en`), dan kontrol **rentang
  waktu** — kolom tanggal Dari/Sampai, bilah rentang yang dapat diseret, dan preset cepat
  (1M · 6M · 1Y · 5Y · All) — kontrol yang *sama* yang dipakai di Pasar, Wawasan, dan jendela
  Analisis. Jika dibiarkan pada rentang penuhnya, kontrol ini tidak mengecualikan apa pun; persempit untuk membatasi
  pencarian ke suatu periode. Semuanya opsional.
- **Pencarian** menjalankan kueri; tabel hasil menampilkan **Judul · Sumber · Diterbitkan ·
  Bahasa**, dan sebuah hitungan (`N result(s)`, serta berapa yang ditampilkan jika dipotong).
- **Tindakan per baris:** **buka** (salinan offline yang bersih dari artikel yang tersimpan),
  **sumber ↗** (URL asli), **Ringkas** dan **Terjemahkan** (LLM lokal, jika
  Ollama tersedia).
- **Ekspor:** **Ekspor CSV**, **Ekspor JSON**, dan **Ekspor bukti bertanda tangan** — paket
  bertanda tangan yang menunjukkan bila dirusak, berisi persis artikel-artikel yang cocok dengan kueri Anda (lihat
  [Bukti & kustodi](#38-bukti--pengawasan)). Ia membuka tinjauan terlebih dahulu: berapa banyak
  artikel dan sumber, apa isi berkasnya, bahwa berkas itu tidak terenkripsi (plaintext), dan kunci mana yang menandatangani;
  menyimpan memerlukan satu klik lagi, dan pesan sesudahnya mencantumkan anggota berkas dan
  kunci yang harus diberikan kepada penerima. Ada juga **Lampiran metode** (catatan kueri + metode
  yang dapat direproduksi).
- **Menjalankan model lokal atas seluruh hasil yang cocok:** **Ringkas semua** / **Terjemahkan semua** mengantrekan
  proses latar belakang model lokal Anda atas setiap artikel yang cocok (disimpan bersama model +
  tanggal, dan — karena merupakan keluaran AI — tidak pernah dimasukkan ke indeks kata kunci tepercaya); **Jalankan
  ekstraktor** menjalankan salah satu ekstraktor AI kustom Anda atas set tersebut; **Sintesis hasil**
  membuka jendela tempat Anda memilih hingga 20 anggota dan mendapatkan satu proses model lokal yang menyertakan kutipan atas
  anggota-anggota itu (lihat pembahasan mendalam). Proses-proses ini diantrekan dan dapat dibatalkan; kontrol yang sama ada di
  jendela analisis.

> **Dua jalan masuk.** Buka **Jelajahi** dari bilah sisi, atau ketik di omnibar dan pilih
> *"Jalankan pencarian Boolean lengkap"*: keduanya membawa Anda ke halaman yang sama dengan kueri sudah terisi.

**Omnibar (Ctrl/⌘-K), dari mana saja:** palet perintah juga merupakan
pencarian gabungan atas data Anda. Mulai dari dua karakter yang diketik, ia menampilkan tiga
hasil pertama per kelompok — **artikel** (FTS Boolean lengkap), **kata kunci** (masing-masing membuka
jendela korpusnya), **sumber**, **halaman Wikipedia yang dipantau**, **teks Wikipedia
yang disimpan di mesin ini** (versi lama dan teks halaman yang berubah yang disimpan jalur Wikipedia,
lihat 3.7), dan **dokumen hukum yang dilacak** — dengan *jumlah total sebenarnya* di balik setiap kelompok dinyatakan di kepalanya.
Semuanya didukung indeks dan dicari hanya di mesin ini; kueri yang baru
setengah diketik tidak pernah dianggap galat. Memilih *"Jalankan pencarian Boolean lengkap"* membawa Anda ke
tab ini dengan kueri sudah terisi, sehingga setiap kemampuan di atas tetap hanya berjarak satu
langkah.

### 3.1a Analisis — jendela korpus

**Kegunaannya:** mengubah sebuah *set* artikel, atau satu kata kunci, menjadi objek
analisis yang dapat Anda baca dari segala sudut. Satu kata kunci adalah sebuah korpus; satu artikel adalah korpus
beranggota satu. Analisis berada di halaman **Jelajahi**, di bawah hasil pencarian. Analisis
muncul ketika Anda:

- menjalankan pencarian di Jelajahi (atau memilih *"Jalankan pencarian Boolean lengkap"* di omnibar),
- menekan **Enter** di omnibar (ini membuka Jelajahi di tab peramban baru),
- mengklik sebuah **kata kunci** di mana pun (Wawasan, sisi belakang Petunjuk, atau pembaca, tempat analisisnya terbuka di tab peramban baru),
- mengklik sebuah **Petunjuk Beranda** (tombol "Buka korpus ↗"-nya membuka set artikel yang *persis*, di tab peramban baru), atau
- mengklik judul grafik komoditas / **Analisis ↗**.

Ketika analisis dibuka dari tempat lain (kata kunci, Petunjuk, komoditas),
daftar pencarian disisihkan dan halaman menyebutkan analisis milik siapa yang sedang ditampilkan, sehingga daftar dan
analisis tidak pernah diam-diam menggambarkan dua set artikel yang berbeda. Beberapa analisis
dapat berdampingan sebagai **tab bernama** dalam sebuah strip di atas; masing-masing diberi judul sesuai kuerinya dan menampilkan
**jumlah artikel** yang menjadi dasar perhitungannya. Subtab-subtabnya adalah:

- **Ikhtisar** — ringkasan sekilas tentang set tersebut.
- **Kata kunci** — tabel kata kunci berperingkat (ko-okurensi / n / PMI nyata, tanpa skor).
- **Tren** — tren sebutan/volume dari waktu ke waktu, digambar dengan perangkat grafik
  interaktif bersama (zoom dengan roda, geser dengan seret, arahkan kursor untuk pembacaan nilai persis; resolusi penuh di dalam
  jendela, dengan rentang yang jarang datanya ditampilkan secara jujur sebagai batang + catatan kehati-hatian korpus-awal, bukan
  kurva yang dipalsukan).
- **Peta pikiran** — peta kata kunci radial yang deterministik (pusat → lengan, selalu ke arah luar).
- **Artikel** — artikel-artikel anggota (berhalaman). Kolom: **Judul · Sumber ·
  Diterbitkan · Kata kunci teratas**, dan setiap kepala kolom adalah **kontrol pengurutan** — klik satu kali
  untuk mengurutkan menurut kolom itu, klik lagi untuk membalikkannya; tanda panah menandai kolom yang berlaku. Nama
  diurutkan A–Z, tanggal dan hitungan dimulai dari yang terbesar. Pilihan yang sama ada di menu
  **Urutkan menurut / Urutan** di atas daftar, karena keduanya adalah dua kolom yang sama: hanya ada
  tepat satu pengurutan di jendela ini, sehingga tidak ada yang bisa diam-diam menimpa pilihan Anda. *(Dulu
  pengurutan berada di **Lanjutan**, tiga subtab jauhnya dari satu-satunya daftar yang membacanya.)*

  **Kata kunci teratas** adalah kata kunci yang paling sering disebut MILIK artikel itu sendiri beserta hitungannya, yang dihitung
  ketika artikel diindeks — pertanyaan yang berbeda dari hitungan kata kunci yang *dicari*,
  yang merupakan tombol terpisah `↕ "term" count`. Jika beberapa kata kunci sama-sama berada pada hitungan itu,
  baris tersebut menyebutkan **seri**, karena yang disebutkan hanyalah yang pertama di antaranya dan menyebutnya
  kata kunci teratas berarti menegaskan peringkat yang tidak pernah dibuat oleh hitungan itu. Artikel yang belum dijangkau
  oleh pengindeksan ulang menampilkan **—**, tidak pernah 0: yang hilang adalah pengukurannya, bukan
  kata kuncinya.

  Setiap baris terbuka di **pembaca offline**, yang bilah tabnya sendiri adalah **Baca · Ringkasan ·
  Terjemahan · Kata kunci · Peta pikiran · Sentimen · Terkait · Sumber · Tautan** — di sanalah
  Anda membacanya, melihat **sumber aslinya** (teks yang terlihat pada tautan adalah URL
  lengkapnya), dan menjalankan **Ringkasan / Terjemahan** dengan model lokal. Ketiganya dulu
  diulang sebagai tanda panah per baris dan dua tombol per baris; kini dipindahkan ke satu-satunya halaman yang
  benar-benar dapat menampilkan hasilnya. Tombol massal **Ringkas semua / Terjemahkan semua** tidak berubah di
  baris tindakan di bawah. Salinan yang nyaris identik diberi lencana "N salinan = satu suara".
- **Kapan/Di mana/Siapa** — tanggal, tempat, dan orang/organisasi yang disebut dalam set, sebagai **faset**
  yang dapat diklik; mengklik sebuah nilai akan **menelusuri lebih dalam** ke artikel-artikel yang menyebutkannya saja (jendela
  analisis yang dipersempit). Disimpulkan dari teks, tidak pernah dikonfirmasi.
- **Tautan** — artikel anggota mana yang **berbagi tautan keluar**. Ini sengaja menampilkan
  *struktur asal-usul bersama*: tiga artikel yang mengutip satu asal adalah satu sumber
  yang memakai tiga topi, sehingga kesesuaian dihitung sebagai penguatan hanya jika jalurnya
  independen. Tujuannya adalah *sumber dari sumber-sumber itu*.
- **Terkait** — salinan yang nyaris identik di berbagai sumber ("N salinan = satu suara") dan asal-usul
  bersama, masing-masing dengan **"Cabangkan ke korpus baru →"** yang membuat jendela analisis
  baru atas persis artikel-artikel tersebut.
- **Sentimen** — nada per sumber (VADER; catatan kehati-hatian bahwa ini hanya untuk bahasa Inggris ditampilkan).
- **Sumber** — asal-usul deskriptif dari media-media dalam set.
- **Kompetitif** — bagaimana media-media dalam set saling dibandingkan (volume / nada / waktu /
  penekanan — deskriptif, tidak pernah ada pemenang atau skor).
- **Harga** — *(hanya ketika jendela diisi dari sebuah komoditas)* kurva harga
  ditumpangkan pada cakupan korpus Anda pada sumbu waktu bersama (kemunculan bersamaan, tidak pernah sebab-akibat),
  masing-masing seri pada skalanya sendiri dengan satuan nyata.
- **Lanjutan** — batasi set menurut **sumber · bahasa · rentang tanggal**; cip "Difilter"
  dan ringkasan menunjukkan apa yang aktif. (Pengurutan dipindahkan ke tab Artikel, di atas.)

Baris tindakan memuat **Lampiran metode**, **Ekspor bukti bertanda tangan**, **Sintesis
hasil** (jendela pemilihan anggota), dan proses model lokal yang diantrekan **Ringkas semua / Terjemahkan semua / Jalankan
ekstraktor** — set yang sama dengan pencarian di atasnya.

### 3.2 Kumpulkan *(di Pengaturan → Lanjutan → Pengumpulan)*

> **Letaknya sekarang.** Pengumpulan adalah permukaan akuisisi, jadi ia dipindahkan dari
> bilah samping ke **Pengaturan → Lanjutan → Pengumpulan** (mengutamakan konten). Kontrolnya tidak berubah.

**Kegunaannya:** memasukkan artikel ke dalam korpus — secara otomatis atau manual.

**A. Penelanan otomatis (penjadwal).** Pekerja latar belakang yang menelan artikel menurut
pengatur waktu. Kontrol:

- **Mulai / Hentikan / Kikis sekarang** — berjalan terus-menerus, berhenti, atau menjalankan satu putaran
  segera. Pil status menampilkan `running` / `running — scrape in progress` /
  `stopped` dan waktu jalan berikutnya; baris di bawahnya menampilkan rekapitulasi putaran terakhir.
- **Interval (menit)** dan penggeser **Kecepatan pengumpulan** (target laju unduh).
  Aplikasi mengukur laju unduhnya sendiri yang sebenarnya dan menaikkan atau menurunkan jumlah host
  yang dihubungi bersamaan untuk mengikuti target Anda, serta mundur secara otomatis ketika CPU, memori, atau
  satu-satunya penulis terenkripsi menjadi batasnya; kesopanan per host tidak pernah dikorbankan demi kecepatan.
  *(Tidak ada batas "sumber maksimum per putaran" — seiring waktu setiap sumber tercakup, sehingga tidak ada yang
  terabaikan.)*
- **Mode:** *Umpan RSS*, *Perayapan rekursif*, *Pasar (aturan harga)*, atau *Wikipedia
  (halaman yang dipantau)*. Memilih **perayapan** memunculkan **Kedalaman perayapan** dan **Maks. halaman /
  sumber** (perayap tetap berada di dalam domain milik setiap sumber, mematuhi robots.txt
  secara gagal-tertutup, dibatasi lajunya, dan dibatasi secara ketat — ia *menemukan* artikel, ia
  tidak mencerminkan seluruh situs).
- **Penargetan:** **Bahasa**, **Jenis sumber**, dan **Tag / kata kunci (cocok salah satu)**
  mempersempit sumber mana yang disentuh oleh satu putaran. **Pratinjau target** menunjukkan dengan tepat berapa banyak
  sumber yang cocok (dengan rincian menurut bahasa dan jenis) *sebelum* Anda menjalankannya.
- **Mulai otomatis saat diluncurkan** + **Simpan jadwal** menyimpan konfigurasi secara permanen.

**B. Penelanan manual.**

- **Telan umpan RSS sumber** — pilih sumber, klik **Ambil umpan**.
- **…atau telan satu URL artikel** — tempel URL, klik **Telan URL**.

Bagaimanapun caranya, baris hasil menampilkan rekapitulasi: tersimpan, duplikat yang dilewati, diblokir oleh
robots, dll. Pengambilan selalu etis (robots gagal-tertutup, dibatasi lajunya).

### 3.3 Sumber *(di Pengaturan → Lanjutan → Sumber)*

> **Letaknya sekarang.** Seperti Kumpulkan, katalog sumber dipindahkan ke **Pengaturan →
> Lanjutan → Sumber** (mengutamakan konten). Kontrolnya tidak berubah.

**Kegunaannya:** mendaftarkan dan mengkurasi media yang menjadi sumber pengumpulan Anda.

- **Menambah sumber:** Nama, Domain, URL RSS, Tag → **Tambah sumber**. Atau **Tambahkan
  sumber awal** untuk mendaftarkan kumpulan sumber kepentingan publik yang telah dikurasi.
- **Kelola sumber (tabel):** saring menurut teks pencarian, negara, bahasa, jenis, tag,
  dan status aktif. Kolom-kolomnya **dapat diurutkan** (Nama, Domain, Tipe, Negara, Bahasa,
  Prioritas (Priority), Artikel). Langsung di tabel Anda dapat mengubah **Prioritas** (1–3), mengalihkan **Aktif**,
  dan **Hapus** (dengan konfirmasi). Berhalaman, dengan hitungan `N source(s)`.
- **Impor / Ekspor (CSV):** **Ekspor semua (CSV)**, **Unduh templat**, dan
  **Impor CSV**. Kolom: `name`, `domain` (wajib), ditambah `rss_url`,
  `source_type`, `country` (2 huruf), `language`, `region`, `tags`
  (dipisahkan koma), `priority` (1–3), `rate_limit_ms`, `enabled`,
  `reliability_score` (1–10). Impor melakukan **upsert berdasarkan domain** — baris baru dibuat,
  yang sudah ada diperbarui — dan **baris yang buruk dilaporkan, tidak dibuang diam-diam**.

#### Kualifikasi sumber — gerbang penerimaan

**Mengaktifkan sumber saja tidak cukup** — sebuah sumber baru akan *dikikis* setelah
ia **memenuhi syarat**. Setiap sumber membawa salah satu dari tiga cap kategoris, tidak pernah
skor kualitas:

- **belum dinilai** (unqualified) — belum dinilai (bawaan untuk sumber yang ditemukan, dikutip, atau ditambahkan
  secara manual);
- **memenuhi syarat** (qualified) — lolos uji pengambilan kecil yang memeriksa *validitas ekstraksi* (prosa
  nyata vs hasil kikisan rusak/sampah, misalnya halaman menu navigasi atau dinding paywall) — kini
  sumber itu ikut dalam pengumpulan reguler;
- **didiskualifikasi** (disqualified) — halaman yang diekstrak dalam uji tersebut tampak rusak secara struktural, bukan
  sekadar "membosankan" atau ringkas (gaya tidak pernah dinilai, hanya apakah teks artikel yang nyata
  kembali atau tidak).

**Katalog terkurasi yang disertakan bersama aplikasi sudah memenuhi syarat sejak awal** (keputusan
pengelola 2026-09-10). Baris-barisnya — katalog berita, spektrum, pasar, dan hukum yang diperiksa secara manual —
membawa cap yang *dasarnya* adalah katalog itu sendiri, ditampilkan di panel asal-usul sumber
sebagai **memenuhi syarat · menurut katalog** (qualified · by catalogue), dan sumber-sumber itu ikut pengumpulan sejak hari pertama alih-alih menunggu
giliran di belakang tumpukan penemuan. Cap ini bukan hasil pengukuran dan tidak pernah dibaca sebagai
pengukuran: cap ini diperiksa ulang dengan **jam tiga bulanan yang sama seperti setiap sumber yang memenuhi syarat** (lihat di bawah),
pemeriksaan ulang yang gagal mendiskualifikasi sumber itu persis seperti sumber lain, putusan yang sudah dicapai instans
ini tidak pernah ditimpa olehnya, dan ekspor kualifikasi menghitung baris seperti itu
secara terpisah dan tidak pernah mengirimkannya sebagai putusan hasil pengukuran. Sumber yang ditemukan, dikutip, dan ditambahkan secara manual
tetap harus melewati uji.

Sebuah **tugas latar belakang menjalankan beberapa uji ini secara otomatis pada setiap putaran
pengumpulan daring** (pengambilan "beberapa artikel" yang terbatas, disetujui, dan memakai jaringan — ditolak
dalam mode pesawat, persis seperti tindakan jaringan lainnya). Pada pemasangan baru dengan
banyak sumber yang baru ditambahkan/ditemukan, aliran kecil itu dapat meninggalkan tumpukan tertunda yang nyata: **Pengaturan
→ Sumber → "Kualifikasi sumber"** menampilkan panelnya dan tombol **"Kualifikasikan tumpukan tertunda"**
yang menjalankan penilaian yang *sama* secara massal, sebagai tugas pengelola tugas yang dapat dibatalkan, untuk
mengejar ketertinggalan lebih cepat.

**Antrean kualifikasi** (Lanjutan → Gerbang kualitas) menunjukkan apa yang akan dinilai oleh putaran berikutnya,
secara berurutan: **sumber baru terlebih dahulu** (belum pernah dinilai, atau sudah dicoba tetapi artikelnya belum
cukup), lalu sumber yang pemeriksaan ulangnya sudah jatuh tempo. Sumber baru selalu lebih mendesak daripada
pemeriksaan ulang (keputusan R94). Panel itu juga menyebutkan berapa banyak sumber memenuhi syarat yang sedang menunggu dan kapan
sumber berikutnya masuk antrean.

**Berapa banyak sumber yang dinilai satu putaran** bertambah sesuai kemampuan mesin (keputusan R95): angka di
Pengaturan → Lanjutan → Gerbang kualitas (*Sumber yang dinilai setiap putaran pengumpulan*) dan
*pemeriksaan ulang kualifikasi per putaran* milik penjadwal (diatur melalui konfigurasi penjadwal, `PUT /api/scheduler/config`;
tidak ada kontrol Pengaturan untuknya) adalah batas minimum, dan selama *anggaran kualifikasi otomatis* aktif (bawaan) setiap putaran menilai sebanyak mungkin
sumber baru dan pemeriksaan ulang yang sanggup ditanggung memori dan inti prosesor mesin, tanpa batas atas yang tetap. Pengaturan
di bawah nilai bawaan, atau 0, dipertahankan apa adanya; mematikan mode otomatis mengunci angka-angka itu
secara persis. Setiap kandidat dinilai berdasarkan artikel terbarunya, sebanyak yang dapat ditampung memori yang tersedia
(sedikitnya 2.000), dan putaran itu menyebutkan untuk berapa kandidat batas tersebut berlaku.

**Pada mesin kecil** (memori lebih sedikit daripada batas bawah pemindaian aplikasi), satu putaran menilai kandidat
terhadap **sampel 20.000 artikel terbaru** alih-alih seluruh korpus, dan
putusannya mencatat bahwa penilaian itu memakai sampel (keputusan R93). Sebelum ini, mesin seperti itu melewatkan setiap
putaran tanpa pemberitahuan dan tidak ada sumber yang pernah memenuhi syarat. Jika sampel pun tidak muat, putaran itu
menyatakannya dan tidak dimulai.

**Sumber yang didiskualifikasi mendapat kesempatan kedua** — sumber itu tidak pernah dihapus, dan jam
(tidak pernah impor ulang atau kutipan baru) adalah satu-satunya pemicu pemeriksaan ulang:
1 bulan setelah diskualifikasi pertama, berlipat dua menuju batas 6 bulan (1 → 2 → 4 →
6), dan diatur ulang begitu sebuah pemeriksaan ulang lolos. **Inilah sebabnya sumber yang baru ditambahkan atau
baru didiskualifikasi dapat tetap aktif-tetapi-tidak-dikikis hingga enam
bulan** tanpa mengumpulkan apa pun — periksa pil kualifikasi pada barisnya (lihat di bawah) jika sebuah
sumber yang Anda tambahkan tampaknya tidak pernah menyumbang artikel.

**Ke mana hitungan kualifikasi pindah:** petak Pustaka yang dulu menampilkan satu angka
"Sumber" kini menjadi **tiga angka jujur yang tidak tumpang-tindih** — *Sumber
(mengumpulkan)* (Sources (collecting); aktif **dan** memenuhi syarat), *Sumber yang menunggu kualifikasi (aktif)* (Sources awaiting qualification (enabled)),
dan *Kandidat yang ditemukan* (masih nonaktif — lihat di bawah) — karena menggabungkannya menjadi
satu angka membuat tumpukan penemuan hasil mesin yang berisi puluhan ribu kandidat
terbaca seolah-olah aplikasi sudah mengumpulkan dari semuanya.

#### Verifikasi ulang — cap tidak berlaku selamanya

Putusan adalah hasil pengukuran, dan hasil pengukuran menua. **Cap memenuhi syarat diperiksa ulang
kira-kira setiap tiga bulan** (keputusan R94, 2026-09-29) (pengaturan `qualification_recheck_per_pass` milik penjadwal, hanya lewat API; 0
mematikan verifikasi ulang). Pemeriksaan ulang ini berselang tetap, bukan berlipat dua seperti tangga
sumber yang didiskualifikasi — pelipatgandaan mencerminkan harapan yang makin menipis setelah kegagalan berulang dan tidak
bermakna apa pun setelah keberhasilan.

**Apa yang dapat dan tidak dapat dilihat oleh pemeriksaan ulang, dinyatakan terus terang:** ia menilai sumber berdasarkan seluruh
riwayat yang tersimpan, jadi ia menangkap sumber yang rusak *secara luas*, dan ia **tidak** akan
menyadari sumber yang baru-baru ini memburuk jika bertahun-tahun artikel yang baik lebih berbobot daripada artikel
terbaru. Nilai sebenarnya berbeda dan layak diketahui: sumber yang diterima sangat awal,
hanya berdasarkan satu atau dua artikel, dinilai ketika korpus belum cukup besar untuk
menjadi pembanding — pemeriksaan ulang adalah kali pertama sumber itu diukur terhadap garis dasar
yang nyata.

Pemeriksaan ulang punya anggaran **sendiri**, terpisah dari anggaran untuk menerima kandidat baru.
Itu bukan hal sepele: selama keduanya berbagi anggaran, pemasangan dengan tumpukan besar
sumber yang belum diperiksa menghabiskan setiap slot untuk kandidat baru, dan tidak ada pemeriksaan ulang — termasuk
kesempatan kedua bagi sumber yang didiskualifikasi yang dijelaskan di atas — yang benar-benar pernah berjalan.

#### Putusan ikut berpindah: cadangan, dan pemasangan baru

Pekerjaan kualifikasi yang dilakukan pada satu instans **tidak hilang ketika Anda memindahkan atau menggabungkan korpus**.

- **Mengimpor cadangan** membawa putusannya. Sumber yang telah dinilai oleh korpus yang masuk
  tiba dalam keadaan sudah dinilai. Sumber yang belum pernah dinilai oleh instans *ini* **mengadopsi** putusan
  yang masuk — ke dua arah, sehingga sumber yang dianggap rusak oleh instans lain tidak
  diam-diam masuk kembali ke antrean uji di sini. Putusan yang dicapai instans *ini* selalu menang:
  korpus yang diimpor tidak pernah dapat membatalkan penilaian mesin Anda sendiri, ke arah mana pun.
  Cap awal milik katalog bukanlah putusan semacam itu: putusan impor yang *diukur*
  menggantikannya. Ketika sumber yang masih hanya membawa cap katalog memiliki penilaian impor yang lebih baru
  berupa *didiskualifikasi*, saat aplikasi dimulai berikutnya sumber itu ditarik dari pengumpulan dan dicantumkan dalam
  diagnostik; jika putusan mesin Anda sendiri berbeda dengan impor tersebut, putusan Anda yang dipertahankan dan
  sumber itu diperiksa ulang lebih awal oleh putaran kualifikasi Anda sendiri.
- **Pemasangan baru dimulai dari apa yang telah diukur oleh instans-instans sebelumnya.** Aplikasi disertai
  `configs/source_qualification.yml`, daftar putusan yang dihasilkan secara otomatis, dan mengadopsinya pada
  boot pertama untuk sumber-sumber yang belum pernah dinilainya. Sumber yang **tidak ada** dalam berkas itu
  disertakan begitu saja dalam keadaan belum dinilai dan dinilai oleh putaran kualifikasi pertama milik pemasangan itu sendiri, persis
  seperti sebelum berkas itu ada — jadi katalog yang disertakan pada dasarnya terdiri atas dua daftar: sumber
  yang sudah memenuhi syarat menurut aplikasi, dan sumber yang belum.

Putusan yang diadopsi dicatat sebagai **warisan**, bukan sebagai sesuatu yang diukur oleh mesin ini,
dan tetap menyimpan tanggal saat putusan itu pertama kali dicapai — sehingga tidak ada yang terbaca seolah-olah
pemasangan Anda yang mengukurnya. Yang dimulai dari awal adalah jam pemeriksaan ulang milik mesin Anda sendiri: jam itu berjalan sejak
hari Anda mengadopsi putusan tersebut, bukan hari pihak lain memperolehnya. Karena itu, unduhan pertama
berjalan tenang, dan memang itulah tujuannya — katalog yang disertakan selalu lebih tua daripada interval
tiga bulan pada saat sampai ke tangan Anda, sehingga menghitung jam dari tanggal aslinya akan membuat setiap
pemasangan baru mengkualifikasi ulang seluruh katalog pada hari pertama, padahal pekerjaan itulah yang
hendak dihemat oleh berkas yang disertakan.

Pertukaran itu disengaja dan memiliki harga yang perlu dinyatakan: kesegaran katalog
yang disertakan tidak lagi ditetapkan ulang oleh setiap pemasangan untuk dirinya sendiri. Kesegaran itu
ditetapkan ulang ketika versi baru dirilis dengan overlay yang disusun ulang dari instans-instans yang *telah* melakukan
verifikasi ulang. Ekspor di bawah ini melaporkan seberapa tua putusan-putusannya, sehingga ketidaksegaran itu
terlihat, bukan tersembunyi.

#### Menyumbangkan kembali putusan instans Anda

`GET /api/diagnostics/source-qualification-export` melaporkan apa yang diketahui instans Anda tentang
sumber-sumber bawaannya — berapa yang memenuhi syarat, berapa yang didiskualifikasi, berapa yang masih
tertunda — dan `?fmt=yaml` mengembalikan daftar yang sama itu sebagai berkas overlay itu sendiri.
`scripts/merge_source_qualification.py` menggabungkan ekspor dari beberapa instans menjadi satu.

Jika Anda sudah mengumpulkan **bundel semua-diagnostik** (all-diagnostics bundles) dari instans-instans itu, Anda tidak perlu
kembali dan mengekspor ulang: bundel tersebut membawa ekspor yang sama sebagai salah satu anggotanya, dan
`--from-bundle` membacanya langsung dari zip. Kedua jalur dapat saling menggantikan dan
dapat dicampur dengan bebas dalam satu kali jalan:

```
python scripts/merge_source_qualification.py laptop-export.json \
    --from-bundle oo-all-diagnostics-desktop.zip \
    --from-bundle oo-all-diagnostics-server.zip
```

Laporan yang dicetak menyebutkan berapa instans yang digabungkan dan melalui jalur mana. Bundel yang
anggota ekspornya tidak selesai disebutkan namanya, beserta alasan yang dicatat instans itu — bundel itu
tidak pernah dilewati diam-diam, karena overlay yang Anda kira bersandar pada tiga instans padahal
sebenarnya hanya bersandar pada dua lebih buruk daripada sebuah galat.

Ada dua hal yang sengaja tidak akan dilakukannya. Ia tidak pernah **menyelesaikan perbedaan pendapat**: jika satu
instans menyatakan sebuah domain memenuhi syarat sementara instans lain mendiskualifikasinya, hal itu dilaporkan agar diperiksa
manusia, karena memilih pemenang secara otomatis berarti mengirim putusan yang tidak pernah ditinjau siapa pun ke setiap pemasangan.
Dan ia tidak pernah menghitung putusan **warisan** sebagai penguat — mengimpor satu cadangan ke
delapan mesin adalah satu pengukuran yang terlihat delapan kali, bukan delapan pengukuran.

#### Jejak penemuan & rekap kutipan yang memenuhi syarat

Klik baris sebuah sumber untuk **membentangkan jejak penemuannya**: **di mana sumber itu ditemukan**
(saluran kutipan, katalog, referensi Wikipedia, …) dan, untuk
sumber yang ditemukan lewat kutipan, **artikel pertama yang mengutipnya** (dengan tautan ke
artikel tersebut maupun ke sumber yang mengutip). Di sampingnya, **rekap kutipan yang memenuhi syarat** menghitung
domain yang dikutip oleh sumber *ini* sendiri, dibagi menjadi **memenuhi syarat / didiskualifikasi /
tertunda / tidak terdaftar** — setiap angka dapat diklik dan dibentangkan menjadi daftar persisnya.

Ini adalah **fakta deskriptif, tidak pernah putusan atas salah satu sumber** — mengutip
domain yang didiskualifikasi bukanlah kesalahan (media yang sehat lazim menautkan perusahaan,
platform, atau halaman rusak yang sekadar *diberitakannya*), dan mengutip banyak domain
yang memenuhi syarat juga bukan dukungan (kantor berita dikutip oleh semua pihak; pusat
pencucian informasi dapat sengaja mengutip sumber terpercaya). Bacalah ini sebagai petunjuk untuk
diselidiki, sama seperti setiap sinyal terukur lain di aplikasi ini adalah petunjuk, bukan
skor.

#### Bahasa yang belum dapat kami analisis — nonaktif secara bawaan (tetap disimpan)

Mesin kata kunci/analitik hanya dapat **menangani** bahasa yang memiliki *stoplist* (daftar kata henti)
dan yang aksaranya **dipisahkan spasi**. Daftar resminya ada di satu
modul — [`src/analytics/managed.py`](../src/analytics/managed.py) (`MANAGED_LANGUAGES`)
— yang dibaca baik oleh penyaringan sumber maupun laporan mesin di dalam aplikasi, sehingga panduan ini tidak dapat
menyimpang dari kode. Menurut modul tersebut, kumpulan yang ditangani adalah: **en, fr, de, es, it, pt, nl,
ru, ar, hu, id, sv, da, nb, no, pl, sr, sl, el, bg, hi, bn, fa, ur, uk, ro, cs, sk, ca,
sw, az, et, tr, fi, bs, hr**. Bahasa yang **tidak** ada dalam kumpulan itu tetap *ditokenisasi*, tetapi
kata-kata fungsinya (padanan "the/of/and") bocor masuk sebagai kata kunci palsu. **ja dan th tidak
tersegmentasi** kecuali komponen tambahan opsional `[segmentation]` dipasang — keduanya tidak memiliki
spasi antarkata, sehingga tanpa segmenter ekstraksi kata kunci rusak sepenuhnya, terlepas
dari ada atau tidaknya stoplist. **zh** berada dalam posisi yang sama sampai jieba menjadi dependensi inti di
0.4; bahasa itu tersegmentasi, dan karena itu ditangani, di setiap pemasangan.

Karena itu, mengikis materi dalam bahasa-bahasa tersebut menghasilkan **kata kunci sampah** yang:

- **mencemari analitik** — kata kunci palsu mendistorsi asosiasi, tren, dan
  supergrup, dan
- **membengkakkan korpus** — setiap agregasi (Wawasan, Grup, peta pikiran) menanggung
  beban ratusan ribu baris tak bermakna, yang merupakan hambatan
  kinerja nyata pada korpus besar.

Jadi, memang dirancang demikian: **sumber baru dalam bahasa yang tidak ditangani ditambahkan dalam keadaan *nonaktif***. Sumber itu
**tetap disimpan** (tidak pernah dihapus) dan sepenuhnya **dapat diaktifkan kembali** — Anda tetap dapat membaca
media tersebut, dan begitu stoplist untuk bahasanya ditambahkan, Anda dapat mengaktifkannya kembali.
Ini adalah pertukaran yang jujur: kami lebih memilih *tidak mengumpulkan* apa yang akan kami *rusak*
daripada menyajikan analitik yang tidak dapat diandalkan. `enabled: true` yang **eksplisit** dalam impor CSV
selalu menang (kurasi Anda dihormati), dan sumber yang bahasanya **tidak diketahui**
tetap aktif (kami tidak pernah menonaktifkan apa yang tidak dapat kami klasifikasikan).

**Untuk menerapkan ini pada korpus yang sudah ada:** Pengaturan → Lanjutan → Sumber menunjukkan berapa banyak sumber
aktif yang berbahasa tidak ditangani (dan bahasa apa saja) serta menawarkan **"Nonaktifkan sumber dalam
bahasa yang belum bisa kami analisis"** — tindakan massal yang dapat dibatalkan untuk menonaktifkannya
(tetap disimpan). Aktifkan kembali salah satunya kapan saja dari tabel sumber.

### 3.4 Pustaka

*(Disebut **Basis data** sebelum 0.05.)*

**Kegunaannya:** pandangan jujur tentang apa yang benar-benar Anda miliki, dan seberapa luas jangkauan
sumber-sumber Anda.

- **Statistik basis data (Database stats):** hitungan langsung beranimasi (artikel, sumber, domain unik,
  …), ditambah backend serta **ukuran dan jalur di disk** dari basis data. Setiap
  angka adalah hitungan atau ukuran byte yang nyata — tidak ada yang diperkirakan.
- **Cakupan dunia:** berapa banyak negara yang dijangkau katalog sumber Anda, dihitung
  terhadap ISO 3166 — `covered/total countries`, `coverage %`, jumlah yang *tidak* tercakup,
  dan jumlah yang "tipis" (di bawah ambang batas). Negara disimpan sebagai kode ISO-2 huruf kecil
  dan **ditampilkan dengan nama lengkapnya** (satu lapisan konversi,
  `src/catalog/countries.py`). Blok **Keseimbangan regional** membandingkan sumber dan negara yang tercakup
  di setiap benua dengan batas bawah kerja di
  `configs/catalog_targets.yml` (aspirasi yang diberi label jelas, disusun dari
  bentuk katalog yang nyata), ditambah **pengaman konsentrasi** negara teratas — metrik
  pengurangan dominasi AS dari 0.0.9. Tabel mencantumkan setiap negara beserta wilayahnya, jumlah
  sumber, dan **pil kata kunci topik** (dari tag sumber). **Klik sebuah negara atau
  kata kunci** untuk melompat ke Sumber yang tersaring tepat pada sumber-sumber tersebut. Laporan kesenjangan
  menyebutkan negara-negara yang belum memiliki sumber. Panel ini diperbarui secara langsung (tidak perlu tombol
  Segarkan); metrik yang sama tersedia secara offline melalui
  `python scripts/catalog_coverage_report.py`.

### 3.5 Pasar

**Kegunaannya:** melacak harga komoditas / mata uang / energi yang **nyata** dan
mengaitkannya dengan volume berita.

- **Dasbor tren pasar (Market trends dashboard):** satu kartu per deret harga — simbol, % perubahan, harga
  terbaru (mata uang/satuan), jumlah titik, dan sparkline mini. Kontrol **rentang waktu**
  — kolom tanggal Dari/Sampai, bilah rentang yang dapat diseret, dan prasetel cepat (1M · 6M · 1Y ·
  5Y · All) — membentuk ulang setiap kartu menurut jendela awal/akhir yang tepat (bukan daftar
  skala yang tetap); deret lengkap selalu digambar dengan resolusi penuh di dalamnya, tidak pernah
  dijarangkan. Klik sebuah kartu untuk bagan lengkap ditambah
  **korelasi harga↔berita** (koefisien Pearson/Spearman yang nyata, nilai-p, dan
  ukuran sampel — tidak pernah angka tebakan). Umpan resmi terkurasi **diperbarui
  otomatis di latar belakang** selama Anda daring (tidak ada tombol Muat/segarkan);
  papan ini juga memiliki **subtab kategori**, pengalih tampilan **Kartu/Keluarga**,
  overlay **Bandingkan** (dengan pengalih skala Absolut/Terindeks/Log) dan sumbu waktu bersama.
- **Konfigurasi sumber data (Configure data sources)** (dapat diciutkan — sebagian besar pengguna tidak memerlukannya):
  - **Umpan harga resmi** (FRED, yang memuat deret **"Pink Sheet" Bank Dunia**
    dan **EIA**): **Impor** sekali klik, ditambah **Bagan**.
  - **Aturan ekstraksi harga (Price-extraction rules):** tambahkan aturan (Sumber, Simbol, Label, URL Halaman, **selektor
    CSS**, atribut/regex opsional, mata uang, satuan, pasar). Aturan emasnya:
    **angka hanya disimpan jika selektor Anda benar-benar mengenai sebuah angka — tidak pernah
    ditebak.** Gunakan **Uji** untuk mengambil halaman sekali dan melihat nilai persis yang ditemukan, atau
    alasan persis mengapa tidak cocok, sebelum mengandalkannya.
  - **Umpan khusus (URL CSV apa pun):** arahkan ke CSV mana pun (pemetaan bawaan adalah kolom 1 =
    tanggal, kolom 2 = nilai, konvensi FRED); nilai yang hilang dilewati, tidak pernah
    disimpan sebagai nol.

Lihat [`docs/USER_MANUAL.md`](USER_MANUAL.md) untuk referensi lengkap aturan ekstraksi.

### 3.5a Indeks

**Kegunaannya:** **indeks** pasar saham dunia (S&P 500, NASDAQ, Dow Jones,
VIX, Nikkei 225 …) — dipisahkan **dari Komoditas**, karena indeks adalah
indeks, bukan komoditas.

- Papan deret indeks dengan bagan terperinci beresolusi penuh yang sama seperti
  Komoditas (subtab kategori, saringan tag, overlay Bandingkan, tampilan Keluarga, sumbu
  waktu bersama). Umpan resmi terkurasi (FRED, Stooq) **diperbarui otomatis di
  latar belakang** selama Anda daring — tidak ada tombol Impor/segarkan.
- Setiap umpan membawa **putusan per umpan yang jujur** ketika tidak dapat diambil —
  *ditolak* ≠ *dilarang robots* ≠ *deret mati* ≠ *tidak terjangkau* ≠ *offline* — sehingga
  umpan yang diblokir menurun kinerjanya secara terang-terangan alih-alih menampilkan angka palsu. Melalui Tor beberapa
  umpan diblokir oleh host-nya; putusan menyebutkan persis hal itu (lihat §5.5).

### 3.6 Wawasan

**Kegunaannya:** analitik kata kunci & entitas atas **teks artikel yang telah
ditelan**. *(Memerlukan komponen tambahan `[analysis]`; pengenalan entitas bernama yang sesungguhnya bersifat
opsional melalui komponen tambahan spaCy `[nlp]`.)*

- **Status & pengindeksan:** sebuah pil menampilkan `indexed/total articles · keywords (entities)
  · mentions · remaining`. **Pengindeksan berjalan otomatis** — mengikuti penelanan, dan saat Anda
  membuka Wawasan, pengisian latar belakang yang senyap menuntaskan sisa tumpukan (hitungan "remaining"
  turun sendiri hingga 0). **Tidak ada tombol "Indeks korpus" (Index corpus)** — tombol itu
  dihapus dan digantikan pengindeksan otomatis. Orang, organisasi, dan tempat disimpan sebagai
  satu kesatuan; pengindeksan dapat dilanjutkan dan bilahnya diperbarui secara langsung. *(Matikan pengindeksan
  otomatis dengan `OO_NO_INDEX=1`.)*
- Delapan subtab:
  - **Jelajahi** — ketik kata kunci atau entitas (mis. *inflasi*, *Emmanuel Macron*,
    *Rio Tinto*) untuk mendapatkan: garis **tren** dari waktu ke waktu; **peta pikiran asosiasi**
    (istilah yang muncul bersamaan, diperingkat menurut PMI — lebar sisi = kemunculan bersama, jarak =
    kekuatan; klik sebuah simpul untuk menjadikannya pusat); tabel **pembingkaian** (bagaimana nada setiap media
    berbeda, melalui VADER, beserta istilah yang ditonjolkannya); dan cuplikan **dalam konteks**
    dengan tautan sumber/tempat/tanggal.
  - **Tren** — **Meningkat** (kata kunci yang tumbuh paling cepat, jendela terbaru vs. garis dasar) dan
    **Teratas** (paling sering disebut), ditambah tiga jendela prasetel (24h · week · month) berdampingan,
    dapat disaring menurut jenis (istilah/entitas/orang/organisasi/tempat) dan negara. Klik istilah
    mana pun untuk Menjelajahinya; klik ✕ untuk mengecualikannya.
  - **Sumber** — sumber yang sedang tren di seluruh korpus Anda.
  - **Keluarga** — keluarga kata kunci (varian morfologis disatukan).
  - **Grup** — supergrup (konsep payung yang tahan lama) dan **cincin** lintas bahasa
    (sebuah konsep beserta terjemahan/sinonimnya), dapat disunting.
  - **Peta** — choropleth ooMap atas korpus Anda (komponen yang sama dengan tab Peta
    dunia).
  - **Konvergensi** — kemunculan bersama dalam ruang-waktu yang hanya-baca: artikel yang berkumpul pada **tempat**
    yang sama dalam satu jendela waktu pada tanggal peristiwa yang disebutkan. Independensi diukur
    dengan **sumber yang berbeda** (satu sumber yang cerewet tidak dapat menciptakannya sendiri); setiap klaster
    membawa catatan kehati-hatian "kemunculan bersama, tidak pernah sebab-akibat — dorongan untuk membaca, bukan bukti".
  - **Pemantauan** — kondisi "jika-ini-maka-pantau" yang Anda simpan: kueri FTS lokal + sebuah
    ambang batas + sebuah jendela. Ketika korpus memperoleh cukup banyak artikel baru yang cocok, sebuah **Petunjuk
    pemantauan** muncul di Beranda. Hanya lokal, tanpa notifikasi, tanpa jaringan, tanpa telemetri;
    buat / aktifkan / sunting / hapus, dengan riwayat kecocokan.

Setiap angka adalah agregat nyata beserta ukuran sampel dan catatan kehati-hatiannya. Lihat
[`docs/USER_MANUAL.md`](USER_MANUAL.md). Untuk mengatur kata kunci mana yang muncul, gunakan
[saringan kata kunci di Pengaturan](#39-pengaturan).

### 3.6a Peta dunia

**Kegunaannya:** melihat *di mana* korpus Anda berada — sebuah **choropleth** ("Cakupan
dunia") yang mewarnai setiap negara menurut dimensi terukur dari data Anda, dengan lapisan
opsional untuk tempat, sinyal, dan lokasi server. Peta ini dibangun di atas satu komponen peta yang dapat dipakai ulang
(**ooMap**), dan setiap kontrol berada **di dalam peta** (konvensi Google Maps):
zoom ＋/－, zoom dengan roda tetikus, geser dengan seret, ⛶ perbesar, dan pemilih lapisan/ukuran.

- **Ukuran choropleth (pemilih di dalam peta):** ganti apa yang mewarnai negara-negara di antara
  **Sumber · Artikel · Penyebutan kata kunci · Nada rata-rata**. Hitungan memakai skala sekuensial;
  **Nada rata-rata** memakai skala **divergen** (positif ↔ negatif di sekitar nol) dan membawa
  catatan kehati-hatian **VADER hanya-bahasa-Inggris** ditambah `n` artikel yang dinilai — negara tanpa
  artikel berbahasa Inggris yang dinilai menampilkan "tidak ada data", tidak pernah nilai netral rekaan.
- **Tidak-ada-data yang jujur ≠ nol:** negara tanpa data berlokasi digambar dengan **pola arsir**
  berlabel "tidak ada data", berbeda secara visual dari nol yang sebenarnya. Wilayah kecil yang tidak dapat digambar oleh
  garis kasar muncul sebagai **titik**; sumber tanpa negara **dihitung tetapi
  tidak pernah ditempatkan** ("N not mapped").
- **Granularitas (pengalih di dalam peta):** tampilkan menurut **Negara** atau agregasikan ke **Benua**
  (jumlah untuk hitungan, rata-rata berbobot `n` untuk nada — tidak pernah rata-rata dari rata-rata; benua
  yang tidak diketahui dengan jujur ditandai "tidak ada data").
- **Overlay Tempat:** nyalakan **Tempat** untuk memetakan lokasi yang *dibicarakan* artikel Anda
  (dari Kapan/Di mana/Siapa yang diekstrak saat penelanan, pada koordinat gazetir) sebagai
  penanda berongga yang ukurannya mengikuti sebaran artikel — dengan catatan kehati-hatian **"Disimpulkan dari teks, tidak pernah
  dikonfirmasi."**
- **Lapisan Sinyal + momen dalam fokus:** nyalakan **Sinyal** untuk memetakan peristiwa ruang-waktu
  yang bertanggal (jangkar terkurasi, artikel korpus, tanggal yang diekstrak) sebagai titik berwarna menurut jenisnya;
  **penggeser momen-dalam-fokus** menyapu waktu (terkonfirmasi = terisi, masa depan/belum terkonfirmasi = cincin
  putus-putus, memudar seiring jarak waktunya). Klik sebuah penanda untuk panel detail — tanggal,
  tempat, sumber, tautan resmi, **"Temukan liputan di korpus Anda"**, dan daftar **"Dekat dalam
  ruang & waktu"** yang secara tegas menyatakan bahwa kemunculan bersama *"bukan hubungan atau
  sebab. Andalah yang menilai."*
- **Lapisan IP server:** secara opsional tampilkan **lokasi server** sumber yang digeolokasi secara offline —
  dengan catatan kehati-hatian jujur bahwa ini adalah tepi CDN / host anycast, **bukan** bukti
  asal sebenarnya penerbit (dan tidak tersedia melalui Tor, karena di sana soket mengarah ke
  proksi, bukan server).
- **Garis pantai & perbatasan sudah disertakan:** geometri negara/garis pantai disertakan bersama aplikasi
  (Natural Earth, disederhanakan) — tidak ada yang perlu dibangun, tidak ada perbatasan yang direka.

Tanggal yang *dibicarakan* sebuah berita juga menjadi **tag tanggal per artikel**: buka pembaca
offline sebuah artikel untuk melihat daftarnya, **konfirmasi atau tolak** setiap kandidat, atau **ekstrak** sesuai permintaan;
korpus kemudian dapat disaring menurut tanggal yang disebutkan (`GET /api/article-dates/by-date`).
Pengekstraknya berpresisi tinggi: tahun saja dan rentang yang samar tidak diekstrak, tetapi
**kata relatif yang berjangkar** ("kemarin") dan **nama hari saja** diekstrak.

### 3.6b Agenda

**Kegunaannya:** kalender peristiwa bertanggal — apa yang akan datang, bersumber dan jujur.

- **Kisi bulan** (dimulai hari Senin; nama bulan/hari dalam bahasa UI Anda) adalah
  tampilan bawaan, dengan tampilan **Minggu · Triwulan · Semester · Tahun · Dekade · Daftar**
  di sampingnya (satu bilah navigasi bersama). Hari yang memiliki peristiwa diberi tanda; klik sebuah hari untuk
  detailnya, dan klik judul peristiwa untuk membukanya di korpus.
- **Peristiwa yang disimpulkan (dari artikel Anda):** tanggal masa depan yang *disebutkan* di beberapa
  artikel muncul sebagai lapisan **disimpulkan** yang terpisah dan dapat disaring — setiap entri menampilkan
  pil "disimpulkan · tidak pernah dikonfirmasi" serta hitungan artikel/sumber, dan judulnya membuka
  kumpulan artikel yang persis itu. Hanya hitungan, tidak pernah putusan.
- **Astronomi, dihitung secara lokal:** empat fase bulan utama (bulan baru, kuartal pertama, purnama, kuartal terakhir) serta ekuinoks/solstis
  dihitung di mesin ini (algoritma Meeus, diverifikasi terhadap nilai almanak
  yang dipublikasikan); setiap entri menyatakan **metode dan akurasinya** di gelembung hover.
  Musim dinamai **dengan jujur sesuai belahan bumi** — tidak pernah sekadar "musim panas".
- **Konteks iklim:** set data episode El Niño / La Niña yang disertakan (konvensi ONI NOAA CPC);
  setiap entri yang masih menunggu pemeriksaan silang lewat clearnet membawa
  tanda menunggu-verifikasi.
- **Tanggal yang berpindah-pindah ditandai demikian** — aplikasi tidak pernah merekayasa hari pasti untuk
  peristiwa yang tanggalnya bergeser setiap tahun.
- **Kalender** (sumber iCal hari libur / keagamaan / astronomi) dilanggan di
  **Pengaturan → Agenda**, bukan di sini — tab ini menampilkan data, sedangkan saluran pipanya berada di
  Pengaturan. Setelah itu kalender-kalender itu memperbarui dirinya sendiri: selama pengumpulan aktif, peristiwa baru
  diimpor dan setiap umpan diperiksa ulang secara bergiliran, beberapa per putaran. Umpan yang gagal
  diperiksa ulang setelah 1 bulan, lalu 2, 4, dan 6 — **dibatasi, sehingga umpan tidak pernah dihapuskan
  secara permanen** — dan rekap per putaran terlihat di **tab Jadwal pengelola
  tugas**. Tidak ada satu pun yang berjalan saat aplikasi dimulai atau saat offline. **Katalog** berisi ~500 umpan itu sendiri
  (putusan, folder penyedia duplikat, menambahkan `.ics` Anda sendiri) adalah saluran pipa dan
  berada di **Pengaturan → Lanjutan → Direktori kalender**.
- **Jika berkas peristiwa yang diimpor rusak sehingga tidak ada isinya yang dapat dibaca** (terpotong,
  bukan JSON yang valid, atau galat baca dari disk di Linux atau macOS), Agenda membacanya sebagai kosong dan log
  menyebutkannya. Sebelum penyimpanan berikutnya menggantikannya (impor, pemulihan, penghapusan umpan), aplikasi menyimpan berkas yang rusak itu satu kali,
  tanpa diubah, sebagai `calendar_feed_imports.json.damaged` di folder data Anda, untuk Anda atau
  alat pemulihan; kerusakan kedua tidak pernah menimpa salinan pertama itu. Berkas itu bukan bagian dari
  cadangan. Anda dapat menghapusnya sendiri kapan saja. Berkas yang hanya sebagian entrinya rusak
  tetap dibaca: entri-entri itu ditinggalkan, log menghitungnya, dan tidak ada salinan yang dibuat.
  Berkas kosong juga tidak disalin: tidak ada isinya yang perlu dipulihkan.

### 3.6b Sumber hidup

Tab **Sumber hidup** menunjukkan apa yang berubah pada sumber-sumber yang terus berubah
setelah Anda mengumpulkannya: Wikipedia, hukum, dan peta, masing-masing satu subtab. Semua isinya
dibaca dari mesin ini; tidak ada yang diambil untuk menggambarnya.

- **Wikipedia:** berapa banyak halaman yang diikuti aliran langsung, berapa banyak perubahan yang
  dilaporkannya dalam 30 hari terakhir dan **berapa banyak yang teksnya disimpan** ("2 dari 4":
  di bawah anggaran, aliran menyimpan sebagian dan menghitung sisanya), titik sampai mana setiap
  umpan dibaca tanpa terputus, dan setiap celah yang diketahuinya terlewat. Di bawahnya, setiap
  perubahan dengan yang terbaru di atas; **Tampilkan diff** membuka diff yang disimpan saat perubahan itu tiba.
  Perubahan yang hanya dihitung menyatakan hal itu dan tidak memiliki diff. Halaman yang Anda lacak secara
  manual (Pengaturan → Wikipedia) juga dicantumkan: pilih salah satunya untuk membaca revisi
  yang dilacaknya. Setiap versi di kedua ujung perbandingan memiliki tombol **Tambahkan ke
  korpus** sendiri: tombol itu menambahkan versi yang persis itu sebagai artikelnya sendiri, bertanggal saat wiki membuatnya,
  dan menyebutkannya jika korpus Anda sudah menyimpan versi itu atau kata-kata yang sama. Versi
  yang teksnya tidak disimpan tidak dapat ditambahkan, dan tombolnya menyebutkan alasannya. Beginilah cara
  revisi yang disimpan oleh **Lacak sekarang** masuk ke korpus Anda, karena pencarian belum membacanya.
  Ketika **penelusuran halaman** aktif (lihat di bawah), grup *Penelusuran halaman* menyebutkan apa yang sedang
  dilakukannya (menelusuri; dijeda, beserta alasannya; atau menunggu penolakan dari wiki berlalu) dan,
  per edisi, halaman-halaman yang telah didaftarnya **dari jumlah artikel milik edisi itu sendiri**
  ("1 234 000 dari 2 700 000"). Itu adalah dua hitungan, tidak pernah persentase: setiap edisi
  menghitung artikelnya dengan caranya sendiri, sehingga angka pertama dapat melampaui angka kedua. Ketika
  pengambilan **halaman lain yang berubah** aktif (lihat di bawah), grup *Halaman lain yang berubah*
  (di atas grup penelusuran) menghitung halaman yang memiliki teks, halaman yang berubah yang masih menunggu
  teksnya, teks yang telah diambil, dan halaman yang sejak itu menjadi halaman yang diikuti aliran,
  juga per edisi, dan menyebutkan kapan ia berhenti: pada porsi tertentu dari anggaran
  penyimpanan, sebuah nilai bawaan usulan yang ditampilkan aplikasi, bukan sebuah keputusan.
- **Hukum:** dokumen yang diikuti pelacak hukum, pemeriksaan terbaru dan tertua, serta
  setiap perubahan nyata (pemeriksaan ulang yang tidak mengubah apa pun tidak dihitung) dengan
  diff tersimpannya dan tautan ke salinan lokal Anda.
- **Peta:** wilayah peta yang telah Anda unduh, mana yang dijeda atau gagal dan alasannya, serta
  ruang yang dipakainya.

Kesegaran ditampilkan sebagai tanggal, tidak pernah dinilai: seberapa baru yang cukup baru bergantung pada
beritanya. Anggaran ditampilkan tetapi diatur di **Pengaturan → Data & cadangan**.

### 3.6c Iklim

**Kegunaannya:** membaca enam catatan iklim dan Bumi yang dipublikasikan di samping korpus Anda,
masing-masing persis seperti yang dirilis penerbitnya. Tab ini memiliki satu subtab per set data:

- **Suhu** — NASA GISTEMP v4: *anomali* suhu global bulanan dan tahunan
  (selisih dari rata-rata 1951-1980, dalam °C, bukan suhu).
- **Es laut** — NSIDC Sea Ice Index v3: luas es laut Arktik atau Antarktika harian, dalam
  juta km².
- **El Niño** — Oceanic Niño Index milik NOAA: anomali suhu permukaan laut tiga bulanan
  di wilayah Niño 3.4 di Pasifik.
- **Gempa bumi** — katalog USGS: gempa bumi bermagnitudo 6,0 ke atas di seluruh dunia,
  dihitung per bulan sejak Januari 1973, dengan magnitudo terbesar setiap bulannya.
- **Emisi & energi** — Our World in Data: angka emisi dan energi tahunan menurut
  negara dan wilayah, setiap kolom mempertahankan ketentuan (lisensi) asli dari produsennya.
- **Stasiun cuaca** — NOAA GHCN-Daily: suhu, curah hujan, dan salju harian di
  **satu** stasiun, dipilih berdasarkan id 11 karakternya (misalnya `USW00094728`, New York
  Central Park). Satu stasiun menggambarkan satu tempat, bukan suatu wilayah dan bukan iklim.

**Cara pengambilannya.** Tidak ada yang diunduh sampai Anda memintanya. Setiap subtab memiliki tombol
**Ambil dari penerbit** sendiri (tombol itu bertuliskan **Perbarui dari penerbit** setelah ada sesuatu
yang tersimpan; pada **Stasiun cuaca** Anda mengetik id stasiun lalu menekan **Ambil stasiun**, kemudian
**Perbarui stasiun ini**), yang menyebutkan server yang dihubunginya. Tombol itu melewati popup persetujuan yang sama seperti setiap
tindakan jaringan lainnya dan ditolak selama mode pesawat aktif. Pengambilan berjalan di
latar belakang; pengelola tugas menampilkannya. Membaca apa yang sudah tersimpan tidak melakukan panggilan
jaringan.

**Apa yang dapat Anda andalkan.** Setiap subtab menyebutkan sumbernya, lisensinya, metodenya, dan kapan
mesin ini terakhir mengambilnya. Pengambilan baru hanya menyimpan nilai yang baru atau yang
direvisi penerbit: nilai sebelumnya tetap dapat dibaca, dan periode yang tidak lagi disajikan penerbit
dihitung, tidak pernah dihapus. Sel kosong adalah celah yang dipublikasikan, tidak pernah nol. Tidak ada satu pun di sini yang
merupakan prakiraan, skor, atau peringkat risiko.

### 3.6d Observatorium

**Kegunaannya:** melihat seluruh korpus Anda sekaligus, digambar sebagai langit malam. Setiap
**galaksi** adalah sekelompok kata kunci yang berkaitan; setiap irisan lingkaran adalah salah satu dari dua belas
domain topik.

- **Sudut** hanya membawa domain. Posisi sebuah galaksi di dalam irisannya adalah hash
  yang stabil, sehingga tetap di tempatnya dari kunjungan ke kunjungan dan tidak bermakna apa pun dengan sendirinya.
- **Jarak dari pusat** membawa satu ukuran yang Anda pilih, dengan cincin berlabel.
  **Ukuran bintang** digambar sebagai luas (penyebutan) dan merupakan isyarat sekunder.
- **Warna** menunjukkan bahasa, atau lensa **Tren**; warna tidak pernah menjadi satu-satunya sinyal.
  Garis rasi menghubungkan galaksi yang berbagi kata kunci anggota, tidak pernah galaksi yang
  sekadar tampak berdekatan.
- **Tabel peringkat** (ranked table) di bawah langit mencantumkan setiap galaksi secara lengkap, termasuk yang
  tidak dapat ditempatkan di langit. Tabel adalah tampilan kanonis; langit adalah cara kedua untuk
  membacanya. Sebuah baris di atasnya menghitung apa yang ditinggalkan gambar (galaksi yang belum teramati, dan
  kata kunci di luar semua galaksi).
- Korpus yang sama selalu menggambar langit yang sama, sehingga perubahan yang Anda lihat adalah perubahan pada
  data Anda. Tidak ada skor gabungan.

### 3.7 Wikipedia *(di Pengaturan → Wikipedia)*

> **Letaknya sekarang.** Pelacakan perubahan Wikipedia dan alat dump luring kini
> dipindahkan ke **Pengaturan → Wikipedia** (konten diutamakan); halaman yang dipantau tetap
> muncul dalam pencarian umum dan analisis seperti artikel lainnya. Kontrolnya tidak berubah.

**Kegunaannya:** memantau halaman Wikipedia tertentu dan **menandai suntingan yang
mencurigakan** — yang menjadi data adalah *suntingannya*, bukan salinan artikelnya.

- Tambahkan halaman untuk dipantau dengan **Edisi** (kode bahasa, mis. `en`, `fr`, `ar`),
  **Judul artikel (Article title)**, dan label **Daftar pantauan** opsional. Aplikasi menyimpan **satu
  snapshot dasar**, lalu hanya **diff/delta** dari setiap suntingan baru — sehingga perubahan
  kosmetik nyaris tidak memakan ruang.
- **Lacak sekarang** (opsional **gunakan skor ORES**) menarik revisi baru dan menandai
  revisi yang besar atau mencurigakan: delta ukuran yang besar, tag revert/pengosongan, suntingan anonim,
  ledakan suntingan, dan — jika diaktifkan — skor ML ORES untuk merusak/beriktikad baik. Kandidat
  *ditampilkan agar Anda yang menilai*; tidak ada yang diberi label "disinformasi."
- **Perubahan yang ditandai** mencantumkan suntingan (Kapan · Edisi · Halaman · Penyunting · Δ bita ·
  Alasan · ORES), dengan penampil **Perbedaan** dan tautan **langsung (live)** ke Wikipedia.
  Saring dengan *hanya yang ditandai* dan berdasarkan edisi.

**Halaman yang dipantau adalah artikel korpus (pilihan sumber hidup, dinyatakan terbuka):**
setiap halaman yang Anda pantau juga masuk ke korpus Anda sebagai artikel di bawah sumber
per edisi ("Wikipedia (en)"), sehingga muncul dalam **pencarian umum, kata kunci, dan
Kapan×Di mana×Siapa seperti artikel lainnya**. Pilihan yang dibuat aplikasi untuk Anda,
secara terlihat: (1) yang dilihat oleh pencarian dan analitik selalu **versi terbaru**
yang telah diambil pelacak, dan id revisi persis yang sesuai dengannya
dicatat; (2) **teks lengkap setiap revisi yang dilacak disimpan di mesin
ini** — versi-versi lama tetap dapat direkonstruksi secara persis (analitik berjangkar versi,
tanpa memutar ulang diff), dengan konsekuensi jujur bahwa penyimpanan bertambah seiring aktivitas
suntingan; (3) teks yang dianalisis adalah wikitext yang disederhanakan menjadi teks biasa — tidak pernah
disajikan seolah-olah artikel yang telah dirender. Semuanya tetap lokal; riwayat
perubahan tetap tersedia per halaman, dan tab **Sumber hidup** menampilkannya
([3.6b](#36b-sumber-hidup)).

**Anggaran penyimpanan jalur ini (150 GB secara bawaan, Anda bebas menurunkannya):** jalur Wikipedia
berhenti menyimpan teks pada total yang Anda tetapkan di wisaya penggunaan pertama (atau di **Pengaturan →
Penyimpanan**, di samping perhitungan terhadap ruang disk kosong mesin ini). Nilai bawaannya
**150 GB** sejak putusan 2026-09-29, naik dari 20 GB; turunkan ke 20 GB, atau ke angka berapa pun
hingga 1 GB, jika disknya kecil. Instalasi yang sudah melewati wisaya
mempertahankan angka yang telah disetujuinya; instalasi yang belum pernah melihat wisaya mengikuti nilai bawaan baru
sampai Anda menetapkan angka sendiri.

**Penelusuran halaman (nonaktif kecuali Anda menyalakannya):** aliran langsung hanya pernah mendengar
tentang halaman yang disunting seseorang, sehingga sebagian besar ensiklopedia tidak pernah sampai kepadanya. Mencentang
**Telusuri juga setiap judul artikel** (Pengaturan → Wikipedia, di bawah *Aliran suntingan
langsung*) mendaftar setiap artikel dari edisi yang Anda pilih, 50 judul per permintaan, satu
permintaan pada satu waktu, di sela-sela pembacaan aliran itu sendiri, selama beberapa hari. Ia menyimpan
judul, ukuran, revisi terbaru, dan id Wikidata setiap halaman, tidak pernah teksnya, di dalam anggaran
penyimpanan yang sama, dan tidak pernah diubah menjadi halaman yang diikuti aliran secara penuh. Ia
hanya berjalan selama aliran langsung berjalan, pada koneksi yang sama: mode pesawat, atau
mode terlindung tanpa proksi yang dapat dipakai, membuatnya **menunggu** (ia tidak pernah tersambung langsung), dan
wiki yang memintanya melambat akan ditanya lagi setelah jeda yang berlipat dua hingga satu
jam. Mulai ulang melanjutkan setiap edisi dari titik ia berhenti. Kemajuannya ada di **Sumber
hidup** dan di pengelola tugas.

**Mengapa penelusuran bisa menunggu di belakang pengurasan pertama aliran.** Aliran menyimpan apa yang didengarnya dalam
sebuah pengurasan (drain) setiap 30 detik; indeks pencarian, pengambilan halaman lain yang berubah, dan penelusuran berjalan
pada waktu *setelah* setiap pengurasan. Sebuah pengurasan mengambil teks halaman yang diikuti yang berubah,
dan di belakang tumpukan tunggakan (aliran yang dilanjutkan dari beberapa jam lalu) itu berarti ribuan permintaan sopan, sehingga
pengurasan kini memiliki **batas 20 detik untuk mengambil teks**, dibagi di antara edisi-edisi
(edisi pertama bergiliran setiap pengurasan). Setiap perubahan tetap dicatat; teks yang tidak terjangkau
tepat waktu dihitung sebagai *ditunda* dan **pengurasan berikutnya mengambilnya**: halaman yang belum pernah disimpan lebih dulu, lalu
yang paling lama belum diperiksa (hingga 200 halaman per edisi per pengurasan; `text_backlog` dalam
laporan pengurasan menyebutkan berapa banyak yang *ditemukan* menunggu oleh proses susulan, yang tidak sama dengan yang diambil). Halaman-halaman itu
dicoba sebelum perubahan terbaru edisi tersebut dalam jatah waktunya. Halaman yang gagal atau
ditolak dibiarkan oleh proses susulan selama 5 menit, sehingga halaman yang terus ditolak layanan tidak
diminta setiap 30 detik. Klien
membuat satu permintaan per detik, sehingga satu pengurasan mengambil sekitar dua puluh teks: di belakang ribuan teks
yang ditunda, proses susulan memakan waktu berjam-jam, bukan satu pengurasan. Batas itu membatasi kapan pengambilan boleh *dimulai*: pengambilan yang
sudah berjalan diselesaikan dulu (setiap koneksi atau pembacaan menunggu hingga 30 detik), sehingga satu pengurasan bisa
berjalan sedikit melewati 20 detik. Selama penelusuran halaman menyala, ia mempertahankan 30% waktu luang, sehingga pengambilan halaman lain yang berubah
tidak dapat memakai seluruhnya. Status (`/api/scheduler/status`, blok `wiki_lane.service.drain`)
menyebutkan posisi pengurasan: tahapnya (`hot-sets` atau `feeds`), edisinya, sudah berapa lama ia
berada dalam pengurasan ini, dan berapa pengurasan yang gagal berturut-turut serta alasannya.

**Membaca W di bilah atas.** W adalah sakelar **aliran**, bukan sakelar penelusuran:
penelusuran adalah kotak centang di atas, dan ia hanya berjalan selama aliran berjalan. Tanda kecil di
sudut W menunjukkan apa yang sedang dilakukan aliran lewat bentuknya: titik penuh berarti tersambung dan menerima;
cincin berarti *dipilih tetapi tidak tersambung* (ditahan oleh mode pesawat, atau belum dimulai dalam
sesi ini); cincin dengan titik berarti sedang menyambung dan gagal, mencoba ulang sendiri; garis pendek berarti dijeda;
silang berarti dihentikan. Arahkan kursor ke atasnya untuk keterangan kata-katanya, termasuk apakah penelusuran halaman menyala. Klik
pada cincin **memulai** aliran (Anda mengonfirmasi untuk online sekali); klik pada titik atau cincin
dengan titik **menjeda**nya; Shift+klik menghentikannya. Pengaturan → Wikipedia menampilkan dua baris yang sama
dalam kata-kata di atas daftar edisi. Keduanya digambar ulang saat Anda online atau offline, dan saat Anda mencentang
atau menghapus centang penelusuran.

**Halaman lain yang berubah (nonaktif kecuali Anda menyalakannya):** aliran langsung menyimpan
teks halaman yang diikutinya dan hanya menghitung perubahan yang dilaporkannya pada setiap
halaman lain. Mencentang **Ambil juga teks halaman lain yang berubah** (Pengaturan →
Wikipedia, di samping kotak penelusuran) juga mengambil teks terbaru halaman-halaman lain itu,
50 halaman per permintaan, halaman yang paling lama menunggu lebih dulu. Halaman yang disunting sepuluh kali
selama menunggu hanya memakan satu pengambilan, yaitu keadaannya saat ini. Aplikasi menyimpan teks
**terbaru dan sebelumnya** setiap halaman, dan halaman yang kemudian dihapus tetap menyimpan teks yang dimilikinya. Teks-teks
ini **tetap berada di berkas jalur itu sendiri, bukan di korpus Anda**; kotak pencarian menemukannya
(lihat *Mencari isi jalur*, di bawah). Pengambilan berhenti ketika berkas jalur mencapai **90% dari anggaran penyimpanannya**, sehingga
sisanya tetap untuk halaman yang diikuti aliran; porsi itu adalah nilai bawaan yang diusulkan, bukan
putusan, dan Sumber hidup menampilkannya. Ia hanya berjalan selama aliran langsung berjalan, pada
koneksi yang sama dan dengan penantian yang sama seperti penelusuran: mode pesawat, atau mode
terlindung tanpa proksi yang dapat dipakai, membuatnya menunggu (ia tidak pernah tersambung langsung), dan wiki yang memintanya
melambat akan ditanya lagi setelah jeda yang berlipat dua hingga satu jam.

**Kerusakan (crash) atau pembaruan tidak menghilangkan proses.** Semua yang disimpan jalur ditulis dalam
langkah-langkah kecil semua-atau-tidak-sama-sekali, sehingga crash (atau mematikan paksa aplikasi) paling banyak menghilangkan langkah yang sedang berjalan;
penelusuran dilanjutkan dari penandanya dan aliran dari posisi terakhir yang disimpannya. Yang memang
berhenti adalah jalur itu sendiri: aplikasi selalu dimulai **offline**, sehingga setelah mulai ulang tidak ada yang
diambil sampai Anda kembali online dengan tombol pesawat, yang melanjutkan proses jika sebelumnya menyala dan membiarkannya mati jika sebelumnya mati (Beranda menampilkan satu baris selama proses menunggu). Tidak ada yang hilang selama menunggu
(riwayat aliran itu sendiri menjangkau sekitar satu minggu ke belakang). Sumber hidup → Wikipedia → Aliran
langsung menampilkan **Waktu berjalan sejauh ini** (jam-jam ketika instalasi ini menyimpan atau meminta sesuatu,
dihitung lintas mulai ulang, beserta jumlah penghentian) dan, ketika jalur sudah senyap, baris
**Dihentikan** dengan lamanya dan sejak kapan. Angka-angka yang sama ikut dalam laporan
jendela uji ketahanan (soak-window) sebagai `wiki_lane.run`. Penghentian berarti jalur tidak menunjukkan tanda kehidupan selama tiga jam
atau lebih, bukan alasannya: crash, pembaruan, mode pesawat, dan aplikasi yang ditutup terlihat sama.

**Mencari isi jalur:** jalur menyimpan indeks pencarian atas teks-teks yang
dimilikinya, di berkas yang sama dan di dalam anggaran penyimpanan yang sama. Teks **terbaru** halaman
yang berubah diindeks secara penuh, termasuk judulnya. Setiap **versi yang lebih lama** (teks
sebelumnya dari halaman yang berubah, dan setiap versi halaman yang diikuti aliran kecuali
yang terbaru, yang sudah menjadi artikel korpus Anda) diindeks berdasarkan **baris-baris yang dihapus oleh suntingan
berikutnya**: sisanya ada di versi yang lebih baru, tempat ia sudah ditemukan.
Jadi pencarian yang kata-katanya sebagian berada di baris yang dipertahankan dan sebagian di baris yang dihapus tidak menemukan
versi mana pun, dan setiap daftar hasil seperti ini menyatakannya. Indeks dibangun selama
aliran langsung berjalan, sebelum pengambilan dan paling banyak separuh dari waktu luangnya, dan
pencarian menyebutkan berapa banyak teks yang masih menunggu untuk diindeks; teks yang tidak dapat dibaca
disisihkan dan dicoba lagi saat jalur berikutnya dimulai. Bahasa Tionghoa, Jepang, dan
Arab dipecah dan dinormalkan persis seperti dalam indeks korpus Anda sendiri, dan kata-kata bahasa Hindi dan
Bengali tetap utuh. Di kotak pencarian (Ctrl/⌘-K) hasil-hasil ini dicantumkan di bawah
**Teks Wikipedia yang disimpan di mesin ini**, di samping hasil korpus Anda dan tidak pernah diperingkatkan
bersama hasil itu, masing-masing menyebutkan edisinya, teks apa itu (teks terbaru atau
sebelumnya dari halaman yang berubah, atau versi lebih awal dari halaman yang diikuti aliran) dan tanggalnya.
Membuka salah satunya menampilkan teks versi tersebut, tempat ia disimpan, dan alamat lengkapnya di
Wikipedia; **Tambahkan ke korpus** menambahkan versi persis itu sebagai artikel tersendiri, bertanggal saat
wiki membuatnya, dan memberi tahu bila korpus Anda sudah memuatnya atau memuat kata-kata yang sama
alih-alih menyimpannya dua kali. Selain itu, tidak ada apa pun dari jalur yang masuk ke korpus Anda.
Halaman **Jelajahi** mencantumkan hasil-hasil yang sama dalam bagian tersendiri di bawah hasil
korpus Anda, masing-masing dengan kutipan yang cocok dan tombol **Tambahkan ke korpus**
miliknya sendiri. Di atasnya disebutkan apa yang dicari: hanya teks yang disimpan jalur Wikipedia
di mesin ini, tidak pernah Wikipedia itu sendiri, beserta halaman dan edisi asal
teks-teks itu, berapa banyak teks yang masih menunggu indeks, dan apakah pengambilan halaman lain yang
berubah nonaktif. Jadi daftar kosong berarti teks jalur tidak memuat kata-kata Anda,
bukan berarti Wikipedia tidak memuatnya. Versi yang disimpan oleh **Lacak sekarang** (Pengaturan → Wikipedia)
untuk halaman yang dipantau juga ada dalam pencarian ini: versi-versi itu tetap di basis data korpus Anda,
dan indeks jalur, di berkasnya sendiri, membacanya dengan cara yang sama (setiap versi lama berdasarkan
baris yang dihapus oleh versi tersimpan berikutnya, yang terbaru secara penuh kecuali artikel korpus Anda
sudah merupakan versi itu). Versi-versi itu ditemukan di bawah judul yang sama, ditandai sebagai
disimpan oleh pelacak halaman, dan **Tambahkan ke korpus** menambahkan versi persis itu seperti yang
lainnya; pencarian menyebutkan berapa banyak halaman terlacak yang dibacanya. Halaman yang Anda ikuti sekaligus Anda lacak dapat
mencantumkan satu versi sekali untuk setiap penyimpanan: kedua penyimpanan dibaca secara terpisah, dan tidak ada yang bergantung pada
yang lain. Dump yang diunduh tidak termasuk dalam pencarian ini: teksnya
ditemukan di grup Wikipedia pada kotak pencarian. Sebuah kueri dibaca dengan cara yang sama di kedua daftar (`salt*`,
`NEAR(salt works, 5)`, `title:salt`), tetapi filter yang menggambarkan artikel (kotak
Sumber, Bahasa, dan Waktu, serta `source:`, `author:`, `url:`, `tag:` dan
`title:=`) tidak menjangkau teks-teks ini, dan bagian itu menyatakannya setiap kali salah satunya disetel.
Ekspor, jendela analisis, dan tindakan massal bekerja pada korpus Anda; sebuah teks Wikipedia
ikut di dalamnya begitu Anda menambahkannya.

**Satu butir di seluruh edisi, dan halaman yang paling banyak dilihat** (Sumber hidup → Wikipedia, di
bagian bawah). Dua tampilan yang hanya membaca apa yang sudah disimpan mesin ini; tidak ada yang mengambil data.
*Satu butir di seluruh edisi*: ketik sebuah item Wikidata (Q42) atau tekan salah satu saran (item-item
yang halamannya paling banyak dicatat perubahannya oleh aliran minggu ini) dan sebuah tabel menampilkan, untuk
setiap edisi yang Anda ikuti, halaman edisi tersebut, **ukurannya dalam bita wikitext** (dibaca sekali,
saat penelusuran halaman mencapai halaman itu), kapan dibaca, dan **perubahan yang dicatat mesin ini
dalam tujuh hari terakhir**. Edisi yang tidak memiliki halaman menyebutkan alasannya: penelusuran belum berjalan
untuknya, belum menyelesaikannya (beserta sejauh mana kemajuannya, jadi item itu mungkin ada), atau sudah menyelesaikannya
dan tidak menemukannya. Jumlah perubahan adalah yang dicatat aliran langsung di mesin ini; untuk edisi yang
belum ia catat apa pun, tertulis "tidak diketahui", karena itu tidak sama dengan nol. Batang di samping ukuran adalah ukuran itu dibandingkan dengan yang terbesar di layar,
dari nol; tidak ada hal lain yang dihitung, dan edisi-edisi itu adalah artikel yang terpisah, bukan
terjemahan. Penelusuran halaman nonaktif sampai Anda menyalakannya (Pengaturan → Wikipedia), jadi pada
instans yang belum melakukan penelusuran belum ada yang bisa dibandingkan dan tabel menyatakannya.
*Halaman paling banyak dilihat di samping korpus Anda*: daftar milik sumber itu sendiri tentang halaman yang paling banyak dilihat pada
hari terakhirnya (peringkat dan jumlah tayangan sebagaimana diberikan; lima puluh baris pertama disimpan), masing-masing di samping
jumlah artikel di **korpus Anda** yang menyebut judul itu sebagai frasa, yang diterbitkan pada hari
UTC itu dan dalam tujuh hari yang berakhir pada hari itu. Ini **satu hari, bukan sebuah deret**: daftar itu
ditimpa setiap hari dan tidak ada riwayat tayangan per halaman yang disimpan. Jumlah itu milik korpus Anda,
yaitu apa yang dikumpulkan mesin ini, bukan pers; sebuah judul bisa ambigu atau ditulis
berbeda dalam bahasa lain; artikel yang bersumber dari Wikipedia dan yang dikarantina tidak dihitung;
baris yang tidak terjangkau penghitungan dalam batas waktunya, atau yang judulnya tidak memiliki kata yang dapat dicocokkan indeks pencarian (sebuah "-" saja), tertulis "tidak dihitung", dengan alasannya di keterangan arahkan-kursornya; saran-saran hanya membaca 400 halaman yang paling banyak berubah minggu itu. Kedua angka itu diletakkan
berdampingan dan tidak pernah digabungkan.

**Basis teks lengkap luring** yang berat (dump satu edisi utuh) bersifat *terpisah* dan berada
di **Pengaturan → Wikipedia** — Anda tidak memerlukannya untuk pelacakan perubahan. Lihat
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

**Membaca dump yang diunduh (luring):** unduhan dump baru menggunakan bentuk
*multistream*, dan indeks pendamping kecilnya ikut terunduh bersamanya — pasangan
itu membuat dump dapat diakses langsung ke posisi mana pun. Di **Pengaturan → Wikipedia → Baca halaman dari
dump yang diunduh**, pilih edisi yang siap, ketik judul halaman, dan aplikasi memindai
indeks, mendekompresi satu blok kecil pada offset bitanya, dan menampilkan
**wikitext mentah** halaman itu — sepenuhnya di mesin ini, dengan statistik pemindaian ditampilkan.
Yang Anda baca adalah *snapshot per tanggal dump*, bukan artikel yang sedang tayang; kecocokan judul
yang tidak membedakan huruf besar-kecil ditawarkan dan diberi label. Berkas single-stream yang lebih lama
tidak dapat diakses secara acak — aplikasi menyatakannya dan menyarankan unduh ulang.
**Daftar bahasa dump dibatasi pada bahasa aplikasi** (12 bahasa
antarmuka ditambah bahasa korpus yang didukung penganalisis); pemilih edisi
halaman yang dipantau di atas tetap memakai daftar lengkap.

### 3.7a Pemerintah

**Kegunaannya:** tab bilah samping **Pemerintah** (jangkar kodenya tetap `law`,
labelnya "Pemerintah") mengumpulkan data resmi per negara dan melacak bagaimana **hukum**
berubah. Tab ini memiliki enam subtab:

- **Negara** — **statistik resmi** per negara dari Bank Dunia (PDB,
  populasi, angka harapan hidup, tenaga kerja, keuangan publik + indeks umum). **Muat data negara
  standar** mengambilnya (online, dengan persetujuan). Setiap nilai adalah angka yang diterbitkan
  produsennya, **tidak pernah skor kredibilitas**; **nilai yang hilang adalah celah yang diterbitkan,
  bukan nol**; para produsen ditampilkan, **tidak pernah dirata-ratakan**. Setiap angka membawa satuannya, dan
  keterangan arahkan-kursor setiap indikator menjelaskan apa yang diukurnya — dua yang tampak seperti kesalahan padahal bukan:
  langganan seluler dapat melebihi 100 per 100 orang (orang memiliki beberapa SIM) dan angka partisipasi
  kasar sekolah dapat melebihi 100% (ia menghitung siswa yang mengulang dan yang melewati usia sekolah).
- **Bandingkan** — dua negara berdampingan, setiap indikator sebagai baris yang sejajar. Ini adalah
  **tampilan**, bukan perhitungan: ia menunjukkan angka terbaru yang diterbitkan masing-masing negara dan
  tahun yang dirujuknya, dan bila satu negara tidak memiliki angka, selnya terbaca sebagai **celah**.
  Ia tidak pernah mengurangkan, memeringkat, atau memberi skor pasangan itu — perbandingannya Anda sendiri yang membuat.
- **Grup** — agregat dan blok, dalam dua **lensa** yang dapat Anda pilih:
  - *Diterbitkan* menampilkan agregat yang diterbitkan oleh produsen itu sendiri ("High income",
    "Sub-Saharan Africa", "European Union" milik Bank Dunia, dan seterusnya). Daftar pendek pilihan
    terbuka lebih dulu; **Tampilkan semua** memperluasnya ke kumpulan lengkap. Ini adalah angka
    produsen sendiri, bukan angka kami. **Kawasan Bank Dunia bukanlah benua** — "Sub-Saharan Africa"
    tidak mencakup Mesir, Libya, Tunisia, Aljazair, dan Maroko, yang termasuk kawasan Middle East &
    North Africa-nya, sehingga lensa ini **sama sekali tidak memiliki angka untuk Afrika sebagai benua** dan menyatakannya
    alih-alih menyusun angka yang akan tampak resmi.
  - *Dihitung (Computed)* mengagregasi negara-negara anggota oleh kami sendiri, dan menampilkan **beberapa strategi
    berdampingan** (rata-rata berbobot populasi, rata-rata sederhana, berbobot PDB, median, dan total
    bila total bermakna) sehingga Anda dapat melihat seberapa besar jawaban bergantung pada metodenya
    alih-alih disodori satu angka. Tidak ada yang diperingkat dan tidak ada strategi yang disebut
    terbaik. **Total** hanya ditawarkan untuk indikator yang penjumlahannya bermakna
    (populasi, PDB, angkatan kerja); untuk persentase, laju, atau angka harapan hidup, total
    **ditolak dengan alasan yang ditampilkan**, karena menjumlahkan persentase menghasilkan angka yang tidak pernah
    diukur siapa pun. Setiap angka menyatakan **cakupan** dan **sebaran**-nya (min/maks/n) —
    angka utama blok yang menyembunyikan rentang sepuluh kali lipat itu benar sekaligus menyesatkan, jadi rentangnya selalu ikut
    bersamanya. Bila ada anggota yang hilang, agregat **ditolak secara bawaan**; Anda tetap dapat
    menerbitkannya, dan hasilnya kemudian diberi label parsial serta menyebutkan dengan tepat anggota
    mana yang hilang. Keanggotaan blok berubah seiring waktu (BRICS beranggotakan lima negara hingga
    2024; Uni Eropa kehilangan Inggris pada 2020), sehingga setiap angka blok menyatakan **versi keanggotaan**
    yang dipakai dalam perhitungannya, dan blok yang daftar anggotanya belum dapat kami peroleh sumbernya menyatakan
    hal itu secara terus terang alih-alih menampilkan angka.
- **Peta** — **choropleth ooMap** dari indikator yang dapat dipilih dengan pemilih
  tahun/riwayat; klik sebuah negara untuk membuka detailnya di subtab Negara.
- **Hukum** — melacak **hukum** (undang-undang, lembaran negara, catatan kekayaan intelektual) dari sumber resmi
  di seluruh dunia, memantau bagaimana ia berubah seiring waktu (*perubahannya adalah data*). Sebuah **cermin
  riset**, tidak pernah menjadi sumber otoritatif dan **bukan nasihat hukum** — setiap catatan menautkan
  kembali ke lembaran negara resminya. Katalog sumber resmi nyata di seluruh dunia
  (`legislation.gov.uk`, EUR-Lex, Légifrance, govinfo, WIPO Lex, USPTO, EPO, …) disediakan
  secara bawaan. **Lacak perubahan sekarang** mengambil dokumen yang dilacak melalui pengambil
  etis, menyimpan versi dasar lalu **diff** yang jujur dengan tanda perubahan besar; **Perubahan
  hukum yang ditandai** mencantumkannya (yurisdiksi · judul · Δ bita · alasan) dengan diff dan
  tautan ke sumber resmi. Ringkasan juga memunculkan Petunjuk **legislasi-model**
  ketika teks yang nyaris identik muncul di berbagai yurisdiksi.
- **Statistik** — direktori produsen dan angka mentah berversi yang mendasari subtab
  lainnya, ditambah **Tambahkan seri ke korpus** (di bawah).

**Statistik dalam pencarian biasa.** Angka yang tidak dapat ditemukan siapa pun sebenarnya tidak berada di korpus Anda,
jadi setiap **seri** — satu indikator untuk satu negara, mencakup setiap tahun yang tersimpan — juga dapat
diwujudkan sebagai **Artikel** biasa. Seri itu lalu menempuh jalur yang normal: pencarian menemukan
"life expectancy France", kata-katanya masuk ke tren dan Petunjuk, dan ia muncul di Feed
seperti hal lainnya, tanpa kotak pencarian khusus yang perlu diingat. Empat hal patut diketahui:

- Ini adalah **satu Artikel per indikator per negara**, bukan satu per revisi. Angka 1991 yang
  dinyatakan ulang memperbarui Artikel yang sudah ada alih-alih menambahkan salinan yang hampir sama, sehingga menjalankan ulang
  pekerjaan ini tidak memakan biaya dan tidak menambahkan apa pun.
- Artikel-artikel itu **diberi label sesuai jati dirinya** — sumbernya terbaca "Official statistics
  (World Bank)" dan kelas provenansnya `statistics` — sehingga Anda dapat menyaringnya masuk atau
  keluar dari tampilan mana pun, dan pemeriksaan koordinasi yang mencari banyak media saling
  mengulang tidak dapat salah mengira ribuan baris berbentuk sama sebagai kesepakatan.
- Isinya sengaja **hanya menyebut subjek dan angka-angkanya**, dengan **celah yang diterbitkan
  ditampilkan sebagai celah**. Mengulang nama produsen dan kode seri mesin di setiap
  satu dari ~9.800 Artikel menempatkan "World Bank" di puncak peringkat kata kunci seluruh
  korpus — kerangka mengalahkan apa yang sebenarnya menjadi isi korpus Anda — jadi hal itu tidak dilakukan.
- Untuk menemukannya **berdasarkan produsen** alih-alih berdasarkan subjek, saring berdasarkan sumber atau tag
  `statistics`; untuk mencarinya **berdasarkan kode seri**, gunakan subtab Statistik, yang
  menjawab secara persis, bukan melalui pencocokan teks.

Mewujudkannya adalah pekerjaan latar belakang yang Anda mulai dari **Pemerintah → Statistik**; pekerjaan itu
dapat dilanjutkan, dapat dibatalkan, dan tidak menahan pengumpulan.

### 3.8 Bukti & pengawasan

*(Dicapai dari **Pengaturan → Lanjutan → Keamanan** — "Rantai pengawasan" adalah judul panelnya; ia meninggalkan
bilah samping dalam perombakan yang mengutamakan konten.)*

**Kegunaannya:** membuktikan — kepada pihak ketiga yang skeptis, secara luring — bahwa korpus Anda
memuat butir *ini*, dengan konten *ini*, pada waktu *ini*, dan bahwa catatannya tidak
berubah sejak itu. Ini **bukan** sistem pelapor pelanggaran/SecureDrop; "sumber" di sini adalah
media berita, bukan manusia yang dirahasiakan.

Panel ini memiliki tiga bagian:

- **Pengaturan & status (Settings & status).** Sakelar untuk **Tanda tangan pasca-kuantum** (menambahkan tanda tangan ML-DSA /
  FIPS-204 di samping Ed25519), **Penjangkaran OpenTimestamps** (menjangkarkan ke
  Bitcoin untuk bukti waktu yang independen), **Catat otomatis saat menelan** (menambahkan entri
  bertanda tangan pada setiap penelanan yang berhasil), dan label **Aktor bawaan**. Yang terpenting,
  status selalu menampilkan keadaan yang **efektif**, bukan sekadar keinginan Anda: jika Anda mengaktifkan PQC
  atau OpenTimestamps tetapi pustaka pendukungnya tidak terpasang, status menyatakan *"diminta,
  pustaka tidak terpasang"* dan tetap hanya Ed25519/lokal — **ia tidak pernah menampilkan lampu hijau
  yang tidak dapat dipertanggungjawabkannya.** Perlindungan kunci juga ditampilkan (`aes256gcm-scrypt` ketika frasa sandi
  tersedia, dari `OO_KEY_PASSPHRASE` atau frasa sandi basis data; `plaintext-0600` jika tidak; dan `pkcs8-pbkdf2`
  atau `plaintext-0600` dengan frasa sandi tersedia, untuk kunci dari sebelum 0.6 yang belum dapat dibungkus ulang,
  yang menyebutkan apa yang sebenarnya dimuat berkasnya).
- **Lihat & verifikasi rantai (View & verify chain).** Masukkan id butir (mis. `article:42`) untuk **Lihat rantai**
  (urutan, tindakan, aktor, waktu, algoritme tanda tangan), **Verifikasi** (memeriksa ulang tautan
  rantai, hash, tanda tangan, stempel waktu), atau **Ekspor bundel** (berkas yang
  dapat diverifikasi secara luring).
- **Jangkarkan akar Merkle (Anchor Merkle root).** Tempelkan akar Merkle untuk dijangkarkan melalui penyedia yang dikonfigurasi.

> **Peringatan privasi yang ditampilkan di aplikasi:** menjangkarkan ke blockchain publik menerbitkan
> sebuah hash secara permanen dan mengungkapkan IP/waktu Anda kepada operator kalender. Utamakan
> lokal + OpenTimestamps daripada dompet on-chain yang berisi dana; arahkan melalui Tor (`HTTPS_PROXY`)
> jika Anda membutuhkan anonimitas; atau tetap hanya lokal (bawaan, tidak membocorkan apa pun).

**OpenTimestamps dan mode pesawat.** Dalam mode OpenTimestamps, entri penelanan yang
pengirimannya ditolak oleh sakelar pemutus jaringan (Stop selama pengumpulan) tidak diberi
bukti hanya-lokal sebagai gantinya, karena bukti itu akan permanen: entri itu menjadi utang,
dan ditulis kemudian, ditandai terlambat, beserta jangkarnya. Antrean utang tidak memiliki batas ukuran, dan
akhir setiap putaran pengumpulan menulis paling banyak 200 entri darinya, masing-masing dengan hingga tiga
pengiriman ke kalender yang dilakukan selama log pengawasan dikunci untuk penulisan. Jadi tunggakan yang besar
memperlambat akhir putaran pengumpulan untuk sementara waktu begitu Anda kembali online.
Selama sakelar masih aktif, penulisan entri utang ("Catat, ditandai terlambat", atau
`POST /api/custody/reconcile`) berhenti pada penolakan pertama dan menyatakan bahwa sakelar pemutus yang menolaknya;
entri-entri itu tetap menjadi utang. Pemeriksaan celah saja tetap memberikan jawaban, dan blok `drained`-nya
melaporkan `refused_offline`.

Verifikasi bundel di mana saja, tanpa aplikasi ini:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
python scripts/verify_evidence.py bundle.json [signer_pubkey]
```

Rancangan lengkapnya — dan apa persisnya yang dibuktikan dan **tidak** dibuktikan oleh setiap mekanisme — ada
di [`docs/USER_MANUAL.md`](USER_MANUAL.md). *(Rencana perombakan untuk membuat
tab ini sangat mudah dipakai dan sebagian besar otomatis tercatat di
[`docs/ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).)*

### 3.8a Integritas sumber

*(Meja integritas sumber dipindahkan ke **Pengaturan → Lanjutan → Keamanan → "Buka meja integritas
sumber"**; koordinasi kini juga dimunculkan secara otomatis — sebagai Petunjuk di Beranda, dalam tampilan **Terkait**
di jendela analisis, dan sebagai lencana sebaris "N salinan = satu suara" pada daftar artikel
dan pembaca.)*

**Kegunaannya:** melihat *struktur* di balik sumber-sumber Anda — dan memutuskan, sendiri,
sinyal siapa yang diperhitungkan. Sengaja **tidak ada skor kepercayaan**; satu angka tunggal akan
menanamkan bias dan membungkam sumber yang kecil, asing, baru, atau pembangkang. Panduan lengkap:
[`docs/USER_MANUAL.md`](USER_MANUAL.md).

- **Anti-amplifikasi (Anti-amplification) (mengusulkan → Anda yang memutuskan):** *Pindai koordinasi* menemukan
  banjir konten yang nyaris duplikat yang diterbitkan serempak di banyak sumber, beserta buktinya
  (teks bersama, waktu, host). Secara bawaan konten itu hanya **diberi anotasi** — tidak pernah digabungkan
  diam-diam. **Terapkan penggabungan** untuk menghitung suatu jaringan sebagai **satu suara** (dalam setiap hitungan yang
  mengukur konsensus); ia tetap ditandai, **Perluas (kembalikan)** memulihkan tampilan mentah yang setara
  secara persis. Tidak ada yang pernah digabungkan tanpa tindakan Anda. Petunjuk ruang gema di Beranda
  membawa tindakan yang sama.
- **Profil sumber:** panel berisi dimensi terukur — koordinasi, kebaruan
  (memulai vs menggemakan), kapasitas keluaran, fakta transparansi, rekam jejak — masing-masing dengan
  metode dan caveat-nya, dan **tanpa skor gabungan**.
- **Anotasi bersama (Shared annotations) (jaringan kepercayaan):** tuliskan fakta deskriptif yang dapat diperdebatkan tentang
  sumber (kepemilikan, kecenderungan, koordinasi, koreksi); **ekspor** sebagai bundel
  **bertanda tangan**; **impor** bundel yang Anda pilih untuk dipercaya. *Siapa mengatakan apa?* menampilkan
  setiap atribusi untuk suatu sumber dan memunculkan **perbedaan pendapat** — tidak pernah dirata-ratakan menjadi satu angka.
  Lihat [`docs/USER_MANUAL.md`](USER_MANUAL.md).

### 3.9 Pengaturan

**Kegunaannya:** preferensi, permukaan akuisisi, dan pemeliharaan — disusun
menjadi **sembilan** bagian lewat sub-navigasi: **Grafis · Umum · Kartu · AI · Wikipedia ·
OpenStreetMap · Agenda · Data & cadangan · Lanjutan**.
Buka Pengaturan dari **tombol di bagian bawah bilah sisi**; palet perintah juga
langsung membawa Anda ke sini. Semuanya disimpan secara lokal; tanpa telemetri.

Penggunaan sehari-hari sama sekali tidak memerlukan **Lanjutan**: saluran pengumpulan, pengelolaan sumber, kurasi
kata kunci, direktori produsen statistik, katalog feed kalender, meja
diagnostik, **Keamanan**, dan **Copot pemasangan dan hapus** semuanya ada di sana, dalam **bagian terlipat yang baru
memuat datanya ketika Anda membukanya** (katalog sumber saja bisa berisi puluhan ribu
baris). Keamanan dulu merupakan subtab tersendiri; kini ia menjadi bagian kedua dari akhir di Lanjutan,
dengan dua tindakan yang tidak dapat dibatalkan — **Hapus darurat** dan **Hapus instalasi aplikasi** — dipisahkan
ke bagiannya sendiri (**Copot pemasangan dan hapus**) agar keduanya tidak terjangkau secara tidak sengaja
saat Anda sedang membaca tentang enkripsi. Tidak ada yang hilang dalam kedua pemindahan itu: setiap kontrol
yang dulu ada di subtab Keamanan masih ada, di bawah judul yang sama. **Kumpulkan** dan **Sumber**
dijelaskan di atas ([3.2](#32-kumpulkan-di-pengaturan--lanjutan--pengumpulan),
[3.3](#33-sumber-di-pengaturan--lanjutan--sumber)) dan dijangkau lewat Lanjutan;
**Wikipedia** ([3.7](#37-wikipedia-di-pengaturan--wikipedia)) tetap memiliki bagiannya sendiri.
**Angka** resmi sama sekali tidak ada di sini — angka adalah data, jadi tempatnya di
**Pemerintah → Statistik**.

- **Grafis (Tampilan):** tema, warna aksen, kepadatan, **jenis huruf**,
  dan bilah sisi diperluas/diciutkan. (Tidak ada penggeser ukuran teks: penggeser itu hanya pernah menskalakan
  elemen akar, yang hampir tidak diwarisi oleh apa pun di lembar gaya, sehingga tidak berpengaruh apa-apa.
  Gunakan zoom bawaan peramban Anda — zoom itu menskalakan semuanya, termasuk bagian yang tidak pernah dapat dijangkau
  penggeser khusus elemen akar.) Bagian ini juga memuat galeri **Antarmuka alternatif**
  (ditandai *Eksperimental*): delapan skin opsional — **Aurora, Atlas, Command, Field,
  Focus, Terminal, Canvas, Editorial** — di atas data yang sama dan jaminan kejujuran
  yang sama; memilih salah satunya memuat ulang halaman untuk menerapkannya. (Laci "Sesuaikan" yang dulu mengambang
  kini menjadi bagian kelas satu ini.)
- **Kartu (Petunjuk di Beranda):** setiap produsen Petunjuk yang dapat dijalankan aplikasi, dikelompokkan menurut keluarganya
  (*Meningkat · Terlalu diberitakan · Kurang diberitakan · Layak diselidiki · Periksa pembingkaian · Terus pantau ·
  Konteks · Integritas data*). Matikan salah satunya dan ia berhenti muncul — hal itu tidak mengubah apa pun
  pada artikelnya sendiri, hanya ajakan mana yang sampai ke Beranda Anda. Jika sebuah Petunjuk memiliki
  ambang batas, ambang itu kini terlihat dan dapat disesuaikan, masing-masing dengan **rentang aman** yang dinyatakan,
  catatan satu baris tentang akibat menggesernya, dan tombol **Atur ulang**. Anda selalu dapat membuat sebuah Petunjuk
  *lebih ketat*; batas bawah ada agar sebuah Petunjuk tidak pernah dapat mengklaim lebih dari yang didukung
  buktinya — pemeriksaan banjir (flooding), misalnya, tidak akan turun di bawah ambang p<0.05,
  karena di bawahnya uji itu tidak lagi dapat membedakan lonjakan nyata dari variasi biasa. Setiap
  nilai di luar rentang dikoreksi **dan dilaporkan**, tidak pernah disesuaikan diam-diam.
- **Preferensi (Umum):** **Tema** (Sistem/Gelap/Terang), **bahasa**, dan **Hasil pencarian
  bawaan**.
- **Penyaringan kata kunci (Lanjutan → Kata kunci):** kata fungsi yang "bodoh" (the, you, not, …) dibuang oleh
  daftar kata henti (stoplist) multibahasa bawaan. Sesuaikan: atur **Panjang minimum kata kunci**, **Buang
  istilah yang murni angka**, aktifkan/nonaktifkan daftar kata henti bawaan, dan kelola daftar **Kata kunci
  yang dikecualikan** (satu per baris atau dipisahkan koma). Mengecualikan menyembunyikan sebuah istilah
  di mana-mana tetapi dapat dibatalkan — sebutan yang tersimpan tetap dipertahankan. (Anda juga dapat mengklik ✕
  di samping kata kunci mana pun di Wawasan.)
- **Baseline luring Wikipedia:** pilih **edisi bahasa** dari **daftar datar**
  (bahasa antarmuka Anda lebih dulu, lalu edisi terbesar), setiap opsi diawali dengan
  **nama asli** (autonim) — edisi berbasis bahasa, bukan berbasis negara, jadi
  tidak ada pengelompokan per benua. Setiap edisi yang memenuhi syarat dump menampilkan **perkiraan ukuran
  langsung di baris** (`~X GB`, dari tabel bertanggal yang dibundel — tanpa panggilan jaringan tambahan) agar Anda dapat menilai
  sebelum mengunduh; ukuran persisnya dibaca saat unduhan dimulai. **Unduh** dapat
  dilanjutkan (jeda/lanjutkan + tabel kemajuan). Dump luring ini berat dan
  opsional, dan hanya untuk membaca/mencari secara luring — pelacakan perubahan langsung (tab
  Wikipedia) tidak memerlukannya.
- **AI (LLM lokal):** kotak **Siapkan AI lokal** di bagian atas menyatakan seluruh rencana yang tersisa
  di satu tempat — backend mana yang akan dipakai mesin ini (vLLM jika GPU NVIDIA
  khusus dapat menjalankannya, selain itu Ollama), apa yang masih perlu dipasang, dan
  ukuran unduhannya — dan menjalankannya dari **satu tombol** setelah **satu** persetujuan. Kotak itu menyembunyikan
  dirinya setelah tidak ada lagi yang perlu dilakukan; kontrol per komponen di bawahnya
  tidak berubah, sehingga Anda tetap dapat melakukan setiap langkah sendiri. Di bawahnya: backend yang aktif
  dan **mengapa** backend itu dipilih, model yang terpasang dan katalog terkurasi bertanggal, **tarik** sebuah
  model (tugas unduhan yang **diantrekan** — satu per satu, dapat dibatalkan, dengan kemajuan byte
  langsung; byte-nya lewat clearnet melalui proses Ollama, **bukan** Tor — dinyatakan pada
  dialog persetujuan), **hapus** sebuah model, dan atur **model aktif**.
  **Kesesuaian perangkat keras (Hardware suitability)** dinyatakan sekali, di sini, beserta artinya bagi Anda: inferensi
  lokal ditolak secara bawaan hanya di bawah batas minimum (kurang dari 4 inti CPU, atau kurang
  dari 6 GB RAM, tanpa akselerator); berjalan tanpa GPU khusus, pada
  kartu dengan VRAM tipis, atau pada Mac kecil dengan memori terpadu adalah **peringatan tentang apa yang
  dapat diharapkan**, bukan penolakan. Ini **tidak pernah menjadi blokade** — sebuah kotak centang menyalakan AI kembali, dan
  pengungkapannya tetap terlihat dalam kedua kasus. **Menjalankan** AI lokal dilakukan lewat
  **label AI** di bilah atas, dari layar mana pun.
  Editor **"Perilaku & prompt"** menampilkan empat prompt sistem yang dapat disunting
  (ringkasan / terjemahan / sintesis / ekstraksi kata kunci) serta keep-alive model.
  Keempat prompt itu **tersedia dalam kedua belas bahasa antarmuka**, sehingga pembaca berbahasa Prancis atau
  Jepang mendapat ringkasan yang ditulis dalam bahasanya, bukan hasil kerja berbahasa Inggris;
  editor menampilkan teks bawaan untuk bahasa **Anda**, dan prompt persis yang dipakai
  dicatat bersama setiap hasil. Prompt Anda sendiri, jika Anda menulisnya, dipakai **persis
  seperti yang Anda tulis**, dalam bahasa apa pun Anda menulisnya. Daftar **Pengekstrak kustom**
  memungkinkan Anda mendefinisikan prompt terkelola yang menulis metadata turunan AI (berlabel
  *tidak dapat diandalkan*, tidak pernah masuk indeks kata kunci tepercaya).
  Jika Ollama tidak ada, **pemasang di dalam aplikasi** akan muncul (Linux/Debian): pemasang itu mengunduh
  skrip instalasi resmi, memverifikasinya terhadap digest sha256 yang dibuktikan GitHub, menampilkan
  langkah elevasi hak akses yang terlihat, lalu menjalankannya — menolak jika digest tidak cocok. macOS/Windows
  mendapat petunjuk yang jujur ke ollama.com/download.
- **Statistik — direktori produsen (Lanjutan → Statistik resmi):** sebuah
  direktori deskriptif produsen statistik pemerintah + internasional. **Angka**
  itu sendiri adalah data, jadi tempatnya di **Pemerintah → Statistik**,
  bukan di Pengaturan. Setiap produsen membawa **catatan deskriptif yang sama tentang sumber
  yang memiliki sikap** — sebuah angka resmi menyatakan lembaga yang memproduksinya dan sikapnya — **tidak pernah
  label "kontroversial", vonis, atau skor per sumber**. Anda dapat **menambahkannya ke sumber Anda** — produsen yang
  bagian berita/persnya diketahui akan diaktifkan dan dikumpulkan dari sana, sedangkan produsen yang
  alamatnya belum diteliti ditambahkan dalam keadaan nonaktif alih-alih dirayapi masuk ke portal
  datasetnya — dan **mengambil angka resmi** dari endpoint mesin yang terdokumentasi
  (World Bank API / Eurostat SDMX), disimpan dengan provenans lengkap dan **vintage**
  kelas satu (pengambilan ulang adalah baris baru, tidak pernah menimpa). Para produsen ditampilkan **berdampingan,
  tidak pernah dirata-ratakan**, dan tampilan **Triangulasi (Triangulate)** menandai sel yang mencampurkan satuan
  yang tidak sebanding / penyesuaian musiman / tahun dasar. **Periksa anomali revisi** menandai, murni
  secara retrospektif, angka tersimpan yang vintage terbarunya menggeser nilai masa lalu secara luar biasa jauh
  dibandingkan riwayat revisi seri itu sendiri (tanpa skor). Pengambilan itu keluar melalui
  transport yang Anda konfigurasi dan ditolak dalam mode pesawat.
- **OpenStreetMap:** pilih wilayah peta (dengan perkiraan `~GB` bertanggal) dan unduh
  sebagai tugas pengelola tugas yang dapat dilanjutkan dan dijeda (dijaga oleh satu-satunya dialog persetujuan jaringan).
- **Buletin:** impor buletin sebagai artikel — **dianonimkan saat penyerapan** (penerima
  tidak pernah disimpan, gema penerima disamarkan, token pelacak dibuang,
  dan pembungkus pelacak sisi server ditandai; **tidak ada yang pernah diambil dari jaringan**, sehingga mengimpor
  tidak pernah dapat mengungkapkan bahwa Anda membuka atau mengklik). Tiga jalur:
  - **Pilih berkas .eml (Choose .eml files)** — unggahan multi-berkas yang kecil.
  - **Impor seluruh folder** — tunjuk sebuah folder di mesin ini; setiap `.eml` di dalamnya
    diimpor sebagai **tugas latar belakang yang dapat dijeda dan dilanjutkan** (terlihat di pengelola tugas) yang
    sanggup menangani arsip 20 GB+, dengan melewati pesan yang sudah diimpor.
  - **Tarik dari kotak surat (IMAP/POP3)** — tarik langsung dari kotak surat, dengan
    pengungkapan yang terlihat di titik penggunaan (TLS ke penyedia, IP Anda terlihat, **tidak** lewat
    Tor, kredensial tidak disimpan). Melalui TLS, sertifikat server harus cocok dengan namanya
    dan berasal dari otoritas yang dipercaya komputer Anda; jika tidak, penarikan ditolak sebelum
    kata sandi Anda dikirim, dan pesannya menjelaskan alasannya. Melalui API, penarikan dengan
    `use_ssl` diatur ke false (biasanya di port 143/110) terlebih dahulu meningkatkan koneksi dengan STARTTLS di bawah
    pemeriksaan yang sama, dan ditolak jika server tidak menawarkannya: kata sandi Anda tidak pernah
    dikirim tanpa enkripsi.
  - **Penerbit mana pemilik setiap buletin?** — buletin yang diimpor saat ini
    semuanya berada dalam satu sumber penampung. `GET /api/newsletters/publisher-preview` menunjukkan seperti apa
    pengarsipan per penerbit AKAN terlihat untuk buletin yang sudah Anda miliki: setiap domain
    pengirim, berapa banyak pesan yang berasal darinya, dan sumber yang ada mana yang menjadi hasil resolusinya (eTLD+1
    yang nyata dari Public Suffix List yang dibundel — sehingga `email.bbc.com` diresolusikan ke `bbc.com` — dengan
    platform buletin ditangani sebaliknya, sehingga dua publikasi Substack tidak pernah
    dilebur menjadi satu "Substack"). Ini **hanya pratinjau**: tidak ada yang dilampirkan atau dipindahkan, dan
    jika buktinya tidak menentukan, ia mengatakannya alih-alih menebak.
  - **Hapus buletin yang diimpor** — hapus setiap artikel buletin yang diimpor (.eml +
    kotak surat) dari korpus aktif, untuk mengganti kumpulan yang bermasalah dengan impor ulang yang bersih
    (pemulihan bersifat aditif, jadi tidak menyertakan buletin dalam cadangan tidak pernah menghapusnya — tindakan ini
    yang menghapusnya).
- **Data & cadangan — Ekspor / Impor terpadu:** satu tempat untuk mencadangkan semuanya, pada
  **ukuran basis data berapa pun**. **Ekspor / Cadangkan…** membuka dialog: pilih **folder
  atau drive tujuan**, centang apa yang disertakan (korpus, buletin yang diimpor, model LLM lokal,
  peta luring, dump Wikipedia), dan berikan **frasa sandi** — korpus terenkripsi dialirkan
  ke folder itu sebagai **volume yang masing-masing diautentikasi secara independen ditambah paritas Reed-Solomon** (sehingga
  volume yang hilang/rusak, bahkan volume korpus, dapat dibangun kembali), dan blob publik yang besar
  (model / peta / dump) disalin **apa adanya**. **Tidak ada batas ukuran** dan arsipnya
  tidak pernah dimuat utuh di RAM. Frasa sandi **tidak dapat dipulihkan** — frasa sandi yang hilang berarti
  cadangan korpus tidak dapat dibuka.
  - **Setiap ekspor membuat folder bertanggalnya sendiri.** Tujuan yang Anda pilih adalah folder INDUK:
    di dalamnya, setiap ekspor membuat `YYYYMMDDHHMM_OpenOmniscience_Backup` — tanggal dan waktu
    lokal saat ekspor dimulai, sehingga folder-folder itu terurut sesuai urutan Anda membuatnya. Ekspor kedua
    dalam menit yang sama mendapat `_2`, `_3`, dan seterusnya. Folder yang sudah ada **tidak pernah
    ditulisi**, sehingga cadangan sebelumnya di drive yang sama tidak dapat dirusak oleh cadangan berikutnya.
  - **Setiap ekspor adalah cadangan baru yang lengkap.** Tidak ada yang dipakai ulang dari cadangan sebelumnya, jadi sebuah
    ekspor memakan waktu dan ruang sebesar semua yang Anda pilih — dan sebagai gantinya setiap
    byte di folder itu ditulis oleh satu putaran itu saja.
  - **Verifikasi setelah menulis (Verify after writing)** (aktif secara bawaan). Saat volume terakhir selesai ditulis, setiap volume
    dibaca kembali dari tujuan dan checksum-nya dibandingkan dengan yang dicatat saat
    ditulis. Ini membaca setiap byte untuk kedua kalinya, yang kira-kira melipatgandakan lama sebuah
    ekspor pada drive yang lambat; inilah satu-satunya hal yang dapat mendeteksi drive yang menerima
    penulisan tetapi menyimpan sesuatu yang lain. Panel penyelesaian kemudian bertuliskan **"Terverifikasi (Verified)"** —
    dan jika tidak, panel itu menyebutkan mana dari empat alasan yang berlaku: verifikasi
    dimatikan, verifikasi dibatalkan, set tidak dapat dibaca ulang, atau verifikasi **gagal** dan menyebut
    volumenya.
  - **`BACKUP_SUMMARY.md`** ditulis di samping `volumes.json` pada akhir setiap ekspor:
    fakta yang sama dengan yang ditampilkan panel penyelesaian — volume, byte, baris per tabel dengan
    artikel paling depan, berkas yang disalin per kategori, waktu yang berlalu, tujuan, status enkripsi,
    versi skema dan aplikasi, hasil verifikasi, dan baris atribusi yang berlaku untuk
    isi cadangan. Berkas ini ada agar folder itu dapat menjelaskan dirinya sendiri di drive lepasan
    bertahun-tahun kemudian, ketika panel yang menyatakan semua ini sudah lama tiada. Ini sebuah deskripsi,
    bukan tanda tangan: `volumes.json` memuat checksum per volume yang membuktikan byte-nya.
    **Ini juga satu-satunya berkas di folder itu yang tidak terenkripsi** — korpus tidak
    dapat dibaca tanpa frasa sandi Anda, dan ringkasan ini berupa teks biasa di sampingnya, yang menyebutkan
    berapa banyak artikel, sumber, dan dokumen yang dilacak di dalam korpus. Itulah kompromi
    yang dibuat berkas ini, hal itu dinyatakan di dalam berkas itu sendiri, dan Anda dapat menghapusnya jika folder
    yang menjelaskan dirinya sendiri kurang penting bagi Anda dibanding tidak memberi tahu apa pun kepada siapa pun yang menemukan drive itu.
  - **Ekspor tidak pernah dijadwalkan.** Tidak ada ekspor otomatis atau berjadwal dan tidak ada yang
    direncanakan — ekspor adalah **tindakan yang disengaja**, karena ekspor menulis korpus Anda ke tempat
    yang Anda pilih, pada saat yang Anda pilih.
  **Impor…** menunjuk ke sebuah folder, menemukan apa yang dapat diimpor di dalamnya (cadangan untuk dipulihkan,
  data besar, atau buletin), lalu memulihkannya. **Pemulihan hanya bersifat aditif** — pemulihan
  **melengkapi** korpus Anda dan **tidak pernah menggantinya**: tidak ada yang sudah Anda miliki yang
  ditimpa, duplikat dideteksi bit demi bit, dan nilai yang bertentangan **mempertahankan nilai
  lokal Anda dan melaporkan keduanya**, tidak pernah dirata-ratakan.
  - **Laporan impor.** Baik penggabungan-pemulihan maupun impor buletin dari folder
    secara otomatis menulis **laporan yang tersimpan** ke disk setelahnya (dalam satuan
    ARTIKEL — tidak pernah jumlah baris lintas tabel yang terbaca seperti jutaan artikel padahal
    sebenarnya baris dari banyak tabel) — berapa banyak artikel yang masuk, berapa banyak yang
    disaring keluar sebagai non-artikel (lihat **Penyaringan non-artikel**, di bawah), dan
    "pekerjaan yang ditimbulkan" yang ditinggalkannya (mis. berapa banyak sumber yang baru diimpor masih
    menunggu kualifikasi, lihat [§3.3](#33-sumber-di-pengaturan--lanjutan--sumber)). Laporan
    itu sendiri ikut dalam cadangan terenkripsi Anda **berikutnya**, sehingga ia ikut bepergian bersama korpus. Laporan dapat
    diunduh melalui `GET /api/backup/import-reports` (daftar) dan
    `GET /api/backup/import-reports/{filename}` (sebagai JSON, atau `?format=md` untuk
    tampilan Markdown yang mudah dibaca) — belum ada layar khusus di dalam aplikasi untuk itu,
    jadi gunakan endpoint tersebut (atau peramban) untuk membacanya.
  - **Penyaringan non-artikel.** Setiap penggabungan-pemulihan dan impor buletin dari folder
    secara otomatis menyaring artikel yang baru dibawanya masuk dan **mengarantina** — disimpan,
    tidak pernah dihapus, dan dapat dibatalkan — artikel apa pun yang cocok dengan kriteria
    validitas ekstraksi yang sama dengan yang dipakai uji kualifikasi sumber (halaman menu navigasi, daftar tautan,
    hasil scraping yang rusak). Artikel yang dikarantina dikecualikan dari pencarian dan analitik tetapi
    tetap berada di basis data dan ikut dalam cadangan Anda; hitungannya ada di laporan impor.
  > **Jalur lama / migrasi (dipertahankan untuk cadangan lama).** Panel terpisah memulihkan
  > arsip **`oo-backup-2` berkas-tunggal yang lebih lama** dengan **pratinjau** penggabungan aditif yang sama
  > (baru / duplikat / konflik) sebelum **Terapkan (Apply)** (pada salinan bertahap yang sudah diverifikasi, pertukaran atomik,
  > snapshot `pre-restore-*.db` disimpan di samping basis data). Snapshot mentah **Unduh cadangan (.db)**
  > (API pencadangan daring SQLite) disimpan di bawah *"Alat cadangan lama… (Older backup tool…)"* untuk penggunaan
  > manual. **Pemulihan destruktif "ganti korpus Anda" telah dihapus sepenuhnya** — tidak ada alur
  > yang dapat menimpa data Anda, dan memulihkan cadangan **terenkripsi** tidak pernah mendekripsi
  > korpus Anda secara diam-diam.
- **Pemeliharaan (panel Diagnostik):** **Bersihkan kata kunci (indeks ulang, lalu pangkas)** dan
  **Indeks ulang seluruh korpus** menjalankan **tugas latar belakang yang dapat dijeda dengan kursor tersimpan**
  (bertahan saat tab ditutup atau aplikasi dimulai ulang dan berlanjut dari titik berhentinya). Jalankan pembersihan setelah
  peningkatan mesin kata kunci untuk menerapkan daftar kata henti/keluarga yang lebih baru ke artikel yang sudah ada.
  **Gabungkan bentuk kata kunci (studies → study)**, di sampingnya, melakukan satu bagian dari pembersihan itu
  yang dibutuhkan lematisasi tanpa membaca ulang artikel apa pun: kata kunci yang diindeks sebelum lematisasi
  ditambahkan memisahkan "studies" dari "study" yang dipakai artikel baru, dan penggabungan ini menyimpan
  sebutan-sebutan lama itu di bawah bentuk dasarnya persis seperti yang akan dilakukan indeks ulang. Lalu ia menetapkan
  bahasa setiap kata kunci dari bahasa-bahasa sebutannya. Frasa, nama, dan kata kunci yang dipakai
  keluarga atau grup Anda tidak pernah digabungkan. Ini adalah tugas yang dapat dijeda di pengelola tugas, dan
  **Laporan penggabungan (.json)** menunjukkan apa yang dihitung penggabungan terakhir yang selesai beserta penggabungan terbesarnya.
  Penggabungan tidak dapat dibatalkan; pemangkasan berikutnya akan menghapus kata kunci yang dikosongkannya.
  **Indeks ulang pencarian (Arab, Tionghoa, Jepang)** mengindeks artikel yang ditulis sebelum
  versi ini dengan cara yang sama seperti artikel baru, sehingga artikel lama berbahasa Arab, Tionghoa, dan Jepang juga ditemukan
  per kata. Ia membaca setiap artikel satu kali dan hanya mengindeks ulang artikel yang entri pencariannya akan
  berubah; ini adalah tugas yang dapat dijeda di pengelola tugas, dan **Laporan indeks ulang pencarian (.json)**
  menunjukkan berapa banyak yang diperiksa dan diindeks ulang, per aksara. Jalankan lagi setelah memperbarui jieba atau
  kamus bahasa Jepang: artikel yang dipenggal secara berbeda oleh kamus baru akan
  diindeks ulang, dan laporannya menyebutkan versi yang dipakai saat dijalankan.
- **Instrumentasi uji lapangan sementara (siklus uji langsung 0.0.8).** Selama
  siklus ini aplikasi secara otomatis menguji setiap permukaan jaringan satu kali *di dalam
  putaran pengumpulan Anda sendiri* (verifikasi feed kalender dalam kelompok kecil yang sopan, impor feed pasar
  dan indeks, satu jalur hukum, satu jalur wiki) dan mencatat setiap
  hasil kata demi kata di `data/field_test.jsonl`, yang disertakan dalam paket debug.
  **Tujuan:** perbaikan diri berulang atas daftar sumber, feed,
  dan kalender instalasi bawaan berdasarkan hasil nyata — pemelihara memasang ulang,
  mengklik seluruhnya, dan membagikan paket itu kepada tim pengembangan. **Fitur ini nonaktif
  secara bawaan sejak 0.1** — aktifkan untuk siklus uji langsung dengan `OO_FIELD_TEST=1`.
  Aplikasi tidak pernah mengirimkan apa pun: log tetap di mesin ini sampai *Anda*
  mengunduh dan membagikannya. Proses mulai tetap sepenuhnya luring dalam kedua kasus.
- **Log diagnostik:** sintesis yang dapat dibagikan tentang bagaimana aplikasi melihat korpus Anda — dibuat
  hanya ketika Anda mengklik, hanya berisi hitungan dan struktur (tidak pernah skor), dan hanya Anda yang menentukan siapa
  yang mendapat berkasnya. Panel ini memiliki SATU tombol **Diagnostik**, kotak **Menyeluruh**-nya, dan dua tautan kecil, **Semua kata kunci** dan **Simpan lagi Diagnostik terakhir**; setiap log lain di tabel ini adalah **anggota arsip Diagnostik**, bukan tombol
  tersendiri (beberapa memuat lebih dari satu laporan: `selftests.json` memuat tiga belas uji-mandiri mekanisme
  masing-masing dengan vonisnya, `storage.json` pembacaan jejak penyimpanan, komposisi, volume, dan persistensi,
  `contention.json` gerbang tulis dan atribusi kemacetan, `ai-runs.json` hasil tugas AI terakhir,
  `run-journal.json` ringkasan beserta baris mentahnya; `merged.replaces` milik anggota yang digabung di manifes
  menyebutkan berkas yang digantikannya, sehingga arsip lama dapat dibaca berdampingan dengan arsip baru):

  | Ekspor atau anggota arsip | Apa itu |
  |---|---|
  | **Diagnostik** (dan kotak **Menyeluruh**-nya) | SATU arsip berisi semua yang dapat dikatakan instalasi ini tentang dirinya, dibangun di latar belakang (aplikasi tetap dapat dipakai) lalu diserahkan: **satu berkas** jika muat dalam 4 MB, jika tidak **berkas bernomor masing-masing paling banyak 4 MB** (`…-part-03-of-12.zip`) ditambah `…-manifest.zip` kecil yang mencantumkan setiap berkas beserta ukuran dan SHA-256-nya. Setiap berkas dapat dibuka sendiri-sendiri di alat unzip apa pun. **Cepat (Quick)** (bawaan) menulis catatan lebih dulu, saat pengumpulan masih berjalan, lalu sebanyak mungkin pemindaian korpus Anda yang muat dalam sepuluh menit, yang tersingkat lebih dulu; pemindaian yang tidak muat **disebutkan di dalam berkas** sebagai tidak dijalankan, beserta alasannya, tidak pernah dibuang diam-diam. **Menyeluruh** (kotak di samping tombol, kosong lagi setiap kali panel dibuka) menjalankan setiap pemindaian, masing-masing hingga lima menit, dengan pengumpulan dijeda selama pemindaian berjalan (terukur 27 hingga 47 menit pada korpus besar). `manifest.json` di dalam berkas menyebutkan mode mana yang dijalankan, mesin tempat ia dijalankan (build, versi pustaka, tingkat memori, nama sakelar `OO_*` yang diatur, tidak pernah nilainya), dan untuk setiap anggota areanya (memori, penyimpanan, basis data, sesi, jalannya proses, kata kunci, antarmuka, sumber, AI, uji-mandiri, build). Lihat "Menyimpan berkas bernomor" di bawah |
  | **Simpan lagi Diagnostik terakhir** (tautan di bawah tombol, ditampilkan setelah ada build) | arsip jadi yang sama, disimpan lagi (ketik nomor bagian di "Mulai dari nomor bagian" terlebih dahulu dan penyimpanan dimulai dari sana, sehingga Anda dapat mengirim ulang hanya bagian yang gagal diunggah). Tautan ini hanya memakai ulang arsip yang sudah Anda bangun — tidak pernah memulai build baru. Jika satu log terlalu besar untuk muat dalam satu berkas, log itu dipotong pada batas catatan menjadi potongan bernomor, dan manifes menyebutkan yang mana (potongan per byte, `.part0001of0003`, adalah pilihan terakhir dan disebutkan di `volumes.json`) |
  | **Semua kata kunci** (tautan) | daftar per kata kunci: setiap kata kunci di korpus (bukan hanya yang teratas per bahasa), tanpa batas ukuran total, sebagai berkas bernomor masing-masing paling banyak 4 MB. Berkas-berkas pertama memuat 5.000 teratas setiap bahasa, jadi jika Anda tidak dapat mengirim semuanya, kirimlah sesuai urutan nomor. Daftar ini ditulis ke disk satu kelompok demi satu kelompok, sehingga memori aplikasi tetap datar berapa pun ukuran korpusnya; korpus besar menghasilkan banyak berkas (halaman menyebutkan berapa banyak sebelum Anda menyimpan satu pun) dan memakan waktu beberapa menit, dan ekspor berhenti dengan pesan yang jelas (dan menghapus berkas parsialnya, sejauh drive mengizinkan) jika memori atau disk tidak cukup. Semua hal lain yang dimuat log kata kunci, jika build Diagnostik menjalankannya, ada di arsip Diagnostik sebagai `keyword-log-digest.json`: keluarga (1.000 teratas dicetak, setiap keluarga dihitung dalam ringkasan berkas), koreksi Anda, super-grup, konsentrasi per sumber, kandidat kata henti dan cincin, serta hitungan korpus, sebagaimana dimuat log kata kunci, ditambah 100 kata kunci teratas menurut jumlah sebutan dengan angkanya dihilangkan. Build Cepat pada korpus besar dapat menyebut digest itu sebagai tidak dijalankan karena tidak muat dalam sepuluh menit (centang **Menyeluruh**), komputer yang tidak memiliki memori cukup untuknya menyebutnya sebagai ditolak, dan digest yang melewati batas lima menitnya sendiri disebut sebagai dilewati (Menyeluruh tetap mempertahankan batas itu); tautan ini kemudian menjadi jalan menuju kata kunci, dan ringkasannya sendiri dibangun atas setiap kata kunci, bukan hanya 5.000 pertama tiap bahasa. Pada komputer yang kekurangan memori tetapi tetap menjalankan digest, keluarga dikelompokkan hanya atas kata kunci pertama tiap bahasa, dan berkasnya menyatakan hal itu serta menunjuk ke tautan ini. Tidak ada tombol untuk menyimpan lagi set berkas kata kunci terakhir: setelah Anda memuat ulang halaman, tekan tautan itu untuk membangun set baru |
  | **Uji-mandiri kata kunci (.json)** | pemeriksaan kasus acuan (golden case) bahwa pra-seleksi kata kunci masih berperilaku benar (mis. *WHO* ≠ *who*) |
  | **Laporan mesin kata kunci (.json)** | komposisi, presisi entitas, cakupan terjemahan/tag, status per bahasa |
  | **Kurva pertumbuhan kata kunci / (.json)** | kumulatif kata kunci berbeda dibandingkan kata yang ditambahkan (apakah kosakata mulai jenuh?) |
  | **Diagnostik kartu beranda (.json)** | apakah setiap Petunjuk di Beranda membuka korpus persisnya atau cadangan yang kabur? |
  | **Log ekstraksi tanggal (.json)** | cakupan penandaan tanggal |
  | **Keterisian bulan (Month occupancy) (.json)** | dari nama-nama bulan yang dibuang oleh filter kata kunci, berapa banyak yang sebenarnya merupakan bagian dari tanggal — bukti untuk menentukan apakah filter itu sebaiknya menjadi sadar-tanggal |
  | **Log jaringan (.json)** | hasil pengambilan dengan vonis yang memperhitungkan transport |
  | **Laporan kinerja / Tolok ukur penskalaan / Tolok ukur rollup (.json)** | pengukuran waktu dan pemeriksaan penskalaan |
  | **Paket debug (.json)** | paket dukungan yang terkonsolidasi |

  **Menyimpan berkas bernomor.** Halaman menyebutkan berapa banyak berkas yang siap ("13 berkas berukuran paling banyak 4 MB sudah siap (manifes: 1, bagian bernomor: 12)")
  dan menyerahkannya ke peramban Anda **lima per klik**, manifes lebih dulu, karena lima adalah jumlah yang muat dalam satu pesan unggahan dan sebuah klik adalah yang membuat
  peramban mau menerima unduhan. Peramban Anda mungkin bertanya sekali untuk mengizinkan beberapa unduhan: izinkan. Setelah lima yang pertama, tombolnya bertuliskan "Simpan 5 berikutnya";
  "Simpan semua sisanya" ditawarkan setiap kali tersisa lebih dari lima berkas, untuk satu klik yang menyelesaikan semuanya. Bundel berisi lima berkas atau kurang, yang merupakan kasus biasa,
  diserahkan ke peramban Anda oleh halaman itu sendiri saat build selesai (klik yang memulainya sudah lama berlalu); "Simpan lagi Diagnostik terakhir" mengirim berkas yang sama lagi. Halaman hanya dapat *meminta peramban Anda* menyimpan
  sebuah berkas, jadi ia mengatakan "Peramban Anda diminta menyimpan 5 dari 13 berkas", tidak pernah bahwa berkas itu sudah tersimpan: periksa folder unduhan Anda (peramban yang menolak
  pertanyaan beberapa-unduhan tidak menyimpan apa pun dan tidak memberi tahu halaman). Selama berkas sedang dikirim, tombol-tombol berwarna abu-abu, dan klik kedua tidak
  berpengaruh apa-apa. Setiap berkas paling banyak 4.000.000 byte (ukuran tempat aplikasi ini memotong) dan dapat dibuka sendiri-sendiri, sehingga Anda dapat mengirim sebagian sekarang dan
  sisanya nanti. Untuk mengirim lagi hanya sebagian berkas, ketik nomor bagian di "Mulai dari nomor bagian" lalu tekan "Simpan mulai dari bagian ini": ia menyerahkan lima berkas
  mulai dari bagian itu (manifes tidak disimpan lagi), dan nomor yang melewati bagian terakhir dimulai dari bagian terakhir dan mengatakannya. Nomor yang Anda ketik di kotak yang sama juga memberi tahu
  "Simpan lagi Diagnostik terakhir" dari mana harus mulai (nomor yang ditulis halaman itu sendiri di sana diabaikan, jadi "lagi" dengan kotak yang tidak disentuh
  dimulai dari manifes). Mengirim ulang sebuah bagian tidak menggeser "Simpan 5 berikutnya": tombol itu melanjutkan dari berkas terjauh yang sudah diserahkan ke peramban. Mengetik nomor yang mendahului berkas yang sudah tersimpan akan melewati berkas-berkas
  di antaranya (hitungan di baris status menyebutkan berapa banyak yang diminta); ketik nomor bagian pertama yang hilang untuk mengisi celahnya.
  Sebuah set lengkap jika setiap nama dari `…-part-01-of-NN` hingga `…-part-NN-of-NN` ada dan SHA-256-nya cocok dengan
  manifes. Untuk membaca sebuah set dengan skrip analisis, berikan foldernya (atau salah satu berkasnya): `python scripts/analyze_keyword_log.py <folder>` — skrip itu
  menyebutkan bagian yang hilang atau berbeda dari manifes, melewati bagian yang rusak, dan membaca sisanya.

  Panel yang sama juga menjalankan **pengayaan sumber** lokal (menyimpulkan tag topik dari
  korpus Anda) dan putaran **Wikidata** dengan persetujuan (jenis sumber, penemuan sumber baru).
- **Keamanan & penggunaan berisiko (Lanjutan → Keamanan):** alat untuk jurnalis yang bekerja di bawah
  tekanan, masing-masing diberi label dengan **batasan jujurnya**:
  - **Enkripsi saat diam (bawaan untuk korpus baru).** Basis data baru
    dienkripsi SQLCipher 4 di disk: setiap kali dimulai, aplikasi meminta **FRASA
    SANDI itu** — satu rahasia yang tetap, seperti ID pengguna (`OO_DB_PASSPHRASE` untuk
    penggunaan berskrip/tanpa antarmuka). **Tidak ada pemulihan dan tidak ada alternatif
    dekripsi**: frasa sandi yang hilang berarti waktu untuk mengumpulkan ulang, karena
    korpus dibangun kembali dari web — korpus tidak memuat apa pun yang bersifat pribadi selain yang
    di-scrape dan disimpulkan dari sumber publik. Korpus teks biasa yang sudah ada tetap
    berfungsi tanpa diubah; **Pengaturan → Lanjutan → Keamanan → "Enkripsi korpus ini…"** mengonversi
    satu korpus *di tempat* (persetujuan eksplisit, verifikasi penuh sebelum pertukaran, dan
    snapshot teks biasa yang sengaja disimpan sebagai jalan keluar Anda — hapus snapshot itu setelah
    Anda berhasil membuka kunci). **Doctor** (`GET /api/system/doctor`,
    dan panel yang sama) membuktikan keadaan *sebenarnya* dari setiap penyimpanan dengan membaca
    header berkasnya — korpus, log kustodi, kunci penandatanganan — tidak pernah berdasarkan asumsi.
    **Batasan jujurnya:** enkripsi saat diam melindungi *berkas yang disita atau
    disalin*. Enkripsi ini tidak dapat melindungi sesi berjalan yang telah dibobol (kunci berada di
    memori selama aplikasi berjalan), dan enkripsi ini independen dari enkripsi disk penuh
    hanya jika kedua frasa sandi berbeda. Pengoperasian teks biasa tetap tersedia
    sebagai pilihan eksplisit (`OO_DB_PLAINTEXT=1`) — aplikasi tidak pernah menampilkan layar
    kunci di atas berkas teks biasa, karena itu akan menjadi keamanan palsu.
    Cadangan dari korpus terenkripsi berfungsi tanpa perubahan: anggota artefak bersifat
    portabel, amplop artefak terenkripsi itu sendiri melindunginya saat diam,
    dan pemulihan mempertahankan enkripsi korpus Anda (diverifikasi oleh pengujian).
  - **Cadangan terenkripsi** — snapshot yang dilindungi frasa sandi (AES-256-GCM + scrypt).
    Frasa sandi yang hilang atau salah berarti berkas tidak dapat dibuka: tidak ada pemulihan.
    Untuk mengembalikan cadangan terenkripsi, gunakan **pemulihan penggabungan aditif** di
    **Data & cadangan** (di atas) — pemulihan itu menampilkan pratinjau, lalu melengkapi korpus Anda tanpa pernah
    menggantinya, dan tidak pernah mendekripsi penyimpanan aktif Anda secara diam-diam. *(Pemulihan lama yang destruktif
    dengan mengganti korpus terenkripsi telah dihapus.)*
  - **Pemeliharaan basis data** — *Padatkan basis data (VACUUM)* membangun ulang berkas
    basis data: memulihkan ruang yang ditinggalkan oleh penghapusan (ditampilkan sebagai “Ruang yang dapat
    dipulihkan”, pembacaan `PRAGMA freelist_count` yang nyata) dan mendefragmentasi indeks.
    Waktunya sebanding dengan ukuran berkas dan penulisan pengumpulan dijeda
    selama prosesnya berjalan; hasilnya melaporkan byte yang benar-benar dibebaskan dan durasinya. Proses ini
    tidak pernah menafsirkan atau menghapus data. Ia membangun salinan yang dipadatkan di memori
    (menulisnya ke berkas sementara merusak berkas terenkripsi pada ukuran halaman aplikasi,
    terukur), jadi ia terlebih dahulu memeriksa bahwa komputer memiliki memori yang cukup untuk itu
    (sekitar 1,25 kali bagian berkas yang terpakai, di atas memori bebas
    yang selalu disisakan aplikasi untuk dirinya sendiri) dan ruang di drive (sekitar dua kali
    bagian yang terpakai, ditambah ukuran log berkas itu), dan jika salah satunya kurang
    ia menyebutkan yang mana, beserta angkanya, dan tidak dimulai. Angka yang tidak dapat
    dibacanya tidak diperiksa, dan ia juga menyatakan hal itu.
  - **Mode pengambilan jaringan** — *Transparan* (bawaan; sopan, menyebut nama alat ini di
    User-Agent) atau *Terlindungi* (pengambilan web oleh aplikasi dialihkan melalui proxy yang **Anda** jalankan,
    mis. Tor, dengan User-Agent generik). Satu-satunya pengecualian User-Agent adalah permintaan API
    dan dump aplikasi ke server Wikimedia (fitur Wikipedia, Wikidata, dan dump-nya):
    kebijakan API Wikimedia meminta setiap alat menyebutkan namanya, jadi dalam mode terlindungi permintaan
    tersebut tetap membawa User-Agent milik alat itu sendiri, melalui proxy yang sama dan hanya lewat
    https. Apa pun lainnya yang diambil dari situs Wikimedia (artikel yang dikumpulkan seperti halaman
    lainnya) mendapat User-Agent generik. Tiga hal tetap terhubung langsung bahkan dalam mode terlindungi, sebagaimana
    disebutkan keterangan hover jendela persetujuan jaringan untuk masing-masing: penarikan kotak surat buletin,
    penjangkaran OpenTimestamps, dan unduhan AI lokal.
    Mode terlindungi **tidak dapat menjamin anonimitas** — Anda harus menjalankan dan memercayai proxy itu
    sendiri; mode ini menolak diaktifkan tanpa URL proxy. Proxy SOCKS seperti Tor tidak memerlukan
    pemasangan tambahan apa pun.
  Dua tindakan yang **tidak dapat dibatalkan** berada satu bagian lebih ke bawah, di **Lanjutan →
  Copot pemasangan dan hapus**, sengaja dijauhkan dari semua yang ada di atas:

  - **Hapus darurat** — menghapus korpus, kunci, dan cache di mesin ini secara permanen
    (dikonfirmasi dua kali). **Batasan:** menimpa di tempat *tidak* menjamin data
    tidak dapat dipulihkan pada SSD/flash — untuk itu, gunakan enkripsi disk penuh (LUKS/Qubes/Tails)
    dan musnahkan kuncinya. Tersedia juga CLI `panic` dan mode jalan `--ephemeral`
    (data hanya di RAM, dihapus saat keluar).
  - **Hapus instalasi aplikasi** — menghapus **virtualenv** dan **peluncur desktop** aplikasi,
    lalu menghentikan server (dikonfirmasi dengan mengetik). **Data Anda tetap disimpan** (gunakan Hapus darurat terlebih dahulu untuk
    memusnahkannya); folder aplikasi dibiarkan di tempatnya untuk dihapus secara manual. Setara dengan
    `./install.sh --uninstall` atau ikon desktop **“Copot Open Omniscience” (“Uninstall Open Omniscience”)** yang dibuat
    pemasang di samping dua peluncur aplikasi.

  Tata kelola dan batas merah penggunaan ganda yang membatasi semua ini ada di
  [`GOVERNANCE.md`](GOVERNANCE.md) (juga di **Bantuan & dokumen**).

### 3.10 Bantuan & dokumen

**Kegunaannya:** membaca dokumentasi **di dalam aplikasi**, secara luring. Sebuah
daftar di sisi kiri memilih dokumen (**Manual pengguna** ini adalah bawaannya; dokumen lain
membahas topik tertentu secara lebih mendalam), yang ditampilkan di sebelah kanan dengan **pencarian di halaman**. Buka
dari **?** di bilah atas atau dari palet perintah ("Buka Manual pengguna" ("Open the User Manual")). Skema
API mentah ada di `/openapi.json`.

---

## 4. Alur kerja umum (panduan langkah demi langkah)

**Mengumpulkan berita tentang suatu topik lalu mencarinya**
1. **Pengaturan → Lanjutan → Sumber** → pastikan sumber yang relevan sudah diaktifkan (saring menurut negara/tag).
2. **Pengaturan → Lanjutan → Pengumpulan** → klik **Ambil umpan** untuk tiap sumber, atau atur
   **penjadwal (scheduler)** ke mode RSS dengan **Tag / kata kunci** Anda lalu **Mulai** (atau cukup sambungkan ke internet
   — pengumpulan berjalan otomatis).
3. Cari dari **omnibar** → kueri Boolean → **Ekspor CSV/JSON (Export CSV/JSON)** bila perlu.

**Memantau suatu bidang liputan secara terus-menerus di latar belakang**
1. **Pengaturan → Lanjutan → Pengumpulan** → penjadwal **Mode: Umpan RSS**, atur **Bahasa**/**Tag**,
   **Pratinjau target**, atur **Interval**, centang **Mulai otomatis saat diluncurkan**,
   **Simpan (Save)**.
2. Jika mau, aktifkan **Bukti & kustodi → Catat otomatis saat menelan** agar setiap tangkapan
   ditandatangani begitu masuk.

**Menghasilkan bukti suatu artikel yang dapat dipertanggungjawabkan di pengadilan atau di depan redaktur**
1. Cari artikel tersebut dari omnibar.
2. **Ekspor bukti bertanda tangan** (atau **Bukti & kustodi → Ekspor bundel** untuk satu item).
3. Serahkan kepada penerima bundel tersebut beserta `scripts/verify_evidence.py` /
   `verify_custody.py`; mereka memverifikasinya secara luring, tanpa harus memercayai Anda atau alat ini.
4. Untuk bukti *waktu* yang independen, aktifkan **OpenTimestamps** dan jangkarkan akar Merkle
   bundel tersebut (perhatikan peringatan privasinya).

**Mengawasi artikel Wikipedia yang diperdebatkan dari upaya perusakan**
1. **Pengaturan → Wikipedia** → tambahkan halaman (edisi + judul), centang **gunakan ORES (use ORES)**,
   **Lacak sekarang**.
2. Tinjau **Perubahan yang ditandai**; buka **Perbedaan** pada apa pun yang mencurigakan.

**Melacak harga komoditas terhadap berita**
1. **Komoditas** — umpan pilihan sudah diperbarui otomatis di latar belakang;
   untuk harga dari halaman tertentu, tambahkan **aturan ekstraksi harga** lalu **Uji** aturan itu.
2. Klik kartu deret → baca grafiknya dan **korelasi**-nya dengan suatu kueri berita.

**Memindahkan (atau menggabungkan) korpus Anda ke mesin lain**
1. **Pengaturan → Data & cadangan → Ekspor / Cadangkan…** — pilih folder/drive tujuan dan
   frasa sandi; korpus dialirkan keluar sebagai volume terenkripsi + paritas (berapa pun ukurannya).
2. Di mesin lain, **Pengaturan → Data & cadangan → Impor…** — arahkan ke folder itu dan
   pulihkan. Pemulihan ini bersifat aditif — ia melengkapi korpus mesin tersebut dan tidak pernah
   menggantikannya, sehingga Anda juga dapat memakainya untuk *menggabungkan* dua korpus. Berkas tunggal
   lama `oo-backup-2` tidak memerlukan perlakuan khusus: pemindaian Impor menemukannya di mana pun ia
   tersarang di dalam folder yang Anda tunjuk dan menawarkannya sebagai item tersendiri, sehingga cadangan lama tetap dapat dipulihkan.

**Sebagai gantinya, salin seluruh folder — cara utama yang sah untuk memindahkan atau mencadangkan**

Alat di dalam aplikasi ada untuk menambahkan hal-hal yang tidak bisa dilakukan oleh salinan berkas (manifes
bertanda tangan, paritas yang memperbaiki volume rusak, penggabungan aditif dua korpus, pemulihan selektif). Alat itu
bukan gerbang yang wajib Anda lewati. Menyalin folder data adalah cara yang didukung pada ukuran berapa pun, dan
itulah cara yang tepat untuk memindahkan seluruh isi sebuah mesin:

1. **Hentikan aplikasi** — tombol daya di bilah atas, atau Ctrl-C di terminalnya. Ini
   tidak opsional: salinan yang diambil saat aplikasi berjalan dapat menangkap WAL yang baru setengah tertulis.
2. Salin seluruh folder **data** (§5.1 — `<app folder>/data/`, atau ke mana pun `OO_DATA_DIR`
   menunjuk). Bukan folder aplikasi/kode: kode dapat dipasang ulang, data tidak.
3. Di mesin lain, letakkan folder itu di tempat yang Anda inginkan dan arahkan `OO_DATA_DIR` ke sana —
   atau, pada pemasangan yang benar-benar baru, pilih folder itu pada langkah peluncuran pertama (§5.1).

Korpus tetap terenkripsi saat tersimpan selama penyalinan, dan kuncinya ikut berpindah di dalam folder,
sehingga **frasa sandi adalah satu-satunya hal yang harus Anda bawa secara terpisah**. Sejak 2026-08, bobot AI lokal
juga berada di folder data, sehingga salinan ikut membawanya — itulah yang membuatnya
benar-benar pemindahan seluruh mesin, bukan hanya pemindahan korpus.

---

## 5. Referensi teknis

### 5.1 Lokasi data Anda

Ditentukan oleh `src/paths.py`, dengan urutan prioritas berikut:

1. **`OO_DATA_DIR`** jika diatur (selalu menang).
2. **Checkout sumber** — jika dijalankan dari repo yang dapat ditulisi (pemasangan dev/editable/Qubes
   di `$HOME`), data berada di `<repo>/data/`.
3. **Per pengguna** — selain itu XDG: `$XDG_DATA_HOME/open-omniscience` atau
   `~/.local/share/open-omniscience`.

Kasus 2 adalah yang normal untuk pemasangan lewat `install.sh`: pemasang mengkloning pohon yang
dapat ditulisi, sehingga data Anda ada di `<app folder>/data/` dan jalur XDG pada kasus 3
tidak pernah dibuat. Jadi bukan bug bila Anda mencarinya dan jalur itu tidak ada.

**Memilih folder pada peluncuran pertama.** Saat pertama kali Anda menjalankan aplikasi —
setelah langkah bahasa dan dokumen hukum, sebelum Anda mengatur frasa sandi — aplikasi menanyakan di mana
korpus Anda akan disimpan. Mempertahankan bawaan cukup satu klik. Jika Anda memilih folder
lain (misalnya drive eksternal), aplikasi membuat folder bernama **`OOS data`**
di dalamnya dan mencatat pilihan itu di `oo.env` pada akar pemasangan, yang
dibaca oleh `scripts/launch.sh` setiap kali dijalankan.

Dua hal tentang langkah itu disengaja dan perlu Anda ketahui:

* **Langkah ini hanya muncul pada pemasangan yang benar-benar baru.** Begitu korpus sudah ada, aplikasi menolak
  mengubah pengaturan ini, karena ia tidak dapat memindahkan apa yang sudah ada di sana: kunci,
  log kustodi, dan penyimpanan model akan mengikuti pengaturan baru sementara korpusnya
  tertinggal, dan saat dijalankan berikutnya aplikasi akan menemukan folder kosong lalu menawarkan untuk menyiapkannya.
  Memindahkan korpus yang sudah ada dilakukan dengan penyalinan folder biasa yang dijelaskan di §4 ("Sebagai gantinya, salin
  seluruh folder") — hentikan aplikasi, salin folder data, arahkan `OO_DATA_DIR`
  ke salinannya.
* **Memilih folder lain mengakhiri penyiapan dan meminta Anda menjalankan aplikasi lagi.**
  Belum ada yang dibuat pada saat itu; folder tersebut baru berlaku pada saat aplikasi
  dijalankan berikutnya, sehingga melanjutkan dalam sesi yang sama akan menaruh korpus di folder lama
  sementara pilihan yang tercatat menunjuk ke folder baru.

Anda diberi tahu, bukan dihalangi, jika foldernya tidak lazim: folder yang sudah berisi
korpus (melanjutkan akan membukanya alih-alih membuat yang baru), sistem berkas yang
berbasis RAM (apa pun yang ditulis di sana hilang saat mesin dinyalakan ulang), atau ruang kosong yang sedikit, disertai
angkanya. Hanya folder yang benar-benar tidak dapat ditulisi oleh aplikasi yang ditolak.

**Jika drive dicabut.** Folder yang dipilih dengan cara ini mendapat berkas penanda kecil,
`.oos-volume`, yang id-nya juga dicatat di `oo.env` (`OO_DATA_VOLUME_ID`). Aplikasi
membacanya setiap dua detik selama berjalan. Jika drive hilang:

* Aplikasi mencatat pemutusan itu di disk internal (di bawah
  `~/.local/state/open-omniscience/`, karena ia tidak dapat menulis ke drive yang hilang).
  Bundel diagnostik membawa log itu, dan saat dijalankan berikutnya aplikasi menyebutkannya ketika
  menjelaskan bagaimana sesi sebelumnya berakhir.
* Pengumpulan dijeda dan sebuah jendela meminta Anda menyambungkan kembali drive dalam 30 detik.
  Jika drive yang sama kembali, aplikasi dimulai ulang untuk membuka kembali data Anda (korpus
  terenkripsi akan meminta frasa sandinya lagi). Aplikasi tidak bisa sekadar melanjutkan: koneksi
  basis data ditetapkan saat aplikasi dimulai.
* Setelah 30 detik itu, hitung mundur kedua menutup aplikasi dengan rapi dalam 30 detik
  berikutnya; **Tutup sekarang** melakukannya seketika. Menyambungkan kembali selama hitung mundur kedua ini
  tetap akan memulai ulang aplikasi.
* Apa pun yang sedang ditulis pada saat-saat terakhir sebelum drive dicabut dapat hilang. Basis
  data itu sendiri tetap konsisten: SQLite membatalkan penulisan yang belum selesai saat basis data
  dibuka berikutnya.

Jika Anda menjalankan aplikasi ketika drive tidak tersambung, aplikasi tidak membuat folder kosong
sebagai gantinya: ia menampilkan halaman "drive data Anda tidak tersambung", memeriksa
lagi setiap beberapa detik, dan membuka aplikasi begitu drive kembali. Drive lain
yang dipasang pada jalur yang sama dikenali sebagai drive yang berbeda (penandanya tidak
cocok). Jika Anda sengaja menghapus folder itu, hapus baris `OO_DATA_DIR` dan
`OO_DATA_VOLUME_ID` dari `oo.env` untuk memulai lagi dengan korpus baru yang kosong.
Penghapusan darurat melakukan ini untuk Anda. Jika sistem memasang drive pada jalur baru
setelah dicolokkan kembali, aplikasi tidak dapat menemukannya di sana: tutup aplikasi, lalu arahkan `OO_DATA_DIR` di
`oo.env` ke jalur baru tersebut.

Di direktori itu Anda akan menemukan: `open_omniscience.db` (korpus, SQLite/WAL),
`app_settings.json` (tema, batas hasil), `custody_settings.json` (preferensi
kustodi), kunci kustodi, dump Wikipedia yang telah diunduh, snapshot `pre-restore-*.db`
jika ada, dan `models/` — bobot AI lokal, yang berada di dalam direktori data milik
aplikasi sendiri alih-alih di direktori rumah masing-masing backend:

| jalur | isi |
| --- | --- |
| `models/ollama/` | Penyimpanan model Ollama (`OLLAMA_MODELS` menunjuk ke sini) |
| `models/huggingface/hub/models--<org>--<name>/` | Bobot vLLM, satu folder per repo (`HF_HOME` menunjuk ke `models/huggingface`) |
| `cache/` | Cache komputasi server vLLM — kernel Triton, torch Inductor, cache JIT CUDA, akar cache dan konfigurasi milik vLLM sendiri. Dibangun pada saat pertama dijalankan, aman dihapus (akan dibangun ulang), dan dapat mencapai beberapa GB |
| `vllm_start_attempts.jsonl` | Setiap kali server vLLM dimulai dan setiap kali berhenti, beserta kata-kata kegagalan itu sendiri. Disimpan **di sini** alih-alih di dalam lingkungan vLLM, sehingga memasang ulang vLLM — hal pertama yang dicoba kebanyakan orang ketika server tidak mau berjalan — tidak menghapus catatan tentang mengapa server itu gagal |
| `vllm_failed_starts/` | Log lengkap dari masing-masing beberapa percobaan mulai terakhir yang **gagal**. Log server yang sedang berjalan ditimpa oleh percobaan berikutnya, dan perulangan coba-lagi menimpanya dalam satu menit, sehingga salinan diambil begitu suatu percobaan mulai terlihat gagal. Paling banyak beberapa ratus KB |

Mengatur sendiri `OLLAMA_MODELS`, `HF_HOME`, atau variabel cache mana pun
(`XDG_CACHE_HOME`, `TRITON_CACHE_DIR`, `TORCHINDUCTOR_CACHE_DIR`,
`CUDA_CACHE_PATH`, `VLLM_CACHE_ROOT`, `VLLM_CONFIG_ROOT`) selalu menang —
aplikasi mengekspor ulang nilai Anda alih-alih menimpanya. Pengalihan ini hanya berlaku untuk
**server**: pemasangan vLLM tetap memakai cache wheel normal milik pip, sehingga
pemasangan ulang tidak mengunduh ulang beberapa GB yang sudah ada. Bobot yang diunduh **sebelum** 2026-08-04
masih berada di `~/.cache/huggingface/hub/` milik Hugging Face sendiri; Pengaturan → AI melaporkannya
dan menyebutkan ke mana harus memindahkannya, dan tidak ada yang dipindahkan atau dihapus untuk Anda.

### 5.2 Variabel lingkungan

> **Catatan kejujuran:** tabel ini mencantumkan hal-hal pokok yang dihadapi operator — ini **bukan** setiap
> variabel lingkungan yang dapat dibaca kode (sebuah audit menghitung ~259 rujukan variabel lingkungan
> di basis kode). Variabel yang tidak ada di tabel ini mencerminkan keringkasan
> manual, bukan klaim bahwa variabel tersebut tidak ada.

| Variabel | Kegunaan |
|---|---|
| `OO_DATA_DIR` | Mengganti direktori data (lihat di atas). |
| `OO_HOST` / `OO_PORT` | Alamat/port pengikatan (bawaan `127.0.0.1:8000`). |
| `OO_AUTOSEED` | Mengisi katalog seluruh dunia pada saat pertama dijalankan (bawaan aktif; `0` untuk menonaktifkan). |
| `OO_NO_SCHEDULER` | Atur `1` agar penjadwal latar belakang tidak pernah dimulai otomatis; aplikasi lalu dijalankan dalam keadaan daring, bukan dalam mode pesawat. Pelindung soket mode pesawat tetap dipasang dalam kedua kasus (hanya `OO_AIRPLANE_SOCKET_GUARD=0` yang meniadakannya), sehingga menyalakan mode pesawat belakangan tetap memblokir koneksi keluar di tingkat soket (beberapa sisa pengecualian tercantum di SECURITY.md). |
| `OO_NO_INDEX` | Atur `1` untuk melewati pengindeksan Wawasan otomatis. |
| `OO_CUSTODY_ON_INGEST` | Bawaan lama untuk pencatatan kustodi otomatis saat menelan (preferensi di UI menimpanya begitu disimpan). |
| `OO_KEY_PASSPHRASE` | Mengenkripsi kunci privat kustodi saat tersimpan (AES-256-GCM melalui scrypt). Tanpa variabel ini, frasa sandi basis data yang membungkusnya; tanpa keduanya, kunci ditulis `0600` tanpa enkripsi dan dilaporkan apa adanya sebagai `plaintext-0600`. |
| `OO_FETCH_TIMEOUT` / `OO_FETCH_MIN_INTERVAL` | Menyetel batas waktu dan interval minimum per host milik pengambil etis. |
| `OO_LLM_MODEL` / `OO_OLLAMA_URL` (atau `OLLAMA_BASE_URL`) | Model lokal bawaan dan endpoint Ollama. |
| `OO_ALLOW_BIG_SCANS` | Atur `1` untuk menjalankan pemindaian latar belakang atas seluruh korpus pada mesin yang memorinya di bawah batas minimum (lihat [Memori pada mesin kecil](#55a-memori-pada-mesin-kecil--satu-satunya-batas-nyata)). Putusannya lalu melaporkan bahwa Anda telah mengesampingkannya. |
| `OO_CKPT_GATE_TIMEOUT_S` | Berapa lama checkpoint WAL di antara putaran menunggu gerbang penulis tunggal sebelum mencatat lewatan secara jujur dan melanjutkan (bawaan `30`). `0` mengembalikan penantian lama yang tanpa batas (checkpoint milik pelindung penyimpanan sendiri tetap menunggu gerbang tulis paling lama 30 s, di thread tersendiri, sehingga lanjutan yang dipaksakan tetap diawasi). |
| `OO_STORAGE_GUARD` | Atur `0` untuk mematikan pelindung penyimpanan (tanpa pengambilan sampel, tanpa jeda). Pelindung ini menjeda pengumpulan dengan sendirinya ketika log tulis-di-muka (write-ahead log) basis data telah tumbuh melewati batas yang diukur dari mesin Anda atau drive hampir penuh, dan melanjutkan dengan sendirinya; "Lanjutkan tetap" pada pemberitahuan memaksa pengumpulan berjalan selagi batas itu masih berlaku, dan berakhir dengan sendirinya jika ruang kosong turun terlalu rendah atau tidak dapat dibaca, jika suatu penulisan gagal karena kekurangan ruang, atau jika batas kedua terlampaui. Jeda yang sama juga menahan pengindeksan ulang latar belakang yang menyelesaikan impor yang terputus serta pembangunan satu kali indeks daftar artikel selama jeda berlangsung (baris task manager keduanya menyebutkan hal ini, dan keduanya berlanjut dengan sendirinya; "Lanjutkan tetap" memaksa pengumpulan berjalan, bukan keduanya). |
| `OO_DAMAGE_GUARD` | Atur `0` untuk mematikan jeda yang mengikuti laporan basis data tentang kerusakan pada salah satu berkas data Anda (laporannya sendiri tetap dicatat di `database-damage.json` di folder data Anda, dan pemberitahuannya lalu menyatakan bahwa jeda dimatikan). Tanpa pengaturan ini, berkas yang dinyatakan rusak oleh basis data tidak ditulisi oleh pengumpulan, langkah-langkah pemeliharaan, atau jalur Wikipedia (masing-masing hanya untuk berkasnya sendiri) sampai Anda memulai pengumpulan lagi (berkas Wikipedia: sampai Anda mematikan lalu menyalakan kembali pengambilan Wikipedia). Jeda yang dipasang oleh pemeriksaan saat mulai (lihat `OO_BOOT_VERIFY`) hanya berakhir ketika tabel-tabel yang disebut pemeriksaan itu terbaca bersih lagi; jeda lainnya berakhir, lalu berhenti lagi pada pembacaan gagal yang pertama jika kerusakannya masih ada. Tidak bergantung pada `OO_STORAGE_GUARD`. |
| `OO_BOOT_VERIFY` | Atur `0` untuk mematikan pemeriksaan berkas data Anda yang berjalan saat aplikasi dimulai, ketika aplikasi masih luring, setelah penghentian yang tidak terduga (dan setelah pemeriksaan sebelumnya tidak selesai atau menemukan kerusakan): setiap tabel dibaca sekali dengan `PRAGMA quick_check` milik SQLite, satu tabel demi satu tabel, pada koneksi hanya-baca, sehingga pemeriksaan ini tidak menulis apa pun. Tabel, daftar tabel, atau pemeriksaan halaman yang melaporkan kerusakan dibaca untuk kedua kalinya pada koneksi baru dan hanya dihitung sebagai kerusakan bila pembacaan kedua sependapat: pembacaan kedua yang berbeda, atau yang tidak dapat dilakukan, membiarkannya tidak terperiksa beserta alasannya, dan tidak ada yang dijeda atau diperbaiki karenanya. Pada berkas terenkripsi, ketika suatu tabel tidak dapat dipastikan (SQLCipher memunculkan galat umum untuk banyak halaman yang rusak), aplikasi juga meminta pemeriksaan halaman milik SQLCipher sendiri sekali (`PRAGMA cipher_integrity_check`, sekitar satu detik per 230 MB) dan mencatat halaman mana yang gagal autentikasinya (berkas yang lebih besar dari 4 GiB tidak diberikan ke pemeriksaan halaman itu, karena ia membaca byte yang salah setelah titik tersebut; catatannya menyebutkan hal ini dan berkas itu tidak dinyatakan bersih); berkas dengan halaman yang gagal dianggap rusak, dan berkas yang semua halamannya lolos tetap tidak dinyatakan bersih selama ada tabel yang belum terjawab. Halaman yang sama sekali tidak dapat dibaca (drive yang gagal) dihitung terpisah dan tidak dengan sendirinya merupakan temuan, dan keluar dari aplikasi saat pemeriksaan itu berjalan tidak menghabiskan salah satu dari tiga percobaan. Pengumpulan menunggu sampai pemeriksaan selesai; berkas yang ditemukan rusak dijeda (lihat `OO_DAMAGE_GUARD`), dan memulai pengumpulan lagi membaca sekali lagi tabel-tabel yang disebutkannya sebelum melepas jeda (untuk berkas Wikipedia, hal ini dilakukan dengan mematikan lalu menyalakan kembali pengambilan Wikipedia). Pemeriksaan yang tidak dapat selesai tidak dicoba lagi setelah tiga kali mulai berturut-turut, dan aplikasi menyatakannya (penahanan ini berlaku melewati setiap mulai normal sampai aplikasi berikutnya berhenti secara tidak terduga, yang merupakan alasan baru untuk memeriksa); hal itu tidak pernah menghapus temuan: berkas yang ditemukan rusak oleh pemeriksaan sebelumnya tetap dijeda sampai tabel-tabel yang disebutkannya terbaca bersih (atau berkas itu diganti). Hasil tiap berkas ada di `database-damage.json` di folder data Anda. |
| `OO_BOOT_REPAIR` | Atur `0` untuk mematikan perbaikan berkas pustaka yang rusak (dan, bersamanya, penghapusan yang dijelaskan di bawah). Secara bawaan, ketika pemeriksaan saat mulai (lihat `OO_BOOT_VERIFY`) membaca suatu tabel di berkas pustaka Anda sebagai rusak, aplikasi memperbaiki berkas itu pada saat mulai tersebut, ketika masih luring dan sebelum pengumpulan menulis apa pun: ia menyalin setiap baris yang masih dapat dibaca, tabel demi tabel, ke berkas baru di sebelahnya, membangun ulang indeks dan indeks pencarian, memeriksa berkas baru dengan pembacaan per tabel yang sama, dan baru setelah itu beralih ke berkas baru. Baris pada halaman yang tidak dapat dibaca tidak ada di berkas baru; pemberitahuannya menyebutkan berapa entri yang tersalin dan berapa yang tidak dapat dibaca, serta di tabel mana. Baris yang baris induknya tidak dapat dibaca tetap disimpan, tidak pernah dihapus, dan dihitung per tabel; di mana suatu tabel akan memberikan nomor baris yang hilang kepada baris berikutnya yang disimpan, perbaikan menambahkan SATU baris pengganti bertanda «(lost …)» pada nomor hilang tertinggi (ini baris yang terlihat, dan indeks pencarian menemukannya dengan tanda tersebut), dan pemberitahuannya menyebutkan tabel-tabel itu. Apa pun yang disimpan aplikasi menunggu selama perbaikan berlangsung (perbaikan memerlukan gerbang tulis, yang aktif secara bawaan: dengan `OO_WRITE_GATE=0` perbaikan menolak dan menyatakannya), dan jika ternyata ada sesuatu yang tetap tersimpan ke berkas itu selama salinan dibuat, salinan itu dibuang dan dibuat lagi pada saat mulai berikutnya, bukan dipasang menggantikan penyimpanan tersebut. Perbaikan memerlukan ruang kosong sebesar seluruh berkas ditambah lognya ditambah cadangan yang dijaga oleh pelindung disk, serta drive yang dapat memberi suatu berkas nama kedua (hard link); ia menyebutkan mana yang kurang dan tidak mengubah apa pun bila ada yang kurang. Hanya berkas pustaka yang diperbaiki, dan hanya setelah pemeriksaan pada saat mulai itu sendiri menemukan kerusakan: berkas Wikipedia dan hukum dijeda seperti sebelumnya tetapi tidak diperbaiki, berkas yang ditemukan rusak saat aplikasi berjalan diperiksa pada saat mulai berikutnya dan diperbaiki saat itu jika pemeriksaan mengonfirmasinya, dan tabel yang tidak dapat dibaca oleh pemeriksaan bukanlah temuan. **Berkas yang rusak disimpan, tidak dihapus:** perbaikan memberinya nama kedua di sebelah berkas baru, `<name>.damaged-<date and time>.<ending>` (dengan lognya di bawah nama yang sama dan `-wal`), karena berkas itu mungkin masih berisi baris yang tidak dapat dibaca oleh salinan, untuk alat pemulihan. **Aplikasi menghapus berkas itu 30 hari setelah berkas baru pertama kali terbaca bersih**, pada saat mulai pertama pada atau setelah tanggal tersebut, tidak pernah selagi perbaikan atau pemeriksaan sedang berjalan atau selagi pustaka dilaporkan rusak lagi; pemberitahuan perbaikan dan zip Diagnostik menyebutkan ukurannya, lokasinya, dan tanggalnya, dan setelah penghapusan menyebutkan bahwa berkas itu telah dihapus dan berapa ukurannya. Jika drive itu sendiri tidak dapat membaca suatu halaman berkas pustaka Anda (pemberitahuannya menyebutkan berapa halaman), aplikasi sama sekali tidak menghapus berkas itu, karena drive yang mulai rusak bisa jadi penyebab halaman-halaman itu tidak terbaca: berkas itu tetap ada sampai Anda menghapusnya sendiri, dan pemberitahuannya meminta Anda memeriksa drive. Dengan `OO_BOOT_REPAIR=0` penghapusan dimatikan dan pemberitahuannya menyatakan demikian. Anda dapat menghapusnya sendiri kapan saja. Aplikasi hanya menghapus berkas yang disisihkan oleh perbaikan (berkas itu harus berada di folder data Anda, berupa berkas biasa, dengan nama persis seperti itu dan merupakan berkas yang sama dengan yang dicatat oleh perbaikan) dan tidak ada yang lain; jika salah satu syarat itu tidak terpenuhi, aplikasi tidak menghapus apa pun, menyatakannya, dan tidak mencoba lagi. Perbaikan yang dimulai dan tidak selesai dicoba lagi pada saat mulai berikutnya; dua kali mulai berturut-turut yang berakhir di tengah perbaikan tidak diikuti percobaan ketiga sampai aplikasi diperbarui (catatannya adalah `database-repair-attempt.json` di folder data Anda). Catatan setiap perbaikan (tanggal, hitungan, nama berkas, dan, begitu terjadi, penghapusannya) ada di `database-damage.json`; catatan ini menyimpan sepuluh terakhir, dan berkas simpanan yang catatannya sudah tergeser dari sepuluh itu tidak pernah dihapus oleh aplikasi. |
| `OO_ARTICLE_INDEXES` | Atur `0` agar dua indeks daftar artikel tidak dibangun. Secara bawaan aplikasi membangunnya sekali, pada saat mulai pertama setelah pembaruan, ketika masih luring: satu untuk filter bahasa dan satu untuk pengurutan menurut judul, sehingga keduanya tetap cepat seiring pustaka bertambah besar (keduanya memakan sekitar 190 MB per 1,5 juta artikel). Pada pustaka besar di drive yang lambat, pembangunan ini dapat memakan beberapa menit; ia tampil di task manager sebagai "Membangun indeks daftar artikel", apa pun yang disimpan aplikasi menunggu sampai selesai, dan ia memerlukan dua hal yang diukurnya terlebih dahulu dan dinyatakannya, tanpa memulai, bila salah satunya kurang: sekitar 400 byte ruang kosong per artikel pada drive tempat berkas data Anda berada, dan memori untuk pengurutan judul (sekitar 300 byte per artikel, disimpan di memori dan tidak pernah ditulis ke berkas sementara, ditambah memori bebas yang selalu disisihkan aplikasi untuk dirinya sendiri; ia menyebutkan angkanya). Saat mulai yang berakhir di tengah pembangunan akan memulainya lagi; dua kali mulai berturut-turut yang berakhir di tengah pembangunan (komputer kehabisan memori atau daya) tidak diikuti percobaan ketiga sampai aplikasi diperbarui, karena pembangunan yang justru menjatuhkan aplikasi tidak boleh menjadi proses mulai yang tidak pernah selesai (catatannya adalah `article-indexes-attempt.json` di folder data Anda; menghapusnya membuat aplikasi mencoba lagi, dan keluar dari aplikasi dengan cara normal mengembalikan percobaan itu). Dengan sakelar dimatikan, atau setelah penolakan yang berulang, setiap kali mulai aplikasi menghabiskan sepersekian detik untuk membandingkan versi basis data dengan tabel-tabelnya. Dengan sakelar dimatikan, daftar tetap berfungsi seperti sebelumnya, hanya lebih lambat pada kedua pilihan itu. |
| `OO_WAL_HIGH_MB` / `OO_DISK_RESERVE_MB` | Mengganti dua batas turunan pelindung penyimpanan dengan angka dalam MB: ukuran log tulis-di-muka saat pengumpulan dijeda, dan ruang kosong yang di bawahnya pengumpulan dijeda (bawaan: diukur dari mesin Anda; batas-batasnya ditampilkan dalam pemberitahuan yang ditampilkan pelindung di task manager selama ia menahan pengumpulan). |
| `OO_STORAGE_GUARD_TRIP_AFTER` / `OO_STORAGE_GUARD_RESUME_AFTER` | Berapa banyak sampel berturut-turut (berjarak sekitar lima detik) yang mengaktifkan dan melepas pelindung (bawaan `2` dan `2`). |
| `OO_WRITE_GATE_WARN_S` | Mencatat peringatan, beserta nama thread yang memegang dan satu tumpukan panggilan (stack), ketika satu penulisan memegang gerbang lebih lama dari nilai ini (bawaan `60`); peringatan ditulis saat penahanan itu terdeteksi, sehingga angkanya paling sedikit sama dengan ambang dan bukan lamanya penahanan. Ketika penahanan seperti itu berakhir, log mendapat baris kedua, `write gate released after 61.3s by 'name'` (lama sebenarnya, hingga sepersepuluh detik, menggantikan 61,3; penahanan di bawah satu detik tidak pernah mendapatkannya). `OO_WRITE_GATE_WATCHDOG=0` mematikan pengawasan ini sepenuhnya. |
| `OO_REINDEX_HOLD_TARGET_S` | Berapa lama satu kelompok (batch) pengindeksan ulang boleh memegang gerbang penulis tunggal sebelum ia melakukan commit dan mempersilakan penulis yang menunggu masuk (bawaan `10`). Ini berlaku untuk pengindeksan ulang latar belakang atas artikel yang diimpor, untuk tugas pengindeksan ulang seluruh korpus (ketika `OO_REINDEX_COMMIT_BATCH` di atas 1), dan untuk pengindeksan ulang yang mengakhiri pemulihan. Commit terjadi lebih awal lagi, pada artikel berikutnya setelah ada penulisan lain yang mengantre di belakangnya, begitu kelompok itu telah memegang gerbang paling sedikit satu detik (sehingga penahanan dapat melewati target sebesar artikel yang sedang diproses dan commit-nya, dan penulis yang selalu mengantre membuat pengindeksan ulang menanggung sekitar satu commit per detik alih-alih satu per artikel). Lebar kelompok (`OO_IMPORT_REINDEX_COMMIT_BATCH`, `OO_REINDEX_COMMIT_BATCH`) tetap menjadi batas atas, dan pada lebar `1` setiap artikel di-commit sendiri-sendiri, sehingga tidak ada kelompok yang bisa diakhiri lebih awal oleh target (laporan pemulihan dan kemajuan tugas pengindeksan ulang tetap menyebutkan target yang berlaku). `0` adalah aturan lama: commit hanya pada lebar kelompok. Nilai yang bukan jumlah detik bernilai nol atau lebih akan mempertahankan bawaan. |
| `OO_HEAVY_TAIL_WAIT_S` | Berapa lama penghitungan ulang briefing Beranda dan jalur pemeliharaan latar belakang saling menunggu alih-alih berjalan bersamaan (bawaan `900`). `0` menunggu tanpa batas. |
| `HTTPS_PROXY` | Merutekan lalu lintas keluar (mis. OpenTimestamps) melalui proksi/Tor. |

### 5.3 Ekstra opsional

Pasang dengan `pip install -e ".[extra]"`:

- **`analysis`** — statistik, analitik kata kunci/entitas, korelasi pasar.
- **`nlp`** — model spaCy untuk pengenalan entitas bernama yang sesungguhnya di Wawasan.
- **`pqc`** — penandatanganan ML-DSA pascakuantum untuk Rantai pengawasan.
- **`timestamping`** — penjangkaran OpenTimestamps (Bitcoin).
- **`dev`** — perkakas pengujian/lint.

Jika suatu ekstra tidak ada, fitur yang bergantung padanya **menurun dengan terang-terangan** (galat yang jelas atau
`503`, status "tidak terpasang" yang jujur) — ia tidak pernah diam-diam memalsukan kemampuan tersebut.

### 5.4 API HTTP

Aplikasi ini adalah server FastAPI di `127.0.0.1:8000`; UI web adalah satu
`index.html` tanpa dependensi yang disajikan di `/`. Skema yang dapat dibaca mesin ada di **`/openapi.json`**. Halaman interaktif Swagger (`/docs`) dan ReDoc
(`/redoc`) **nonaktif secara bawaan**: halaman itu membuat peramban mengambil skrip, gaya, dan sebuah fon dari host
pihak ketiga, sehingga pengembang yang menginginkannya menjalankan aplikasi dengan `OO_API_DOCS=1`. Metrik Prometheus ada di `/metrics`. **Tidak ada autentikasi** secara sengaja
(hanya loopback, satu pengguna). Semua endpoint **dibatasi lajunya** (kira-kira: baca
100/jam, tulis/ekspor 50/jam, hapus 20/jam, impor massal 10/jam; `429` dengan
`Retry-After` bila terlampaui).

Inventaris ringkas (lihat `/openapi.json`, atau `/docs` dengan `OO_API_DOCS=1`, untuk skema yang otoritatif dan selalu mutakhir, serta
`docs/ARCHITECTURE.md` untuk uraian prosa):

**Inti & pencarian** — `GET /api/health`; `GET /api/articles` (FTS + filter);
`GET /api/articles/export` (csv|json); `GET /api/articles/{id}/view` (HTML luring);
`GET /api/sources`.

**Penelanan** — `POST /api/sources/seed-defaults`;
`POST /api/sources/{id}/ingest`; `POST /api/sources/{id}/ingest-email` (IMAP);
`POST /api/ingest` (URL tunggal).

**Sumber & katalog** — CRUD lengkap di bawah `/api/sources/…` (termasuk operasi massal, grup,
grup berbasis tag, metadata, penemuan, impor/ekspor YAML, statistik, pencarian); katalog
CSV di `/api/catalog/sources`, `/export.csv`, `/template.csv`, `POST /import`.

**Penjadwal** — `GET /api/scheduler/status|config|targets`;
`PUT /api/scheduler/config`; `POST /api/scheduler/start|stop|run-now`.

**Basis data & cadangan** — `GET /api/database/stats|coverage|countries`;
`GET /api/database/backup` (snapshot `.db` mentah; di bawah nama yang Anda cantumkan di `OO_ALLOWED_HOSTS`, permintaan yang tidak menyebutkan halaman asalnya harus menambahkan header `X-OO-Download: 1`, seperti yang dilakukan `curl -H "X-OO-Download: 1" …`; mengetik alamat itu di peramban, atau membuka markah, pada nama HTTP biasa semacam itu tidak mengirimkan apa pun yang akan ditambahkan peramban pada loopback atau HTTPS, sehingga permintaan itu ditolak di sana). Cadangan **dibuat** oleh mesin
streaming: volume terenkripsi+paritas di `POST /api/backup/v2/volumes/start` (+ `/restore`,
`/cancel`, `GET /volumes/status`) dan penyalinan folder data besar di
`POST /api/backup/folder/start` (+ `/plan`, `/restore`, `/{action}`, `GET /folder/status`).
Pemulihan arsip berkas tunggal yang lebih lama adalah **penggabungan aditif**:
`POST /api/backup/v2/restore/preview`, `POST /api/backup/v2/restore/commit`,
`GET /api/backup/v2/batches`. *(`POST /api/database/restore` dan
`/api/safety/restore/encrypted` yang bersifat destruktif telah dihapus.)*

**Sistem & jaringan** — `GET /api/system/vitals|network|interfaces`;
`POST /api/system/network` (sakelar mode pesawat); `GET /api/system/doctor|lock-state`;
`POST /api/system/unlock|create-db|encrypt-db`. **Tugas / task manager** —
`GET /api/jobs`; `POST /api/jobs/dumps/reorder`; `POST /api/jobs/{id}/cancel`.

**Peta dunia** — `GET /api/timemap` (sinyal ruang-waktu; `?kinds`, jendela tahun pecahan
`?start`/`?end`, `?hazards`, `?articles`, `?mentions`, `?days`); `GET /api/timemap/range`.

**Tag tanggal artikel** — `GET/POST /api/article-dates/article/{id}` (daftar / ekstrak);
`POST /api/article-dates/{tag_id}/confirm|reject`; `POST /api/article-dates/index`;
`GET /api/article-dates/by-date`.

**Wawasan** — `GET/PUT /api/insights/filter`; `POST /api/insights/exclude|include`;
`GET /api/insights/status`; `POST /api/insights/reindex`;
`GET /api/insights/top|trending|trend|associations|context|map`; rekapitulasi
**Kapan×Di mana×Siapa** untuk seluruh korpus di `GET /api/insights/who|where`.
**Pembingkaian** — `GET /api/framing`.

**Pencarian (omnibar)** — `GET /api/search/omni` (federasi berbasis indeks atas artikel,
kata kunci, sumber, Wikipedia yang diawasi, dan hukum yang dilacak).

**Tautan** — `GET /api/links/shared` (artikel anggota mana yang berbagi tautan keluar, dengan
catatan independensi); `GET /api/links/preview` (ekstraksi pratinjau tautan lokal).

**Peristiwa agenda** — `GET /api/events/calendars|feeds|imported`;
`GET /api/events/astronomy` (fase bulan yang dihitung secara lokal — bulan baru, kuartal pertama, purnama, kuartal terakhir — + ekuinoks/solstis, diverifikasi terhadap
almanak) dan `GET /api/events/climate` (dataset El Niño yang dibundel). **Konteks cuaca** —
`POST /api/weather/context` (potongan reanalisis Open-Meteo yang digerakkan korpus, dengan persetujuan).

**Pasar & komoditas** — `/api/markets/rules` (CRUD + `/run`),
`/api/markets/overview|series|feeds`, `/api/markets/feeds/{key}/import`,
`/import-all`, `/import-url`; `/api/commodities/{symbol}/prices` (+ `/import-csv`,
`/correlation`).

**Pemerintahan** — indikator Bank Dunia per negara + peta koroplet, hanya-baca
kecuali satu pengambilan dengan persetujuan: `GET /api/governments/indicators|map|country/{iso}`;
`POST /api/governments/load-standard` (+ `/load-standard/status`, tugas latar belakang).
**Hukum dunia** — undang-undang/lembaran negara/catatan kekayaan intelektual yang dilacak, cermin riset (bukan nasihat
hukum): `GET /api/law/status|documents|documents/{id}|documents/{id}/view|changes`;
`POST /api/law/documents` (menambahkan dokumen melalui URL — langsung diambil);
`DELETE /api/law/documents/{id}` (berhenti melacak; riwayat tetap disimpan); `POST /api/law/track`
(mengambil setiap dokumen yang diawasi sekarang) dan `/api/law/seed` (mengisi ulang katalog seluruh dunia).
Dokumen yang dilacak menjadi artikel korpus kelas utama yang dapat dicari (Kapan×Di mana×Siapa,
kata kunci) berdampingan dengan berita hasil scraping, dengan riwayat amandemennya sebagai lapisan yang tertaut.

**Wikipedia** — `GET /api/wiki/status|pages|changes`; `POST /api/wiki/pages`,
`/track-now`, `/pages/{id}/track`; `GET /api/wiki/revisions/{id}`;
`GET /api/wiki/languages` (daftar **datar, dengan bahasa UI didahulukan**, setiap opsi diawali
nama aslinya; `region` disimpan hanya sebagai metadata deskriptif — tanpa `groups` benua;
`?scope=dumps` menambahkan perkiraan ukuran `~GB` sebaris); dump di bawah `/api/wiki/dumps…`.

**Rantai pengawasan** — `POST /api/custody/log`; `GET /api/custody/{item}` (+
`/verify`); `POST /api/custody/verify`; `GET /api/custody/export`;
`GET /api/custody/providers`; `POST /api/custody/anchor`;
`GET/PUT /api/custody/settings`; `POST /api/custody/reconcile` (entri INGEST yang
tidak dapat ditulis ketika artikelnya disimpan akan diantrekan dan ditulis belakangan, di akhir
putaran pengumpulan berikutnya selama pencatatan otomatis aktif, ditandai terlambat dalam metadata bertanda tangannya sendiri --
tab Rantai pengawasan menghitungnya, dan tombol
"Periksa entri pengambilan yang hilang" di tab itu menghitung celah yang lebih lama tanpa mencatat apa pun
sampai Anda menekan "Catat, ditandai terlambat"). **Bukti** — `POST /api/reports/evidence`
(+ `/verify`).

**LLM (Ollama lokal)** — `GET /api/llm/health|models`; `POST /api/llm/generate`;
`POST /api/llm/articles/{id}/summarize|translate`.

**Lainnya** — `/api/analysis/*` (uji-t, korelasi, ANOVA, …);
`/api/keywords/*` (utilitas ekstraksi); `/api/monitoring/health|anomalies`;
`POST /api/verify/image-metadata` (EXIF/GPS).

### 5.5 Menjalankan melalui Tor

Aplikasi ini berfungsi melalui Tor (mode pengambilan Terlindungi → proksi Tor yang Anda jalankan sendiri), dengan
jangkauan yang, terus terang saja, lebih kecil — diukur, bukan ditebak (log langsung 2026-06-12: 32 dari 50
sumber bawaan berhasil diimpor melalui Tor dalam satu putaran):

- **Penolakan per koneksi itu normal, bukan fatal.** Sebagian host menolak sebagian
  simpul keluar (exit) Tor: dalam putaran yang sama, 21/28 deret FRED berhasil diimpor sementara yang lain gagal.
  Itulah sebabnya kegagalan umpan disertai **putusan yang sadar-transport** — *ditolak*
  ("koneksi ditolak/direset — melalui Tor ini sering kali penolakan oleh satu simpul keluar;
  percobaan ulang sering kali mendapat sirkuit lain") bukanlah *dilarang robots*
  (kebijakan yang dinyatakan host, yang kami hormati dan tidak pernah kami coba ulang atau
  akali), bukan *deret mati* (HTTP 404 — entri katalog perlu
  pengganti; mencoba ulang tidak akan membantu), dan bukan *tidak terjangkau*. Kegagalan sementara
  dicoba ulang sekali secara otomatis; tombol **Coba lagi umpan yang gagal**
  menjalankan ulang tepat umpan-umpan yang memang layak dicoba ulang.
- **Pemblokiran Tor oleh suatu host adalah pilihan host tersebut.** Kami menampilkannya; kami tidak pernah mengakali
  robots, pemblokiran, atau CAPTCHA. Utamakan endpoint resmi yang toleran terhadap Tor bila
  tersedia.
- **Unduhan model tidak berfungsi melalui Tor.** Ollama menarik modelnya melalui internet
  terbuka lewat prosesnya sendiri (pasang/tarik dari **Pengaturan → AI**); jalur clearnet
  yang berfungsi adalah prasyarat yang dinyatakan untuk mengunduh model. Setelah ditarik, inferensi
  berjalan di loopback dan tidak terpengaruh. *(Paket LLM luring sudah direncanakan, belum dirilis.)*
- **Jika pemasangan vLLM terhenti di tengah jalan**, hampir selalu penyebabnya adalah unduhan yang kehabisan waktu
  pada salah satu wheel yang sangat besar — torch saja sekitar 500 MB. Pesannya menyebutkan
  wheel tersebut, dan wheel yang sudah diunduh disimpan di cache, sehingga memulai pemasangan lagi akan melanjutkan
  alih-alih mengulang dari awal. Pada sambungan yang cukup lambat hingga terus gagal, naikkan
  `UV_HTTP_TIMEOUT` (dalam detik) sebelum menjalankan aplikasi.
- **Jika server vLLM berulang kali menyala lalu mati**, alasannya tercatat entah
  Anda sedang mengamatinya atau tidak: setiap kali mulai dan setiap kali berhenti masuk ke
  `vllm_start_attempts.jsonl` beserta kata-kata kegagalan itu sendiri, dan log lengkap dari
  masing-masing beberapa percobaan mulai terakhir yang gagal disimpan di `vllm_failed_starts/` — keduanya di
  direktori data, sehingga memasang ulang vLLM tidak menghapusnya. Keduanya ikut dalam ekspor
  **Diagnostik → semua diagnostik (all diagnostics)**, sehingga jawabannya ada di dalam bundel, bukan
  sesuatu yang harus ditangkap secara langsung.
- **Anonimitas tetap menjadi tanggung jawab Anda**: mode Terlindungi tidak dapat menjamin
  anonimitas — Anda yang menjalankan dan memercayai proksinya; bagian aplikasi adalah merutekan
  pengambilan web-nya melaluinya dengan User-Agent generik, kecuali dalam permintaan API dan dump
  ke server Wikimedia, yang tetap menyebutkan nama alat ini (kebijakan API Wikimedia
  memintanya). Penarikan kotak surat buletin, penjangkaran OpenTimestamps, dan
  unduhan AI lokal tersambung secara langsung.

---

### 5.5a Memori pada mesin kecil — satu-satunya batas nyata

Aplikasi sudah mengecilkan dirinya sendiri pada mesin kecil: di bawah **4 GB RAM**, atau dengan
memori bebas kurang dari **1 GB**, ia memakai cache basis data yang lebih kecil dan lebih sedikit koneksi
dalam pool, membatasi berapa banyak sumber yang diambilnya sekaligus, dan **menjeda pemindaian
latar belakang atas seluruh korpus** (kualifikasi sumber). Aplikasi memberi tahu Anda hal ini, beserta
angkanya, di samping status pengumpulan di Pengaturan → Lanjutan → Pengumpulan.

**Katakan biayanya dengan terus terang:** pada mesin dengan korpus besar dan memori bebas
yang sedikit, ini bisa berarti kualifikasi sumber tidak pernah berjalan di sana. Itulah biaya
pengaturan ini, bukan kegagalan. Untuk tetap menjalankannya, mulai aplikasi dengan
`OO_ALLOW_BIG_SCANS=1` — putusannya lalu melaporkan bahwa Anda telah mengesampingkannya, dan ia
tetap melaporkan bahwa mesinnya kecil, karena pengesampingan mengubah apa yang *dilakukan*
aplikasi, tidak pernah mengubah apa yang *diukurnya*.

#### Tampilan berat berhenti sebelum sempat menjatuhkan aplikasi

Pembacaan analitik yang berat (sebagian besar tampilan Wawasan, Observatorium, sumber yang paling
banyak dikutip, bundel diagnostik) sudah berjalan dengan batas waktu. Pembacaan itu juga
mengawasi memori yang tersedia selama basis data menyerahkan baris-baris kepadanya. Jika memori turun sampai
batas minimum pelindung memori (**256 MB** secara bawaan, `OO_MEM_GUARD_AVAIL_MB`), pembacaan
dihentikan dan tampilannya menyebutkan alasannya, beserta angkanya: *"pembacaan ini dihentikan setelah
12 s: mesin hampir kehabisan memori (180 MB tersedia, pada atau di bawah batas minimum
256 MB yang dipakai pelindung memori) ..."*. Pembacaan yang diminta ketika memori
sudah serendah itu tidak dimulai, dan sebagai gantinya menyatakan *"pembacaan ini tidak dimulai"*.
Buka lagi tampilannya setelah memori pulih; tidak ada yang hilang,
karena pembacaan tidak mengubah apa pun.

**Yang tidak dilakukannya:** ini penghentian, bukan pembatasan. Ia melihat apa yang tumbuh selama baris-baris
sedang dibaca, yaitu tempat tumbuhnya tampilan yang memuat seluruh tabel, dan
tidak ada yang lain. `OO_READ_MEMORY_STOP=0` mematikannya tanpa menyentuh pelindung.

#### Ketika memori tetap habis, aplikasi menghentikan dirinya sendiri dan menyatakannya

Pelindung memori menjeda pengumpulan baru ketika memori menipis. Jeda tidak
mengembalikan apa yang sudah dipegang aplikasi, sehingga pada mesin kecil memori bisa tetap berada di
batas minimum selama bermenit-menit lalu sistem operasi mematikan aplikasi tanpa
penjelasan sedikit pun. Kini aplikasi mengakhiri dirinya sendiri sebagai gantinya. Ia hanya melakukannya ketika **semua**
hal berikut terpenuhi: pelindung telah aktif selama keseluruhan **5 menit** terakhir
(`OO_MEM_STOP_WINDOW_S`), paling sedikit sembilan dari sepuluh pembacaannya berada pada atau di bawah
**64 MB** tersedia (`OO_MEM_STOP_AVAIL_MB`), tidak ada yang di atas 128 MB, tidak ada jeda antar
pembacaan yang lebih lama dari sepersepuluh jendela (30 s), dan aplikasi ini memegang paling sedikit sepertiga
memori mesin (jika ada hal lain yang memegangnya, berhenti tidak akan membebaskan apa pun,
dan aplikasi tidak berhenti). Pemulihan, sesingkat apa pun, atau menekan mulai atau
lanjutkan akan mengosongkan jendela itu.

Sebelum berhenti, aplikasi menyimpan apa yang diketahuinya: snapshot tentang apa yang sedang
dilakukan setiap thread, satu baris di buku besar sesi, dan `memory_stop.json` di samping data Anda
(angka dan nama langkah, paling banyak 8 KB). Lalu ia berakhir melalui jalur yang sama dengan
tombol daya. Data Anda yang sudah tersimpan tidak disentuh; ia terlebih dahulu menunggu hingga satu menit
agar proses impor, tugas latar belakang yang memegang korpus, atau penulisan basis data yang sedang
berlangsung selesai (pemulihan atau pemindahan drive data dicatat sebagai sedang berlangsung tetapi
tidak ditunggu secara khusus), menyatakan dalam catatan jika masih ada yang berjalan, dan apa pun yang tidak
dapat selesai dalam waktu itu tidak diselesaikan.
Selama proses ini berjalan, task
manager menampilkan *"Aplikasi menghentikan dirinya sendiri karena memori tetap habis"*.
Pada saat mulai berikutnya, baris **Sesi** di tab Sistem berbunyi *"Berhenti sendiri —
memori tetap habis"* (arahkan kursor untuk melihat catatannya), pesan satu kali menyatakan hal
yang sama, dan zip Diagnostik membawa catatannya. **Yang berakhir adalah apa yang sedang
berjalan; Anda yang memulainya lagi.** `OO_MEM_STOP=0` mematikan penghentian ini dan mempertahankan
jedanya.

#### Mengapa aplikasi tidak bisa begitu saja membatasi memorinya sendiri

Tidak ada cara yang jujur bagi sebuah program untuk memberlakukan batas memori pada dirinya sendiri:

- **`RLIMIT_RSS` diabaikan oleh Linux.** Ia ada di API dan tidak melakukan apa pun.
- **`RLIMIT_AS` membatasi *ruang alamat*, bukan memori yang sedang dipakai.** Pustaka yang dipakai
  aplikasi ini (DuckDB, numpy) mencadangkan ruang alamat virtual jauh lebih banyak daripada yang pernah
  mereka sentuh, sehingga batas ruang alamat memunculkan `MemoryError` di kode yang tidak berkaitan jauh
  sebelum prosesnya benar-benar besar. Aplikasi sengaja tidak mengatur keduanya, dan sebuah
  pengujian menggagalkan build jika salah satunya pernah ditambahkan.

#### Batas yang benar-benar berfungsi: jalankan dalam cgroup

Di Linux dengan systemd, mulai aplikasi dengan batas memori keras:

```bash
systemd-run --user --scope -p MemoryMax=3G -p MemorySwapMax=0 \
  ~/open-omniscience/scripts/launch.sh
```

**Apa yang didapat, secara jujur:** ini mengubah *desktop yang membeku* menjadi *aplikasi yang
dimulai ulang dengan bersih*. Tanpa batas, mesin yang kehabisan memori akan melakukan swap hingga tidak
dapat dipakai untuk apa pun — peramban, terminal, desktop — dan Anda mungkin
harus mematikan lalu menyalakannya kembali. Dengan batas, kernel mematikan **aplikasi ini** sebagai gantinya, dan
hanya aplikasi ini.

**Biayanya:** aplikasi dimatikan, di tengah pekerjaan, tanpa kesempatan untuk berbenah.

**Mengapa korpus Anda tetap aman:** basis data berjalan dalam mode WAL dengan
`synchronous=NORMAL`, sehingga pematian hanya dapat menghilangkan pekerjaan yang belum pernah di-commit.
Semua yang sudah di-commit ada di disk, dan log tulis-di-muka diputar ulang saat berikutnya
Anda membuka kunci. **Tidak ada yang sudah Anda kumpulkan yang hilang.**

**Cadangan** yang terputus dengan cara ini lain ceritanya: cadangan itu dibiarkan tidak lengkap.
Namun, ia tidak dipercaya begitu saja secara diam-diam — setiap volume membawa checksum di
manifes, dan langkah verifikasi milik cadangan itu sendiri memeriksa semuanya serta menyebutkan mana
yang hilang atau tidak cocok. Jalankan verifikasi (atau cukup ambil cadangan lagi)
sebelum mengandalkan cadangan yang pernah terputus.

Pilih `MemoryMax` sekitar **60–75 % dari total RAM**, sisakan ruang untuk
desktop dan peramban. `MemorySwapMax=0` adalah separuh yang menghentikan thrashing:
tanpanya aplikasi masih bisa membuat mesin melakukan swap hingga merayap sebelum batasnya
tercapai.

Jika Anda tidak memakai systemd, hal yang sama tersedia melalui Docker/Podman
(`--memory=3g --memory-swap=3g`) atau `memory.max` cgroup v2 biasa.

#### Setelah crash: apa yang dapat diberitahukan saat mulai berikutnya

Ketika aplikasi dimatikan atau mengalami crash, jendela peluncur kini tetap terbuka dan menyatakan
bagaimana aplikasi berakhir: `SIGKILL` adalah tanda yang biasa dari pembunuh proses saat memori rendah. Penghentian
biasa (tombol Hentikan milik aplikasi sendiri, menutup jendela, keluar dari sesi login) menutup
jendela seperti sebelumnya.

Saat mulai berikutnya, aplikasi lalu menyatakan bagaimana sesi sebelumnya berakhir, di **Pengaturan →
Lanjutan → Diagnostik → forensik sesi** dan di `session-forensics.json`
di dalam arsip Diagnostik, dari saksi mana pun di antara berikut yang memberikan jawaban:

- catatan peluncur tentang status keluar (`diagnostics/launcher_exits.jsonl`);
- log kernel, yang menyebutkan pematian karena kehabisan memori oleh kernel sendiri;
- baris log dari pembunuh proses memori di ruang pengguna (systemd-oomd, earlyoom,
  nohang) dan dari systemd-coredump yang menyebut aplikasi. Baris-baris ini tidak pernah muncul di
  log kernel, dan systemd-oomd menyebut cgroup aplikasi, bukan prosesnya;
- jejak crash dari setiap thread ketika kode native gagal mendadak (abort)
  (`diagnostics/crash_trace.log`).

Pembacaan log itu bersifat lokal dan hanya-baca, dan hanya menyimpan baris tentang aplikasi ini.
`OO_NO_KERNEL_LOG=1` mematikannya; `OO_CRASH_TRACE=0` mematikan jejak crash.
Pembunuh proses memori menulis ke jurnal sistem, yang hanya dapat dibaca oleh anggota `adm` atau
`systemd-journal` (`wheel` di Fedora); bila akun Anda tidak bisa membacanya, laporan
menyatakannya alih-alih menyebut log itu kosong. Tanpa saksi sama sekali, laporan
menyatakan bahwa cara berakhirnya tidak diketahui, tidak pernah bahwa sesi berakhir dengan bersih.

Laporan yang sama menyatakan apa saja isi memori pada puncak sesi. Ketika
puncak itu terjadi saat memori sudah terlalu sedikit untuk membaca heap C dengan aman, yang
biasanya terjadi tepat sebelum crash karena kehabisan memori, laporan juga menampilkan puncak
sebelumnya yang terbaru yang berhasil membacanya, dengan ukuran dan waktu puncak itu sendiri. Laporan juga menyatakan
apa yang sedang dilakukan setiap thread (namanya, kode aplikasi yang dijalankannya, dan CPU
yang dipakainya) pada dua jenis momen: ketika memori yang tersedia turun di bawah 15% RAM
(paling banyak 1 GB), pertama pada saat melewati batas itu dan lagi pada setiap titik terendah baru, dan ketika
aplikasi membuat satu juta objek Python atau lebih dalam lima detik, paling sering sekali
setiap lima menit. Delapan snapshot terbaru disimpan di
`session_pressure.json` di folder data, dan semuanya tetap di komputer ini seperti
diagnostik lainnya.

## 5.6 Batas yang diketahui & pengungkapan jujur

Kejujuran sejak rancangan berarti menyatakan apa yang *tidak dapat* diberitahukan alat ini, bukan hanya
apa yang dapat. Inilah batas tetap dari metode-metodenya (audit-07 "penyisiran
pengungkapan"). Tidak satu pun merupakan bug; masing-masing menentukan cara membaca suatu hasil.

- **Hitungan kata kunci/tren bersifat leksikal, bukan semantik.** Hitungan itu mengukur seberapa sering
  kata-kata muncul, bukan apa yang dimaksud. Negasi ("bukan krisis"), kutipan,
  sarkasme, dan ironi dihitung apa adanya. Volume adalah liputan, tidak pernah
  kepentingan atau kebenaran.
- **Sentimen/nada memakai VADER, metode berbasis leksikon bahasa Inggris.** Skor untuk artikel
  non-Inggris tidak andal; tampilan Sentimen dan Pembingkaian (Framing) mengungkapkan hal ini dan
  menunjukkan porsi yang diberi skor dalam bahasa Inggris. Nada adalah sinyal yang dapat diukur, tidak pernah vonis
  bahwa suatu media bias.
- **Ringkasan/terjemahan LLM adalah artefak model.** Model lokal bisa
  fasih sekaligus keliru. Setiap sel yang dihasilkan diberi label "verifikasi terhadap artikel
  yang tersimpan"; perlakukan keluarannya sebagai petunjuk awal, dan periksa terhadap teks asli
  yang Anda kumpulkan.
- **Artikel panjang dipecah, bukan dipotong.** Jendela konteks model itu terbatas. Ketika
  Anda meminta ringkasan atau terjemahan artikel yang tidak muat, aplikasi
  memecahnya di batas paragraf dan memproses setiap bagian — terjemahan adalah
  bagian-bagian yang digabungkan, dan ringkasan adalah bagian-bagian yang diringkas lalu diringkas
  bersama. Bagaimanapun juga, hasilnya menyatakan hal itu ("diterjemahkan dalam N bagian", "ringkasan
  hierarkis atas N bagian"), karena ringkasan dua langkah adalah artefak yang berbeda dari
  ringkasan sekali jalan dan Anda perlu tahu mana yang sedang Anda baca. Aplikasi tidak pernah diam-diam
  berhenti di tengah jalan: terjemahan yang terpotong tampak persis seperti terjemahan yang lengkap.
  Penyisiran latar belakang (ekstraksi siapa/di mana/kapan) MEMANG memotong artikel panjang, dan
  mencatat bahwa hal itu dilakukan — "menganalisis N karakter pertama dari M" — sehingga
  ekstraksi yang tipis tidak pernah disangka artikel yang tipis.
- **AI latar belakang adalah satu jalur, dan pekerjaan Anda didahulukan.** Penyisiran yang Anda aktifkan
  berjalan satu per satu pada satu backend lokal, bukan saling berebut.
  Apa pun yang Anda minta sendiri — terjemahan massal, penyisiran manual — menjeda
  jalur itu selama berlangsung dan jalur itu berlanjut sendiri setelahnya; tidak ada yang kehilangan
  urutannya. Pada mesin yang tidak praktis untuk inferensi lokal, jalur ini nonaktif secara
  bawaan, dengan alasan yang dinyatakan, dan Anda tetap dapat mengaktifkannya.
- **Aplikasi ini hanya menangani teks.** Ia menganalisis teks artikel. Gambar hanya membawa kejujuran
  EXIF/metadata (tanpa klaim forensik/deepfake); tidak ada analisis audio atau
  video. Klaim yang hanya ada di dalam video atau gambar berada di luar apa yang dapat
  dilihat alat ini.
- **Bahasa Jepang dan Thai memerlukan ekstra opsional `[segmentation]`.** Ekstraksi kata kunci
  bergantung pada tokenisasi berdasarkan spasi kecuali pemenggal kata (word segmenter) terpasang. Bahasa Tionghoa
  dipenggal pada setiap instalasi (jieba, dependensi inti sejak 0.4); analisis kata kunci bahasa Jepang dan Thai
  praktis tidak berfungsi tanpa ekstra itu (janome, pythainlp), meskipun
  antarmukanya tersedia dalam bahasa-bahasa tersebut, dan pencarian bahasa Jepang dipecah menjadi kata
  hanya dengan sudachipy dari ekstra itu. Kumpulan **terkelola** (managed)
  (dipisahkan spasi, dengan daftar kata henti) didefinisikan di
  [`src/analytics/managed.py`](../src/analytics/managed.py); *kedalaman analitis* per
  bahasa berbeda-beda, dan aksara yang tidak dipenggal merupakan celah terbesar saat ini.
- **Bias kelangsungan host yang permisif.** Karena robots.txt bersifat gagal-tertutup (fail-closed),
  korpus terlalu banyak mewakili situs yang *mengizinkan* perayapan dan secara struktural
  kurang mewakili jurnalisme berbayar (paywall) atau yang membatasi perayapan. Hal ini tidak dapat
  "diperbaiki" secara etis — ia dikurangi dengan mengutamakan API/arsip resmi dan
  diungkapkan di sini agar Anda membaca liputan dengan mempertimbangkannya.
- **Catatan Anda dimulai saat Anda mulai mengumpulkan.** Tren dan sinyal "naik"
  dibatasi oleh jendela pengumpulan Anda; alat ini tidak memiliki riwayat dari sebelum Anda
  mulai. Dump Wikipedia dan arsip (di masa depan) memperpanjang masa lalu; selain itu, bacalah
  hasil korpus awal dengan peringatan n yang ditampilkan.
- **Wikipedia membawa bias sistemiknya sendiri.** Wikipedia yang dipantau/ditelan
  ikut membawa kecenderungan editorial dan cakupan yang sudah terdokumentasi baik dari setiap edisi.
  Sumber per edisi (`xx.wikipedia.org`) membuatnya tetap dapat disaring, dan ia dapat
  ditriangulasi seperti sumber lain — tidak pernah sebagai orakel.
- **Bias pemilihan katalog diukur, bukan disembunyikan.** Katalog sumber adalah
  kumpulan yang dikurasi manusia, yang sedang dalam proses dikurangi sentrisme AS-nya; tampilan **Cakupan dunia**
  menunjukkan negara mana yang terwakili dan yang tidak sehingga Anda dapat melihat bentuk
  apa yang Anda kumpulkan (dan tidak Anda kumpulkan).

---

## 6. Pemecahan masalah

- **Halaman tidak mau dimuat.** Pastikan prosesnya berjalan dan terikat ke
  `127.0.0.1:8000` (atau `OO_HOST`/`OO_PORT` Anda). Pil kesehatan di header berubah menjadi
  `offline` jika API tidak dapat dijangkau.
- **Pencarian kosong.** Anda belum mengumpulkan apa pun — **sambungkan ke internet** dengan tombol
  pesawat (satu popup persetujuan) dan pengumpulan dimulai otomatis; jalur manualnya adalah
  **Pengaturan → Lanjutan → Pengumpulan → Ambil umpan**.
- **Penelanan tidak menyimpan apa pun.** Itu sering kali benar dan etis: halaman itu mungkin
  diblokir oleh `robots.txt` (gagal-tertutup), dibatasi lajunya, merupakan duplikat, atau tidak memiliki
  isi yang dapat diekstrak. Rekap hasilnya memberi tahu Anda yang mana.
- **Kontrol Wawasan/Pasar hilang atau galat.** Ekstra `[analysis]`
  belum terpasang — jalankan ulang `install.sh` (ekstra analisis terpasang secara bawaan).
- **Pil LLM menunjukkan offline.** Ollama tidak berjalan/tidak dapat dijangkau; jalankan atau atur
  `OLLAMA_BASE_URL`. Ringkas/terjemahkan mengembalikan `503` yang jelas saat tidak tersedia.
- **Kustodi menampilkan "requested, library not installed".** Pasang ekstra `pqc` dan/atau
  `timestamping`; status efektifnya akan berubah setelah pustakanya ada.
- **Pemulihan menolak berkas saya / pratinjau tidak mau Terapkan (Apply).** Memang dirancang begitu — berkas itu harus
  cadangan Open Omniscience yang asli, dan **Terapkan (Apply)** tetap nonaktif jika verifikasi
  bertahap gagal. Korpus Anda saat ini tidak tersentuh dalam kedua kasus; pemulihan hanya pernah
  *menambah*, tidak pernah menggantikan.
- **Dump Wikipedia sangat besar.** `enwiki` berukuran puluhan GB. Gunakan **Perkirakan ukuran (Estimate size)** terlebih dahulu;
  sebagian besar edisi jauh lebih kecil, dan Anda tidak memerlukan dump untuk pelacakan perubahan.

---

## 7. Glosarium

- **Korpus** — basis data SQLite lokal Anda yang berisi artikel-artikel yang dikumpulkan.
- **Provenans** — asal-usul tersimpan dari setiap item (sumber, URL, URL kanonis,
  hash konten, waktu pengambilan) yang digunakan untuk deduplikasi dan kepercayaan.
- **FTS5** — pencarian teks lengkap SQLite, yang menjalankan kueri Boolean.
- **Pengambilan etis** — satu-satunya jalur pengambilan, yang menghormati robots dan dibatasi lajunya.
- **Rantai kustodi** — log yang hanya dapat ditambah, berantai hash, dan bertanda tangan yang membuktikan
  integritas, provenans, dan waktu suatu item.
- **Bundel bukti** — ekspor artikel terpilih yang bertanda tangan, berakar Merkle, dan dapat diverifikasi
  secara luring.
- **OpenTimestamps** — cara menjangkarkan hash ke Bitcoin sebagai bukti independen bahwa sesuatu
  "ada tidak lebih lambat dari" suatu blok.
- **ML-DSA** — skema tanda tangan pasca-kuantum FIPS-204 (dipakai dalam mode *hibrida*
  bersama Ed25519).
- **ORES** — layanan ML Wikimedia yang memberi skor suntingan untuk kerusakan / itikad baik.
- **PMI** — pointwise mutual information (informasi mutual titik); mengurutkan seberapa kuat dua istilah muncul bersama
  melampaui kebetulan ("peta pikiran" Wawasan).
- **VADER** — pemberi skor nada/sentimen berbasis leksikon (tampilan "pembingkaian" Wawasan).

---

*Lihat juga:* [QUICKSTART](QUICKSTART.md) · [CHAIN_OF_CUSTODY](USER_MANUAL.md) ·
[INSIGHTS](USER_MANUAL.md) · [MARKETS](USER_MANUAL.md) · [WIKIPEDIA](USER_MANUAL.md) ·
[DATABASE](ARCHITECTURE.md) · [API_DOCUMENTATION](ARCHITECTURE.md) ·
[SECURITY](SECURITY.md) · [PRODUCT_SYNTHESIS](DESIGN.md) ·
[OPEN_QUESTIONS](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

*© 2026 Ideotion — dibangun untuk jurnalisme investigatif, dengan jujur. GPLv3.*

---

# Pendalaman fitur

Kedalaman referensi untuk setiap alat, dihimpun dari panduan per fitur yang sebelumnya terpisah. Tur di Bagian 1–6 di atas tetap menjadi orientasi tercepat; bagian ini adalah rinciannya.

**Di bagian ini:**
- [Briefing Beranda — intelijen sebagai "kartu" yang jujur](#briefing-beranda--intelijen-sebagai-kartu-yang-jujur)
- [Integritas sumber & anti-amplifikasi](#integritas-sumber--anti-amplifikasi)
- [Anotasi sumber bersama — bertanda tangan, portabel, terfederasi berdasarkan kepercayaan](#anotasi-sumber-bersama--bertanda-tangan-portabel-terfederasi-berdasarkan-kepercayaan)
- [Wawasan — analitik kata kunci & entitas](#wawasan--analitik-kata-kunci--entitas)
- [Pelacakan perubahan Wikipedia](#pelacakan-perubahan-wikipedia)
- [Hukum dunia — pelacakan perubahan untuk undang-undang, lembaran negara & HKI](#hukum-dunia--pelacakan-perubahan-untuk-undang-undang-lembaran-negara--hki)
- [Pasar: intelijen keuangan, bursa saham, dan komoditas/logam tanah jarang](#pasar-intelijen-keuangan-bursa-saham-dan-komoditaslogam-tanah-jarang)
- [Rantai kustodi](#rantai-pengawasan)


---

## Briefing Beranda — intelijen sebagai "kartu" yang jujur

> **Status:** `0.06` Fase A (tulang punggung GUI) — sudah dirilis dan diuji. Rencana bertahapnya
> ada di [`ROADMAP.md` → "0.06 — The Intelligence Layer"](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md);
> *apa & mengapa*-nya di [`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md).

Tab **Beranda** bukan lagi sekadar statistik sekilas. Tab ini adalah **umpan triase**:
aplikasi mengumpulkan dan mengukur di latar belakang, lalu memunculkan *calon berita* sebagai
**kartu — yang di layar ditampilkan sebagai "Petunjuk"** (bab ini menyebut "kartu" untuk mekanisme
internalnya; label di UI adalah "Petunjuk"). Aplikasi melakukan pengumpulan; **Anda yang menilai**. Setiap kartu
adalah **satu sinyal terukur + tautan bukti + satu peringatan**, dipilah ke dalam satu
kelompok editorial, dan disajikan sebagai **kartu bolak-balik dua sisi** (depan = petunjuknya; belakang = peringatan +
metode + bukti + "Buka korpus").

Sebuah kartu **memunculkan sinyal; ia tidak pernah menjatuhkan vonis.** Tidak ada "bias", tidak ada
"propaganda", tidak ada "benar/palsu", dan — sesuai rancangan dan *ditegakkan dalam kode* — **tidak ada skor
kepercayaan gabungan** (lihat "Pengaman kejujuran" di bawah).

---

### Apa yang Anda lihat

Briefing mengelompokkan kartu ke dalam **kelompok** (urutan tampilan):

| Kelompok | Artinya | Kegunaan editorial |
|---|---|---|
| **Sedang naik** | sesuatu sedang bergerak / baru | calon petunjuk |
| **Terlalu diberitakan** | sumber-sumber sepakat terlalu cepat / terlalu seragam | patahkan paduan suaranya |
| **Kurang diberitakan** | sesuatu bergerak tetapi sedikit/tidak ada yang meliputnya | munculkan celahnya |
| **Layak diselidiki** | sumber atau data saling bertentangan | gali lebih dalam |
| **Periksa pembingkaian** | peristiwa yang sama dibingkai dengan cara yang berlawanan | verifikasi klaimnya |
| **Terus pantau** | perubahan yang layak diawasi (mis. entri yang dirombak) | pantau |
| **Konteks** | latar belakang / audit diri / fakta tetap | beri konteks |
| **Integritas data** | sinyal kebersihan tentang korpus itu sendiri | perbaiki alurnya |

Tiga serangkai di baliknya adalah mesinnya: **konvergensi → terlalu diberitakan**, **divergensi →
selidiki/patahkan**, **ketiadaan → kurang diberitakan**.

Setiap Petunjuk (nama di layar untuk kartu briefing) menampilkan **judul**, satu baris
**ringkasan**, dan **sinyal terukur** (mis. `growth_ratio = 4.2`, `n=6`) di
**sisi depannya**. **Klik (atau tekan Enter) untuk membaliknya:** **sisi belakang** memuat
**peringatan**, **metode** (persis bagaimana angka itu dihitung dan apa yang *tidak*
dimaksudkannya), mengapa kartu itu muncul, **tautan bukti** kembali ke korpus Anda, dan tombol **"Buka korpus
↗"**. Peringatan ada di DOM secara bawaan, di sisi belakang yang setara tepat di samping
tindakan — tidak pernah di balik sakelar tampilan tenang. Itulah intinya: **transparansi adalah
antarmukanya.**

> **Tampilan setara (Equal view).** Dalam versi ini setiap sumber dihitung satu kali dan **tidak ada sumber yang
> diredam amplifikasinya**. Lapisan integritas sumber / anti-amplifikasi (meringkas
> banjir terkoordinasi menjadi satu aktor, pembobotan kebaruan) adalah fase berikutnya dan
> **dipandu pengguna** — aplikasi akan *mengusulkan*, Anda yang akan *memutuskan*. Sampai saat itu,
> briefing ini, dengan jujur, adalah tampilan mentah dengan perlakuan setara.

---

### Siklus kartu → draf → nawala

Siklus manfaatnya terlihat sejak hari pertama:

1. Pada kartu mana pun, klik **+ Tambah ke draf**.
2. Buka panel **Draf nawala**; tambahkan catatan Anda sendiri pada setiap kartu yang disematkan.
3. **Ekspor Markdown** (atau **Salin**). Setiap klaim dikirim **bersama tautan sumber,
   metode, dan peringatannya** — jurnalisme yang dapat direproduksi sejak rancangan.

Untuk salinan artikel yang mendasarinya yang *bertanda tangan dan menunjukkan bila dirusak*, ekspor **bundel
bukti** dari **Bukti & kustodi** — tanda buktinya dapat dikirim bersama edisi Anda.

---

### Bagaimana kartu dihasilkan (Briefing v0)

Setiap kartu dibuat oleh sebuah **produsen**: fungsi `corpus → [Card]`. Produsen menyusun
analitik yang *sudah mengembalikan angka nyata* — tidak ada yang dikarang. Produsen yang
tidak memiliki masukannya atau dependensi opsional `[analysis]` **tidak mengembalikan apa pun dan mencatat
alasannya** (degradasi yang lantang); ia tidak pernah mengarang kartu.

| Kartu | Kelompok | Ditenagai oleh | Status |
|---|---|---|---|
| **“X” sedang naik** | sedang naik | `insights.trending` (rasio periode terkini vs sebelumnya) | sekarang |
| **Pembingkaian berbeda** | periksa pembingkaian | nada VADER per sumber dari istilah yang sedang tren | sekarang¹ |
| **Entri dirombak** | terus pantau | deteksi suntingan besar/bertanda di Wikipedia | sekarang |
| **Harga ↔ narasi (Price ↔ narrative)** | konteks | korelasi scipy yang jujur (koef + p + n) | sekarang¹ |
| **Data kedaluwarsa** | integritas data | `last_run_at` / `last_status` aturan ekstraksi pasar | sekarang |
| **Audit diri pola konsumsi (Diet self-audit)** | konteks | `signals.concentration` (Gini + porsi 3 teratas atas sumber Anda) | sekarang |
| **Ruang gema** | terlalu diberitakan | grafik aktor `signals.coordination` (hampir-duplikat + waktu + host) | baru |
| **Sinyal tunggal** | kurang diberitakan | klaster hampir-duplikat satu sumber yang tidak bergema | baru |
| **Kapasitas tidak masuk akal (Capacity implausible)** | selidiki | artikel/hari vs median korpus | baru |
| **Profil emosi** | konteks | leksikon emosi atas jendela konteks suatu kata kunci | baru² |
| **Denyut HKI / hukum (IP / legal pulse)** | konteks | istilah HKI/hukum yang sedang naik di korpus berita | tipis |
| **Perubahan kepemilikan** | selidiki | bahasa kata kerja transaksi (diakuisisi/merger/divestasi) dalam berita terkini | tipis |
| **Silsilah berita** | konteks | `signals.lineage` — klaster hampir-duplikat yang diurutkan menurut waktu terbit + atribusi kantor berita | baru |
| **Penasihat cakupan** | konteks | `signals.concentration` atas negara/bahasa sumber Anda (kecondongan, bukan batasan) | baru |
| **Pemeriksaan cuaca tersedia (Weather check available)** | selidiki | `analytics.corroboration` — istilah peristiwa iklim × tempat yang disimpulkan × tanggal artikel | baru |

¹ Memerlukan ekstra `[analysis]` (VADER / scipy). Tanpanya, kartu-kartu itu tidak
muncul — bagian briefing lainnya tetap berfungsi.
² Menggunakan leksikon emosi; **sampel** minimal bahasa Inggris disertakan, arahkan
`OO_EMOTION_LEXICON` ke leksikon JSON yang lebih lengkap untuk penggunaan serius (hanya bahasa Inggris).

Kartu **ruang gema**, **sinyal tunggal**, dan **kapasitas tidak masuk akal** berasal dari
lapisan integritas sumber — lihat [`USER_MANUAL.md`](USER_MANUAL.md). Kartu ruang gema membawa
tindakan *Gabungkan jadi satu aktor* (anti-amplifikasi yang dipandu pengguna — usulkan → Anda yang memutuskan).

**Audit diri pola konsumsi** menggunakan primitif murni pertama dari substrat bersama
[`src/signals/`](../src/signals/): **konsentrasi** (koefisien Gini +
porsi N teratas). Ini adalah *matematika yang sama* yang dimaksudkan untuk konsentrasi kepemilikan media
(FUTURE_DEVELOPMENTS §1) dan keterkemukaan tokoh (§4) — satu mesin, banyak ranah.

**Silsilah berita** menelusuri sebuah berita yang bergema menuju **sumber primernya**: untuk klaster
hampir-duplikat di banyak media, ia mengurutkan potongan-potongannya menurut waktu terbit dan mendeteksi
**atribusi kantor berita** yang eksplisit ("menurut Reuters", "(AFP)") sehingga liputan asli ditonjolkan
di atas gema turunan. Garis tegasnya jujur: *"yang paling awal kami lihat" ≠ "kebenaran"* — ia
memunculkan struktur; manusia yang menilai. **Penasihat cakupan** memunculkan **kecondongan** geografis/linguistik
**dalam koleksi Anda sendiri** (mis. "~80% dari yang Anda kumpulkan berasal dari satu negara") sebagai
saran halus untuk memperluas — ia tidak pernah menyaring atau membatasi apa pun; korpus yang condong membuat condong setiap
sinyal turunan, jadi melihat kecondongan itulah intinya.

**Pemeriksaan cuaca tersedia** adalah kartu *jika-ini-maka-sarankan* yang pertama: ketika beberapa
artikel Anda menyebut kata peristiwa iklim yang sama (kekeringan, banjir, gelombang panas… — daftar awal
yang dikurasi dalam 12 bahasa, `configs/corroboration_rules.yml`) bersama tempat yang disimpulkan yang sama
dalam satu jendela waktu, kartu itu **menawarkan** untuk mengambil data cuaca independen untuk
tempat dan jendela waktu itu persis. Kartu itu sendiri dihitung secara lokal — dan menyatakannya — dan
tidak ada yang diambil sampai Anda mengklik **Ambil konteks cuaca**, yang melewati
popup persetujuan jaringan yang sama seperti setiap tindakan daring lainnya. Yang kembali adalah satu irisan
**reanalisis** Open-Meteo yang terbatas (CC BY 4.0, atribusi ditampilkan): sebuah *perkiraan model*, bukan
catatan stasiun — ia dapat **menguatkan atau menantang** apa yang dikatakan artikel, tidak pernah membuktikannya.
Irisan itu disimpan dalam cache di disk sehingga membacanya ulang nanti dapat dilakukan secara luring; status cache dan
waktu pengambilannya selalu ditampilkan.

---

### Kinerja — hitung di muka, simpan ke cache, sajikan dari cache

Briefing **tidak pernah dihitung per permintaan**. Penjadwal latar belakang menyegarkannya
setelah setiap pengikisan dan menulis cache (`briefing_cache.json` di direktori data Anda);
Beranda membaca cache itu dan dimuat seketika. Briefing ini **memperbarui diri sendiri** — ia menghitung ulang di
latar belakang setelah setiap putaran dan Beranda memeriksa ulang dengan sendirinya (spanduk kemajuan tampil
selama penyegaran berjalan); tidak ada tombol Segarkan manual. Daftar yang disingkirkan
(`briefing_dismissed.json`) dan draf (`briefing_draft.json`) adalah berkas JSON lokal yang kecil
— untuk satu pengguna, mengutamakan lokal, tidak pernah dikirimkan.

---

### Pengaman kejujuran (di dalam kode, bukan hanya di dokumen)

FUTURE_DEVELOPMENTS §6 melarang satu skor kepercayaan/kualitas otomatis (skor semacam itu menanamkan
pandangan dunia pemberi skor ke dalam angka yang seolah objektif dan *akan* salah menggolongkan sumber yang kecil, asing,
baru, atau pembangkang). Larangan itu ditegakkan **secara mekanis**:

- `src/briefing/card.py:assert_no_score_fields()` menolak setiap bidang `Card` yang namanya
  menyiratkan skor gabungan (`score`, `trust_score`, `credibility`, `rating`,
  `verdict`, …). Fungsi ini berjalan saat impor dan sebuah tes memastikan larangan itu berlaku.
- Nilai numerik yang dibawa sebuah kartu berada di `signal` sebagai **satu kuantitas terukur dengan
  metode yang dinyatakan** — rasio pertumbuhan, nilai Gini, koefisien korelasi — tidak pernah
  skor campuran atas dimensi-dimensi yang tidak sebanding.
- **Munculkan, jangan tekan.** Penyingkiran dapat dibatalkan; setiap penurunan bobot di masa depan akan
  transparan, dapat disetel, nonaktif secara bawaan, dan dapat dibatalkan.

---

### API

Semuanya di bawah `/api/briefing` (hanya loopback, seperti bagian aplikasi lainnya):

| Metode & jalur | Tujuan |
|---|---|
| `GET /api/briefing` | umpan dari cache, dikelompokkan per kelompok (`?force=true` untuk menghitung ulang) |
| `POST /api/briefing/refresh` | hitung ulang sekarang |
| `POST /api/briefing/dismiss` · `/restore` · `/dismissed/clear` | kelola penyingkiran |
| `GET /api/briefing/draft` | draf saat ini (kartu yang disematkan + catatan + judul) |
| `POST /api/briefing/draft/add` · `DELETE /api/briefing/draft/{id}` | sematkan / lepaskan kartu |
| `PUT /api/briefing/draft/note` · `/title` · `POST /draft/clear` | sunting draf |
| `GET /api/briefing/draft/export.md` | Markdown yang membawa bukti |

---

### Peta jalan (status)

Fase A–D sudah dirilis: tulang punggung kartu+briefing (A), substrat `src/signals/` lengkap
— konsentrasi, hampir-duplikat/koordinasi, kebaruan (B), profil integritas sumber +
anti-amplifikasi yang dipandu pengguna (C, lihat [`USER_MANUAL.md`](USER_MANUAL.md)), dan bundel anotasi
bertanda tangan hasil urun daya (D, lihat [`USER_MANUAL.md`](USER_MANUAL.md)). Fase E merilis
vertikal yang dapat disusun sebagai kartu (emosi, berita HKI/hukum); **vertikal pelacakan perubahan
sumber primer hukum / HKI** (menelan `legislation.gov.uk`, EUR-Lex, paten/berkas perkara)
tetap menjadi langkah berikutnya yang terdokumentasi — vertikal ini memakai ulang mesin pelacakan perubahan dan
mesin hampir-duplikat/korelasi yang sudah ada, tetapi memerlukan sumber eksternal yang aktif. Lihat
[`ROADMAP.md`](archive/roadmaps/DESIGN_MEMORY_pre-0.2.md) Fase B–E.


---

## Integritas sumber & anti-amplifikasi

> **Status:** `0.06` Fase C — sudah dirilis dan diuji. Batu kunci lapisan
> intelijen (FUTURE_DEVELOPMENTS §6). Berpasangan dengan [`USER_MANUAL.md`](USER_MANUAL.md) dan
> [`USER_MANUAL.md`](USER_MANUAL.md).

Alat-alat lain memunculkan sinyal; **alat ini menentukan sinyal siapa yang dihitung** — *tanpa
menjadi wasit kebenaran*. Inilah jawaban atas masalah "sampah masuk".

### Kejutannya: memperlakukan setiap sumber secara setara **tidak** netral

Tren, keterkemukaan, keserempakan, dan "apa yang diliput" semuanya **menghitung media dan volume**.
Jadi perlakuan setara terhadap media, bila diterapkan pada metrik volume, memiliki bias bawaan:
*siapa pun yang memproduksi paling banyak, dialah yang menang.* Aktor bermodal besar yang mendirikan 40 media (atau
peternakan troll, atau pabrik konten) mengubah modal langsung menjadi konsensus semu dan
**mengencerkan** berita jujur dari satu sumber hingga tak berarti. Tidak berbuat apa-apa bukanlah netral —
itu menyubsidi si pembanjir.

Penyelesaiannya bukan dengan *memberi skor* pada sumber. Melainkan dengan mendefinisikan kenetralan atas
**satuan** yang tepat: perlakuan setara terhadap *aktor independen yang dibobot menurut informasi baru yang mereka
sumbangkan*, bukan terhadap *media*. **Menghitung akun boneka (sock-puppet) sebagai suara adalah kesalahan
pengukuran, bukan kenetralan.**

### Apa yang diukur (dan apa yang dilarang)

Kami berada sepenuhnya di sisi yang **diizinkan** dari pembedaan §6:

- **(A) Pemberian skor kebenaran / kualitas** — "apakah sumber ini jujur / baik?" —
  **dilarang diotomatiskan.** Skor semacam itu menanamkan pandangan dunia pemberi skor ke dalam angka yang seolah
  objektif dan pada akhirnya *akan* menurunkan skor sumber yang baik-tetapi-tidak-lazim juga.
- **(B) Sinyal keaslian / struktur** — "apakah sumber ini sesuai dengan yang diakuinya? satu
  simpul dari jaringan terkoordinasi? apakah ia *mengawali* atau hanya *menggemakan*? apakah keluarannya
  masih dalam kapasitas manusia? apakah ia transparan tentang siapa yang menjalankannya?" — hal-hal ini, hingga
  taraf yang nyata, merupakan **fakta struktural yang dapat diukur.** Seluruh rancangan berada di sini.

#### Mesin bersama (`src/signals/`)

| Primitif | Mengukur | Menenagai |
|---|---|---|
| `concentration` | Gini + porsi N teratas | konsentrasi kepemilikan/pola konsumsi, keterkemukaan |
| `near_dup` | klaster hampir-duplikat MinHash + LSH | deteksi gema / sindikasi |
| `coordination` | grafik aktor dari hampir-duplikat + waktu serempak + host bersama | penggabungan aktor |
| `novelty` | porsi shingle kata yang baru bagi korpus | pembobotan mengawali-vs-menggemakan |

Keempatnya **murni** (tanpa DB, tanpa jaringan), diuji berbasis properti, dan membawa metode + peringatan.

### Anti-amplifikasi **dipandu pengguna** (usulkan → Anda yang memutuskan)

Anti-amplifikasi **tidak pernah** merupakan transformasi diam-diam yang dilakukan aplikasi dan hanya Anda
*batalkan* — itu akan menjadikan aplikasi sebagai wasit yang dilarang oleh §6.

- **Bawaan = "setara tetapi sadar."** Tampilan mentah dengan perlakuan setara adalah garis dasarnya;
  banjir terkoordinasi **dianotasi di atasnya** (kartu *ruang gema*), bukan digabungkan.
- **Anda yang menerapkan penggabungan**, per klaster atau secara global. Baru setelah itu jaringan
  terkoordinasi melebur menjadi **satu suara** dalam setiap hitungan yang mengukur konsensus (berapa banyak
  suara independen yang membawa suatu berita).
- **Setiap penggabungan yang diterapkan tetap bertanda dan dapat dibatalkan.** Satu klik memperluasnya menjadi
  anggota-anggotanya; pembatalan mereproduksi hitungan setara yang mentah **secara persis**. *Tidak ada penggabungan yang pernah
  diterapkan tanpa tindakan eksplisit Anda* — ditegakkan oleh sebuah tes.

Inilah **meja integritas sumber** (Pengaturan → Lanjutan → Keamanan → "Buka meja integritas sumber"):
*Pindai koordinasi* mencantumkan aktor yang diusulkan beserta buktinya (teks bersama,
waktu serempak, host bersama); *Terapkan penggabungan* / *Perluas (kembalikan)* adalah pilihan Anda.
Petunjuk ruang gema di Beranda membawa tindakan *Gabungkan jadi satu aktor* yang sama.

### Profil sumber — dimensi terukur, **tanpa skor gabungan**

Per sumber, sebuah panel sinyal yang *terukur* — dan **dengan sengaja tanpa satu angka
kepercayaan** ("B" yang dilarang). Skor 0–100 adalah presisi palsu atas dimensi-dimensi yang tidak sebanding,
mudah dipermainkan ala Goodhart, satu titik penguasaan, dan *akan* salah menggolongkan sumber yang
kecil / asing / baru / pembangkang. Larangan ini ditegakkan dalam kode (profil
mengembalikan `no_composite_score: true` dan sebuah tes memastikan tidak ada kunci `*score*` agregat).

Dimensi-dimensinya (masing-masing dengan metode + peringatannya sendiri):

- **Koordinasi** — keanggotaan aktor, dengan siapa, berapa banyak berita bersama.
- **Kebaruan** — apakah sumber ini mengawali atau sebagian besar menggemakan? (relatif terhadap korpus *Anda*).
- **Kapasitas keluaran** — artikel/hari vs median korpus (sebuah *pertanyaan*, bukan vonis;
  kantor berita dan ruang redaksi besar memang sah untuk sangat produktif).
- **Transparansi** — tag negara, bahasa, kepemilikan/kecenderungan (bersifat reputasional,
  dapat diperdebatkan, dapat disunting), dan `reliability_score` yang ditetapkan operator (tidak dihitung di sini).
- **Rekam jejak** — apa yang telah disumbangkan sumber ini ke korpus Anda.

Anda yang menentukan bobot dimensi mana yang penting dalam tampilan *Anda* — nonaktif secara bawaan, dapat dibatalkan,
tampilan setara yang mentah selalu hanya berjarak satu klik.

### Kartu briefing baru dari lapisan ini

- **Ruang gema** (terlalu diberitakan) — satu berita yang dibawa oleh N sumber terkoordinasi.
- **Sinyal tunggal** (kurang diberitakan) — berita substantif dari satu sumber yang tidak bergema.
- **Kapasitas tidak masuk akal** (selidiki) — sumber yang menerbitkan jauh di atas norma korpus.

### API

| Metode & jalur | Tujuan |
|---|---|
| `GET /api/integrity/profile?source=` | panel sinyal terukur tanpa skor gabungan |
| `GET /api/integrity/actors` | aktor terkoordinasi yang diusulkan, masing-masing bertanda diterapkan/tidak |
| `GET /api/integrity/prominence` | keterkemukaan berita dalam suara independen, mentah vs digabungkan |
| `POST /api/integrity/collapse/apply` · `/revert` | terapkan / batalkan penggabungan (per aktor) |
| `POST /api/integrity/collapse/apply_all` · `/revert_all` | gabungkan / atur ulang secara global |

### Batas yang jujur (disebutkan)

- **Perlombaan senjata / Goodhart** — setiap sinyal yang dipublikasikan menjadi sasaran optimasi; ini adalah
  pertahanan berlapis, tidak pernah klaim kelengkapan.
- **Penggabungan keliru merugikan yang tidak bersalah** — deteksinya berpresisi tinggi, condong untuk
  *kurang*-menggabungkan, selalu menampilkan bukti, selalu dapat dibatalkan.
- **Penguasaan** — kami merilis *mekanisme, bukan vonis*; bawaannya adalah tampilan setara yang
  transparan; Anda dapat mengesampingkan segalanya.
- **Tujuannya** bukan "mendeteksi semua sampah" (mustahil, dan mengklaimnya justru merupakan langkah
  yang tidak jujur) melainkan **melucuti keunggulan mekanis sampah** sehingga permainan 40 media
  itu *tidak lagi menguntungkan*.


---

## Anotasi sumber bersama — bertanda tangan, portabel, terfederasi berdasarkan kepercayaan

> **Status:** `0.06` Fase D — sudah dirilis dan diuji. Jawaban penskalaan untuk profil
> sumber (FUTURE_DEVELOPMENTS §6). Berpasangan dengan [`USER_MANUAL.md`](USER_MANUAL.md).

Profil sumber memungkinkan *Anda* menentukan bobot dimensi mana yang penting. Tetapi **tak seorang pun dapat menilai
ribuan sumber secara netral seorang diri** — sehingga pembobotan itu harus bersifat **kolektif**. Cara yang
jujur, mengutamakan lokal, dan tidak terpusat untuk melakukannya adalah **bundel anotasi yang bertanda tangan
dan dapat dibagikan**.

- Anda menerbitkan anotasi sumber Anda — tag koordinasi, fakta kepemilikan/transparansi,
  tag kecenderungan, koreksi, catatan — sebagai **bundel yang bertanda tangan kustodi, dapat diverifikasi, dan
  portabel** (memakai ulang penanda tangan hibrida Ed25519 + ML-DSA yang sama dengan rantai kustodi —
  *mutualisasi*, bukan tumpukan kripto kedua).
- Pengguna lain **mengimpor** bundel yang mereka pilih untuk dipercaya — **jaringan kepercayaan** yang bersifat opt-in,
  **tidak pernah** otoritas pusat.
- Agregasinya **transparan**: Anda selalu melihat *siapa menyatakan apa*, dan **perbedaan pendapat
  ditampilkan, bukan dirata-ratakan** menjadi angka tersembunyi.

Tanpa server, tanpa akun, tanpa skor global — **federasi melalui pertukaran bertanda tangan.**

### Apa itu anotasi (dan apa yang bukan)

Anotasi adalah **fakta atau tag deskriptif yang dapat diperdebatkan** tentang suatu sumber. Jenis-jenisnya:
`ownership`, `leaning`, `coordination-tag`, `transparency-fact`, `correction`, `note`.
Anotasi **tidak pernah** berupa skor kepercayaan/kualitas gabungan — itu dilarang, sesuai rancangan dan di dalam
kode (jenis yang tidak sah seperti `trust-score` ditolak).

### Model kepercayaan — apa yang dibuktikan dan tidak dibuktikan oleh tanda tangan

Setiap bundel menyematkan **identitas publik** penulisnya dan tanda tangan atas manifes
kanonis. Verifikasi **mematok** kunci yang tersemat, sehingga serangan ubah-lalu-tanda-tangani-ulang tidak dapat
*menyamar* sebagai penulis aslinya — serangan itu hanya menghasilkan penulis yang **berbeda**. Bundel yang
terverifikasi karenanya selalu diatribusikan dengan benar kepada kunci mana pun yang menandatanganinya.
Anda kemudian memutuskan *kunci mana yang dipercaya*; hanya anotasi dari penulis tepercaya yang diagregasi.

Ini adalah **jaringan kepercayaan, bukan bukti kebenaran**: memercayai seorang penulis berarti "saya ingin
melihat pernyataan mereka," bukan "pernyataan mereka benar." Perbedaan pendapat antarpenulis tepercaya
dimunculkan agar Anda yang menilai, tidak pernah diselesaikan atas nama Anda.

### Cara menggunakannya (meja integritas sumber — Pengaturan → Lanjutan → Keamanan)

1. **Tulis** anotasi (target + jenis + nilai) di bawah *Anotasi bersama (jaringan kepercayaan)*.
2. **Ekspor bundel bertanda tangan** → berkas JSON yang dapat Anda terbitkan atau bagikan.
3. **Impor bundel…** → aplikasi **memverifikasi tanda tangannya** sebelum menyimpannya (bundel yang
   tidak sah ditolak, dengan lantang), lalu mencantumkan penulisnya di bawah *Penulis tepercaya* dengan
   sakelar kepercayaan.
4. **Siapa mengatakan apa?** → menghimpun setiap pernyataan tentang suatu sumber dari Anda + penulis
   tepercaya, dengan atribusi dan perbedaan pendapat ditampilkan.

Mencabut kepercayaan dari seorang penulis mengecualikan anotasinya; menghapus penulis menghapus anotasinya secara bersih.

### API

| Metode & jalur | Tujuan |
|---|---|
| `GET /api/annotations/mine` · `POST` · `DELETE /mine/{i}` | anotasi yang Anda tulis |
| `GET /api/annotations/export` | bundel anotasi Anda yang bertanda tangan dan portabel |
| `POST /api/annotations/import` | verifikasi + simpan bundel yang diimpor (ditolak jika tidak sah) |
| `GET /api/annotations/authors` · `PUT /authors/trust` · `DELETE /authors/{id}` | jaringan kepercayaan |
| `GET /api/annotations/for?target=` | agregasi transparan — siapa menyatakan apa |

### Batasan kejujuran

- **Tanpa perataan, tanpa angka konsensus, tanpa skor.** Agregasi mengembalikan klaim yang
  diatribusikan dan menyebutkan *perbedaan pendapat*; ia tidak pernah meringkas ketidaksepakatan menjadi satu angka.
- **Mengutamakan lokal.** Semuanya berupa berkas di direktori data Anda; tidak ada yang dikirimkan dan
  tidak ada server atau akun.
- **Dapat diperdebatkan sejak rancangan.** Setiap anotasi adalah tag/fakta yang dapat Anda dan orang lain
  perdebatkan — secara terbuka.


---

## Wawasan — analitik kata kunci & entitas

### Maksud

Mengubah korpus terpadu dari sekadar kotak pencarian menjadi instrumen analitis. Kata kunci
dan entitas diekstrak dari **teks artikel yang ditelan**, disimpan beserta
kemunculan dan konteksnya, lalu dimunculkan sehingga jurnalis investigatif dapat bertanya:
*apa yang sedang dibicarakan, di mana, kapan, oleh siapa, dan bersama apa?*

Semua yang ada di sini adalah **agregat nyata** atas data tersimpan dengan metode dan
ukuran sampel yang dinyatakan — tidak pernah skor yang dikarang (PRODUCT_SYNTHESIS §3.5).

### Cara kerjanya

```
ingest an article ──► extract (baseline / opt-in spaCy) ──► KeywordMention rows
                          terms + entities, offsets        (count + first offset +
                                                            denormalised date/country/city)
                                                                   │
                          Insights tab / /api/insights  ◄──────────┘
                          trends · associations (PMI) · context · map
```

- **Ekstraksi** (`src/analytics/extract.py`): **istilah** n-gram topikal
  (disaring dari kata henti) plus **entitas** — orang, perusahaan/organisasi, tempat — sebagai
  satuan tunggal. Ekstraktor dasar (tanpa dependensi) mendeteksi entitas sebagai rangkaian
  kata berhuruf Kapital Di Awal dan memberikan jenis `person`/`org`/`location` hanya dari
  gazeter (selain itu, `entity` generik yang jujur); ekstra **spaCy** `[nlp]` yang opt-in
  menambahkan NER `PERSON`/`ORG`/`GPE` yang sesungguhnya. Setiap kata kunci mencatat **ekstraktor mana
  yang melabelinya** — jenis entitas adalah *pernyataan yang dilabeli oleh X*, bukan kebenaran dasar.
  Paling cocok untuk aksara yang dipisahkan spasi; segmentasi CJK/Arab adalah langkah lanjutan yang sudah diketahui.
- **Penyimpanan** (`src/analytics/store.py`): satu `KeywordMention` per (artikel,
  kata kunci) — jumlah kemunculan + offset karakter pertama (kalimat konteks diiris
  dari artikel yang tersimpan saat dibaca, sehingga DB tetap ramping) + `observed_on` /
  `country` / `city` yang didenormalisasi dari sumbernya. Pengindeksan berjalan sebisanya saat
  penelanan (dasar yang cepat, gagal-terbuka). Pengindeksan bersifat **otomatis** — tunggakan apa pun dibereskan
  oleh pelengkapan latar belakang yang senyap saat Anda membuka Wawasan (hitungan "tersisa" turun ke 0
  dengan sendirinya); tidak ada tombol "Indeks korpus (Index corpus)". Pengindeksan ulang penuh atas korpus yang ada
  tersedia dari **Pengaturan → Lanjutan → Diagnostik** ("Indeks ulang seluruh korpus" / "Bersihkan
  kata kunci") sebagai pekerjaan latar belakang yang dapat dijeda.

### Fungsi (tab Wawasan + `/api/insights`)

| Tampilan | Endpoint | Yang ditampilkan |
|------|----------|---------------|
| Jelajahi — tren | `GET /trend?term=&bucket=` | Volume penyebutan dari waktu ke waktu (hari/minggu/bulan), dengan kata kunci yang teresolusi + jenisnya |
| Jelajahi — peta pikiran | `GET /associations?term=` | Kata kunci yang muncul bersama, diurutkan menurut **PMI** (pointwise mutual information) dengan ukuran sampel + peringatan "asosiasi ≠ sebab-akibat"; klik sebuah simpul untuk memusatkannya kembali |
| Jelajahi — konteks | `GET /context?term=` | Cuplikan penyebutan terbaru yang diiris dari teks artikel, dengan tautan artikel/sumber + negara/kota/tanggal |
| Tren | `GET /trending`, `GET /top` | Istilah yang sedang naik (**rasio** terkini-vs-sebelumnya, ukuran yang diberi label) dan istilah teratas, dapat disaring menurut jendela / jenis / negara |
| Peta | `GET /map?days=&kind=` | Kata kunci teratas **per negara dan per kota** (sinyal wilayah berbasis sumber) |
| Pengindeksan | `GET /status`, `POST /reindex?limit=` | Hitungan yang terindeks/tersisa; pengisian balik korpus secara bertahap |

Filter `kind`: `term`, `entity`, `person`, `org`, `location`.

### Jaminan kejujuran

- Tren/teratas adalah hitungan nyata; "naik" adalah **rasio** terkini-vs-sebelumnya yang terdefinisi,
  secara eksplisit *bukan* uji signifikansi.
- Asosiasi menggunakan **PMI** atas kemunculan bersama dalam artikel, dikembalikan dengan `n` dan
  peringatan bahwa sampel kecil itu bising.
- Jenis entitas membawa provenans ekstraktornya; ekstraktor dasar tidak pernah mengklaim jenis
  orang/organisasi/tempat yang presisi yang tidak dapat ia buktikan.
- Wilayah di peta adalah negara/kota **sumbernya** (sinyal yang andal). Tampilan
  Peta kini menyertakan **SVG equirectangular interaktif** (perbesar/geser, label kota
  saat diperbesar) yang memetakan kota menurut lintang/bujur nyata dari sebuah **gazeter**: sampel kecil
  disertakan (`configs/cities.sample.yml`); kumpulan lengkapnya dibuat dari
  Wikidata (`scripts/build_city_gazetteer.py` → `configs/cities.yml`). Kota yang
  tidak cocok dengan gazeter tetap menyimpan data kata kuncinya tetapi **tanpa posisi yang dipetakan** (tidak pernah
  lokasi yang dikarang). Tabel negara/kota tetap ada di samping peta.


---

## Pelacakan perubahan Wikipedia

### Maksud

Wikipedia adalah wilayah yang diperebutkan: artikel terus-menerus disunting, dan di era LLM
menghapus atau menulis ulang sejarah lebih mudah daripada sebelumnya. Alat ini memperlakukan setiap
**edisi bahasa** Wikipedia sebagai sumber yang dilacak yang *suntingannya* adalah datanya, sehingga
jurnalis dapat **mendeteksi dan mendokumentasikan** perubahan berskala besar atau revisionis —
mis. membuktikan bahwa sebuah kalimat ada pada tanggal tertentu dan dihapus oleh akun
tertentu.

> Edisi bersifat per-**bahasa** (`en`, `fr`, `ar`, `ru`, `zh`, …), bukan
> per-negara (tidak ada Wikipedia nasional); UI memetakan bahasa ke negara.

### Mengapa ini bukan penelanan "artikel biasa"

Artikel berubah dari waktu ke waktu, sehingga tidak dapat disimpan sebagai baris `Article` sekali jadi.
Dua pilihan rancangan menyusul dari situ:

1. **Gunakan MediaWiki Action API, bukan pengikisan halaman** — `revisions`,
   `recentchanges` (dengan delta byte), dan `compare` (diff yang dihitung server). Inilah
   jalur yang efisien, ramah Ketentuan Layanan, dan berorientasi perubahan.
2. **Simpan delta, bukan salinan ulang** — simpan **satu** baseline teks lengkap yang terkompresi
   per halaman (`wiki_pages.baseline_text`); setiap suntingan sesudahnya adalah baris `wiki_revisions`
   yang memuat **diff + delta byte bertanda + bendera**, tidak pernah keseluruhan
   artikel baru. Versi historis mana pun dapat direkonstruksi dengan memutar ulang diff.

**Inilah jawaban atas pertanyaan redundansi/disk:** suntingan kosmetik adalah diff kecil
yang membawa bendera `minor` MediaWiki dan disaring oleh ambang ukuran/minor, sehingga
hampir tidak memakan apa-apa. Penyimpanan bertambah seiring **aktivitas suntingan pada halaman yang dipantau**, bukan
seiring korpus artikel yang berukuran multi-GB — Anda tidak pernah memerlukan dump lengkap untuk pelacakan.

### Mendeteksi suntingan berskala besar / mencurigakan (secara jujur)

`src/wiki/flagging.py` menandai suatu suntingan dan mencatat **kode alasan** — ia memunculkan
*kandidat*, ia tidak memvonis "disinformasi":

- `large_removal` / `large_addition` — delta byte melampaui suatu ambang
- `revert` / `blank` — tag perubahan MediaWiki (`mw-reverted`, `mw-undo`, `mw-blank`…)
- `anon_large` — suntingan berukuran sedang ke atas dari IP anonim
- `burst` — banyak suntingan pada satu halaman dalam jendela waktu singkat
- `ores_damaging` — probabilitas "merusak" opsional dari **Wikimedia ORES**, disajikan
  sebagai pernyataan *yang dilabeli oleh ORES* (seperti provenans entitas kami)

Suntingan kosmetik kecil tidak pernah ditandai. Setiap suntingan yang ditandai didokumentasikan dengan
diff + provenansnya (revid, penyunting, stempel waktu), yang tersambung ke
**rantai kustodi** yang sudah ada untuk bukti yang bertanda tangan/berstempel waktu.

### Dua subsistem yang dipisahkan dengan jelas (UX)

1. **Pantau & lacak (Watch & track)** (ringan, seketika, bawaan): daftar pantauan halaman /
   kategori per edisi bahasa; periksa revisi melalui penjadwal di dalam aplikasi; simpan
   revisi + diff + bendera; penampil diff + linimasa per halaman. Tanpa unduhan massal.
2. **Baseline luring (Offline baseline)** (berat, opsional): berada di **Pengaturan → Baseline luring
   Wikipedia** (sengaja dijauhkan dari pelacak ringan). Sebuah
   **daftar edisi bahasa yang dapat dipilih** (dikurasi, dari yang terbesar, dengan nama
   masing-masing bahasa dalam bahasanya sendiri dan tingkat ukuran kasar) menggantikan entri kode teks bebas; ukuran
   dump saat ini yang persis dibaca dari server sesuai permintaan (`Estimate size`),
   lalu unduh / jeda / lanjutkan / hapus. Daftar itu berasal dari
   `GET /api/wiki/languages`; pengunduh tetap menerima kode edisi apa pun.
   (Kenyataan ukurannya: enwiki teks terkini ≈ 22 GB terkompresi; riwayat lengkapnya berukuran
   terabyte — hanya diperlukan untuk diff historis luring.)

### Status

- **Selesai:** skema (`wiki_pages`, `wiki_revisions`; migrasi `d4e5f6a7b8c9`);
  parser MediaWiki API + klien langsung (`mediawiki.py`, `client.py`); logika
  penandaan suntingan (`flagging.py`); klien ORES (`ores.py`); orkestrator
  pelacakan (`track.py`, penyimpanan baseline + delta); mode `wiki` penjadwal;
  **API** (`/api/wiki/*`) dan **Pengaturan → Wikipedia** (daftar pantauan, lacak sekarang,
  umpan perubahan yang ditandai, penampil diff); **pengunduh baseline luring**
  (`dumps.py` — per bahasa, dapat dilanjutkan, pemeriksa ukuran) yang kini digerakkan oleh **pemilih
  bahasa** (`languages.py`, `GET /api/wiki/languages`) yang dipindahkan ke **Pengaturan →
  Baseline luring Wikipedia**. Semua logika murni + orkestrasi diuji unit dengan
  fixture (tanpa jaringan).
- **Berikutnya:** menautkan silang diff wiki ke analitik kata kunci Wawasan; firehose
  EventStreams opsional; ekspor bukti atas diff yang ditandai melalui rantai kustodi.

### Etika

Semua pengambilan mematuhi kebijakan penggunaan MediaWiki API (User-Agent yang mengidentifikasi diri,
`maxlag`, batas laju) — lebih santun daripada pengikisan. Kami hanya menyimpan data
revisi publik; tidak ada yang diambil sampai pelacakan berjalan.


---

## Hukum dunia — pelacakan perubahan untuk undang-undang, lembaran negara & HKI

> **Status:** `0.06` Fase E — sudah dirilis. Vertikal §5: sebuah "Wikipedia untuk hukum."
> Memakai ulang mesin pelacakan perubahan (`src/wiki`) dan mesin bersama `src/signals/`.

Menghimpun **hukum** — undang-undang, peraturan perundang-undangan, lembaran negara resmi, catatan HKI — dari
sumber resmi di seluruh dunia, dan **melacak bagaimana hukum itu berubah dari waktu ke waktu**. Hukum bersifat publik di
banyak negara dan berubah melalui amandemen, sehingga datanya *adalah diff itu sendiri*: apa yang berubah, kapan.

### Aktif secara bawaan — katalog sumber resmi nyata dari seluruh dunia

`configs/legal_sources.yml` menyertakan kumpulan **sumber primer resmi yang nyata** dari seluruh dunia
yang telah dikurasi — basis data peraturan perundang-undangan nasional (`legislation.gov.uk`, EUR-Lex, Légifrance,
`gesetze-im-internet.de`, `congress.gov`/`govinfo.gov`, `legislation.gov.au`,
`indiacode.nic.in`, `elaws.e-gov.go.jp`, `law.go.kr`, …), lembaran negara resmi, kantor HKI
(WIPO Lex, USPTO, EPO, EUIPO, JPO, …) dan sistem putusan pengadilan/pengarsipan yang terbuka (CourtListener,
SEC EDGAR). Pada peluncuran pertama, semuanya dimasukkan sebagai sumber biasa yang **dapat ditelan dan dicari**
(`source_type` legal/ip), sehingga mengalir melalui alur etis yang *sama* dengan berita.

Subkumpulan **dokumen hukum terkonsolidasi** yang stabil dan terkenal yang telah dikurasi (mis. Human
Rights Act Inggris, GDPR Uni Eropa, Konstitusi AS) didaftarkan untuk **pelacakan perubahan** sejak
awal.

### Cara kerja pelacakan (memakai ulang mesin Wikipedia)

Untuk setiap dokumen yang dilacak, pengambilan pertama yang berhasil adalah **baseline** yang tidak dapat diubah
("hukum sebagaimana adanya pada tanggal X"). Setiap pengambilan berikutnya yang *teks tampaknya yang dinormalisasi*
berbeda mencatat sebuah revisi yang membawa delta byte, **diff** terpadu yang dibatasi ukurannya terhadap
baseline, dan **bendera perubahan besar** yang jujur (memakai ulang ambang penandaan wiki).
Jalankan dari **tab Pemerintah → subtab Hukum** ("Lacak perubahan sekarang") atau melalui
penjadwal latar belakang (mode `law`). Semua pengambilan melewati jalur yang **etis
dan gagal-tertutup terhadap robots**.

### Membaca undang-undang dari XML milik penerbitnya sendiri (sumber terstruktur)

Halaman web harus *direkonstruksi* menjadi teks: buang navigasi, formulir pencarian,
spanduk cookie, lalu berharap yang tersisa adalah undang-undangnya. Cara itu berhasil, dan memang itulah
yang dilakukan pelacak untuk sebagian besar sumber — tetapi salinan tersimpan dari satu Undang-Undang Inggris pernah
diawali dengan formulir pencarian milik portal itu sendiri, dan segala sesuatu yang diturunkan darinya (seorang "Personal Acts"
sebagai orang, sebuah "PART" sebagai organisasi) berasal dari teks yang tidak pernah ada di dalam undang-undang tersebut.

Ketika sebuah penerbit menyajikan **XML miliknya sendiri**, semua itu tidak berlaku: tidak ada elemen tampilan halaman
di dalam berkas, karena berkas itu bukan halaman. Open Omniscience dapat membaca
CLML dari `legislation.gov.uk` secara langsung, yang juga memberikan dua hal yang tidak dapat diberikan halaman web:

- **Ketentuan dengan alamat yang dapat dikutip.** Setiap pasal dibaca beserta jalur Bagian/Bab
  di atasnya, sehingga suatu perubahan dapat dilaporkan sebagai *"pasal 12 dari Bagian 2 berubah"*, bukan
  sebagai jumlah byte. Pasal dicocokkan berdasarkan alamat itu dan tidak pernah berdasarkan posisinya —
  jika tidak, menyisipkan satu pasal akan membuat seluruh sisa undang-undang dilaporkan sebagai telah diubah.
- **Tanggal yang berarti persis seperti yang dikatakannya.** Tanggal pengundangan, titik konsolidasi, dan tanggal *kami*
  mengambilnya adalah tiga bidang terpisah tanpa saling menggantikan. Tanggal yang tidak dinyatakan
  dokumen ditampilkan sebagai tidak diketahui, tidak pernah diisi dari tanggal lain. (Inilah sebabnya
  undang-undang yang dilacak tidak menampilkan tanggal terbit kecuali dokumen itu sendiri menyediakannya: satu-satunya
  tanggal yang tersedia adalah hari kami memeriksa halaman itu, dan tanggal pemeriksaan bukanlah tanggal
  terbit.)

Perbandingan per pasal bersifat **tambahan dan eksperimental**: diff teks biasa tetap
menentukan apakah suatu revisi dicatat dan tetap membawa penanda perubahan besar. Dan satu
batas dinyatakan alih-alih ditutupi — pasal yang *dinomori ulang sekaligus ditulis ulang*
dalam amendemen yang sama dilaporkan sebagai satu penghapusan ditambah satu penambahan, karena mencocokkannya dengan
dirinya yang lama berarti menebak mana dari dua pasal bernomor berbeda yang merupakan "pasal
yang sama, yang disunting".

**Yang belum ada:** belum ada yang mengambil dokumen-dokumen XML tersebut secara otomatis. Membaca
seluruh korpus hukum suatu yurisdiksi berarti menelusuri daftar milik penerbit itu sendiri (Inggris
mendaftar setiap undang-undangnya; Prancis mendaftar 76 kitab undang-undang), dan penyusunan daftar itu belum dibuat. Sampai saat itu,
kumpulan yang dilacak tetap kumpulan yang dikurasi, dan laporan cakupan dengan jujur menyatakan
"cakupan tidak diketahui" alih-alih menyajikan jumlah dokumen yang dilacak seolah-olah itu adalah
seluruh korpus.

### Memeriksa bahwa perbaikan hukum sudah sampai ke data Anda

Dua perbaikan hukum pulih **secara diam-diam, pada pengambilan berikutnya yang berhasil atas suatu dokumen**: elemen tampilan halaman
dibaca ulang keluar dari garis dasar yang tersimpan, dan tanggal terbit yang sebenarnya adalah tanggal pemeriksaan
dihapus. Keduanya benar — dan dokumen yang portalnya tidak dapat dijangkau tidak pernah pulih, dan
justru itulah kasus yang patut diketahui.

Laporan **law-ingest** (dalam paket semua diagnostik, atau tersendiri) menjawabnya dari
data tersimpan tanpa panggilan jaringan: apa yang dicatat oleh pemeriksaan terakhir setiap dokumen yang dilacak (jumlah
per hasil, seperti tidak berubah, dibaca ulang, galat, atau ditunda, serta hasil masing-masing dokumen
dan waktu percobaan terakhirnya), dan apakah ada artikel hukum yang masih membawa
tanggal terbit yang seharusnya tidak dimilikinya. Dokumen yang pemeriksaan terakhirnya gagal patut
diperiksa, tetapi laporan itu tidak dapat mengetahui apakah dokumen tersebut pernah dibaca ulang sebelum mulai gagal:
hal itu tidak dicatat. Jumlah baca-ulang itu sendiri hanya menghitung dokumen yang pemeriksaan
terbarunya adalah baca-ulang, sehingga pada instalasi tempat semua dokumen telah pulih, angkanya turun
mendekati nol.

Laporan itu juga melaporkan **sisa elemen tampilan** — teks navigasi yang masih ada dalam isi yang tersimpan. Bacalah
itu sebagai *pengukuran*, bukan vonis: pembersihan elemen tampilan sengaja hanya membuang apa yang
dinyatakan markup sebagai elemen tampilan dan membiarkan sisanya, karena aturan pencocokan teks juga
akan menghapus judul-judul pasal milik undang-undang itu sendiri. Sisa setelah baca-ulang yang benar memang wajar;
angkanya memberi tahu Anda seberapa banyak elemen tampilan yang tidak dinyatakan ada di korpus Anda, dan daftar penandanya adalah
batas bawah, sehingga nol berarti "tidak satu pun dari ini", tidak pernah "tidak ada elemen tampilan".

### Kartu ringkasan dari korpus hukum

- **Hukum berubah** (pantau) — perubahan yang ditandai pada dokumen hukum yang dilacak.
- **Legislasi model** (selidiki) — teks hukum yang hampir identik di dua yurisdiksi atau lebih
  (mesin hampir-duplikat §1/§2), pola difusi yang dapat diukur.

Selain itu, karena teks hukum berada di korpus terpadu, korelasi **hukum ↔ berita** dan
analitik kata kunci bekerja atasnya seperti pada sumber lainnya.

### API

| Metode & jalur | Tujuan |
|---|---|
| `GET /api/law/status` | cakupan: dokumen per yurisdiksi, total perubahan/penanda |
| `GET /api/law/documents` | dokumen yang dilacak (opsional `?jurisdiction=`) |
| `GET /api/law/documents/{id}` | satu dokumen beserta riwayat perubahannya (diff) |
| `GET /api/law/changes` | perubahan hukum terbaru (yang ditandai), terbaru lebih dulu |
| `POST /api/law/track` | ambil semua dokumen yang dipantau sekarang (pengambil etis) |
| `POST /api/law/seed` | isi (ulang) katalog seluruh dunia + daftarkan dokumen |

### Batasan kejujuran (hukum menyangkut taruhan tinggi)

- **Bukan nasihat hukum, bukan sumber yang otoritatif.** Salinan teragregasi adalah
  *cermin riset*; setiap catatan menautkan kembali ke lembaran negara resmi, dan UI menyatakannya.
  Lacak dan tampilkan; jangan pernah menafsirkan keabsahan atau menilai suatu undang-undang.
- **"Publik" ≠ "bebas didistribusikan ulang."** Lisensi berbeda-beda bahkan ketika teksnya publik —
  masing-masing dihormati, diberi atribusi, dengan provenans tersimpan, robots gagal-tertutup (seperti untuk berita).
- **Batasi cakupan dengan jujur.** "Setiap negara" adalah bintang penunjuk arah, bukan v1: katalognya luas tetapi
  dikurasi, dan pelacakan perubahan dilakukan dengan diff teks yang dinormalisasi (portal teks terkonsolidasi memberikan
  sinyal paling bersih). Ketika penerbit menyajikan XML terstruktur, diff per pasal
  tersedia (lihat di atas) — saat ini CLML; Akoma Ntoso / ELI belum dibaca. Alat ini menyatakan
  mana yang dimilikinya untuk setiap dokumen, dan menolak menebak: dokumen yang tidak dapat diurainya
  secara terstruktur tetap memakai diff teks, alih-alih dilaporkan seolah-olah memiliki pasal-pasal.
- **Terjemahan** (melalui LLM lokal) adalah alat bantu terpisah yang diberi label jelas — tidak pernah
  terjemahan hukum yang otoritatif.


---

## Pasar: intelijen keuangan, bursa saham, dan komoditas/logam tanah jarang

Open Omniscience menyertakan **katalog sumber pasar seluruh dunia yang dikurasi** sehingga
siap menyerap liputan pasar keuangan sejak awal, serta tab **Komoditas** yang
mengubah halaman yang *dikonfigurasi* menjadi deret harga nyata yang dapat dibuat grafiknya dan dikorelasikan dengan berita.

Dokumen ini menjelaskan apa yang sudah dikemas, apa yang belum, dan alasannya — karena
batas yang jujur di sini lebih penting daripada daftar fitur yang panjang.

### Apa yang sudah dikemas (siap dijalankan apa adanya)

`configs/markets_sources.yml` diisikan secara otomatis bersama katalog berita
(`configs/sources.yml`) pada peluncuran pertama dan melalui **Pengaturan → Lanjutan → Sumber → Tambahkan sumber awal**.
Isinya ~110 entri yang dikurasi, diidentifikasi berdasarkan domain utama
yang stabil:

- **Bursa saham & efek** di seluruh dunia (Amerika, Eropa, Asia-Pasifik,
  Timur Tengah, Afrika) — NYSE, Nasdaq, LSE, Euronext, Deutsche Börse, JPX, HKEX,
  SSE/SZSE, NSE/BSE India, SGX, ASX, B3, Tadawul, JSE, dan banyak lagi.
- **Bursa komoditas / logam / energi / derivatif** — CME Group, ICE, LME,
  SHFE, DCE, ZCE, INE, **GFEX** (kontrak berjangka logam tanah jarang & silikon industri), MCX,
  Eurex, MGEX.
- **Sumber harga/data komoditas & logam tanah jarang** — Shanghai Metals Market, Kitco,
  USGS, World Bank Pink Sheet, EIA, IEA, OPEC, Fastmarkets, Argus, Benchmark
  Mineral Intelligence, S&P Global Commodity Insights.
- **Penerbit berita & data keuangan** — Bloomberg, Reuters, FT, WSJ, CNBC,
  MarketWatch, Nikkei Asia, Caixin, dan lainnya.

Ini adalah **sumber** biasa: semuanya mengisi korpus terpadu melalui
pengambil etis yang sama (robots.txt gagal-tertutup, dengan batas laju). Masing-masing membawa
`source_type` (`stock_exchange` / `commodity` / `financial`), wilayah, negara, dan
tag, sehingga Anda dapat menyaringnya di **Pengaturan → Lanjutan → Sumber** dan memasang aturan harga di
**Komoditas**.

> Umpan RSS sengaja dikosongkan untuk entri-entri ini (URL umpan yang salah
> hanyalah derau). Serap entri-entri ini dengan perayap rekursif, atau tambahkan umpan RSS yang terverifikasi
> per sumber dari **Pengaturan → Lanjutan → Sumber**.

### Mendapatkan angka harga yang nyata

Deret harga hanya dihasilkan ketika Anda memberi tahu aplikasi **di mana tepatnya angka itu
berada** — memang sengaja tidak ada pembacaan halaman secara ajaib. Dua jalur yang jujur:

#### 1. Aturan ekstraksi per halaman (tab Komoditas → "Konfigurasikan sumber data")

*(Umpan dan aturan ekstraksi berada di bagian "Konfigurasikan sumber data" yang terlipat di
tab Komoditas; umpan yang dikurasi itu sendiri diperbarui secara otomatis di
latar belakang.)*

Tambahkan aturan (sumber, simbol, URL halaman, **pemilih CSS**, atribut opsional /
regex nilai, mata uang, satuan), lalu tekan **Uji**. Uji mengambil halaman itu sekali dan
menampilkan nilai *persis* yang ditemukan — atau alasan *persis* mengapa tidak cocok — sehingga Anda dapat
menyetel pemilih dengan umpan balik yang nyata. Aturan yang cocok menyimpan satu `CommodityPrice`
per hari, yang dibaca oleh grafik sebaris dan korelasi harga↔berita.

Templat untuk disalin: `configs/market_rules.example.yml`.

**Peringatan (bacalah ini):** sebagian besar halaman bursa/kuotasi menampilkan harga dengan JavaScript,
sehingga angkanya *tidak* ada di HTML statis yang diterima pengambil dan pemilih tidak akan
menemukan apa pun. Inilah sebabnya pemilih yang berfungsi **tidak** disertakan sejak awal — menebaknya
berarti angka yang dikarang. Halaman yang dirender di server (banyak situs resmi/statistik,
sebagian tabel data) berfungsi dengan baik; widget kuotasi yang sangat bergantung pada perenderan di sisi klien tidak.

#### 2. Umpan CSV resmi (disarankan — andal, disertai katalog)

Untuk riwayat angka yang tepercaya, impor deret CSV yang dapat dibaca mesin dari
sumber resmi. Ini jalur yang andal, dan aplikasi menyertakan katalog awal
(`configs/commodity_feeds.yml`) yang dapat Anda impor dengan satu klik dari
**Komoditas → Konfigurasikan sumber data → Umpan harga resmi**, atau melalui API:

```
GET  /api/markets/feeds                # list curated feeds + how many points each has
POST /api/markets/feeds/{key}/import   # import one (e.g. copper, wti_crude, brent_crude)
POST /api/markets/feeds/import-url      # import ANY CSV URL you supply (user-customizable)
```

**Penyedia utama — FRED** (Federal Reserve Bank of St. Louis): titik akhir CSV yang stabil
tanpa kunci API, `https://fred.stlouisfed.org/graph/fredgraph.csv?id=<ID>`,
yang **mendistribusikan ulang deret komoditas "Pink Sheet" Bank Dunia** (ID
"Global price of …" — tembaga `PCOPPUSDM`, brent `POILBREUSDM`, dll.) dan
deret energi **EIA** (`DCOILWTICO`, `DHHNGSP`, …). Kolom pertama adalah tanggal,
kolom kedua nilainya; nilai yang hilang (`.`) dilewati, tidak pernah disimpan sebagai nol. Impor
bersifat idempoten per `(symbol, market, date)`.

**Sumber sebanding** yang dapat Anda tambahkan sebagai umpan kustom (URL + nama kolom opsional):
- **World Bank** Commodity Markets ("Pink Sheet"): berkas `.xlsx` ada di
  <https://www.worldbank.org/en/research/commodity-markets>; deret yang sama dalam
  CSV yang bersih tersedia melalui umpan FRED di atas.
- Data terbuka energi **U.S. EIA**: <https://www.eia.gov/opendata/>
- **IMF** Primary Commodity Prices: <https://www.imf.org/en/Research/commodity-prices>
- Data komoditas mineral **USGS** (logam tanah jarang): <https://www.usgs.gov/centers/national-minerals-information-center>

Pemetaan kolom bawaan adalah kolom 1 = tanggal, kolom 2 = nilai (konvensi
FRED); sebutkan `date_column` / `value_column` secara eksplisit untuk tata letak lain.

Ada juga jalur unggah berkas langsung untuk CSV yang sudah Anda miliki:

```
POST /api/commodities/{symbol}/prices/import-csv      (multipart file upload)
```

> Jika penyedia mengganti nama atau menghentikan suatu deret, impor gagal **secara terang-terangan** (galat
> HTTP / tidak ada baris yang dapat dipakai) alih-alih mengarang data — perbaiki URL di
> `configs/commodity_feeds.yml` atau gunakan umpan kustom.

### Mengapa tidak ada harga yang diekstrak otomatis sejak hari pertama?

Karena angka tanpa asal-usul yang dapat diverifikasi lebih buruk daripada tidak ada angka sama sekali. Segala sesuatu dalam
alat ini dibangun agar angka yang ditampilkan kepada pengguna berasal dari
pengukuran nyata: pemilih yang benar-benar cocok, atau CSV yang benar-benar
diimpor. Katalog memberi Anda *sumber-sumbernya* seketika; Anda yang memutuskan, per halaman, kapan
suatu harga cukup tepercaya untuk dicatat.


---

## Rantai pengawasan

Open Omniscience sengaja membuat klaim pembuktian yang *sempit dan jujur*:

> **Korpus ini memuat item _ini_, dengan isi _ini_, dicatat pada waktu _ini_,
> dan catatan itu tidak diubah sejak saat itu — dan inilah bukti
> kriptografis yang dapat Anda periksa sendiri, secara luring, tanpa harus memercayai alat ini.**

Itu sungguh berguna bagi jurnalis investigasi: klaim ini membela diri terhadap tuduhan
"Anda mengarang ini," "Anda memundurkan tanggalnya," atau "Anda diam-diam menyuntingnya setelah
kejadian," dan memungkinkan Anda menunjukkan bahwa Anda memberitakan sesuatu *sebelum* suatu halaman sumber
diubah atau dihapus. Ini **bukan** sistem pengiriman untuk pelapor pelanggaran (seperti
SecureDrop), dan "sumber" dalam alat ini adalah *media berita*, bukan narasumber manusia
yang dirahasiakan. Ingatlah cakupan ini ketika menimbang soal perlindungan.

Dokumen ini menjelaskan mekanisme yang sebenarnya (`src/custody/`, `src/reporting/`) dan
menyatakan secara eksplisit apa yang dibuktikan dan **tidak** dibuktikan oleh masing-masing.

---

### Tiga sifat, dan cara kami memperoleh masing-masing dengan jujur

| Sifat | Mekanisme | Apa yang dibuktikannya | Apa yang **tidak** dibuktikannya |
|---|---|---|---|
| **Integritas** | Tanda tangan Ed25519 (+ ML‑DSA opsional) atas serialisasi kanonis; akar Merkle atas semua bidang provenans | Byte-nya tidak berubah sejak ditandatangani; semuanya tercakup, bukan hanya isinya | — |
| **Provenans** | **Penyematan (pinning)** kunci publik penanda tangan yang sudah diketahui | Catatan itu ditandatangani oleh penanda tangan *tersebut* | Tidak apa pun, jika Anda tidak menyematkan kunci — tanda tangan yang sah saja hanya berarti "ditandatangani oleh kunci yang tertanam dalam paket" |
| **Waktu** | `local` (dinyatakan sendiri) **atau** OpenTimestamps (berjangkar ke Bitcoin) | Lokal: waktu yang dinyatakan alat ini. OTS: isinya sudah ada *paling lambat* pada suatu blok Bitcoin | Waktu lokal tidak membuktikan apa pun kepada pihak ketiga; OTS membuktikan *batas atas* waktu, bukan saat yang persis |

Kami menolak memalsukan satu pun dari ketiganya. Jika stempel waktu pihak ketiga yang nyata tidak dapat diperoleh
(luring, atau pustakanya tidak terpasang), kode akan memunculkan galat alih-alih mengarang
waktu — mode kegagalan yang dilarang oleh piagam proyek (PRODUCT_SYNTHESIS §3.7).

---

### Komponen

#### 1. Paket bukti bertanda tangan — `src/reporting/evidence.py`
Ekspor pada satu titik waktu atas artikel-artikel terpilih, masing-masing dengan provenans dan hash
isinya, diikat oleh **akar Merkle dengan pemisahan domain** dan **tanda tangan Ed25519**.
Verifikasi secara luring dengan `scripts/verify_evidence.py <bundle.json> [signer_pubkey]`.
Tersedia di `POST /api/reports/evidence` dan `/api/reports/evidence/verify`.

Kunci penandatanganan berada di `keys/evidence_ed25519.pem` di dalam folder data Anda. Pada penyimpanan
terenkripsi, kunci itu dibungkus dengan frasa sandi Anda (kunci yang dibuat sebelumnya dibungkus, tanpa diubah, saat pertama kali
suatu ekspor memuatnya ketika penyimpanan dalam keadaan terbuka), sehingga salinan folder data saja tidak dapat menandatangani atas nama
Anda; tanpa frasa sandi, kunci itu tetap `0600` dalam bentuk teks biasa. Jika cadangan yang dipulihkan membawa kunci yang dibungkus
dengan frasa sandi instalasi lain, ekspor bukti dan setiap pencadangan (pencadangan menandatangani manifesnya
dengan kunci ini) menyatakan bahwa keduanya tidak dapat membukanya dan tidak mengganti apa pun: gunakan frasa sandi yang dipakai untuk membungkusnya,
atau pindahkan berkas itu ke tempat lain agar kunci baru dibuat (paket yang ditandatangani dengan kunci lama tetap dapat diverifikasi dengan
kunci publiknya). Frasa sandi yang hilang berarti kunci itu hilang; tidak ada pemulihan.

#### 2. Tanda tangan hibrida — `src/custody/signing.py`
Menggabungkan **Ed25519** (cepat, klasik) dengan **ML‑DSA** (FIPS 204, pascakuantum,
penerus terstandardisasi dari CRYSTALS‑Dilithium). Dua aturan membuat ini jujur:

- **Label yang jujur.** Tanda tangan diberi label `hybrid` hanya ketika kunci ML‑DSA
  benar-benar dipakai. Tanpa paket tambahan `pqc` terpasang, penandatanganan menghasilkan tanda tangan `ed25519`
  dan menyatakannya — tidak pernah mengklaim ketahanan kuantum yang tidak dihasilkannya.
- **Hibrida berarti DAN.** Tanda tangan `hybrid` hanya lolos verifikasi jika **kedua** komponennya
  lolos verifikasi. Pemverifikasi yang tidak memiliki pustaka pascakuantum tidak dapat memeriksa separuh
  ML‑DSA dan karena itu **gagal secara terang-terangan** — tidak pernah diam-diam meloloskan hanya berdasarkan separuh
  klasiknya. (Skema yang menerima tanda tangan *mana pun dari keduanya* tidak berharga begitu yang
  klasik dibobol.)

Kunci privat dienkripsi saat tersimpan dengan AES‑256‑GCM menggunakan kunci turunan scrypt
ketika aplikasi memegang frasa sandi (`OO_KEY_PASSPHRASE`, atau jika tidak ada, frasa sandi
basis data); jika tidak, kunci ditulis `0600` dalam bentuk teks biasa dan tingkat perlindungannya
dilaporkan dengan jujur sebagai `plaintext-0600`.

#### 3. Log pengawasan — `src/custody/log.py`
Buku besar SQLite yang **hanya-tambah (append-only)**. Setiap tindakan (`ingest`, `access`, `export`,
`redact`, …) menjadi entri yang **dirantai dengan hash** ke entri sebelumnya,
**ditandatangani**, dan **diberi stempel waktu**. `verify()` memeriksa ulang urutan, mata rantai,
hash per entri, tanda tangan, dan digest stempel waktu. Ekspor dapat diverifikasi secara luring:

```bash
python scripts/verify_custody.py custody_bundle.json [--pin]
```

REST: `POST /api/custody/log`, `GET /api/custody/{item}`, `.../verify`,
`GET /api/custody/export`, `POST /api/custody/verify`.

Pencatatan otomatis saat penyerapan bersifat opsional (opt-in): setel `OO_CUSTODY_ON_INGEST=1`
(`Config.custody_on_ingest`). Fitur ini **nonaktif secara bawaan** — pilihan pembuktian yang eksplisit
dengan sedikit biaya penandatanganan per artikel, bukan perilaku yang diam-diam selalu aktif.
Fitur ini gagal-terbuka: galat pengawasan tidak pernah merusak penyerapan.

#### 4. Penjangkaran — `src/custody/anchor.py`
Menerbitkan akar Merkle ke saksi eksternal sehingga waktu keberadaannya tidak bergantung
pada jam atau kunci Anda sendiri:

- **`local`** (bawaan, luring): mencatat akar dalam buku jangkar lokal. Hanya membuktikan
  bahwa *alat ini* menyimpannya — audit internal, bukan bukti pihak ketiga.
- **`opentimestamps`** (jaringan): menjangkarkan hash yang tidak terbaca ke Bitcoin. Tanpa dompet,
  tanpa biaya, dapat diverifikasi secara independen. Beralih ke galat *tidak tersedia* yang eksplisit
  saat luring — tidak pernah tanda terima palsu.
- **`ethereum` / `ipfs` / `arweave`**: dinyatakan tetapi **tidak diimplementasikan**. Ketiganya
  menolak dengan galat yang jelas alih-alih dirilis sebagai kerangka kosong yang `verify()`-nya selalu
  mengembalikan false.

REST: `POST /api/custody/anchor`, `GET /api/custody/providers`.

#### 5. Pengaturan — `src/custody/settings.py` (dapat dikonfigurasi lewat GUI)
Perilaku pengawasan dikendalikan operator saat aplikasi berjalan, tidak hanya melalui env/YAML.
Preferensi disimpan ke `custody_settings.json` di direktori data dan disunting
dari panel **Rantai pengawasan** di UI web (atau REST API):

- **`pqc_enabled`** — meminta penandatanganan hibrida Ed25519 + ML‑DSA.
- **`anchoring_mode`** — `local` (bawaan) atau `opentimestamps`.
- **`auto_log_on_ingest`** — menambahkan entri bertanda tangan pada setiap penyerapan yang berhasil
  (mengikuti flag lama `OO_CUSTODY_ON_INGEST` sampai suatu preferensi disimpan).
- **`default_actor`** — label pelaku opsional untuk entri yang dicatat otomatis.

**Invarian kejujuran.** Sakelar adalah *permintaan*, bukan jaminan. API dan GUI
selalu menampilkan keadaan yang **efektif** (preferensi **DAN** ketersediaan pustaka):
jika PQC diaktifkan tetapi `pqcrypto` tidak terpasang, penanda tangan tetap hanya Ed25519
dan UI menyatakannya — tidak pernah menampilkan lampu hijau "hybrid" yang tidak dapat dibuktikannya. Begitu pula
untuk OpenTimestamps tanpa paket tambahan `timestamping`.

REST: `GET /api/custody/settings`, `PUT /api/custody/settings`.

Alur kerja "bukti maksimum" yang umum:

```
export evidence bundle  ->  take its merkle_root  ->  POST /api/custody/anchor
  (POST /api/reports/evidence)                         {merkle_root, "opentimestamps"}
```

---

### ⚠️ Privasi: penjangkaran dapat membuka anonimitas Anda

Penjangkaran ke blockchain **publik** adalah **publikasi permanen** atas sebuah hash dan sebuah
stempel waktu. Hash itu sendiri tidak mengungkapkan apa pun tentang isinya, tetapi *tindakan*
mengirimkannya mengungkapkan IP dan waktu Anda kepada operator kalender/RPC, dan dompet
on‑chain yang berisi dana menciptakan jejak uang. Bagi siapa pun yang membutuhkan anonimitas:

- Utamakan **lokal + OpenTimestamps** daripada dompet blockchain publik.
- Arahkan pengiriman OpenTimestamps melalui **Tor** (mis. `HTTPS_PROXY`).
- Atau lewati penjangkaran eksternal sepenuhnya dan andalkan stempel waktu lokal + penandatanganan.

Kerahasiaan dan penjangkaran ke blockchain publik saling bertentangan. Konfigurasi
bawaan (penyedia lokal luring, waktu lokal yang dinyatakan sendiri) tidak membocorkan apa pun.

---

### Apa yang sengaja **tidak** kami bangun

- **Tidak ada TSA RFC‑3161 palsu.** Mengembalikan `datetime.now()` lalu menyebutnya "stempel waktu
  tepercaya" adalah sandiwara. Gunakan OpenTimestamps (nyata) atau lokal (diberi label dengan jujur).
- **Tidak ada tanda tangan hibrida dengan semantik ATAU.** Lihat "Hibrida berarti DAN" di atas.
- **Tidak ada daemon integritas latar belakang yang selalu aktif, tidak ada penyimpanan kunci tanpa enkripsi yang diiklankan
  sebagai "terenkripsi".** Kunci menyatakan bagaimana kunci itu dilindungi; verifikasi dilakukan sesuai permintaan.

### Model ancaman dalam satu paragraf

Alat ini berjalan sebagai **satu pengguna lokal, hanya loopback, di Qubes** (lihat
`docs/SECURITY.md`). Sistem pengawasan membela *integritas dan provenans
jejak bukti milik Anda sendiri* dari perusakan di kemudian hari dan dari tantangan "Anda mengarang ini".
Sistem ini tidak, dan tidak dapat, melindungi identitas narasumber manusia dengan sendirinya,
dan penjangkaran naif ke blockchain publik justru dapat *merugikan* anonimitas — karena itu penjangkaran bersifat
opt-in, bawaannya luring, dan disertai peringatan di atas.


---

# Yang dirilis di 0.0.8 — siklus peta jalan

> **Potret historis, lihat CLAUDE.md.** Ini adalah catatan pada satu titik waktu dari siklus 0.0.8;
> catatan ini tidak dipelihara terhadap rilis-rilis berikutnya. `docs/ledger/OPEN_QUEUE.md` + `docs/ledger/`
> adalah sumber kebenaran yang hidup untuk apa yang telah dirilis sejak itu.

Semua yang ada di bawah ini tersedia sekarang, sepenuhnya dari UI peramban. Setiap fitur menyatakan
batasnya yang jujur di tempat fitur itu muncul.

## Resep investigasi (Beranda) dan dasbor `/investigate`

Ringkasan di Beranda kini mengamati korpus Anda sendiri untuk mencari **sinyal ruang-waktu** dan memunculkan kartu —
semuanya dihitung secara lokal, tidak pernah dari jaringan:

- **Janji jatuh tempo** — sebuah artikel menyebut tanggal yang masih *di masa depan* saat artikel itu
  terbit; tanggal itu kini telah tiba. Saatnya menanyakan apa yang sebenarnya terjadi.
- **Lonjakan perang suntingan** — halaman Wikipedia yang Anda lacak sedang disunting dengan laju ≥3× laju
  mingguan terbarunya sendiri; catatan publiknya sedang bergerak.
- **Wilayah jadi senyap** — sebuah negara yang selama ini rutin menghasilkan artikel untuk Anda (hampir)
  berhenti. Peringatannya sudah tertanam: ini mengukur *korpus Anda*, bukan wilayahnya — umpan yang
  mati tampak sama persis dengan keheningan yang sebenarnya, jadi periksa sumbernya terlebih dahulu.
- **Kandidat sumber menunggu tinjauan (Source candidates await review)** — lihat *Kandidat temuan* di bawah.

Kartu dengan tombol **"Buka investigasi ↗"** membuka dasbor khusus **di tab
peramban baru** (aplikasi utama tetap berjalan; buka beberapa sekaligus). Dasbor itu
menyusun sendiri panel-panel terkait — artikel asli beserta cuplikan provenansnya,
pencarian lanjutan yang sudah terisi, daftar revisi yang tersimpan, konteks cakupan — membawa
peringatan kartu itu kata demi kata di bagian atas, dan diakhiri dengan strip **"Gali lebih dalam"** tempat setiap
saran merupakan tindakan biasa dengan parameternya ditampilkan. Seluruh keadaan halaman itu tersimpan di
URL-nya: tandai, buka kembali, bagikan di antara mesin-mesin milik Anda sendiri.

Matikan resep satu per satu di **Pengaturan → Kartu**, tempat resep-resep itu kini berada berdampingan dengan setiap
Petunjuk lain yang dapat dimunculkan aplikasi ini, dikelompokkan menurut keluarga — sakelar yang sama, berlaku untuk semuanya.

## Lampiran metode

Tombol **Lampiran metode** (di halaman pencarian dan di baris tindakan jendela analisis)
mengunduh dokumen Markdown yang mencatat *bagaimana* pilihan Anda saat ini dihasilkan:
versi aplikasi, kueri Boolean kata demi kata, jumlah hasil, konteks korpus, dan satu
baris provenans per artikel (judul · sumber · tanggal terbit · URL · SHA-256 isi). Dokumen ini
hanya mencatat pilihan dan tidak menegaskan kesimpulan apa pun — klaim analitis tetap milik Anda,
dapat diperiksa terhadap baris-barisnya. Dibuat untuk putusan pemeriksaan fakta dan tinjauan sejawat; pasangkan dengan
paket bukti bertanda tangan (Bukti & kustodi) ketika Anda membutuhkan dokumen + bukti sekaligus.

## Sintesis hasil

**Sintesis hasil** (di halaman pencarian dan di jendela analisis) membuka jendela dalam
dua langkah: jendela ini mengambil kumpulan kandidat, menampilkan artikel-artikel yang cocok beserta metadatanya,
dan memungkinkan Anda **memilih hingga 20 anggota** (≤20 yang pertama sudah dicentang); lalu menjalankan SATU
pemrosesan model lokal atas tepat artikel-artikel itu dan mengembalikan fakta bersama, titik-titik ketidaksepakatan, dan
pertanyaan terbuka, dengan mengutip artikel anggota berdasarkan nomornya. Hasilnya membawa korpus tersintesis lengkap
dengan metadata setiap artikel dan tautan pembaca, serta opsi **ekspor** (Salin, .md, atau
buka sebagai halaman tersendiri). Sintesis disimpan dengan provenans model + versi prompt
per artikel anggota, dan peringatannya ikut menyertainya: ini adalah bantuan membaca atas
anggota yang tercantum saja — tidak pernah vonis. Memerlukan Ollama, seperti fitur LLM lainnya;
tanpanya Anda mendapat pesan jujur "tidak dapat dijangkau".

## Ekspor berversi dan graf sitasi

- Ekspor yang dapat dibaca mesin kini membawa kontrak yang stabil (`oo-export-1`): ekspor JSON adalah
  amplop yang menjelaskan dirinya sendiri (skema, versi aplikasi, waktu pembuatan, kueri persisnya, jumlah);
  kolom CSV mempertahankan urutannya, dengan provenans yang sama seperti header HTTP `X-OO-*`. Kolom
  terakhir, **Fetched From Host** (`fetched_host` di JSON), adalah host tempat halaman itu sebenarnya
  diambil setelah pengalihan-pengalihannya; kolom ini kosong untuk artikel yang disimpan sebelum informasi itu dicatat.
- **Graf sitasi** — domain eksternal mana yang dikutip artikel-artikel tersimpan Anda, hanya hitungan,
  tanpa kredibilitas yang disimpulkan — diekspor sebagai GraphML (`/api/links/export.graphml`) untuk
  Gephi/yEd/NetworkX, atau JSON.

## Log jalannya penjadwal dan ekspor ke folder lokal (Kumpulkan)

Setiap kali penjadwal berjalan — berhasil atau gagal — satu baris ditambahkan ke log jalan lokal yang dapat diaudit
(`scheduler_runs.jsonl`), sehingga korpus dapat menjawab "apa yang berjalan selama saya pergi?". Secara opsional,
setel jalur **Ekspor ke folder lokal** di kartu penjadwal Kumpulkan: setiap kali berjalan, penjadwal lalu menulis
delta artikel baru sebagai berkas JSON-amplop ke folder lokal itu agar dapat dipantau oleh alur kerja Anda
sendiri. Kosong = nonaktif (bawaan); tidak ada yang baru = tidak ada berkas.

## Kandidat temuan (Sumber)

Aplikasi kini menyarankan sumber dengan sendirinya — **hanya luring**: domain yang berulang kali dikutip
artikel-artikel tersimpan Anda, dan media dari katalog bawaan untuk negara-negara yang liputannya masih tipis di korpus Anda.
Saran-saran itu ditampung, tidak pernah langsung dijalankan: masing-masing membawa buktinya di panel **Kandidat
temuan** (Pengaturan → Lanjutan → Sumber), setiap jalannya dibatasi oleh anggaran penemuan penjadwal dan
dicatat di log jalan, dan sebuah kartu Beranda memberi tahu Anda ketika ada kandidat yang menunggu tinjauan.
**Terima** membuat sumber yang *nonaktif* yang masih harus Anda aktifkan; **Abaikan** diingat
dan tidak pernah disarankan lagi. Pencarian topik berbasis DuckDuckGo tetap terpisah, **nonaktif
secara bawaan**, dan dikunci di balik Pengaturan → Lanjutan → Keamanan (lihat di bawah).

## Penemuan topik eksternal bersifat opt-in (Pengaturan → Lanjutan → Keamanan)

*Penemuan topik* adalah satu-satunya fitur yang **mengirim kueri pencarian teks bebas ke mesin
pencari**: fitur ini mengirim kueri topik Anda ke DuckDuckGo. (Tindakan daring lainnya — pengumpulan,
pengambilan pasar/statistik, penarikan model Ollama, OpenTimestamps — masing-masing juga meminta persetujuan dan disebutkan namanya;
yang ini adalah satu-satunya yang mengirimkan kueri yang Anda ketik.) Fitur ini **nonaktif secara bawaan** dan
menolak dengan pesan
yang jujur sampai Anda mengaktifkan **Pengaturan → Lanjutan → Keamanan → Penemuan topik eksternal** ("Kueri Anda
akan meninggalkan mesin ini"). Penemuan umpan RSS untuk sumber yang Anda tambahkan sendiri tetap berada di
jalur pengambilan etis lokal dan tidak terpengaruh.

## Bahasa

Antarmuka kini hadir dengan **terjemahan lengkap dalam 12 bahasa** (English, العربية, বাংলা,
Deutsch, Español, Français, हिन्दी, Bahasa Indonesia, 日本語, Português, Русский, 中文),
termasuk tata letak kanan-ke-kiri untuk bahasa Arab. Pilih bahasa Anda dari pemilih bahasa; terjemahannya
adalah draf pertama hasil mesin — koreksi adalah kontribusi yang disambut baik
(lihat `docs/ARCHITECTURE.md` → Internationalisation).
