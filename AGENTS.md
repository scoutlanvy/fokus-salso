# Panduan kerja

- Baca PROJECT_OVERVIEW.md sebelum mengubah kode.
- Pahami kode terkait sebelum melakukan perubahan.
- Jika kebutuhan ambigu, minta klarifikasi.
- Kerjakan perubahan yang sudah diminta pengguna.
- Minta konfirmasi sebelum menghapus data, merombak arsitektur, atau memperluas lingkup pekerjaan.
- Pertahankan fitur yang tidak terkait dengan perubahan.
- Jangan menghapus atau mengubah database pengguna tanpa permintaan eksplisit. Gunakan database sementara untuk pengujian.
- Perbarui PROJECT_OVERVIEW.md jika fitur, arsitektur, atau cara menjalankan proyek berubah.
- Jalankan pemeriksaan yang relevan.
- Jelaskan hasil perubahan, validasi, dan kendala.

## Pemeriksaan

- Jalankan pengujian dari folder proyek: `.\.venv\Scripts\python.exe -m pytest -q`.
- Pengujian GUI membutuhkan sesi desktop Windows dan dapat membuka jendela sementara.
