# Study Timer

[English](README.md) | **Bahasa Indonesia**

Aplikasi desktop Windows untuk mencatat waktu belajar dengan timer manual dan Pomodoro. Riwayat disimpan secara lokal menggunakan SQLite, tanpa koneksi ke layanan eksternal. Antarmuka aplikasi menggunakan bahasa Inggris.

## Fitur

- Timer manual dengan pengaturan jam, menit, dan detik.
- Pomodoro: fokus 25 menit dengan kredit istirahat 5, 5, 5, lalu 15 menit secara berulang.
- Saldo istirahat tersimpan dan dapat digunakan sesuai kebutuhan.
- Settings untuk memilih progres Pomodoro bersama atau terpisah per subjek.
- Pilihan subjek belajar, ringkasan per subjek, dan 30 sesi terbaru.
- Pause, Resume, Reset, Skip Break, serta alarm yang berbunyi sampai dihentikan.
- Tema terang dan gelap.

## Instalasi

Gunakan Windows dengan Python 3.9 atau lebih baru beserta Tkinter. Unduh atau clone repositori, lalu jalankan perintah berikut di PowerShell dari folder proyek:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
```

`tzdata` menyediakan data zona waktu untuk pencatatan sesi dalam `Asia/Jakarta`.

## Menjalankan aplikasi

Klik dua kali `Study Timer.vbs` untuk membuka aplikasi tanpa jendela terminal. Launcher harus tetap berada di folder proyek dan menggunakan Python dari `.venv`.

Untuk menyematkan aplikasi ke taskbar, buat pintasan lokal ke
`.venv\Scripts\pythonw.exe` dengan argumen path lengkap `main.py`,
Start in folder proyek, dan ikon `timer.ico`. Pintasan `.lnk` tidak
disertakan dalam repositori karena menyimpan path komputer lokal.

Atau jalankan dari PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
```

Tanpa progres tersimpan, aplikasi dibuka dalam mode **Pomodoro**, dengan fokus 25 menit yang menunggu tombol **Start** ditekan. Pilih subjek jika diperlukan. Untuk mode Manual, pilih **Manual** dan atur durasi terlebih dahulu. Setelah alarm Pomodoro dihentikan dengan **Stop Alarm**, pilih **Continue Focus** atau gunakan saldo istirahat. Fase berikutnya menunggu pilihan pengguna.

Tekan **Space** saat jendela aplikasi aktif untuk **Pause/Resume** timer Manual, fokus Pomodoro, atau istirahat. Space tidak memulai timer, menghentikan alarm, atau memilih sesi berikutnya. Saat mengetik di kolom input, Space tetap berfungsi sebagai spasi. Menahan tombol hanya mengubah status sekali.

Panel riwayat tersembunyi setiap aplikasi dibuka. Klik **Show History** di dekat judul untuk menampilkan ringkasan dan sesi terbaru, atau **Hide History** untuk memberi seluruh lebar area kepada timer. Tombol ini dapat digunakan saat timer berjalan maupun paused, tanpa mengubah progres. Tab riwayat yang dipilih tetap dipertahankan selama aplikasi terbuka.

Untuk menambah subjek, klik **+** di samping pilihan **Subject** saat timer belum aktif, masukkan nama, lalu klik **OK**. Subjek langsung terpilih dan tersimpan untuk penggunaan berikutnya. Nama kosong ditolak; nama yang sama (tanpa membedakan huruf besar/kecil) memilih subjek yang sudah ada. Daftar disimpan di `subjects.json` dalam direktori data normal atau percobaan masing-masing, terpisah dari database riwayat.

Untuk menghapus subjek dari daftar, pilih subjek lalu klik **−** dan konfirmasi. Anda juga bisa membuka daftar Subject, klik kanan pada subjek, lalu pilih **Hapus**. Klik kanan tidak mengubah pilihan Subject dan daftar tetap terlihat selama menu Hapus terbuka. Tekan Escape untuk kembali ke daftar; klik di luar daftar dan menu untuk menutup keduanya. Memilih Hapus menutup kedua popup sebelum konfirmasi. Semua subjek kecuali **Umum** dapat dihapus; pilihan kembali ke **Umum**. Riwayat sesi tetap tersimpan dan muncul lagi jika subjek ditambahkan kembali dengan nama yang sama. Progres target bersama tidak berubah. Penghapusan tidak tersedia saat timer aktif atau dijeda, atau penyimpanan bermasalah.

Saat fokus Pomodoro **paused**, gunakan **Break** untuk memakai seluruh saldo atau **Choose Duration** untuk memilih durasi. Setelah break selesai dan alarm dihentikan, atau setelah **Skip Break**, sisa fokus kembali paused. Klik **Resume** saat siap. Menutup aplikasi selama break tetap menyimpan sisa break dan fokus tersebut.

## Settings progres Pomodoro

Klik **Settings** di dekat **Show History**, pilih salah satu, lalu klik **Save**:

- **Shared across subjects** (default): semua subjek melanjutkan sisa target yang sama.
- **Per subject**: setiap subjek memiliki sisa target sendiri. Saat pertama memakai pilihan ini, setiap subjek mulai dari 25 menit.

Kedua pilihan menyimpan progres masing-masing. Misalnya, Bersama tersisa **18:00**; beralih ke Per subject Anki yang belum dipakai menampilkan **25:00**. Jika kembali ke Bersama, sisanya tetap **18:00**. Progres tidak dipindahkan atau digandakan saat mengganti pilihan. Pilihan dan kedua simpanan progres tetap ada setelah aplikasi ditutup. Data progres per subjek dari versi lama tetap diarsipkan dan tidak dimasukkan ke simpanan Per subject yang baru, agar progres yang pernah dibawa ke Bersama tidak dihitung kembali.

Settings hanya dapat diubah saat timer tidak aktif. Saat timer berjalan, paused, break, alarm, atau menunggu **Continue Focus**, selesaikan atau **Reset** timer terlebih dahulu. Jika penyimpanan bermasalah, pulihkan dulu aksesnya. **Cancel**, Escape, atau menutup dialog membatalkan pilihan yang belum disimpan. Jika Save gagal, dialog menampilkan kesalahan dan pilihan sebelumnya tetap dipakai; Save dapat dicoba lagi.

Untuk bunyi tik di semua mode, aktifkan **Tick every second**, lalu atur slider
**Tick volume** dari **0–400%** dan klik **Save**. Nilai 0% membisukan tik,
100% memakai volume asli, dan di atas 100% memperkeras bunyi tik. Pilihan
On/Off dan volume tetap tersimpan setelah aplikasi ditutup dan dibuka kembali.
Volume ini hanya mengatur tik, tanpa mengubah volume alarm atau Windows.

History tetap mencatat waktu per subjek. Saldo break dan urutan hadiah tetap bersama untuk kedua pilihan. Pengaturan ini tidak mengubah durasi Manual. Mode percobaan menyimpan pilihan dan progresnya sendiri.

## Mencoba Pomodoro dengan cepat

Klik dua kali `Coba Pomodoro.vbs`. Mode ini memakai fokus 10 detik dan kredit istirahat 5, 5, 5, lalu 15 detik. Data percobaan disimpan terpisah. Tutup jendelanya dan buka `Study Timer.vbs` untuk kembali ke mode normal.

## Penyimpanan data

- Data normal: `%LOCALAPPDATA%\StudyTimer\study_sessions.sqlite3`
- Data percobaan: `%LOCALAPPDATA%\StudyTimerPreview\study_sessions.sqlite3`

Riwayat, saldo istirahat, posisi siklus Pomodoro, dan progres timer tersimpan setelah aplikasi ditutup. Untuk membuat cadangan, tutup aplikasi lalu salin file database normal ke lokasi lain.

## Melanjutkan progres

Progres Manual, fokus Pomodoro, dan istirahat disimpan setiap detik. Jika aplikasi ditutup pada `24:52`, saat dibuka kembali sisa waktunya tetap `24:52` dalam keadaan **Pause**. Tekan **Resume** untuk melanjutkan; waktu selama aplikasi tertutup tidak dihitung. Mode dan subjek ikut dipulihkan dan terkunci selama sesi aktif.

Progres juga dipulihkan dari detik terakhir yang berhasil disimpan jika aplikasi crash atau komputer mati mendadak. **Reset** pada Pomodoro otomatis mencatat waktu fokus yang sudah dijalani dan mengumpulkannya menuju target 25 menit sesuai pilihan di Settings. Contohnya, setelah belajar **14:53**, Reset mencatat bagian itu ke riwayat dan timer menampilkan sisa **10:07**, menunggu **Start**. Setelah sisa itu selesai, total fokus mencapai 25 menit, bonus istirahat diberikan sekali, dan target berikutnya kembali **25:00**. Riwayat mencatat **14:53 + 10:07**, tanpa menghitung waktu yang sama dua kali. Reset berulang tanpa belajar tidak mengurangi progres.

Secara default, **Shared across subjects** memakai satu progres target: mengganti dari Umum ke Anki tidak mengubah sisa waktu. Contohnya, belajar Umum **7 menit**, lalu Reset dan pindah ke Anki: sisa timer tetap **18 menit**. Menyelesaikan 18 menit di Anki memberikan satu bonus istirahat; riwayat mencatat Umum 7 menit dan Anki 18 menit. Target berikutnya kembali 25 menit.

**Target progress** menunjukkan waktu terkumpul pada pilihan yang sedang dipakai ditambah fokus yang sedang berjalan. Akumulasi tetap tersimpan setelah aplikasi ditutup. Waktu paused, aplikasi tertutup, dan break tidak dihitung sebagai fokus. Jika Reset dilakukan saat break dengan fokus tertunda, hanya bagian fokus yang ditambahkan. Reset saat fokus sudah mencapai nol menyelesaikan target dan bonusnya sekali. Saldo istirahat dan urutan bonus 5, 5, 5, lalu 15 menit tetap bersama untuk semua subjek.

Saat pertama beralih dari versi lama ke progres Bersama, progres lama **Umum** dilanjutkan sebagai progres bersama. Jika Umum sudah 6:55, semua subjek menampilkan sisa **18:05**. Jika tidak ada progres Umum, target dimulai penuh. Jika ada fokus lama yang masih aktif atau tersimpan selama break, sisa sesi tersebut dipertahankan beserta progres target yang mendasarinya. Migrasi hanya sekali; data progres lama subjek lain tetap tersimpan tetapi tidak digabungkan. Riwayat, saldo break, dan urutan bonus dipertahankan; riwayat lama tidak dihitung ulang.

Mode percobaan memakai aturan yang sama dengan target 10 detik dan penyimpanan terpisah. Jika sisa target tidak dapat dibaca, **Start** diganti **Retry**; klik untuk membaca ulang sebelum memulai.

**Reset** pada mode Manual tetap membuang progres aktif dan kembali ke **00:00:00**. Riwayat sebelumnya serta daftar dan pilihan subjek tetap dipertahankan. Jika penyimpanan saat Reset gagal, progres tetap paused; perbaiki kendala penyimpanan lalu tekan **Reset** lagi.

Jika aplikasi ditutup saat alarm berbunyi, sesi yang sudah selesai tidak dicatat ulang dan alarm tidak diputar saat dibuka kembali. Pomodoro menampilkan pilihan sesi berikutnya; Manual kembali siap memulai.

Jika penyimpanan gagal, timer berhenti sementara. Tekan **Resume** untuk mencoba kembali. Jika gagal menyimpan saat menutup, jendela tetap terbuka agar penutupan bisa dicoba lagi. Jika progres tidak dapat dibaca, kontrol timer dinonaktifkan untuk melindungi data tersimpan; tutup dan buka kembali setelah masalah penyimpanan diperbaiki.

Hanya satu jendela diizinkan untuk setiap database. Aplikasi normal dan mode percobaan tetap dapat dibuka bersamaan karena memakai database terpisah.

## Pemeriksaan untuk pengembangan

Pasang pytest, lalu jalankan pengujian dari folder proyek:

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.\.venv\Scripts\python.exe -m pytest -q
```

Sebagian pengujian membuka jendela GUI sementara, sehingga membutuhkan sesi desktop Windows.

Lihat [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) untuk rincian teknis dan [AGENTS.md](AGENTS.md) untuk panduan kerja AI.

## Struktur kode

`main.py` tetap menjadi entry point untuk PowerShell, kedua launcher VBS, dan
pintasan lokal. Launcher tetap berada di root bersama `.venv` dan `timer.ico`.
Package `study_timer/` harus ikut disalin ketika memindahkan proyek.

- `study_timer/app.py`: startup dan mutex per database.
- `study_timer/ui/`: jendela utama, dialog, dropdown subjek, input durasi, dan history.
- `study_timer/timer_service.py`: countdown, transisi fase, recovery, dan retry.
- `study_timer/audio.py` dan `study_timer/assets/`: playback dan audio bawaan.
- `study_timer/models.py`: model checkpoint timer.
- `study_timer/session_repository.py`: query dan transaksi SQLite.
- `study_timer/schema.py`: pembuatan schema serta migrasi dalam transaksi repository.
- `study_timer/subject_store.py`: penyimpanan daftar subjek JSON.
- `study_timer/config.py` dan `study_timer/instance_lock.py`: konfigurasi dan mutex Windows.

Pemindahan kode tidak memindahkan database atau `subjects.json` pengguna.
Import kode pengembangan sekarang menggunakan namespace `study_timer`.
