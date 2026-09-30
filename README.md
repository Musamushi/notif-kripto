# Notif Kripto

Memantau BTC, ETH, XRP, LTC, ADA, XLM di CoinMarketCap tiap 15 menit, lalu mengirim
pesan Telegram bila harga:

- menyentuh **Low** atau **Peak** salah satu tahun sebelumnya (sejak 2017), atau
- mencetak **Low baru** atau **Peak baru** tahun ini.

Pesan berisi indeks Fear & Greed, harga sekarang, level terdekat, dan daftar
Low/Peak setiap tahun. Setiap harga ditulis dalam dolar diikuti rupiahnya, dengan kurs
USD→IDR hari ini dari CoinMarketCap (cadangan: Yahoo). Peringatan tetap dihitung dalam dolar. Pengaturan (daftar koin, toleransi, dll.) ada di bagian atas `pantau.py`.

## 1. Buat bot Telegram

1. Di Telegram, buka **@BotFather** → kirim `/newbot` → ikuti petunjuk → salin **token**-nya.
2. Buka bot baru Anda dan kirim pesan apa saja (misalnya `halo`).
3. Di PowerShell, dari folder ini:
   ```
   $env:TELEGRAM_TOKEN = "token-dari-botfather"
   python pantau.py --chat-id
   ```
   Salin angka **chat id** yang muncul.

## 2. Pasang di GitHub (gratis)

1. Buat repository baru di GitHub, lalu unggah seluruh isi folder ini
   (termasuk folder `.github` dan `data`).
2. **Settings → Secrets and variables → Actions → New repository secret**, isi dua:
   - `TELEGRAM_TOKEN`: token dari BotFather
   - `TELEGRAM_CHAT_ID`: chat id dari langkah 1
3. **Actions** → pilih **Pantau Kripto** → **Run workflow** → mode **tes**.
   Kalau berhasil, pesan ringkasan keenam koin masuk ke Telegram.

Setelah itu program berjalan sendiri tiap 15 menit.

Catatan:
- Repository **public**: menit GitHub Actions gratis tanpa batas. Token tetap aman di Secrets;
  yang terlihat orang hanya kode dan data harga.
- Repository **private**: jatah gratis 2.000 menit/bulan, tidak cukup untuk tiap 15 menit.
  Ubah jadwal di `.github/workflows/pantau.yml` menjadi `*/30 * * * *`.
- Jadwal GitHub bisa telat 5–20 menit saat server GitHub sibuk. Harga yang turun lalu naik lagi
  di antara dua pemeriksaan tidak akan terdeteksi.

## Uji di komputer sendiri

```
python pantau.py --kering        # tampilkan pesan di layar, tidak dikirim
python pantau.py --tes           # kirim ringkasan semua koin ke Telegram
```

## Cara kerja singkat

- `data/riwayat.json`: Low/Peak per tahun dari candle harian CoinMarketCap, sama dengan tabel
  di halaman *Historical Data* koin, misalnya https://coinmarketcap.com/currencies/xrp/historical-data/.
  Low = low harian terendah dalam setahun, Peak = high harian tertinggi (tanggal menurut UTC). Tahun lampau
  diambil sekali saja; tahun berjalan diperbarui sekali sehari.
- `data/status.json`: posisi harga terhadap tiap level, supaya peringatan yang sama tidak
  terkirim berulang. Level yang sudah dilaporkan baru aktif lagi setelah harga menjauh 5%.
- Kalau pesan gagal terkirim, statusnya tidak disimpan, jadi peringatan diulang di pemeriksaan berikutnya.
- Data diambil dari endpoint internal yang dipakai situs CoinMarketCap sendiri (tanpa API key).
  Kalau suatu saat berubah atau diblokir, harga otomatis diambil dari Yahoo Finance dan
  Fear & Greed dari alternative.me (ditandai di pesan).
