# Kebijakan Privasi (RGPD/GDPR)

> **Terjemahan mesin (draf) — menunggu peninjauan oleh penutur asli. Versi Prancis
> ([`../POLITIQUE_DE_CONFIDENTIALITE.md`](../POLITIQUE_DE_CONFIDENTIALITE.md)) adalah teks
> yang sah secara hukum.**

> ⚠️ **Pemberitahuan penting — dokumen ditulis tanpa validasi hukum profesional, secara
> permanen.** Dokumen ini adalah **dokumen kerja** yang ditulis untuk tujuan informasi
> oleh Penerbit sendiri. **Dokumen ini bukan nasihat atau konsultasi hukum.** **Open
> Omniscience adalah proyek bebas, gratis, dan tanpa tujuan komersial, yang dikerjakan
> tanpa anggaran**: dokumen ini **tidak akan ditinjau maupun divalidasi oleh profesional
> hukum** — ini adalah pilihan yang disadari, bukan sekadar tahap yang ditunda.
> Keterangan dalam tanda kurung siku **[À COMPLÉTER: …]** dan **[À VÉRIFIER: …]**
> menandai informasi yang sengaja dibiarkan apa adanya, atau yang belum diverifikasi
> secara independen oleh seorang profesional.

**Versi:** 1.0
**Tanggal berlaku:** 2026-07-16
**Kontak:** open-omniscience@ideotion.com

---

## 1. Prinsip pemandu: tanpa pemrosesan oleh Penerbit

**Open Omniscience** ("Perangkat Lunak") adalah **perangkat lunak bebas "local-first"**.
**Penerbit (Ideotion) tidak mengumpulkan, tidak meng-host, dan tidak memproses data pribadi
apa pun** milik Pengguna, dan **tidak mengoperasikan server apa pun**. **Tidak ada akun,
pendaftaran, layanan daring, maupun telemetri.** **100% pemrosesan** yang dilakukan dengan
Perangkat Lunak berjalan **secara lokal, di mesin Pengguna**.

Oleh karena itu:

- Penerbit **bukan pengendali maupun pemroses** data yang diproses oleh Pengguna dengan
  Perangkat Lunak;
- Penerbit **tidak memiliki akses** ke data Pengguna apa pun;
- kebijakan ini bersifat **informatif**: ia menjelaskan cara kerja Perangkat Lunak dan
  **kewajiban yang dibebankan kepada Pengguna** ketika ia memproses data pribadi.

## 2. Tanpa telemetri dan tanpa pengumpulan (dapat diverifikasi)

Desain Perangkat Lunak menjamin, **secara konstruksi**:

- **tanpa telemetri**, tanpa pelacak, tanpa pengenal penggunaan;
- **mulai tanpa panggilan jaringan apa pun**; sebuah **sakelar jaringan ("mode pesawat")**
  di antarmuka memutus seluruh lalu lintas keluar;
- **satu-satunya** koneksi jaringan adalah yang **dipicu oleh Pengguna** untuk mengumpulkan
  sumber (melalui komponen pengambilan "etis") dan, jika berlaku, penggunaan **lokal**
  sebuah model AI (Ollama) yang **tidak meninggalkan mesin**;
- karena kode bersifat **bebas (GPL v3)**, perilaku ini **dapat diaudit oleh siapa pun**.

> *Catatan konsistensi:* pernyataan ini mencerminkan keadaan Perangkat Lunak yang
> terdokumentasi (lihat `README`, [`../../SECURITY.md`](../../SECURITY.md), dan
> [`../../ETHICS.md`](../../ETHICS.md)). Setiap perkembangan di masa mendatang yang
> memperkenalkan transmisi data apa pun harus didokumentasikan di sini **sebelum**
> dioperasikan. **Titik kewaspadaan permanen (harus diverifikasi ulang pada setiap versi,
> sebelum pembaruan apa pun terhadap kolom "Versi" di atas): mengonfirmasi ulang
> ketiadaan telemetri dalam kode yang benar-benar diterbitkan.**

## 3. Data teknis yang diproses secara lokal oleh Perangkat Lunak

Perangkat Lunak menyimpan, **hanya di mesin Pengguna**, data yang diperlukan untuk
operasinya: korpus yang dikumpulkan, metadata asal, indeks pencarian, pengaturan, log
lokal, kunci penandatanganan, dan **catatan persetujuan lokal** (versi yang diterima +
stempel waktu ISO 8601). Data ini **tetap berada di bawah kendali eksklusif Pengguna** dan
tidak pernah dikirim ke Penerbit.

## 4. Pengguna, satu-satunya pengendali data

Apabila konten yang dikumpulkan, diimpor, atau dianalisis Pengguna **mengandung data
pribadi** (misalnya nama, pernyataan yang dinisbahkan, gambar, pengenal), Pengguna
bertindak sebagai **pengendali data** dalam arti **Règlement (UE) 2016/679 (RGPD)** dan
**loi n° 78-17 du 6 janvier 1978 relative à l'informatique, aux fichiers et aux libertés
("Loi Informatique et Libertés")**, sebagaimana telah diubah.

Sebagai pengendali data, **Pengguna berkewajiban** mematuhi, khususnya, kewajiban-kewajiban
berikut:

### 4.1. Dasar hukum dan minimalisasi

- menentukan **dasar hukum** yang sesuai (misalnya **kepentingan yang sah**, dengan
  menghormati **penyeimbangan** terhadap hak subjek data);
- menerapkan prinsip **minimalisasi**, **pembatasan tujuan**, dan **pembatasan
  penyimpanan**.

### 4.2. Data kategori khusus

- menerapkan **kewaspadaan yang lebih tinggi** terhadap **kategori khusus data** (dugaan
  asal ras atau etnis, opini politik, keyakinan, kesehatan, orientasi seksual, data
  biometrik atau genetik, dsb.) yang dicakup oleh **article 9 du RGPD**, yang
  pemrosesannya **pada prinsipnya dilarang** kecuali jika ada pengecualian yang berlaku.

### 4.3. Transparansi dan hak subjek data

- memastikan, sejauh diperlukan, **transparansi** terhadap subjek data;
- memungkinkan pelaksanaan **hak** mereka: **akses, pembetulan, penghapusan ("hak untuk
  dilupakan"), pembatasan, keberatan, dan keterbawaan**.

### 4.4. Permintaan penghapusan

Setiap permintaan penghapusan atau pembetulan yang berkaitan dengan konten yang dikumpulkan
Pengguna adalah **tanggung jawab Pengguna** (yang memiliki dan mengendalikan data secara
lokal). **Penerbit tidak dapat memproses permintaan semacam itu**, karena tidak memiliki
akses ke data. Untuk memudahkan kewajiban ini, Perangkat Lunak memungkinkan Pengguna
**mencari dan menghapus** konten dari korpus lokalnya.

### 4.5. Pengecualian "jurnalistik"

Apabila pemrosesan dilakukan untuk **tujuan jurnalistik** atau **ekspresi dan informasi**,
Pengguna dapat, dengan syarat tertentu, memperoleh **penyesuaian** yang diatur dalam
**article 85 du RGPD** dan dalam ketentuan terkait **Loi Informatique et Libertés**.
Pengecualian ini **tidak membebaskan** dari kepatuhan terhadap prinsip-prinsip esensial dan
**harus dinilai kasus per kasus**; hal ini termasuk dalam **penilaian dan tanggung jawab
Pengguna**. Transposisi nasionalnya tercantum pada **article 80 de la loi n° 78-17 du 6
janvier 1978** (sebagaimana diubah oleh ordonnance tanggal 12 Desember 2018), yang
mengesampingkan, secara pengecualian dan sejauh diperlukan untuk mendamaikan perlindungan
data dengan kebebasan berekspresi dan informasi, penerapan ketentuan-ketentuan tertentu
RGPD terhadap pemrosesan yang dilaksanakan khususnya untuk tujuan pelaksanaan, secara
profesional, kegiatan sebagai jurnalis.

## 5. Hasil yang dihasilkan AI dan data pribadi

Hasil yang dihasilkan atau dibantu oleh AI (ringkasan, terjemahan, ekstraksi entitas,
analisis sentimen, dsb.) dapat **menyebut atau menyimpulkan** informasi yang berkaitan
dengan orang. Hasil-hasil ini bersifat **probabilistik dan dapat keliru** (lihat **Pasal 7
[Ketentuan Penggunaan](CGU.md)**) dan **bukan temuan maupun tuduhan**. Penghasilan,
penyimpanan, dan terutama **kemungkinan penyebaran**-nya termasuk dalam **tanggung jawab
Pengguna** sebagai pengendali data dan penulis redaksional.

## 6. Keamanan

Perangkat Lunak menawarkan langkah keamanan **lokal** (misalnya **enkripsi saat diam**
melalui SQLCipher, eksekusi yang dibatasi pada antarmuka loopback). **Implementasi dan
ketangguhan** langkah-langkah ini, serta **keamanan fisik dan logis** mesin, menjadi
tanggung jawab Pengguna. Enkripsi saat diam melindungi berkas yang **disita atau disalin**,
**bukan** sesi berjalan yang telah disusupi, dan **tidak menyediakan pemulihan** frasa
sandi.

## 7. Otoritas pengawas

Di Prancis, otoritas pengawas yang berwenang adalah **Commission nationale de
l'informatique et des libertés (CNIL)**. Pengguna, dalam kapasitasnya sebagai pengendali
data, adalah **titik kontak** otoritas pengawas untuk pemrosesan yang dilakukannya.

## 8. Kontak

Karena kebijakan ini bersifat **informatif** (Penerbit tidak memproses data), tidak ada
permintaan pelaksanaan hak yang dapat dipenuhi oleh Penerbit. Untuk **pertanyaan apa pun
mengenai dokumen ini**: **open-omniscience@ideotion.com**.

---

*Dokumen terkait: [Ketentuan Penggunaan](CGU.md) · [Pemberitahuan Hukum](MENTIONS_LEGALES.md) · [Piagam Penggunaan yang Dapat Diterima](CHARTE_USAGE.md) · [Indeks](README.md). Lihat juga [`../../SECURITY.md`](../../SECURITY.md) dan [`../../ETHICS.md`](../../ETHICS.md).*
