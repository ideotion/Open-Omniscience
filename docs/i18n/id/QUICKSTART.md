<!-- id: AI-drafted translation of docs/QUICKSTART.md (2026-11-13, R677), not yet reviewed by a native speaker; the English original is authoritative. Coverage: the whole document, 17 of 17 headings. Improve it with a pull request; corrections by native speakers are welcome. -->

# Mulai cepat — menjalankan aplikasi

Inilah **inti yang dapat dipercaya** (aplikasi ini masih **alfa** dan jujur mengakuinya — `v0.5.0`, siklus
`0.5` meja-penyelidik, diberi tag pada 2026-10-26; aplikasi yang sedang berjalan menampilkan versi
persisnya): tambahkan sumber → kumpulkan secara etis → simpan beserta asal-usulnya →
pencarian teks lengkap Boolean → ekspor. Lokal lebih dulu, hanya loopback, tanpa akun.

---

## 0. Cara mudah — satu perintah, lalu klik dua kali untuk menjalankan

Jika Anda hanya ingin memakai aplikasinya (setelah itu tidak perlu pengetahuan baris perintah):

**Linux / macOS** — di terminal:

```bash
curl -fsSL https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/scripts/bootstrap.sh | bash
```

**Windows 11** — di PowerShell. Unduh dulu, *baru* jalankan:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1
```

Windows Defender mungkin tetap mengarantina berkas itu — berkas tersebut tidak ditandatangani dan masih baru. Itu
positif palsu; [§C](#c-di-windows-11-powershell) menjelaskan persis alasannya, dan memberi Anda
jalur tanpa skrip yang tidak bisa dihapus apa pun.

Dukungan Windows lebih sempit daripada Linux, dan perbedaannya dinyatakan terus terang di
[§C](#c-di-windows-11-powershell) — bacalah sebelum mengandalkannya.

> **Periksa sebelum Anda percaya.** Menyalurkan skrip ke shell berarti menjalankan kode di
> mesin Anda. Keduanya sengaja dibuat kecil — silakan baca dulu jika mau
> ([scripts/bootstrap.sh](../scripts/bootstrap.sh), [install.ps1](../install.ps1)).
> Keduanya memeriksa git + Python 3.13, mengkloning repositori ini ke `~/open-omniscience`
> (`%USERPROFILE%\Open-Omniscience` di Windows), lalu menyerahkan proses ke
> penginstal di dalam repositori. Anda juga bisa mengkloning sendiri lalu menjalankan `./install.sh` / `install.ps1`.

`install.sh` **tanpa pertanyaan** — **tidak ada menu komponen**. Satu perintah memasang
kumpulan bawaan yang masuk akal:

| Terpasang secara bawaan | Yang Anda dapatkan |
|----------------------|--------------|
| **Inti (Core)** *(selalu)* | pengumpulan · penyimpanan beserta asal-usul · pencarian Boolean · ekspor |
| **Analisis** | kata kunci · perbandingan pembingkaian · sentimen |
| **Kompresi (Compression)** | penyimpanan korpus di disk yang lebih cepat |

Penyiapan LLM lokal / Ollama **bukan** bagian dari penginstal — semuanya ada di
tab **Pengaturan → AI** di dalam aplikasi (lihat §E). Ubah kumpulan yang dipasang dengan variabel lingkungan
`OO_COMPONENTS="…"` (mis. `OO_COMPONENTS="analysis,nlp"`); menjalankan ulang
`./install.sh` bersifat idempoten dan hanya memasang yang belum ada.

**Lalu aplikasi berjalan otomatis.** Penginstal membuat peluncur **Open Omniscience** (menu
aplikasi + Desktop) dan membuka aplikasi di peramban Anda. Untuk menjalankannya lagi nanti:

- buka menu aplikasi Anda dan cari **Open Omniscience**, **atau**
- klik dua kali ikon **Open Omniscience** di **Desktop** Anda.

Sebuah jendela terminal kecil muncul, aplikasi berjalan, dan peramban Anda terbuka di
**http://127.0.0.1:8000**. **Tutup jendela itu (atau gunakan tombol daya / matikan di bilah atas)
untuk menghentikan aplikasi.** (Di macOS peluncurnya adalah `Open Omniscience.command` di
Desktop Anda; di Windows berupa pintasan Desktop + menu Start yang dibuat oleh `install.ps1`.)

**Peluncuran pertama.** Pada instalasi baru, aplikasi memandu Anda melalui penyiapan singkat satu kali
*sebelum* antarmuka utama: **pilih bahasa → baca dan setujui ketentuan hukum**
(menolak berarti aplikasi **dihapus**, melalui konfirmasi yang diketik) **→ buat frasa sandi
korpus Anda**. Korpus **dienkripsi saat disimpan secara bawaan** (SQLCipher 4) dan
**tidak ada pemulihan** untuk frasa sandi yang hilang (frasa sandi yang hilang berarti waktu pengumpulan ulang — korpus
dibangun kembali dari web). Aplikasi kemudian dimulai dalam keadaan **luring (mode pesawat)**;
beralih ke daring melewati **satu jendela persetujuan** yang menyebutkan tindakannya dan menampilkan IP
antarmuka lokal Anda sebelum permintaan apa pun dikirim.

Lebih suka terminal? `cd ~/open-omniscience && ./scripts/launch.sh` melakukan hal yang sama.

**Memeriksa atau menghapusnya nanti:**
```bash
./install.sh --check        # health report: Python, data dir, database, LLM, launcher
#   (same as: open-omniscience doctor)
./install.sh --uninstall    # remove the virtualenv + launcher; your data is kept
                            #   (it asks separately, defaulting to NO, before deleting data)
```

---

## A. Di AppVM Debian Qubes OS (target utama)

Qubes mengatur ulang sistem berkas root AppVM setiap kali dinyalakan; hanya `/home` (serta
`/usr/local`, `/rw`) yang bertahan. Jadi paket sistem dipasang di **TemplateVM**, sedangkan
aplikasi + virtualenv + basis data berada di bawah `/home` di **AppVM**.

**1. Di TemplateVM (sekali saja):**
```bash
sudo ./install.sh --template      # installs python3.13, venv, git, sqlite3, ...
```
Matikan TemplateVM, lalu **nyalakan ulang AppVM** agar paket-paketnya terlihat.

**2. Di AppVM (sebagai pengguna Anda, tanpa sudo):**
```bash
./install.sh                      # promptless: Core + Analysis + Compression, then auto-launches
# Qubes AppVM (unattended, creates the launcher, no prompts): Core + Analysis + Compression
./install.sh --appvm
```

**3. Jalankan (hanya terikat ke 127.0.0.1):**
Klik dua kali peluncur **Open Omniscience** (menu aplikasi / Desktop), atau:
```bash
cd ~/open-omniscience && ./scripts/launch.sh    # starts the app + opens the browser
```
Buka **http://127.0.0.1:8000** di peramban AppVM.

Server tidak pernah mendengarkan di luar loopback. Agar sepenuhnya luring setelah sebuah proses berjalan, lepaskan
NetVM dari AppVM — antarmuka tidak bergantung pada apa pun di luar dan tetap berfungsi dengan data yang tersimpan.

---

## B. Menjalankan untuk pengembangan lokal (Linux apa pun dengan Python 3.13)

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q                          # full test suite
open-omniscience                   # serve at http://127.0.0.1:8000
```

Variabel lingkungan yang berguna: `OO_DATA_DIR` (lokasi DB SQLite + data), `OO_HOST`/`OO_PORT`,
`OO_FETCH_MIN_INTERVAL` (jeda kesopanan per host, dalam detik).

### Di Tails

Debian/Ubuntu/Tails menyertakan `venv`/`ensurepip` dari pustaka standar dalam **paket apt terpisah**, sehingga
`python3 -m venv` gagal sampai paket itu dipasang. `install.sh` kini memasangnya
**secara otomatis** — di Tails hal itu membutuhkan **kata sandi administrasi** (atur di
Layar Sambutan (Welcome Screen); secara bawaan nonaktif) dan **koneksi Tor** yang berfungsi (apt mengunduh melalui
Tor). Nonaktifkan dengan `OO_NO_APT=1` jika Anda lebih suka menjalankan apt sendiri.

Dua catatan jujur khusus untuk Tails:

- **Versi Python.** Tails adalah Debian 12 → **Python 3.11**, sedangkan aplikasi ini menargetkan **3.13**.
  Anda harus menyediakan interpreter 3.13 dan mengarahkan penginstal ke sana
  (`OO_PYTHON=python3.13 ./install.sh`); 3.13 dan paket `python3.13-venv`-nya **tidak**
  ada di repositori bawaan Tails.
- **Amnesia.** Apa pun yang dipasang lewat apt — dan seluruh `.venv` — **hilang saat dinyalakan ulang** kecuali
  disimpan di Penyimpanan Persisten (Persistent Storage): tambahkan paket venv melalui **Penyimpanan Persisten → Perangkat Lunak
  Tambahan (Persistent Storage → Additional Software)**, dan simpan salinan repositori + `OO_DATA_DIR` di volume persisten.

### Meningkatkan basis data yang sudah ada

Instalasi baru membangun skema secara otomatis (`init_db()`), dan basis data
diberi cap pada garis dasar migrasi saat ini. Jika rilis mendatang mengubah
skema, tingkatkan basis data yang sudah ada dengan:
```bash
alembic upgrade head
```
`alembic check` melaporkan apakah model dan migrasi sudah selaras (CI menjaga hal ini).

---

## C. Di Windows 11 (PowerShell)

**Status dukungan yang jujur — baca ini dulu.** Setiap proses CI membuktikan tiga hal di
`windows-latest`: pemasangan dependensi, **pemeriksaan boot** (seluruh aplikasi dapat diimpor),
dan **enkripsi SQLCipher saat disimpan** — yang terakhir pada jalur yang *memblokir*, sehingga
enkripsinya bukan tebakan. Tidak ada yang terbukti di luar itu. **Jalur pytest
Windows macet** (proses terbaru yang selesai tertahan di `pytest` selama 3h21m dan ~6h, dibandingkan 18 menit
di macOS), dan **belum ada yang mengeklik seluruh antarmuka di Windows**. Jadi: harapkan pemasangan
dan peluncuran berhasil, anggap segala sesuatu setelah boot belum terverifikasi, dan mohon laporkan apa yang
rusak. Linux tetap menjadi gerbang rilis.

### 1. Instalasi

Buka **PowerShell** (tidak perlu hak administrator kecuali Python sendiri harus
dipasang). Unduh penginstal, baca dulu jika mau, lalu jalankan:

```powershell
irm https://raw.githubusercontent.com/ideotion/Open-Omniscience/HEAD/install.ps1 -OutFile $env:TEMP\oo-install.ps1
notepad $env:TEMP\oo-install.ps1                                     # optional: see what you are about to run
powershell -NoProfile -ExecutionPolicy Bypass -File $env:TEMP\oo-install.ps1 -Extras analysis
```

Penginstal memasang Git dan Python 3.13 melalui `winget` hanya jika keduanya belum ada, mengkloning ke
`%USERPROFILE%\Open-Omniscience`, membangun `.venv`, dan memverifikasi hasilnya dengan
mengimpor aplikasi yang sebenarnya. Hapus flag `-Extras` untuk kumpulan bawaan yang lebih lengkap, atau lihat
[Opsi penginstal](#opsi-penginstal).

Sudah mengkloning? Jalankan di tempat — penginstal mendeteksi salinan repositorinya sendiri dan melewati kloning:

```powershell
powershell -ExecutionPolicy Bypass -File .\install.ps1
```

> **Mengapa tidak satu baris `irm … | iex` saja?** Karena mengambil kode jarak jauh lalu menjalankannya
> langsung dari memori adalah cara paling umum malware Windows dikirimkan, sehingga
> Defender menilai bentuk itu sebagai berbahaya apa pun isi skripnya. Menyimpan berkasnya
> lebih dulu lebih kecil kemungkinannya diblokir sekaligus lebih jujur — Anda bisa membacanya
> sebelum dijalankan.

### 2. Jika Windows Defender mengarantina penginstal

Defender mungkin langsung menghapus `install.ps1`. Itu **positif palsu**, dan Anda tidak perlu
sekadar memercayai kata-kata kami — inilah tepatnya mengapa hal itu terjadi, agar Anda bisa menilai sendiri:

- Berkas ini **tidak ditandatangani dan masih baru**, sehingga reputasi cloud Defender belum pernah melihatnya.
  Tidak dikenal + tidak ditandatangani saja sudah cukup untuk memicu heuristik pembelajaran mesin; nama
  deteksinya biasanya berakhiran `!ml`.
- **Bentuknya** seperti penginstal: memanggil pengelola paket, membaca ulang `PATH` dari
  registri, menulis pintasan menu Start, dan jalur `-Uninstall`-nya menghapus
  direktori. Program dropper melakukan hal-hal yang sama. Pengklasifikasi menilai bentuk, bukan niat.

Apa yang *tidak* dikandungnya, dan dapat Anda periksa sendiri dalam ~500 baris yang mudah dibaca: tidak ada
`Invoke-Expression`, tidak ada muatan yang dienkode atau dikaburkan, tidak ada `WebClient`, tidak ada jendela
tersembunyi, dan tidak ada unduhan selain dari repositori ini.

Tiga jalan keluar, dari yang terbaik:

1. **Gunakan jalur tanpa skrip** — [Instalasi manual](#instalasi-manual-tanpa-skrip) di bawah.
   Perintahnya sama dengan yang dijalankan penginstal, tanpa berkas yang bisa dikarantina. Cara ini selalu berhasil.
2. **Laporkan positif palsu itu** ke Microsoft di
   <https://www.microsoft.com/en-us/wdsi/filesubmission> (pilih *Pengembang perangkat lunak (Software developer)*).
   Biasanya selesai dalam satu atau dua hari dan memperbaikinya untuk semua orang yang memasang
   setelah Anda — bukan hanya untuk Anda.
3. **Kecualikan foldernya** (Keamanan Windows → Perlindungan virus & ancaman → Kelola
   pengaturan → Pengecualian (Windows Security → Virus & threat protection → Manage settings → Exclusions)). Pahami konsekuensinya sebelum melakukannya: pengecualian membuat
   Defender berhenti memindai folder itu *sepenuhnya*, untuk apa pun, tanpa batas waktu — bukan hanya
   untuk satu berkas ini. Mesin Anda, keputusan Anda; kami tidak akan berpura-pura ini tanpa risiko.

Perbaikan yang jujur dari pihak kami adalah penandatanganan kode, yang belum kami miliki.

### 3. Menjalankannya

Penginstal membuat pintasan **Open Omniscience** di **Desktop** dan di
**menu Start**. Klik dua kali: sebuah jendela terminal muncul, dan peramban Anda terbuka di
**http://127.0.0.1:8000** begitu aplikasi benar-benar merespons. Tutup jendela itu (atau gunakan
tombol daya aplikasi) untuk menghentikannya.

Atau dari terminal: `scripts\launch.cmd`.

### 4. Peluncuran pertama

Alur satu kali yang sama seperti di semua platform: **pilih bahasa → baca dan setujui
ketentuan hukum → buat frasa sandi korpus Anda**. Korpus **dienkripsi saat disimpan secara
bawaan** dan **tidak ada pemulihan** untuk frasa sandi yang hilang. Aplikasi kemudian dimulai dalam keadaan
**luring (mode pesawat)**; beralih ke daring melewati **satu jendela persetujuan**.

### Opsi penginstal

| Flag | Fungsinya |
|------|--------------|
| *(tidak ada)* | Inti + `analysis,compression,columnar`, lalu verifikasi dan buat peluncur |
| `-Path <dir>` | Pasang di lokasi selain `%USERPROFILE%\Open-Omniscience` |
| `-Extras "analysis"` | Pilih extras pip (`""` hanya untuk inti) |
| `-Ref <branch>` | Kloning branch atau tag tertentu |
| `-NoPython` | Jangan pernah memasang Git/Python secara otomatis; gagal disertai petunjuk |
| `-NoLauncher` | Lewati pintasan Desktop / menu Start |
| `-Check` | Laporan kesehatan (sama dengan `open-omniscience doctor`) |
| `-Uninstall` | Hapus `.venv` + peluncur; data tetap disimpan kecuali dikonfirmasi secara terpisah |
| `-Yes` | Anggap jawaban "ya" pada setiap pertanyaan (tanpa pengawasan) |

Hanya `analysis` yang dibuktikan oleh CI di Windows. Jika kumpulan bawaan yang lebih lengkap gagal
dipasang, skrip **kembali ke `analysis` dan memberitahukannya** alih-alih gagal
diam-diam atau berpura-pura extras-nya sudah terpasang.

### Instalasi manual (tanpa skrip)

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

### Catatan khusus Windows

- **Kebijakan eksekusi.** Kebijakan bawaan memblokir `.\.venv\Scripts\Activate.ps1`.
  Tidak ada langkah di sini yang membutuhkannya: panggil `.venv\Scripts\python.exe` lewat path-nya dan seluruh masalah
  hilang. `-ExecutionPolicy Bypass` di baris perintah sudah mencakup penginstal itu sendiri.
- **`python` yang membuka Microsoft Store.** Windows 11 yang baru menyertakan
  stub alias eksekusi bernama `python.exe` yang membuka Store alih-alih menjalankan
  kode. Penginstal mengabaikannya (stub tidak mencetak versi) dan menggunakan peluncur `py -3.13`.
  Jika Anda memasang secara manual, utamakan `py -3.13` daripada `python`.
- **Lokasi data Anda.** Karena ini adalah salinan kode sumber, korpus, kunci
  penandatanganan, dan pengaturan disimpan di **`<repo>\data`** — bukan `%APPDATA%`. Atur `OO_DATA_DIR` untuk menaruhnya
  di drive lain.
- **Izin folder.** Di Linux, direktori data dikunci hanya untuk pengguna Anda
  (`chmod 0700`); panggilan itu tidak berpengaruh di Windows, sehingga folder mewarisi ACL
  Windows biasa. Di PC bersama, batasi akses ke `<repo>\data` sendiri. Basis data korpus
  itu sendiri tetap dienkripsi saat disimpan dalam kedua kasus.
- **SmartScreen / Defender.** Tidak ada yang ditandatangani kodenya di sini, jadi Windows menganggap semuanya
  tidak dikenal: SmartScreen mungkin memberi peringatan pada peluncur, dan Defender mungkin langsung mengarantina
  `install.ps1` — lihat
  [§2](#2-jika-windows-defender-mengarantina-penginstal) untuk mengetahui apa itu dan apa yang harus
  dilakukan. Pemindaian waktu nyata juga memperlambat `pip install` pertama secara nyata.
- **Port.** Atur `OO_PORT` sebelum menjalankan untuk berpindah dari 8000; `scripts\launch.cmd`
  menghormatinya.
- **Arsitektur (x64 / ARM64 / 32-bit).** Dideteksi dan ditangani oleh penginstal; berikut
  apa yang diputuskannya. Yang menentukan berhasil tidaknya `pip install` bukanlah
  mesinnya, melainkan wheel mana yang tersedia untuk platform *interpreter*. Diukur terhadap
  PyPI pada 2026-08-23, untuk CPython 3.13, mencakup seluruh dependensi proyek ini:

  | interpreter | wheel |
  |---|---|
  | `win-amd64` | **setiap dependensi.** Satu-satunya arsitektur yang lengkap. |
  | `win-arm64` | semua kecuali tiga — `cryptography` (inti), `httptools` (inti, melalui `uvicorn[standard]`) dan `statsmodels` (`analysis`) |
  | `win32` | `cryptography` sama sekali tidak menerbitkannya |

  Windows on ARM menjalankan biner x64 secara transparan, sehingga **interpreter x64 adalah jawaban
  yang tepat di ARM64 juga** — bukan kompromi, melainkan kumpulan yang lengkap. Karena itu `install.ps1`
  mengutamakan `win-amd64` di mana pun dan akan mendapatkannya jika mesin belum memilikinya:
  winget dengan arsitektur disebutkan, lalu winget dalam lingkup pengguna, lalu CPython x64 mandiri
  dari Python Software Foundation di nuget.org — diverifikasi terhadap
  SHA-512 yang dijamin nuget untuknya, dibongkar ke
  `%LOCALAPPDATA%\Open-Omniscience\python-x64`, tanpa perlu hak elevasi, tanpa perubahan PATH
  dan tanpa entri registri. Lokasinya sengaja **di luar** salinan repositori: ini adalah sumber daya
  mesin, sehingga tetap ada saat folder aplikasi dihapus (jika tidak, `.venv` yang dibangun di atasnya
  akan rusak) dan salinan `-Path` kedua memakainya kembali. `-Uninstall` menghapusnya. Hash yang tidak cocok, atau
  versi yang tidak memiliki hash yang dijamin nuget, akan **ditolak**.

  Jika semua tahapan gagal, Anda mendapat penghentian disertai perbaikan berupa satu unduhan, bukan build
  Rust dua puluh menit yang berakhir dengan `linker link.exe not found`.

  `.venv` yang sudah ada **diperiksa, bukan sekadar ditemukan**: ia mempertahankan versi dan platform wheel
  dari interpreter mana pun yang membangunnya, sehingga lingkungan yang tertinggal dari proses sebelumnya dengan
  Python berbeda diganti alih-alih dipakai ulang — jika tidak, semua langkah di atas
  diam-diam dibatalkan pada langkah terakhir. Lingkungan yang cocok dipakai ulang tanpa diubah. Menjalankan ulang
  penginstal karenanya adalah perbaikan untuk instalasi yang setengah jadi; tidak ada yang perlu dihapus
  secara manual.

  - **Mengapa instalasi ARM64 native tidak diaktifkan otomatis.** Instalasi itu memerlukan `cryptography`
    yang dipatok ke 46.0.0–46.0.3, satu-satunya seri dengan wheel ARM64. Rilis tersebut memiliki
    **13 catatan advisori yang masih terbuka** (termasuk satu terkait OpenSSL yang ditautkan secara statis, diperbaiki di
    48.0.1). Aplikasi ini menandatangani bukti; memasangnya diam-diam akan menjadi teater
    keamanan. Jika mesin Anda benar-benar memiliki Visual Studio Build Tools **dan** toolchain
    Rust, `-AllowSourceBuilds` mengompilasi ketiganya secara native — pilihan eksplisit,
    tidak pernah bawaan.
  - **Windows 32-bit tidak didukung**, dan itu batasan nyata, bukan sekadar pagar:
    `cryptography` tidak menyediakan wheel `win32`. Windows 64-bit wajib.

---

## D. Alur menyeluruh (antarmuka atau API)

> **Sumber sudah dikonfigurasi sebelumnya.** Pada peluncuran pertama (atau saat `install.sh --appvm`)
> katalog-katalog kurasi (`configs/sources.yml` ~3.200 media kepentingan publik, ditambah
> katalog pasar, spektrum politik, dan hukum/KI — **~3.395 domain unik secara
> keseluruhan**) diisikan secara otomatis — sehingga Anda bisa langsung mulai mengumpulkan.
> (Angka-angka ini **bergeser** seiring katalog bertambah; angka yang berlaku adalah apa pun yang
> saat ini dimuat `configs/*.yml`.) Pengisian ulang bersifat idempoten. Nonaktifkan pengisian otomatis dengan
> `OO_AUTOSEED=0`; isi ulang secara manual dengan `python scripts/seed_sources.py` atau
> `POST /api/sources/seed-defaults`. URL feed/kebijakan robots berubah seiring waktu;
> pengambil etis menolak apa pun yang tidak dapat dikonfirmasinya, jadi pangkas/perluas daftar sesuai
> kebutuhan penyelidikan Anda.

**Di antarmuka:** **beralih ke daring** satu kali (tombol mode pesawat → satu jendela persetujuan) dan
**pengumpulan berjalan sendiri** di latar belakang — terstratifikasi di seluruh bahasa dan tag
sumber, menghormati robots, dan dibatasi lajunya. Lalu **cari di Jelajahi** (tab di bilah samping; menekan Enter di
omnibar, bilah atas atau Ctrl/⌘-K, membuka Jelajahi di tab browser baru) — analisis artikel yang cocok muncul di bawah
hasil, tempat Anda menyaring, membaca, menjalankan kueri Boolean, dan **mengekspor** (CSV/JSON, lampiran
metode, bukti bertanda tangan). Anda tetap bisa menambahkan sumber dan *Menelan (Ingest)* satu feed atau URL
secara manual dari **Pengaturan → Lanjutan → Pengumpulan / Sumber**.

**Melalui API:**
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

Skema API yang dapat dibaca mesin ada di **http://127.0.0.1:8000/openapi.json**. Halaman Swagger interaktif nonaktif secara bawaan (halaman itu memuat aset dari host pihak ketiga); pengembang dapat menjalankan aplikasi dengan `OO_API_DOCS=1` untuk mendapatkannya di `/docs`.

---

## E. Kemampuan analisis

Semuanya lokal lebih dulu dan menurun kemampuannya secara terang-terangan (tidak pernah mengarang). Skema lengkap ada di `/openapi.json`.

**LLM lokal (Ollama).** Siapkan dari **Pengaturan → AI**: penginstal Ollama di dalam aplikasi
yang **diverifikasi dengan checksum** (Linux) ditambah **antrean unduhan model** (kemajuan
byte yang nyata, bisa dibatalkan), pemilih model aktif, dan panel prompt yang dapat diedit. Atau pasang
Ollama sendiri dari **ollama.com** lalu `ollama pull llama3.2:3b`. Unduhan model keluar
melalui **clearnet lewat proses Ollama** (bukan jalur Tor aplikasi) — hal ini diungkapkan saat
persetujuan. Penanda LLM di bilah atas menampilkan status langsung (klik untuk membuka Pengaturan → AI); setiap
hasil pencarian memiliki tombol **Ringkas** dan **Terjemahkan**. API:
```bash
curl http://127.0.0.1:8000/api/llm/health          # {available, installed_models}
curl -X POST http://127.0.0.1:8000/api/llm/articles/1/summarize -d '{}'  # persisted with provenance
```
Jika Ollama tidak berjalan, perintah-perintah ini mengembalikan HTTP 503 dengan pesan yang jelas — bukan ringkasan palsu.

**Harga komoditas + korelasi yang jujur.**
```bash
curl -X POST http://127.0.0.1:8000/api/commodities/Nd/prices -H 'Content-Type: application/json' \
  -d '{"points":[{"observed_on":"2026-01-01","price":100,"unit":"kg"}]}'
curl 'http://127.0.0.1:8000/api/commodities/Nd/correlation?query=neodymium'
```
Korelasi mengembalikan koefisien nyata + nilai p + n dari scipy (Pearson/Spearman),
dengan catatan "korelasi ≠ kausalitas"; tumpang tindih yang terlalu sedikit → `insufficient_data`.

**Pemantauan.** `POST /api/monitoring/health` melakukan pemeriksaan keterjangkauan yang nyata
(melalui pengambil etis); `GET /api/monitoring/anomalies` menandai
lonjakan volume artikel berdasarkan skor-z. **Email:** `POST /api/sources/{id}/ingest-email`
(IMAP) memasukkan pesan ke korpus yang sama yang dapat dicari.

**Verifikasi metadata gambar.** `POST /api/verify/image-metadata`
(unggah gambar) mengembalikan format, dimensi, EXIF, dan GPS-nya disertai pengamatan
faktual sederhana (mis. ada tag perangkat lunak penyuntingan, tidak ada stempel waktu pengambilan). Cakupannya dinyatakan
secara jujur sebagai *pemeriksaan metadata* — **bukan** deteksi deepfake/manipulasi (fitur itu
dikarang-karang dan telah dikarantina dari kode kerja; lihat
[docs/QUARANTINE_ARCHIVE.md](QUARANTINE_ARCHIVE.md)).

**Paket bukti bertanda tangan.** Tombol **Ekspor bukti bertanda tangan** di jendela
analisis (atau `POST /api/reports/evidence`) menghasilkan paket berakar Merkle yang
ditandatangani Ed25519. Siapa pun dapat memverifikasinya secara luring, tanpa aplikasi ini:
```bash
python scripts/verify_evidence.py evidence-bundle.json   # exit 0 = verified
```

**Rantai pengawasan.** Panel antarmuka **Rantai pengawasan** melacak asal-usul yang ditandatangani dan
tahan-rusak (tamper-evident), serta memungkinkan Anda mengubah perilakunya saat aplikasi berjalan:
tanda tangan pascakuantum, mode penjangkaran (`local` luring vs **OpenTimestamps** yang
dijangkarkan ke Bitcoin), dan pencatatan otomatis saat pengumpulan. Sakelar-sakelar ini adalah *preferensi* — panel
menampilkan keadaan yang **efektif**, sehingga tidak ada yang mengaku aktif padahal komponen tambahannya
belum terpasang. API:
```bash
curl http://127.0.0.1:8000/api/custody/settings                       # effective state
curl -X PUT http://127.0.0.1:8000/api/custody/settings \
  -H 'Content-Type: application/json' -d '{"pqc_enabled": true}'
curl -X POST http://127.0.0.1:8000/api/custody/log -H 'Content-Type: application/json' \
  -d '{"item_id":"article:1","item_hash":"<sha256>","action":"ingest"}'
curl 'http://127.0.0.1:8000/api/custody/export' > custody-bundle.json  # offline-verifiable
python scripts/verify_custody.py custody-bundle.json                   # exit 0 = verified
```
Model lengkap, model ancaman, dan catatan privasi: [USER_MANUAL.md](USER_MANUAL.md).

---

## Apa yang dijamin oleh "pengumpulan etis"

- robots.txt diambil, disimpan dalam cache per host, dan **gagal-tertutup**: jika tidak dapat
  dikonfirmasi (galat jaringan, batas waktu habis, 5xx, atau 401/403 yang dibatasi), URL tersebut
  **tidak** diambil.
- Jeda minimum per host diberlakukan (menghormati `Crawl-delay`).
- Satu jalur pengambilan, User-Agent yang mengidentifikasi diri, hanya HTML untuk artikel — tanpa jalan pintas mentah.
- Ekstraksi menggunakan trafilatura; jika tidak ditemukan isi artikel yang sebenarnya, tidak ada yang disimpan
  (tidak ada baris karangan "No Title / No Content").
- Setiap artikel yang disimpan membawa asal-usulnya: sumber, URL asli, URL kanonis,
  hash konten (dipakai untuk deduplikasi), waktu pengambilan.
