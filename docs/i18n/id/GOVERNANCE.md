<!-- id: Translation of docs/GOVERNANCE.md written by AI (2026-11-19, R677; native review dropped by R721, 2026-11-14); it may contain mistakes, and the English original is authoritative. Coverage: the whole document, 7 of 7 headings. Corrections are welcome as a pull request. -->

# Tata kelola & penggunaan yang dapat diterima

Open Omniscience adalah alat untuk **meminta pertanggungjawaban kekuasaan** dengan membantu orang
melihat *struktur* informasi publik secara jujur. Karena kemampuan itu kuat, dokumen ini
menyatakan dengan jelas untuk apa alat ini dibuat, batas-batas yang tidak akan dilanggarnya, dan
bagaimana alat ini bermaksud tetap layak dipercaya seiring pertumbuhannya. Ini adalah bagian dari
etika proyek, bukan sesuatu yang dipikirkan belakangan.

## Untuk apa alat ini

- **Jurnalisme investigatif dan riset untuk kepentingan publik** atas media, lembaga, pasar, dan
  hukum yang *dipublikasikan* — menampilkan struktur yang dapat diukur (konsentrasi kepemilikan,
  koordinasi/gema, kebaruan, pembingkaian, perubahan dari waktu ke waktu) untuk dinilai oleh
  manusia.
- **Perlindungan narasumber dan reprodusibilitas** — lokal sebagai prioritas, dapat bekerja
  luring, dengan provenans yang menunjukkan bila ada perusakan sehingga temuan dapat
  dipertahankan. Jejak rantai pengawasan (chain of custody) yang dirantai dengan hash dan
  ditandatangani bersifat **opsional** (nonaktif secara bawaan — ia menambah sedikit biaya
  penandatanganan per artikel): aktifkan di **Pengaturan → Rantai pengawasan → "Catat otomatis
  saat penyerapan"** (atau `OO_CUSTODY_ON_INGEST=1`) ketika integritas pembuktian penting bagi
  suatu kasus. Sampai saat itu, provenans tetap menyertai setiap artikel (sumber, waktu
  pengambilan, hash konten) dan paket bukti bertanda tangan dapat dibuat sesuai permintaan.

## Garis merah penggunaan ganda (tidak ada sejak rancangan, tidak dapat dikonfigurasi)

Teknik yang sama yang membongkar operasi pengaruh yang terkoordinasi dapat, di tangan yang salah,
diarahkan kepada orang biasa. Garis yang menjaga alat ini tetap menjadi instrumen
*akuntabilitas* dan bukan alat *pengawasan* bersifat tepat, dan garis itu dipegang dalam
**arsitektur**, bukan dalam pengaturan yang dapat diubah pengguna:

1. **Tidak ada pelacakan individu pribadi.** Alat ini menganalisis *sumber yang
   dipublikasikan* (media, lembaga, dokumen publik). Alat ini **tidak** membuat profil orang
   pribadi, dan `src/compliance/gdpr.py` adalah pagar pengamannya. Keterkemukaan mengukur
   *liputan tentang tokoh publik yang sudah diberitakan* — perhatian, tidak pernah kepentingan
   atau jasa.
2. **Tidak ada identifikasi biometrik.** Tidak ada pengenalan wajah, suara, atau cara berjalan.
   Tidak akan pernah.
3. **Tidak ada penyerapan kanal pribadi.** Tidak ada DM, umpan pribadi, pesan yang disadap, atau
   data nonpublik. Korpus dibangun dari sumber yang dapat diakses pengguna secara sah dan etis.
4. **Tidak ada vonis otomatis.** Tidak ada skor kebenaran/kredibilitas/"kepercayaan", tidak ada
   label "bias"/"palsu". Alat ini menampilkan *pengukuran dengan metode + catatan kehati-hatian*;
   manusialah yang menyimpulkan. (Ditegakkan dalam kode: `assert_no_score_fields`.)
5. **Tidak ada server pusat, akun, atau telemetri.** Tidak ada yang keluar dari mesin pengguna
   kecuali pengambilan data yang mereka perintahkan. Tidak ada tumpukan data pengguna yang dapat
   disita atau diminta lewat panggilan pengadilan.
6. **Tidak ada penyaringan atau penurunan bobot sumber secara diam-diam.** Fakta liputan
   *ditampilkan*; setiap pelemahan diterapkan oleh pengguna, ditandai, dan dapat dibatalkan —
   tampilkan, jangan pernah paksakan.

Hal-hal ini ditegakkan sejauh yang dapat dilakukan kode: sebuah tes CI
(`tests/test_repo_invariants.py::test_red_lines_not_crossed`) menggagalkan build jika kemampuan
terlarang (pengenalan biometrik, pelacakan individu) muncul di basis kode. Sebuah tes adalah
kawat pemicu, bukan bukti — jaminan sesungguhnya adalah budaya dan peninjauan.

## Sikap hukum & etis

- Sebuah **cermin riset**, bukan sumber resmi, dan **bukan nasihat hukum**; setiap catatan
  menautkan kembali ke asalnya.
- **Akses etis** secara bawaan: robots.txt gagal-tertutup, batas laju per host, User-Agent yang
  mengidentifikasi diri, atribusi dan provenans disimpan. (Pengguna dapat mengaktifkan pengambilan
  *Terlindungi* — proksi + UA generik, kecuali dalam permintaan aplikasi sendiri ke Wikipedia,
  Wikidata, dan dump Wikimedia, yang kebijakan API-nya meminta setiap alat menyebutkan namanya —
  untuk melindungi narasumber atau diri sendiri saat menyelidiki target yang berkuasa; ini adalah
  kewajiban jurnalistik untuk melindungi narasumber, diambil secara sengaja dan didokumentasikan,
  tidak pernah menjadi bawaan yang diam-diam.)
- **Menghormati lisensi dan hak cipta**; menyimpan provenans dan hanya yang minimum diperlukan;
  mematuhi kewajiban perlindungan data di setiap yurisdiksi.

## Independensi & pendanaan

Alat ini sengaja dibuat **murah untuk dijalankan** (lokal, tanpa infrastruktur) agar dapat tetap
**independen**. Jika proyek ini suatu saat menerima pendanaan, proyek akan menghindari
penguasaan oleh satu penyandang dana atau agenda mana pun, mengatur keputusan secara transparan,
dan tidak pernah membengkokkan definisi "disinformasi" demi kepentingan sponsor. Pilihan paling
politis yang dibuat proyek ini adalah tetap kecil, lokal, dan tidak dapat dikuasai.

## Ketahanan terhadap penyalahgunaan

Tidak ada alat yang dapat mencegah semua penyalahgunaan, dan kami tidak akan berpura-pura
sebaliknya. Ketahanan kami bersifat struktural: garis merah di atas, rancangan yang mengutamakan
lokal (tidak ada data terpusat untuk disalahgunakan dalam skala besar), penolakan untuk
memberikan vonis, dan keterbukaan (siapa pun dapat memeriksa, mem-fork, dan mengaudit). Jika Anda
yakin proyek ini sedang diarahkan melewati garis merah, buka sebuah issue — kemampuan untuk
menggugat itulah intinya.

## Bagaimana keputusan dibuat (niat)

Saat ini proyek ini masih awal dan memiliki satu pengelola. Sebelum alfa publik `0.1`, kami
berniat melakukan: **tinjauan keamanan & etika eksternal**, peralihan menuju **tata kelola dengan
banyak pengelola** dengan pengambilan keputusan yang transparan, dan sebuah **perjanjian
kontributor** yang mengikat kontributor pada garis merah. Sampai saat itu, dokumen ini adalah
komitmen resmi yang tercatat.
