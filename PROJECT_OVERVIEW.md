Study Timer
===========

Aplikasi desktop CustomTkinter untuk mencatat sesi belajar melalui timer
manual atau Pomodoro. Sesi fokus yang selesai disimpan secara lokal ke SQLite,
tanpa koneksi ke layanan eksternal.

Komponen utama
--------------

- `main.py`: entry point aplikasi.
- `gui.py`: antarmuka, pemilihan subjek dan mode, kontrol timer, dan tombol riwayat.
- `timer_service.py`: countdown manual dan Pomodoro, termasuk jeda, reset,
  serta lewati break.
- `session_repository.py`: penyimpanan dan query sesi dari SQLite.
- `history_panel.py`: panel riwayat dengan tab ringkasan per subjek dan daftar sesi terakhir.
- `config.py`: timezone, lokasi database lokal, pilihan subjek, dan durasi.

Penyimpanan
-----------

Database dibuat otomatis di `%LOCALAPPDATA%\StudyTimer\study_sessions.sqlite3`
pada Windows. Catatan berisi subjek, durasi dalam detik, dan waktu sesi dalam
timezone `Asia/Jakarta`. Sesi manual disimpan saat countdown selesai; setiap
sesi fokus Pomodoro disimpan saat sesi fokus selesai. Catatan dari layanan
eksternal sebelumnya tidak dimigrasikan. Bila database lokal tidak dapat ditulis, aplikasi
menampilkan pemberitahuan dan tidak menghentikan timer.

Riwayat
-------

Tombol "Lihat Riwayat" di antarmuka utama membuka dialog dengan dua tab:

- **Ringkasan**: total durasi dan jumlah sesi per subjek, diurutkan dari yang terbanyak.
- **Sesi Terakhir**: daftar 30 sesi terbaru dengan waktu, subjek, dan durasi.

Data diambil langsung dari SQLite; panel menampilkan pesan kosong jika belum ada sesi tersimpan.
