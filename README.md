# Notif Kripto

Memantau koin pilihan di CoinMarketCap tiap 15 menit (awalnya BTC, ETH, XRP, LTC, ADA, XLM),
lalu mengirim grafik + pesan Telegram bila:

- harga menyentuh **Low** atau **Peak** salah satu tahun sebelumnya (sejak 2017),
- harga mencetak **Low baru** atau **Peak baru** tahun ini, atau
- indeks **Fear & Greed** berubah 10 poin atau lebih dari nilai terakhir yang dilaporkan, atau
  menyentuh ambang ekstrem 25/20/15/10 (Extreme Fear) atau 75/80/85/90 (Extreme Greed). Ambang yang
  sudah dilaporkan baru aktif lagi setelah nilainya menjauh 5 poin.

Pesan berisi grafik Low/Peak per tahun dan harga 1 tahun terakhir, indeks Fear & Greed,
harga sekarang, level terdekat, dan tabel Low/Peak setiap tahun (dolar, rupiah, tanggal, dan jarak
dari harga sekarang: 🟢▲ = level di atas harga, 🔴▼ = level di bawah harga). Setiap harga ditulis dalam dolar diikuti rupiahnya, dengan kurs
USD→IDR hari ini dari CoinMarketCap (cadangan: Yahoo). Peringatan tetap dihitung dalam dolar. Pengaturan (toleransi, dll.) ada di bagian atas `pantau.py`.

## Sinyal strategi (`strategi.py`)

Semua ambang berasal dari uji data harian CoinMarketCap 2017–2026. Pola historis, bukan jaminan dan
bukan saran keuangan. Setiap pesan berupa gambar + judul singkat, harga dalam dolar dan rupiah.

**Beli: hanya saat PASAR ANJLOK** (BTC turun ≥ 40% dari harga tertinggi 12 bulan; pulih bila kembali di atas -35%)

| Pesan | Kapan |
|---|---|
| 🚨 Pasar anjlok | sekali di awal; tabel batas beli utama semua koin |
| 🟢🟢 BELI UTAMA | koin masuk zona murah **Ekstrem**; ada perkiraan masih bisa turun: pasti kena -12%, estimasi -49%, rendah -75% (15 kasus sejak 2018), F&G, Mayer, status jaringan |
| ✅ Pasar pulih | sekali, saat BTC kembali di atas -35% |

**Jual**

| Pesan | Kapan | Historis |
|---|---|---|
| ⚠️ JUAL KUAT | laporan Low/Peak menyentuh Peak tahunan saat di zona mahal | 84% turun dalam 90 hari |
| 🔴 Zona mahal | masuk tingkat Aman / Estimasi / Tinggi (aktif lagi setelah menjauh 10%) | ±67% |
| 🔥 Euforia | volume 7 hari ≥ 2,5x rata-rata setahun + naik ≥ 50% dalam 30 hari, hanya di zona mahal | LTC & ADA Des 2024 |
| 🔔 Waspada sell the news | H-7 sampai hari acara, bila harga sudah naik ≥ 30% dalam 60 hari | 8 dari 9 turun |

**Risiko & laporan rutin**

| Pesan | Kapan |
|---|---|
| 🚨 Kasus khusus koin | turun ≥ 25% lebih dalam dari BTC dalam 7 hari + volume ≥ 2x (XRP-SEC 2020, SOL-FTX 2022); dilampiri judul berita terkait |
| 📉 Kesehatan jaringan | bulanan; penggunaan (TVL DefiLlama dalam jumlah koin) turun ≥ 30% dalam 12 bulan, pesan hanya bila status berubah |
| 🗓 Ringkasan mingguan | Senin mulai 07:00 WIB: zona semua koin, status pasar, acara 30 hari |

Zona dihitung dari riwayat Low/Peak tahunan: zona murah altcoin = 30% / 20% / 12% dari puncak siklus terakhir;
BTC = 100% / 81% / 70% puncak siklus sebelumnya; zona mahal = perkiraan puncak berikut (rumus dasar→puncak BTC,
kelipatan altcoin disusutkan seperti BTC). Siklus & tanggal selesainya ada di `SIKLUS` pada `strategi.py`;
siklus 2029 masih perkiraan. Kalender acara tersimpan di `data/acara.json` (diatur dengan `/acara`).

## Perintah Telegram

| Perintah | Fungsi |
|---|---|
| `/cek` | ringkasan harga semua koin |
| `/cek XRP` | grafik dan detail satu koin |
| `/siklus` | zona murah/mahal semua koin (gambar); `/siklus XRP` = satu koin |
| `/acara` | kalender acara; `/acara tambah 2027-07-28 LTC Halving LTC`; `/acara hapus 2` |
| `/daftar` | koin yang sedang dipantau |
| `/tambah SOL` | tambah koin (boleh beberapa: `/tambah SOL DOGE`) |
| `/hapus XLM` | berhenti memantau koin |
| `/bantuan` | cara pakai |

Perintah dibaca setiap pemeriksaan, jadi balasannya bisa datang beberapa menit kemudian.
Hanya pesan dari `TELEGRAM_CHAT_ID` yang dilayani. Daftar koin tersimpan di `data/koin.json`.

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
   Kalau berhasil, grafik Fear & Greed dan grafik setiap koin masuk ke Telegram.

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
pip install -r requirements.txt   # sekali saja, untuk grafik
python pantau.py --kering        # tampilkan pesan di layar, grafik disimpan ke folder pratinjau
python pantau.py --tes           # kirim laporan semua koin ke Telegram
python uji_pantau.py             # uji logika peringatan (tanpa internet/Telegram)
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
