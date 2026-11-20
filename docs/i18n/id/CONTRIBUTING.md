<!-- id: Translation of docs/CONTRIBUTING.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 15 of 15 headings. Corrections are welcome as a pull request. -->

# Berkontribusi

Terima kasih telah membantu. Prinsip panduannya adalah **kejujuran**: sebuah fitur harus
melakukan apa yang diklaimnya, atau fitur itu tidak dirilis. Tidak ada keluaran yang dibuat-buat,
tidak ada skor keyakinan palsu, tidak ada penurunan kualitas diam-diam — lihat
[DESIGN.md](DESIGN.md) §3.

## Penyiapan

```bash
python3.13 -m venv .venv && . .venv/bin/activate
pip install -e ".[analysis,dev]"
pytest -q          # full suite, a few minutes
```

`pyproject.toml` tetap menjadi satu-satunya sumber kebenaran untuk dependensi (kami memasang versi
terbaru dalam batas minimum agar CI menangkap kerusakan dari upstream sejak dini). Untuk
**pemasangan yang dapat direproduksi / pemasangan rilis** tersedia lock yang dipatok dengan hash
yang diturunkan darinya:

```bash
pip install -r requirements.lock          # exact, hash-verified core + analysis pins
# regenerate after a dependency change:
pip-compile --generate-hashes --extra analysis -o requirements.lock pyproject.toml
```

**Ini sudah terpasang di `./install.sh`, bukan sekadar perintah yang Anda jalankan secara
manual.** Jalur pemasangan daring (`pip_install()`) memakai `requirements.lock` secara otomatis
setiap kali file itu ada, dibuat untuk Python yang sedang Anda jalankan, dan mencakup setiap
komponen yang Anda minta (`OO_COMPONENTS`) — diperiksa terhadap header `pip-compile ... --extra=...`
milik lock itu sendiri, tidak pernah dipelihara secara manual. Bila salah satu syarat itu tidak
terpenuhi (lock sudah usang untuk Python Anda, meminta komponen yang tidak disertakan saat lock
dibuat, atau sebuah patokan gagal diselesaikan untuk platform ini), jalur ini kembali ke resolusi
biasa berbasis batas minimum `pip install -e ".[...]"`, dengan pesan yang jelas terlihat
menjelaskan mengapa jalur yang diaudit tidak dipakai — `OO_USE_LOCK=0` menonaktifkan lock tanpa
syarat. **Sebagaimana dirilis, lock hanya mencakup `--extra analysis`**, sedangkan himpunan
komponen bawaan `install.sh` sendiri adalah `analysis,compression,columnar` — sehingga
menjalankan `./install.sh` secara bawaan tanpa pengawasan saat ini kembali ke resolusi berbasis
batas minimum (compression/columnar tidak termasuk cakupan lock). Jalankan
`OO_COMPONENTS=analysis ./install.sh` untuk menjalankan jalur yang diaudit sebagaimana adanya,
atau perluas cakupan lock dengan `pip-compile --extra analysis --extra compression --extra
columnar ...` agar jalur pemasangan bawaan juga berbasis lock.

**Bundel luring/terisolasi dari jaringan** (`scripts/build_offline_bundle.sh`, dipakai oleh jalur
luring `--no-index` milik `install.sh` untuk target Qubes/Tails) **belum terhubung ke lock** —
bundel itu masih menyelesaikan dependensi dari awal berdasarkan batas minimum `pyproject.toml`
setiap kali dibangun. Itu adalah celah yang diketahui dan masih terbuka, bukan kelalaian: membuat
bundel luring juga berbasis lock (`pip download --require-hashes -r requirements.lock`, dengan
resolusi berbasis `$SPEC` dipertahankan sebagai cadangan untuk extra apa pun yang tidak dicakup
lock) dicatat sebagai pekerjaan lanjutan.

## Alur kerja

- **Python 3.13**, satu `pyproject.toml` (tanpa requirements.txt).
- Lint/format dengan **ruff**; pemeriksaan tipe dengan **mypy**: `make lint && make typecheck`.
- Setiap perubahan berakhir hijau: `make check` (ruff + pytest). Tambahkan tes perilaku untuk
  perilaku baru; perbaiki atau karantinakan — jangan tinggalkan kode yang setengah berfungsi di
  jalur impor.
- Lakukan commit dalam langkah kecil yang jujur, dengan pesan yang menyebutkan *apa dan mengapa*.
- Perubahan skema melalui Alembic (`alembic revision --autogenerate`); CI menjalankan
  `alembic check` untuk menangkap selisih antara model dan migrasi.

## Buku catatan rilis: satu file per baris

Jangan menambahkan baris ke `docs/ledger/shipped.csv`. Pemeriksaan merge GitHub mengabaikan aturan
`merge=union` file tersebut, sehingga satu baris yang ditambahkan oleh setiap PR membuat setiap PR
yang terbuka berkonflik setelah setiap merge. Tambahkan SATU file baru sebagai gantinya:

    python scripts/ledger_shipped.py new --date 2026-09-30 --area tests --item "..." \
        --status "shipped (draft)" --refs "PR #1240" --key-paths "src/a.py; tests/b.py" --summary "..."

Perintah itu menulis `docs/ledger/shipped.d/<date>-<slug>.csv` (header buku catatan ditambah satu
baris). Tidak ada PR lain yang dapat berkonflik dengan file yang tidak disentuhnya.
`python scripts/ledger_shipped.py check` memverifikasi setiap fragmen; catatan rilis dan tes
invarian repositori membaca `shipped.csv` terlebih dahulu lalu fragmen-fragmennya.
`ledger_shipped.py fold` menambahkan fragmen ke `shipped.csv` dalam mode biner lalu menghapusnya;
perintah ini untuk pengelola atau untuk sebuah rilis, tidak pernah untuk PR fitur. `refs` harus
berisi nomor PR yang sebenarnya, bukan `PR pending` (sebuah tes akan gagal karenanya).

## Pelajaran dan entri log rilis: masing-masing satu file

Konvensi yang sama berlaku untuk dua arsip besar. Sebuah pelajaran adalah SATU file,
`docs/ledger/lessons.d/<date>-<slug>.md` (`python scripts/lessons.py --new SLUG`); sebuah entri
log rilis kata demi kata adalah SATU file, `docs/ledger/shipped_log.d/<date>-<slug>.md`
(`python scripts/ledger_fold.py new-log SLUG`). Jangan pernah menambahkan ke `LESSONS.md` atau
`SHIPPED_LOG.md` dan jangan pernah mengubah `_LESSONS_LINE_CEILING`: setiap PR yang melakukannya
berkonflik dengan semua PR lain. Sebuah fragmen diawali dengan `## <date> — title`, diakhiri
dengan baris baru, dan berformat UTF-8 dengan akhir baris LF; sebuah pelajaran (bukan entri log
rilis) tidak memiliki judul kedua dan tetap di bawah 200 baris (ini membatasi ukuran satu entri);
`python scripts/ledger_fold.py check` (dan `tests/test_ledger_fragments.py`) memvalidasinya,
menolak penanda `#NNNN` dan `PR pending`, dan `lessons.py <words>` juga menelusuri
fragmen-fragmen itu. `ledger_fold.py fold` menggabungkannya ke dalam arsip saat rilis dan tidak
pernah untuk PR fitur.

## File lokal bahasa dan konflik merge

Ke-12 file `src/static/locales/*.json` dijaga tetap **terurut** (`_meta` lebih dulu, lalu kunci dalam urutan titik kode), sehingga dua PR yang menambahkan string menyisipkannya di tempat yang berbeda dan dapat di-merge dengan bersih. Setelah menambahkan string, jalankan `python scripts/locales_merge.py`; skrip itu mengurutkan file dan memeriksanya (`--check` hanya memverifikasi; `tests/test_locales_merge.py` gagal pada kunci yang tidak terurut atau duplikat).

Jika `git merge origin/main` meninggalkan penanda konflik di file lokal bahasa, jalankan skrip yang sama: skrip itu mempertahankan kedua sisi setiap hunk, mengurutkan, dan berhenti sambil menyebutkan kuncinya jika kedua sisi memberi satu kunci teks yang berbeda (kontradiksi sungguhan yang harus diputuskan). `docs/ledger/shipped.csv` bertanda `merge=union` di `.gitattributes`, yang dihormati oleh `git merge` lokal tetapi tidak oleh merge melalui web GitHub maupun tombol perbarui branch: lakukan merge main secara lokal, lalu periksa baris `(date, area, item)` yang duplikat.

## Standar

- Provenans di mana-mana: data yang disimpan membawa sumber + stempel waktu + hash.
- Setiap angka yang ditampilkan kepada pengguna harus berasal dari metode nyata dengan
  ketidakpastian yang dinyatakan (`src/analysis`), tidak pernah dari sebuah konstanta.
- Penyerapan data melalui satu-satunya fetcher etis (robots gagal-tertutup, dengan batas laju).
- Kode yang dibuat-buat/mati tempatnya di `quarantine/` (terdokumentasi), bukan di `src/`.

## Kode etik

Dengan berpartisipasi, Anda setuju untuk mematuhi [Kode Etik](CODE_OF_CONDUCT.md)
(Contributor Covenant 2.1). Laporkan kekhawatiran secara pribadi ke open-omniscience@ideotion.com.

## Lisensi

Kontribusi berada di bawah **GPL-3.0-or-later** (lihat [LICENSE](../LICENSE)).

---

# Kebijakan penomoran versi

Bagaimana proyek ini diberi nomor versi — dengan kematangan yang sengaja dinyatakan lebih rendah.

**Di bagian ini:**
- [Kebijakan penomoran versi](#kebijakan-penomoran-versi)


---

## Kebijakan penomoran versi

> **Kami sengaja menyatakan kematangan lebih rendah dari kenyataannya. Kejujuran di atas
> sensasi.** Lebih baik pengguna terkejut secara menyenangkan daripada disesatkan. Nomor versi
> adalah janji tentang *kematangan*, dan kami menjaga janji itu tetap konservatif.

### Satu-satunya sumber kebenaran

Versi berada di **satu tempat: `pyproject.toml` (`[project] version`)**. Semua hal lain
diturunkan darinya:

- Aplikasi yang berjalan membacanya dari metadata paket yang terpasang
  (`importlib.metadata.version("open-omniscience")`) — sehingga `/api/health`, `version=` milik
  API, dan antarmuka semuanya melaporkan versi terpasang yang *sebenarnya* secara otomatis.
- Tidak ada kode lain yang menuliskan literal versi secara tetap. Tes memeriksa terhadap metadata
  paket, bukan terhadap string (lihat `tests/test_api_search.py`).
- `README.md` di akar repositori menyatakan versi satu kali, di headernya, dan sebuah penjaga CI
  memastikan versi itu cocok dengan paket
  (`tests/test_repo_invariants.py::test_readme_version_matches_package`).

**Untuk menaikkan versi, ubah `pyproject.toml` saja**, perbarui header README agar sesuai
(penjaga menegakkan hal ini), lalu jalankan `pip install -e .` agar metadata diperbarui.

**Beri tag `vX.Y.Z` hanya pada commit yang `pyproject.toml`-nya sudah berisi `X.Y.Z`.** Workflow
rilis (`.github/workflows/release.yml`) menolak tag lain apa pun sebelum membangun apa pun,
sehingga tag yang dibuat sebelum kenaikan versinya menerbitkan rilis tanpa wheel, sdist, atau
checksum. `v0.4.0` yang pertama dibuat dengan cara itu pada 2026-09-28; versinya ditetapkan
sesudahnya dan tag dipindahkan ke sana (`docs/product/RELEASE_0.4_GATE.md` baris G).
**Memindahkan tag memerlukan git:** situs web GitHub tidak dapat menghapus maupun memindahkan
tag, dan rilis yang diterbitkan di sana memakai ulang tag yang ada tanpa memulai workflow. Tanpa
klon lokal yang dapat melakukan push, buka Codespace pada `main` lalu jalankan
`git fetch origin && git tag -f vX.Y.Z origin/main && git push -f origin vX.Y.Z`. Hapus rilis
GitHub terlebih dahulu jika workflow perlu menulis catatan yang dihasilkan: workflow
mempertahankan catatan rilis yang sudah ada dan hanya menambahkan file serta checksum.

### Tangga kematangan (di mana kita sekarang, ke mana kita menuju)

Perangkat lunak ini masih muda dan masih dalam pembuktian, sehingga tetap berada **di bawah
`1.0`**:

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

Kami **tidak** akan melompat ke nomor versi yang menyiratkan kematangan lebih besar daripada yang
ada (misalnya, `0.2` bukan berarti "selesai 20%" atau "hampir beta" — itu adalah hitungan jujur
siklus alfa sejauh ini). Setiap siklus adalah iterasi kecil yang nyata — tidak ada klaim lebih
dari itu.

### Pemetaan siklus ↔ versi

Siklus pengembangan (dan branch-nya) dinamai menurut versi yang dihasilkannya, dengan angka nol
di depan dihilangkan agar ringkas:

| Nama branch / siklus | Versi paket |
|---|---|
| `0.04` | `0.0.4` |
| `0.05` | `0.0.5` |
| `0.06` | `0.0.6` |
| `0.07` | `0.0.7` |
| `0.08` | `0.0.8` |
| `0.09` | `0.0.9` |
| `0.1`  | `0.1.0` |  (branch siklus `0.09` diganti namanya `0.09 → 0.1` saat peralihan ke alfa)
| `0.2`  | `0.2.0` |  (branch siklus `0.1` diganti namanya `0.1 → 0.2` saat peralihan ke 0.2)
| `main` | `0.2.0` → `0.3.0` → `0.4.0` → `0.5.0` |  (branch siklus `0.2` diganti namanya `0.2 → main` pada 2026-07-15 — branch bawaan kini secara permanen adalah `main`, dan nama branch serta versi tidak saling bergantung; `v0.2.0` diberi tag setelah validasi skala dengan korpus nyata, `v0.3.0` menutup siklus terukur-dan-terverifikasi, `v0.4.0` menutup siklus sumber hidup, dan `main` kini berisi `0.5.0`, rilis meja penyelidik, dengan tag `v0.5.0`)

Jadi "lapisan intelijen `0.06`" berarti "pekerjaan yang dirilis di `0.0.6`". Ketika Anda membaca
singkatan siklus seperti `0.05` di dokumentasi, bacalah sebagai `0.0.5`. PR masuk ke `main`,
branch siklus saat ini — bukan ke salah satu nama branch bernomor yang sudah dipensiunkan di
atas.

**Sejak alfa pertama (`0.1.0`), pemetaannya adalah siklus `0.N` ⇒ `v0.N.0`** — siklus `0.2`
ditutup dengan `v0.2.0`, siklus `0.3` dengan `v0.3.0`, siklus `0.4` dengan `v0.4.0`, siklus `0.5`
dengan `v0.5.0` (satu-satunya pengecualian adalah siklus gabungan `0.09`, yang menghasilkan
`0.1.0`). Sebuah siklus dinamai menurut rilis yang menutupnya — file gerbang rilis
menyatakannya dengan kata-kata mereka sendiri (`RELEASE_0.4_GATE.md` adalah "inventaris yang
dapat diperiksa untuk menutup siklus `0.4`") — dan sebuah nomor versi dapat *ditetapkan* di
tengah siklus sebelum tag (misalnya, `0.4.0` ditetapkan pada 2026-09-28 agar tag dapat dipindahkan
ke sana; `0.5.0` ditetapkan pada PR peralihan versi, dan tag menunjuk commit merge-nya), itulah
sebabnya tanggal pada judul changelog dan tanggal tag-nya dapat berbeda.

### Mengapa ini penting (kaitannya dengan nilai-nilai)

Proyek ini ada untuk membantu orang melihat informasi secara jujur. Alat yang melebih-lebihkan
kematangannya sendiri akan bertentangan dengan hal itu sejak akarnya. Penomoran versi yang
konservatif adalah disiplin yang sama dengan bagian lain basis kode: **klaim hanya apa yang
nyata, dan buktikan.**
