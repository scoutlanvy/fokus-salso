# Study Timer

Aplikasi desktop Windows untuk mencatat waktu belajar dengan timer manual dan Pomodoro. Riwayat disimpan secara lokal menggunakan SQLite, tanpa koneksi ke layanan eksternal. Antarmuka aplikasi menggunakan bahasa Inggris.

## Fitur

- Timer manual dengan pengaturan jam, menit, dan detik.
- Pomodoro: fokus 25 menit dengan kredit istirahat 5, 5, 5, lalu 15 menit secara berulang.
- Saldo istirahat tersimpan dan dapat digunakan sesuai kebutuhan.
- Pilihan subjek belajar, ringkasan per subjek, dan 30 sesi terbaru.
- Pause, Resume, Reset, Skip Break, serta alarm yang berbunyi sampai dihentikan.
- Tema terang dan gelap.

## Instalasi

Gunakan Windows dengan Python 3.9 atau lebih baru beserta Tkinter. Jalankan perintah berikut di PowerShell dari folder proyek:

```powershell
py -m venv .venv
.\.venv\Scripts\python.exe -m pip install customtkinter tzdata
```

`tzdata` menyediakan data zona waktu untuk pencatatan sesi dalam `Asia/Jakarta`.

## Menjalankan aplikasi

Klik dua kali `Study Timer.vbs` untuk membuka aplikasi tanpa jendela terminal. Launcher harus tetap berada di folder proyek dan menggunakan Python dari `.venv`.

Atau jalankan dari PowerShell:

```powershell
.\.venv\Scripts\python.exe main.py
```

Aplikasi selalu dibuka dalam mode **Pomodoro**, dengan fokus 25 menit yang menunggu tombol **Start** ditekan. Pilih subjek jika diperlukan. Untuk mode Manual, pilih **Manual** dan atur durasi terlebih dahulu. Setelah alarm Pomodoro dihentikan dengan **Stop Alarm**, pilih **Continue Focus** atau gunakan saldo istirahat. Fase berikutnya menunggu pilihan pengguna.

## Mencoba Pomodoro dengan cepat

Klik dua kali `Coba Pomodoro.vbs`. Mode ini memakai fokus 10 detik dan kredit istirahat 5, 5, 5, lalu 15 detik. Data percobaan disimpan terpisah. Tutup jendelanya dan buka `Study Timer.vbs` untuk kembali ke mode normal.

## Penyimpanan data

- Data normal: `%LOCALAPPDATA%\StudyTimer\study_sessions.sqlite3`
- Data percobaan: `%LOCALAPPDATA%\StudyTimerPreview\study_sessions.sqlite3`

Riwayat, saldo istirahat, dan posisi siklus Pomodoro tetap tersimpan setelah aplikasi ditutup. Timer yang sedang berjalan tidak dipulihkan saat aplikasi dibuka kembali. Untuk membuat cadangan, tutup aplikasi lalu salin file database normal ke lokasi lain.

## Pemeriksaan untuk pengembangan

Pasang pytest, lalu jalankan pengujian dari folder proyek:

```powershell
.\.venv\Scripts\python.exe -m pip install pytest
.\.venv\Scripts\python.exe -m pytest -q
```

Sebagian pengujian membuka jendela GUI sementara, sehingga membutuhkan sesi desktop Windows.

Lihat [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) untuk rincian teknis dan [AGENTS.md](AGENTS.md) untuk panduan kerja AI.
