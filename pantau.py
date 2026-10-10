"""Pantau harga kripto di CoinMarketCap dan kirim peringatan ke Telegram.

Dijalankan berkala (GitHub Actions, tiap 15 menit). Setiap kali jalan:
1. baca perintah Telegram (/tambah, /hapus, /daftar, /cek, /bantuan),
2. ambil harga koin dan indeks Fear & Greed dari CoinMarketCap,
3. bandingkan dengan Low/Peak setiap tahun (dari riwayat harian CoinMarketCap),
4. kirim grafik + pesan bila harga menyentuh Low/Peak tahun-tahun sebelumnya,
   mencetak Low/Peak baru tahun ini, atau Fear & Greed berubah >= 10 poin.

Pemakaian:
    python pantau.py            jalan normal
    python pantau.py --kering   cetak pesan saja (grafik disimpan ke folder pratinjau); tidak kirim/simpan
    python pantau.py --tes      kirim laporan semua koin (uji Telegram)
    python pantau.py --chat-id  tampilkan chat id Telegram (setelah Anda chat ke bot)

Rahasia dibaca dari environment variable TELEGRAM_TOKEN dan TELEGRAM_CHAT_ID.
Grafik butuh matplotlib (requirements.txt); tanpa itu pesan tetap terkirim sebagai teks.
"""
import calendar
import copy
import html
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import strategi

# ---------------------------------------------------------------- Pengaturan
# Koin awal; setelah data/koin.json terbentuk, daftar koin diatur lewat Telegram (/tambah, /hapus).
KOIN_AWAL = {
    "BTC": {"id": 1, "halaman": "bitcoin", "nama": "Bitcoin"},
    "ETH": {"id": 1027, "halaman": "ethereum", "nama": "Ethereum"},
    "XRP": {"id": 52, "halaman": "xrp", "nama": "XRP"},
    "LTC": {"id": 2, "halaman": "litecoin", "nama": "Litecoin"},
    "ADA": {"id": 2010, "halaman": "cardano", "nama": "Cardano"},
    "XLM": {"id": 512, "halaman": "stellar", "nama": "Stellar"},
}
TAHUN_MULAI = 2017          # tahun paling awal yang dipantau dan ditampilkan
TOLERANSI = 0.005           # dianggap "menyentuh" bila harga sedekat 0,5% dari level
JARAK_SIAGA_ULANG = 0.05    # level yang sudah dilaporkan baru aktif lagi setelah harga menjauh 5%
LANGKAH_LOW_BARU = 0.03     # selama terus mencetak Low/Peak baru, lapor lagi tiap bergerak 3% lagi
MIN_HARI_TAHUN_INI = 14     # awal Januari: Low/Peak baru tahun ini baru dilaporkan setelah ada 14 hari data
LAPOR_PEAK_TAHUN_INI = True   # False = hanya lapor Low baru tahun ini
FG_LANGKAH = 10             # lapor bila Fear & Greed berubah sebanyak ini dari nilai terakhir yang dilaporkan
FG_AMBANG_BAWAH = (25, 20, 15, 10)  # selalu lapor saat turun sampai angka ini (Extreme Fear)
FG_AMBANG_ATAS = (75, 80, 85, 90)   # selalu lapor saat naik sampai angka ini (Extreme Greed)
FG_JARAK_ULANG = 5          # ambang yang sudah dilaporkan baru aktif lagi setelah menjauh 5 poin

WIB = timezone(timedelta(hours=7))
FOLDER = Path(__file__).resolve().parent
FOLDER_DATA = FOLDER / "data"
FOLDER_PRATINJAU = FOLDER / "pratinjau"
BERKAS_RIWAYAT = FOLDER_DATA / "riwayat.json"
BERKAS_STATUS = FOLDER_DATA / "status.json"
BERKAS_KOIN = FOLDER_DATA / "koin.json"
CMC = "https://api.coinmarketcap.com/data-api"
USD, IDR = "2781", "2794"  # id mata uang USD dan IDR di CoinMarketCap
KURS_IDR = None  # (rupiah per 1 USD, sumber); diisi ambil_harga()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
BULAN = "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des".split()
VERSI_PERINTAH = 3  # naikkan bila daftar PERINTAH berubah, supaya menu Telegram diperbarui
PERINTAH = [
    ("cek", "Ringkasan semua koin; /cek XRP = grafik XRP"),
    ("siklus", "Zona murah/mahal semua koin; /siklus XRP = satu koin"),
    ("acara", "Kalender acara (sell the news): lihat/tambah/hapus"),
    ("daftar", "Daftar koin yang dipantau"),
    ("tambah", "Tambah koin, contoh: /tambah SOL"),
    ("hapus", "Hapus koin, contoh: /hapus XLM"),
    ("bantuan", "Cara pakai bot ini"),
]
BANTUAN = (
    "<b>Perintah</b>\n"
    "/cek - ringkasan harga semua koin\n"
    "/cek XRP - grafik dan detail satu koin\n"
    "/siklus - zona harga murah/mahal semua koin (gambar)\n"
    "/siklus XRP - zona harga satu koin\n"
    "/acara - kalender acara; /acara tambah 2027-07-28 LTC Halving LTC; /acara hapus 2\n"
    "/daftar - koin yang sedang dipantau\n"
    "/tambah SOL - tambah koin (boleh beberapa: /tambah SOL DOGE)\n"
    "/hapus XLM - berhenti memantau koin\n\n"
    "Perintah dibaca setiap pemeriksaan (sekitar tiap 15 menit), jadi balasannya bisa "
    "datang beberapa menit kemudian.\n\n"
    "Peringatan otomatis dikirim bila harga menyentuh Low/Peak tahun sebelumnya, mencetak "
    f"Low/Peak baru tahun ini, atau Fear &amp; Greed berubah {FG_LANGKAH} poin / menyentuh "
    f"{', '.join(map(str, FG_AMBANG_BAWAH))} atau {', '.join(map(str, FG_AMBANG_ATAS))}.\n\n"
    "Sinyal tambahan: PASAR ANJLOK (BTC -40% dari tertinggi 12 bulan) + BELI UTAMA di zona murah Ekstrem; "
    "zona mahal, JUAL KUAT, euforia, waspada sell the news (H-7 acara); kasus khusus koin; kesehatan jaringan; "
    "ringkasan mingguan tiap Senin pagi.\n\n"
    "🟢▲ = level di atas harga sekarang, 🔴▼ = level di bawah harga sekarang."
)


# ---------------------------------------------------------------- Ambil data
def ambil_json(url, data=None, kepala=None, coba=3):
    for ke in range(coba):
        try:
            req = urllib.request.Request(url, data=data, headers={**UA, **(kepala or {})})
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except urllib.error.HTTPError as e:
            if e.code < 500 and e.code != 429:  # kesalahan permintaan: percuma diulang
                raise
            if ke == coba - 1:
                raise
        except Exception:
            if ke == coba - 1:
                raise
        time.sleep(2 * (ke + 1))


def ambil_harga(koin):
    """Harga USD tiap koin dan kurs USD->IDR. Utama CoinMarketCap, cadangan Yahoo Finance."""
    global KURS_IDR
    harga, sumber, kurs = {}, "CoinMarketCap", []
    try:
        ids = ",".join(str(k["id"]) for k in koin.values())
        j = ambil_json(f"{CMC}/v3/cryptocurrency/quote/latest?id={ids}&convertId={USD},{IDR}")
        per_id = {d["id"]: d for d in j["data"]}
        for sym, k in koin.items():
            d = per_id.get(k["id"])
            if not d:
                continue
            q = {q.get("name"): float(q["price"]) for q in d["quotes"]}
            harga[sym] = q.get(USD, next(iter(q.values())))
            if q.get(IDR) and q.get(USD):
                kurs.append(q[IDR] / q[USD])
    except Exception as e:
        print(f"[!] Harga CoinMarketCap gagal: {e}")
    if kurs:
        KURS_IDR = (sorted(kurs)[len(kurs) // 2], "CoinMarketCap")
    else:
        try:
            j = ambil_json("https://query1.finance.yahoo.com/v8/finance/chart/IDR=X?range=1d&interval=1d")
            KURS_IDR = (float(j["chart"]["result"][0]["meta"]["regularMarketPrice"]), "Yahoo")
        except Exception as e:
            print(f"[!] Kurs rupiah gagal: {e}")
    for sym in koin:
        if sym in harga:
            continue
        try:
            j = ambil_json(f"https://query1.finance.yahoo.com/v8/finance/chart/{sym}-USD?range=1d&interval=1d")
            harga[sym] = float(j["chart"]["result"][0]["meta"]["regularMarketPrice"])
            sumber = "CoinMarketCap + Yahoo"
        except Exception as e:
            print(f"[!] Harga {sym} dari Yahoo juga gagal: {e}")
    return harga, sumber


def ambil_fear_greed():
    """{skor, nama, sumber, riwayat=[(datetime, skor)] 90 hari}. Utama CoinMarketCap, cadangan alternative.me."""
    try:
        akhir = int(time.time())
        daftar = ambil_json(f"{CMC}/v3/fear-greed/chart?start={akhir - 90 * 86400}&end={akhir}")["data"]["dataList"]
        return {"skor": int(daftar[-1]["score"]), "nama": daftar[-1]["name"], "sumber": "CoinMarketCap",
                "riwayat": [(datetime.fromtimestamp(int(d["timestamp"]), timezone.utc), int(d["score"]))
                            for d in daftar]}
    except Exception as e:
        print(f"[!] Fear & Greed CoinMarketCap gagal: {e}")
    try:
        daftar = ambil_json("https://api.alternative.me/fng/?limit=90")["data"][::-1]
        return {"skor": int(daftar[-1]["value"]), "nama": daftar[-1]["value_classification"],
                "sumber": "alternative.me",
                "riwayat": [(datetime.fromtimestamp(int(d["timestamp"]), timezone.utc), int(d["value"]))
                            for d in daftar]}
    except Exception as e:
        print(f"[!] Fear & Greed alternative.me juga gagal: {e}")
        return None


def ambil_candle(id_koin, akhir):
    """±400 candle harian CoinMarketCap yang berakhir di `akhir` (epoch detik)."""
    j = ambil_json(f"{CMC}/v3.1/cryptocurrency/historical?id={id_koin}&convertId={USD}"
                   f"&timeStart={akhir - 400 * 86400}&timeEnd={akhir}&interval=1d")
    return j["data"]["quotes"]


def ambil_harian(id_koin, sekarang):
    """[(datetime, close)] 365 hari terakhir, untuk grafik."""
    try:
        return [(datetime.fromisoformat(q["timeOpen"][:10]), q["quote"]["close"])
                for q in ambil_candle(id_koin, int(sekarang.timestamp()))][-365:]
    except Exception as e:
        print(f"[!] Data harian untuk grafik gagal: {e}")
        return []


def ambil_tahun(id_koin, tahun, sekarang):
    """Low dan Peak satu tahun dari candle harian CoinMarketCap."""
    akhir = min(calendar.timegm((tahun, 12, 31, 23, 59, 59)), int(sekarang.timestamp()))
    baris = [q for q in ambil_candle(id_koin, akhir) if q["timeOpen"].startswith(str(tahun))]
    if not baris:
        return {"kosong": True, "lengkap": tahun < sekarang.year}
    lo = min(baris, key=lambda q: q["quote"]["low"])
    hi = max(baris, key=lambda q: q["quote"]["high"])
    return {
        "low": lo["quote"]["low"], "low_tgl": (lo.get("timeLow") or lo["timeOpen"])[:10],
        "peak": hi["quote"]["high"], "peak_tgl": (hi.get("timeHigh") or hi["timeOpen"])[:10],
        "hari": len(baris),
        "lengkap": baris[-1]["timeOpen"][5:10] == "12-31",
    }


def perbarui_riwayat(riwayat, koin, sekarang):
    """Tahun lampau cukup diambil sekali; tahun berjalan diperbarui sekali sehari."""
    hari_ini = sekarang.strftime("%Y-%m-%d")
    semua_berhasil = True
    for sym, k in koin.items():
        rk = riwayat["koin"].setdefault(sym, {})
        for tahun in range(TAHUN_MULAI, sekarang.year + 1):
            ent = rk.get(str(tahun))
            if ent and ent.get("lengkap"):
                continue
            if tahun == sekarang.year and ent and riwayat.get("diperbarui") == hari_ini:
                continue
            try:
                rk[str(tahun)] = ambil_tahun(k["id"], tahun, sekarang)
                time.sleep(0.3)
            except Exception as e:
                semua_berhasil = False
                print(f"[!] Riwayat {sym} {tahun} gagal: {e}")
    if semua_berhasil:
        riwayat["diperbarui"] = hari_ini


_PETA_KOIN = None


def cari_koin(teks):
    """Cari koin di CoinMarketCap dari simbol (SOL) atau nama halaman (solana).
    Simbol kembar: dipilih yang peringkatnya paling atas."""
    global _PETA_KOIN
    if _PETA_KOIN is None:
        _PETA_KOIN = ambil_json(f"{CMC}/v3/map/all?listing_status=active&start=1&limit=10000")["data"]["cryptoCurrencyMap"]
    kunci = teks.strip().lower()
    cocok = ([c for c in _PETA_KOIN if c["symbol"].lower() == kunci]
             or [c for c in _PETA_KOIN if c["slug"] == kunci or c["name"].lower() == kunci])
    if not cocok:
        return None
    c = min(cocok, key=lambda c: c.get("rank") or 10 ** 9)
    return c["symbol"].upper(), {"id": c["id"], "halaman": c["slug"], "nama": c["name"]}


# ---------------------------------------------------------------- Pemeriksaan
def status_awal(tahun):
    return {"tahun": tahun, "low_teramati": None, "peak_teramati": None,
            "jangkar_low": None, "jangkar_peak": None, "level": {}}


def ekstrem_tahun_ini(ent, st, jenis):
    """Low/Peak tahun berjalan: gabungan candle harian (s.d. kemarin) dan harga yang teramati hari ini."""
    calon = []
    if ent and not ent.get("kosong"):
        calon.append((ent[jenis], ent[f"{jenis}_tgl"]))
    if st[f"{jenis}_teramati"]:
        calon.append(tuple(st[f"{jenis}_teramati"]))
    if not calon:
        return None
    return min(calon) if jenis == "low" else max(calon)


def periksa(sym, harga, rk, st, sekarang):
    """Ubah `st` di tempat dan kembalikan daftar kejadian yang perlu dilaporkan."""
    tahun_ini = sekarang.year
    tgl = sekarang.strftime("%Y-%m-%d")
    if st.get("tahun") != tahun_ini:  # ganti tahun: status level tahun lampau tetap dipakai
        st.update({k: v for k, v in status_awal(tahun_ini).items() if k != "level"})
    kejadian = []
    ent = rk.get(str(tahun_ini))
    cukup_data = bool(ent) and ent.get("hari", 0) >= MIN_HARI_TAHUN_INI

    # Low/Peak baru tahun ini
    for jenis, lapor, lebih_ekstrem, langkah in (
            ("low", True, lambda a, b: a < b, 1 - LANGKAH_LOW_BARU),
            ("peak", LAPOR_PEAK_TAHUN_INI, lambda a, b: a > b, 1 + LANGKAH_LOW_BARU)):
        ref = ekstrem_tahun_ini(ent, st, jenis)
        jangkar = f"jangkar_{jenis}"
        if ref and lebih_ekstrem(harga, ref[0]):
            if lapor and cukup_data and (st[jangkar] is None
                                         or not lebih_ekstrem(st[jangkar] * langkah, harga)):
                kejadian.append({"tahun": tahun_ini, "teks":
                                 f"<b>{jenis.capitalize()} baru {tahun_ini}!</b>\n"
                                 f"      sebelumnya {usd_idr(ref[0])} ({tanggal(ref[1])})"})
                st[jangkar] = harga
        elif ref and st[jangkar] is not None and abs(harga - ref[0]) / ref[0] >= JARAK_SIAGA_ULANG:
            st[jangkar] = None
        if not st[f"{jenis}_teramati"] or lebih_ekstrem(harga, st[f"{jenis}_teramati"][0]):
            st[f"{jenis}_teramati"] = [harga, tgl]

    # Menyentuh Low/Peak tahun-tahun sebelumnya
    for tahun in range(TAHUN_MULAI, tahun_ini):
        ent = rk.get(str(tahun))
        if not ent or ent.get("kosong"):
            continue
        for jenis in ("low", "peak"):
            nilai = ent[jenis]
            nama = f"{jenis.capitalize()} {tahun}"
            jarak = abs(harga - nilai) / nilai
            sisi = "atas" if harga >= nilai else "bawah"
            lv = st["level"].get(nama)
            if lv is None:  # pertama kali: catat posisi saja, jangan lapor
                st["level"][nama] = {"sisi": sisi, "siaga": jarak > TOLERANSI}
                continue
            if lv["siaga"] and (jarak <= TOLERANSI or sisi != lv["sisi"]):
                gerak = "Turun" if lv["sisi"] == "atas" else "Naik"
                kejadian.append({"tahun": tahun, "teks":
                                 f"<b>{gerak} menyentuh {nama}</b>\n      {usd_idr(nilai)}"})
                lv["siaga"] = False
            elif not lv["siaga"] and jarak >= JARAK_SIAGA_ULANG:
                lv["siaga"] = True
            lv["sisi"] = sisi
    return kejadian


def ambang_terlewati(skor):
    return sorted([a for a in FG_AMBANG_BAWAH if skor <= a] + [a for a in FG_AMBANG_ATAS if skor >= a])


def periksa_fg(fg, status, sekarang):
    """(catatan F&G baru untuk disimpan bila pesan terkirim, daftar alasan lapor).
    Lapor bila bergeser >= FG_LANGKAH dari nilai terakhir yang dilaporkan, atau menyentuh ambang ekstrem."""
    if not fg:
        return None, []
    lama = status.get("fg")
    baru = {"skor": fg["skor"], "nama": fg["nama"], "sumber": fg["sumber"], "waktu": sekarang.isoformat()}
    if not lama or lama.get("sumber") != fg["sumber"]:  # awal, atau ganti sumber (skalanya beda): catat saja
        status["fg"] = {**baru, "ambang": ambang_terlewati(fg["skor"])}
        return None, []
    skor, alasan = fg["skor"], []
    selisih = skor - lama["skor"]
    if abs(selisih) >= FG_LANGKAH:
        alasan.append(f"{'Naik' if selisih > 0 else 'Turun'} {abs(selisih)} poin dari {lama['skor']} "
                      f"({html.escape(lama['nama'])}), {jam_wib(datetime.fromisoformat(lama['waktu']))}")
    # Ambang yang sudah dilaporkan aktif lagi setelah skor menjauh FG_JARAK_ULANG poin
    sudah = {a for a in lama.get("ambang", [])
             if not (a in FG_AMBANG_BAWAH and skor >= a + FG_JARAK_ULANG)
             and not (a in FG_AMBANG_ATAS and skor <= a - FG_JARAK_ULANG)}
    for a in FG_AMBANG_BAWAH:
        if skor <= a and a not in sudah:
            alasan.append(f"🚨 Menyentuh {a} ke bawah (Extreme Fear)")
            sudah.add(a)
    for a in FG_AMBANG_ATAS:
        if skor >= a and a not in sudah:
            alasan.append(f"🚨 Menyentuh {a} ke atas (Extreme Greed)")
            sudah.add(a)
    if alasan:
        return {**baru, "ambang": sorted(sudah)}, alasan
    lama["ambang"] = sorted(sudah)  # tanpa pesan: hanya catat ambang yang aktif lagi
    return None, []


# ---------------------------------------------------------------- Pesan
def uang(x):
    if x >= 1000:
        return f"${x:,.0f}"
    if x >= 10:
        return f"${x:,.2f}"
    if x >= 0.01:
        return f"${x:.4f}"
    return f"${x:.4g}"


def rupiah(x):
    if x >= 100:
        return "Rp" + f"{x:,.0f}".replace(",", ".")
    return "Rp" + f"{x:.2f}".replace(".", ",")


def usd_idr(x):
    """Dolar diikuti rupiahnya (kurs hari ini), misalnya $1.5285 ≈ Rp27.423."""
    return f"{uang(x)} ≈ {rupiah(x * KURS_IDR[0])}" if KURS_IDR else uang(x)


def tanggal(iso):
    return f"{iso[8:10]} {BULAN[int(iso[5:7]) - 1]}"


def jam_wib(waktu):
    return f"{waktu.astimezone(WIB):%d-%m-%Y %H:%M} WIB"


def label_fg(fg):
    if not fg:
        return "Fear &amp; Greed: tidak tersedia"
    skor = fg["skor"]
    emoji = "😱" if skor < 25 else "😨" if skor < 45 else "😐" if skor <= 55 else "🙂" if skor <= 75 else "🤑"
    catatan = "" if fg["sumber"] == "CoinMarketCap" else f" <i>({fg['sumber']})</i>"
    return f"{emoji} <b>Fear &amp; Greed: {skor}/100 ({html.escape(fg['nama'])})</b>{catatan}"


def daftar_level(rk, st, tahun_ini):
    """[(tahun, low, low_tgl, peak, peak_tgl)] dari tahun terbaru ke terlama."""
    hasil = []
    for tahun in range(tahun_ini, TAHUN_MULAI - 1, -1):
        ent = rk.get(str(tahun))
        if tahun == tahun_ini:
            lo, hi = ekstrem_tahun_ini(ent, st, "low"), ekstrem_tahun_ini(ent, st, "peak")
            if lo and hi:
                hasil.append((tahun, lo[0], lo[1], hi[0], hi[1]))
        elif ent and not ent.get("kosong"):
            hasil.append((tahun, ent["low"], ent["low_tgl"], ent["peak"], ent["peak_tgl"]))
    return hasil


def level_terdekat(harga, level):
    """((nama, nilai) di bawah harga, (nama, nilai) di atas harga); None bila tidak ada."""
    semua = [(f"Low {t}", lo) for t, lo, _, _, _ in level] + [(f"Peak {t}", hi) for t, _, _, hi, _ in level]
    # Pakai < dan >: Low/Peak tahun ini yang baru saja tercipta sama dengan harga, jadi tidak ikut
    bawah = max((x for x in semua if x[1] < harga), key=lambda x: x[1], default=None)
    atas = min((x for x in semua if x[1] > harga), key=lambda x: x[1], default=None)
    return bawah, atas


def persen(nilai, harga):
    return f"{(nilai / harga - 1) * 100:+.1f}%"


def panah(nilai, harga):
    """🟢▲ = level di atas harga sekarang, 🔴▼ = di bawah."""
    return "🟢▲" if nilai > harga else "🔴▼"


def rupiah_ringkas(x):
    """Rupiah yang muat di kolom tabel: Rp27.346, Rp689,2 jt, Rp1,33 M (miliar)."""
    if x >= 1e9:
        return "Rp" + f"{x / 1e9:.2f}".replace(".", ",") + " M"
    if x >= 1e6:
        return "Rp" + f"{x / 1e6:.1f}".replace(".", ",") + " jt"
    return rupiah(x)


def tabel_level(level, harga, ditandai):
    """Tabel huruf lebar-sama (<pre>) Low/Peak per tahun: dolar, rupiah, tanggal, jarak dari harga sekarang.
    Lebar maks ±29 huruf supaya muat di layar HP. Tanda > menandai tahun yang sedang disentuh."""
    baris = [f"{'Tahun':<6} {'Low':<11} Peak"]
    for tahun, lo, lo_tgl, hi, hi_tgl in level:
        tanda = "&gt;" if tahun in ditandai else " "
        baris.append(f"{tanda}{tahun:<5} {uang(lo):<11} {uang(hi)}")
        if KURS_IDR:
            baris.append(f"{'':6} {rupiah_ringkas(lo * KURS_IDR[0]):<11} {rupiah_ringkas(hi * KURS_IDR[0])}")
        baris.append(f"{'':6} {tanggal(lo_tgl):<11} {tanggal(hi_tgl)}")
        # Emoji tampil selebar 2 huruf, jadi kolomnya dilebarkan 10 (bukan 11)
        rendah = f"{panah(lo, harga)} {persen(lo, harga)}"
        baris.append(f"{'':6} {rendah:<10} {panah(hi, harga)} {persen(hi, harga)}")
    return "<pre>" + "\n".join(baris) + "</pre>"


def baris_kaki(sekarang, sumber, k=None, sym=None):
    kaki = []
    if k:
        halaman = f"https://coinmarketcap.com/currencies/{k['halaman']}/"
        kaki.append(f'🔗 Sumber: CoinMarketCap · <a href="{halaman}">grafik {sym}</a> · '
                    f'<a href="{halaman}historical-data/">data harian</a>')
    kurs = f"1 USD = {rupiah(KURS_IDR[0])} · " if KURS_IDR else ""
    catatan = "" if sumber == "CoinMarketCap" else f" · harga: {sumber}"
    kaki.append(f"💱 <i>{kurs}{jam_wib(sekarang)}{catatan}</i>")
    return kaki


def susun_pesan(sym, k, harga, kejadian, level, fg, sekarang, sumber):
    """(bagian atas untuk keterangan foto, bagian bawah berisi tabel tahun dan sumber)."""
    atas = [label_fg(fg), "", f"🪙 <b>{sym}  {uang(harga)}</b>"]
    if KURS_IDR:
        atas.append(f"      ≈ {rupiah(harga * KURS_IDR[0])}")
    for x in kejadian:
        atas += ["", f"⚠️ {x['teks']}"]
    bawah_lv, atas_lv = level_terdekat(harga, level)
    if bawah_lv or atas_lv:
        atas += ["", "📍 <b>Level terdekat</b>"]
        atas += [f"   {panah(x[1], harga)} {x[0]}  {uang(x[1])}  ({persen(x[1], harga)})"
                 for x in (atas_lv, bawah_lv) if x]

    bawah = [f"📅 <b>Low &amp; Peak {sym} per tahun</b>",
             f"💰 Harga sekarang: <b>{usd_idr(harga)}</b>",
             tabel_level(level, harga, {x["tahun"] for x in kejadian})]
    bawah += baris_kaki(sekarang, sumber, k, sym)
    return "\n".join(atas), "\n".join(bawah)


def susun_ringkasan(koin, harga, riwayat, status, fg, sekarang, sumber, judul=True):
    baris = [label_fg(fg), ""] if judul else []
    for sym in koin:
        if sym not in harga:
            baris.append(f"<b>{sym}</b> harga tidak tersedia")
            continue
        st = status["koin"].get(sym) or status_awal(sekarang.year)
        bawah_lv, atas_lv = level_terdekat(harga[sym], daftar_level(riwayat["koin"].get(sym, {}), st, sekarang.year))
        detail = "  ".join(f"{panah(x[1], harga[sym])} {x[0]} {persen(x[1], harga[sym])}"
                           for x in (atas_lv, bawah_lv) if x)
        baris.append(f"🪙 <b>{sym}</b>  {usd_idr(harga[sym])}\n      {detail}")
    baris += ["", "🔄 /siklus untuk indikator siklus BTC"]
    return "\n".join(baris + baris_kaki(sekarang, sumber))


def buat_grafik(nama, *args):
    """Panggil grafik.<nama>(...); None bila matplotlib tidak ada atau gagal (pesan tetap terkirim)."""
    try:
        import grafik
        return getattr(grafik, nama)(*args)
    except Exception as e:
        print(f"[!] Grafik gagal dibuat: {type(e).__name__}: {e}")
        return None


def grafik_koin(sym, k, harga, kejadian, level, sekarang):
    return buat_grafik("grafik_koin", sym, harga, level, {x["tahun"] for x in kejadian}, sekarang.year,
                       ambil_harian(k["id"], sekarang), level_terdekat(harga, level), uang, BULAN)


# ---------------------------------------------------------------- Telegram
def telegram(metode, data=None, foto=None):
    """Panggil Bot API. Melempar RuntimeError berisi keterangan dari Telegram bila gagal."""
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        raise RuntimeError("TELEGRAM_TOKEN belum diisi")
    url = f"https://api.telegram.org/bot{token}/{metode}"  # jangan pernah dicetak: berisi token
    data = {k: v if isinstance(v, str) else json.dumps(v) for k, v in (data or {}).items()}
    if foto:
        batas = uuid.uuid4().hex
        bagian = [f'--{batas}\r\nContent-Disposition: form-data; name="{k}"\r\n\r\n{v}\r\n'.encode()
                  for k, v in data.items()]
        bagian.append(f'--{batas}\r\nContent-Disposition: form-data; name="photo"; filename="grafik.png"\r\n'
                      f"Content-Type: image/png\r\n\r\n".encode() + foto + b"\r\n")
        badan, kepala = b"".join(bagian) + f"--{batas}--\r\n".encode(), {
            "Content-Type": f"multipart/form-data; boundary={batas}"}
    else:
        badan, kepala = urllib.parse.urlencode(data).encode(), None
    try:
        hasil = ambil_json(url, data=badan, kepala=kepala)
    except urllib.error.HTTPError as e:
        try:
            keterangan = json.loads(e.read()).get("description", "")
        except Exception:
            keterangan = ""
        raise RuntimeError(f"HTTP {e.code} {keterangan}") from None
    except Exception as e:
        raise RuntimeError(type(e).__name__) from None
    if not hasil.get("ok"):
        raise RuntimeError(hasil.get("description", "gagal"))
    return hasil.get("result")


def kirim_teks(teks):
    try:
        telegram("sendMessage", {"chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""), "text": teks,
                                 "parse_mode": "HTML", "disable_web_page_preview": "true"})
        return True
    except RuntimeError as e:
        print(f"[!] Kirim Telegram gagal: {e}")
        return False


def kirim_foto(png, keterangan):
    try:
        telegram("sendPhoto", {"chat_id": os.environ.get("TELEGRAM_CHAT_ID", ""), "caption": keterangan,
                               "parse_mode": "HTML"}, foto=png)
        return True
    except RuntimeError as e:
        print(f"[!] Kirim foto Telegram gagal: {e}")
        return False


def kirim_laporan(atas, bawah, png, kering, nama_berkas):
    """Foto dengan keterangan `atas`, lalu pesan `bawah`. Tanpa foto: satu pesan teks."""
    if kering:
        print("-" * 60 + "\n" + atas + "\n\n" + bawah + "\n" + "-" * 60)
        if png:
            FOLDER_PRATINJAU.mkdir(exist_ok=True)
            (FOLDER_PRATINJAU / nama_berkas).write_bytes(png)
            print(f"(grafik: pratinjau/{nama_berkas})")
        return True
    lengkap = atas + ("\n\n" + bawah if bawah else "")
    if png:
        muat = len(atas) <= 1024  # batas keterangan foto di Telegram
        if kirim_foto(png, atas if muat else ""):
            return kirim_teks(bawah if muat else lengkap) if (bawah or not muat) else True
    return kirim_teks(lengkap)


def daftarkan_perintah(status):
    """Isi menu perintah bot (muncul saat mengetik /). Cukup sekali per versi."""
    if status.get("versi_perintah") == VERSI_PERINTAH:
        return
    try:
        telegram("setMyCommands", {"commands": [{"command": c, "description": d} for c, d in PERINTAH]})
        status["versi_perintah"] = VERSI_PERINTAH
    except RuntimeError as e:
        print(f"[!] Daftar perintah gagal: {e}")


def teks_daftar(koin):
    return "<b>Koin yang dipantau</b>\n" + "\n".join(
        f"• {sym} ({html.escape(k['nama'])})" for sym, k in koin.items())


def proses_perintah(koin, riwayat, status, antrean_cek):
    """Baca pesan baru ke bot. Hanya pesan dari TELEGRAM_CHAT_ID yang dilayani."""
    chat_id = os.environ.get("TELEGRAM_CHAT_ID")
    if not (chat_id and os.environ.get("TELEGRAM_TOKEN")):
        return
    try:
        pembaruan = telegram("getUpdates", {"offset": status.get("telegram_offset", 0), "timeout": 0,
                                            "allowed_updates": ["message"]})
    except RuntimeError as e:
        print(f"[!] Baca perintah Telegram gagal: {e}")
        return
    for u in pembaruan:
        status["telegram_offset"] = u["update_id"] + 1
        m = u.get("message") or {}
        if str(m.get("chat", {}).get("id")) != str(chat_id):
            continue
        kata = (m.get("text") or "").split()
        if not kata:
            continue
        perintah = kata[0].lstrip("/").split("@")[0].lower()
        argumen = [a.strip(",;") for a in kata[1:] if a.strip(",;")]
        print(f"Perintah: {perintah} {' '.join(argumen)}")

        if perintah in ("start", "bantuan", "help"):
            kirim_teks(BANTUAN)
        elif perintah == "daftar":
            petunjuk = (f"\n\nUntuk menambah koin, pakai /tambah {html.escape(' '.join(argumen))}"
                        if argumen else "")
            kirim_teks(teks_daftar(koin) + petunjuk)
        elif perintah == "cek":
            antrean_cek.update(a.upper() for a in argumen) if argumen else antrean_cek.add("*")
        elif perintah == "siklus":
            antrean_cek.update(f"#siklus:{a.upper()}" for a in argumen) if argumen else antrean_cek.add("#siklus")
        elif perintah == "acara":
            kirim_teks(strategi.perintah_acara(argumen, datetime.now(timezone.utc).date()))
        elif perintah == "tambah":
            if not argumen:
                kirim_teks("Tulis simbol koinnya, contoh: /tambah SOL")
            for a in argumen:
                try:
                    hasil = cari_koin(a)
                except Exception as e:
                    kirim_teks(f"Gagal mencari {html.escape(a)} di CoinMarketCap ({type(e).__name__}). Coba lagi nanti.")
                    continue
                if not hasil:
                    kirim_teks(f"❌ {html.escape(a)} tidak ditemukan di CoinMarketCap.")
                elif hasil[0] in koin:
                    kirim_teks(f"{hasil[0]} sudah dipantau.")
                else:
                    sym, k = hasil
                    koin[sym] = k
                    antrean_cek.add(sym)
                    kirim_teks(f"✅ {sym} ({html.escape(k['nama'])}) ditambahkan. Grafiknya menyusul.\n"
                               f'<a href="https://coinmarketcap.com/currencies/{k["halaman"]}/">Cek di CoinMarketCap</a>')
        elif perintah == "hapus":
            if not argumen:
                kirim_teks("Tulis simbol koinnya, contoh: /hapus XLM")
            for a in (a.upper() for a in argumen):
                if a not in koin:
                    kirim_teks(f"{html.escape(a)} tidak ada di daftar.")
                elif len(koin) == 1:
                    kirim_teks("Minimal harus ada satu koin yang dipantau.")
                else:
                    nama = koin.pop(a)["nama"]
                    riwayat["koin"].pop(a, None)
                    status["koin"].pop(a, None)
                    kirim_teks(f"🗑 {a} ({html.escape(nama)}) tidak dipantau lagi.")
        else:
            kirim_teks("Perintah tidak dikenal. Ketik /bantuan")


def tampilkan_chat_id():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        sys.exit("Isi dulu TELEGRAM_TOKEN.")
    hasil = telegram("getUpdates")
    chat = {u["message"]["chat"]["id"]: u["message"]["chat"] for u in hasil if "message" in u}
    if not chat:
        print("Belum ada pesan. Kirim pesan apa saja ke bot Anda di Telegram, lalu jalankan lagi.")
    for cid, c in chat.items():
        print(f"chat id: {cid}   ({c.get('first_name') or c.get('title', '')} {c.get('username', '')})")


# ---------------------------------------------------------------- Utama
def baca(berkas, bawaan):
    try:
        return json.loads(berkas.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return bawaan


def simpan(berkas, isi, urut=True):
    FOLDER_DATA.mkdir(exist_ok=True)
    berkas.write_text(json.dumps(isi, indent=1, sort_keys=urut, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = set(sys.argv[1:])
    if "--chat-id" in args:
        return tampilkan_chat_id()
    kering, tes = "--kering" in args, "--tes" in args
    normal = not (kering or tes)

    sekarang = datetime.now(timezone.utc)
    strategi.pasang(sys.modules[__name__])  # sebelum perintah Telegram (/acara memakai strategi)
    koin = baca(BERKAS_KOIN, None) or copy.deepcopy(KOIN_AWAL)
    riwayat = baca(BERKAS_RIWAYAT, {"diperbarui": None, "koin": {}})
    status = baca(BERKAS_STATUS, {"koin": {}})
    antrean_cek = set()  # "*" = ringkasan, atau simbol koin

    if normal:
        daftarkan_perintah(status)
        proses_perintah(koin, riwayat, status, antrean_cek)
        simpan(BERKAS_KOIN, koin, urut=False)  # urutan koin = urutan tampil di pesan

    perbarui_riwayat(riwayat, koin, sekarang)
    simpan(BERKAS_RIWAYAT, riwayat)

    harga, sumber = ambil_harga(koin)
    if not harga:
        if normal:
            simpan(BERKAS_STATUS, status)
        sys.exit("[!] Tidak ada harga yang berhasil diambil.")
    fg = ambil_fear_greed()
    gagal_kirim = False
    strategi.siapkan(koin, harga, riwayat, status, sekarang)

    # Fear & Greed: bergeser >= FG_LANGKAH poin, atau menyentuh ambang ekstrem
    fg_lalu = status.get("fg")
    fg_baru, alasan = periksa_fg(fg, status, sekarang)
    if alasan or (tes and fg):
        atas = "\n".join([label_fg(fg), ""] + [a if a.startswith("🚨") else f"⚠️ {a}" for a in alasan])
        png = buat_grafik("grafik_fg", fg["riwayat"], fg["skor"], fg["nama"],
                          fg_lalu["skor"] if alasan else None, fg["sumber"], BULAN)
        bawah = susun_ringkasan(koin, harga, riwayat, status, fg, sekarang, sumber, judul=False)
        if kirim_laporan(atas.strip(), bawah, png, kering, "fear_greed.png"):
            if fg_baru:
                status["fg"] = fg_baru
        else:
            gagal_kirim = True

    for sym, k in koin.items():
        if sym not in harga:
            continue
        # Status baru disimpan setelah pesannya terkirim, supaya peringatan yang gagal terkirim diulang.
        st = copy.deepcopy(status["koin"].get(sym) or status_awal(sekarang.year))
        rk = riwayat["koin"].get(sym, {})
        kejadian = periksa(sym, harga[sym], rk, st, sekarang)
        print(f"{sym:5} {uang(harga[sym]):>12}  {len(kejadian)} kejadian")
        if not (kejadian or tes or sym in antrean_cek):
            status["koin"][sym] = st
            continue
        level = daftar_level(rk, st, sekarang.year)
        atas, bawah = susun_pesan(sym, k, harga[sym], kejadian, level, fg, sekarang, sumber)
        awalan, baris_zona = strategi.keterangan_zona(sym, harga[sym], kejadian)
        atas = awalan + atas + (f"\n{baris_zona}" if baris_zona else "")
        png = grafik_koin(sym, k, harga[sym], kejadian, level, sekarang)
        if kirim_laporan(atas, bawah, png, kering, f"{sym}.png"):
            status["koin"][sym] = st
        else:
            gagal_kirim = True

    # Strategi: pasar anjlok/BELI UTAMA, zona mahal, euforia, kasus khusus, sell the news, jaringan, mingguan
    if strategi.jalankan(koin, harga, riwayat, status, fg, sekarang, kering, tes, antrean_cek):
        gagal_kirim = True

    for sym in {x for x in antrean_cek if not x.startswith("#")} - set(koin) - {"*"}:
        kirim_teks(f"{html.escape(sym)} tidak ada di daftar. Tambahkan dulu: /tambah {html.escape(sym)}")
    if "*" in antrean_cek:
        kirim_teks(susun_ringkasan(koin, harga, riwayat, status, fg, sekarang, sumber))

    if normal:
        simpan(BERKAS_STATUS, status)
    if gagal_kirim:
        sys.exit(1)


if __name__ == "__main__":
    main()
