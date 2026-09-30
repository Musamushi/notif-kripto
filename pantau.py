"""Pantau harga kripto di CoinMarketCap dan kirim peringatan ke Telegram.

Dijalankan berkala (GitHub Actions, tiap 15 menit). Setiap kali jalan:
1. ambil harga koin dan indeks Fear & Greed dari CoinMarketCap,
2. bandingkan dengan Low/Peak setiap tahun (dari riwayat harian CoinMarketCap),
3. kirim pesan Telegram bila harga menyentuh Low/Peak tahun-tahun sebelumnya,
   atau mencetak Low/Peak baru tahun ini.

Pemakaian:
    python pantau.py            jalan normal
    python pantau.py --kering   cetak pesan saja; tidak kirim, status tidak disimpan
    python pantau.py --tes      kirim ringkasan semua koin (uji Telegram)
    python pantau.py --chat-id  tampilkan chat id Telegram (setelah Anda chat ke bot)

Rahasia dibaca dari environment variable TELEGRAM_TOKEN dan TELEGRAM_CHAT_ID.
Hanya memakai pustaka bawaan Python, tidak perlu pip install.
"""
import calendar
import copy
import html
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ---------------------------------------------------------------- Pengaturan
KOIN = {"BTC": 1, "ETH": 1027, "XRP": 52, "LTC": 2, "ADA": 2010, "XLM": 512}  # id CoinMarketCap
# Nama halaman koin: https://coinmarketcap.com/currencies/<nama>/
HALAMAN = {"BTC": "bitcoin", "ETH": "ethereum", "XRP": "xrp", "LTC": "litecoin", "ADA": "cardano", "XLM": "stellar"}
TAHUN_MULAI = 2017          # tahun paling awal yang dipantau dan ditampilkan
TOLERANSI = 0.005           # dianggap "menyentuh" bila harga sedekat 0,5% dari level
JARAK_SIAGA_ULANG = 0.05    # level yang sudah dilaporkan baru aktif lagi setelah harga menjauh 5%
LANGKAH_LOW_BARU = 0.03     # selama terus mencetak Low/Peak baru, lapor lagi tiap bergerak 3% lagi
MIN_HARI_TAHUN_INI = 14     # awal Januari: Low/Peak baru tahun ini baru dilaporkan setelah ada 14 hari data
LAPOR_PEAK_TAHUN_INI = True   # False = hanya lapor Low baru tahun ini

WIB = timezone(timedelta(hours=7))
FOLDER_DATA = Path(__file__).resolve().parent / "data"
BERKAS_RIWAYAT = FOLDER_DATA / "riwayat.json"
BERKAS_STATUS = FOLDER_DATA / "status.json"
CMC = "https://api.coinmarketcap.com/data-api"
USD, IDR = "2781", "2794"  # id mata uang USD dan IDR di CoinMarketCap
KURS_IDR = None  # (rupiah per 1 USD, sumber); diisi ambil_harga()
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/124 Safari/537.36"}
BULAN = "Jan Feb Mar Apr Mei Jun Jul Agu Sep Okt Nov Des".split()


# ---------------------------------------------------------------- Ambil data
def ambil_json(url, data=None, coba=3):
    for ke in range(coba):
        try:
            req = urllib.request.Request(url, data=data, headers=UA)
            with urllib.request.urlopen(req, timeout=30) as r:
                return json.loads(r.read())
        except Exception:
            if ke == coba - 1:
                raise
            time.sleep(2 * (ke + 1))


def ambil_harga():
    """Harga USD tiap koin dan kurs USD->IDR. Utama CoinMarketCap, cadangan Yahoo Finance."""
    global KURS_IDR
    harga, sumber, kurs = {}, "CoinMarketCap", []
    try:
        ids = ",".join(str(i) for i in KOIN.values())
        j = ambil_json(f"{CMC}/v3/cryptocurrency/quote/latest?id={ids}&convertId={USD},{IDR}")
        per_id = {d["id"]: d for d in j["data"]}
        for sym, id_koin in KOIN.items():
            d = per_id.get(id_koin)
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
    for sym in KOIN:
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
    """(skor, keterangan, sumber). Utama CoinMarketCap, cadangan alternative.me."""
    try:
        akhir = int(time.time())
        j = ambil_json(f"{CMC}/v3/fear-greed/chart?start={akhir - 3 * 86400}&end={akhir}")
        d = j["data"]["dataList"][-1]
        return int(d["score"]), d["name"], "CoinMarketCap"
    except Exception as e:
        print(f"[!] Fear & Greed CoinMarketCap gagal: {e}")
    try:
        d = ambil_json("https://api.alternative.me/fng/?limit=1")["data"][0]
        return int(d["value"]), d["value_classification"], "alternative.me"
    except Exception as e:
        print(f"[!] Fear & Greed alternative.me juga gagal: {e}")
        return None


def ambil_tahun(id_koin, tahun, sekarang):
    """Low dan Peak satu tahun dari candle harian CoinMarketCap (None bila belum ada data)."""
    awal = calendar.timegm((tahun, 1, 1, 0, 0, 0))
    akhir = min(calendar.timegm((tahun, 12, 31, 23, 59, 59)), int(sekarang.timestamp()))
    j = ambil_json(f"{CMC}/v3.1/cryptocurrency/historical?id={id_koin}&convertId={USD}"
                   f"&timeStart={awal}&timeEnd={akhir}&interval=1d")
    baris = [q for q in j["data"]["quotes"] if q["timeOpen"].startswith(str(tahun))]
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


def perbarui_riwayat(riwayat, sekarang):
    """Tahun lampau cukup diambil sekali; tahun berjalan diperbarui sekali sehari."""
    hari_ini = sekarang.strftime("%Y-%m-%d")
    semua_berhasil = True
    for sym, id_koin in KOIN.items():
        rk = riwayat["koin"].setdefault(sym, {})
        for tahun in range(TAHUN_MULAI, sekarang.year + 1):
            ent = rk.get(str(tahun))
            if ent and ent.get("lengkap"):
                continue
            if tahun == sekarang.year and ent and riwayat.get("diperbarui") == hari_ini:
                continue
            try:
                rk[str(tahun)] = ambil_tahun(id_koin, tahun, sekarang)
                time.sleep(0.3)
            except Exception as e:
                semua_berhasil = False
                print(f"[!] Riwayat {sym} {tahun} gagal: {e}")
    if semua_berhasil:
        riwayat["diperbarui"] = hari_ini


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
                                 f"{jenis.capitalize()} baru {tahun_ini}! "
                                 f"(sebelumnya {usd_idr(ref[0])}, {tanggal(ref[1])})"})
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
                gerak = "turun" if lv["sisi"] == "atas" else "naik"
                kejadian.append({"tahun": tahun, "teks":
                                 f"Harga {gerak} menyentuh <b>{nama}</b> ({usd_idr(nilai)})"})
                lv["siaga"] = False
            elif not lv["siaga"] and jarak >= JARAK_SIAGA_ULANG:
                lv["siaga"] = True
            lv["sisi"] = sisi
    return kejadian


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
    """Dolar diikuti rupiahnya (kurs hari ini), misalnya $1.5285 / Rp27.423."""
    return f"{uang(x)} / {rupiah(x * KURS_IDR[0])}" if KURS_IDR else uang(x)


def tanggal(iso):
    return f"{iso[8:10]} {BULAN[int(iso[5:7]) - 1]}"


def label_fg(fg):
    if not fg:
        return "Fear &amp; Greed: tidak tersedia"
    skor, nama, sumber = fg
    emoji = "😱" if skor < 25 else "😨" if skor < 45 else "😐" if skor <= 55 else "🙂" if skor <= 75 else "🤑"
    catatan = "" if sumber == "CoinMarketCap" else f" <i>({sumber})</i>"
    return f"{emoji} <b>Fear &amp; Greed: {skor}/100 ({html.escape(nama)})</b>{catatan}"


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


def susun_pesan(sym, harga, kejadian, rk, st, fg, sekarang, sumber):
    level = daftar_level(rk, st, sekarang.year)
    ditandai = {k["tahun"] for k in kejadian}
    baris = [label_fg(fg), "", f"<b>{sym}  {usd_idr(harga)}</b>"]
    baris += [f"⚠️ {k['teks']}" for k in kejadian]

    semua = [(f"Low {t}", lo) for t, lo, _, _, _ in level] + [(f"Peak {t}", hi) for t, _, _, hi, _ in level]
    # Pakai < dan >: Low/Peak tahun ini yang baru saja tercipta sama dengan harga, jadi tidak ikut
    bawah = max((x for x in semua if x[1] < harga), key=lambda x: x[1], default=None)
    atas = min((x for x in semua if x[1] > harga), key=lambda x: x[1], default=None)
    terdekat = []
    if bawah:
        terdekat.append(f"↓ {bawah[0]} {usd_idr(bawah[1])} ({(bawah[1] / harga - 1) * 100:+.1f}%)")
    if atas:
        terdekat.append(f"↑ {atas[0]} {usd_idr(atas[1])} ({(atas[1] / harga - 1) * 100:+.1f}%)")
    if terdekat:
        baris.append("Terdekat:\n" + "\n".join(terdekat))

    baris.append("")
    for tahun, lo, lo_tgl, hi, hi_tgl in level:
        tanda = "👉 " if tahun in ditandai else ""
        baris.append(f"{tanda}[Low {tahun}] {usd_idr(lo)} ({tanggal(lo_tgl)}) - "
                     f"[Peak {tahun}] {usd_idr(hi)} ({tanggal(hi_tgl)})")
    baris.append("")
    halaman = f"https://coinmarketcap.com/currencies/{HALAMAN.get(sym, sym.lower())}/"
    baris.append(f"📊 Sumber Low/Peak: CoinMarketCap, data harian (high/low per hari) · "
                 f'<a href="{halaman}">grafik {sym}</a> · <a href="{halaman}historical-data/">data harian</a>')
    if KURS_IDR:
        baris.append(f"<i>Kurs hari ini: 1 USD = {rupiah(KURS_IDR[0])} ({KURS_IDR[1]})</i>")
    baris.append(f"<i>{sekarang.astimezone(WIB):%d-%m-%Y %H:%M} WIB · harga sekarang: {sumber}</i>")
    return "\n".join(baris)


# ---------------------------------------------------------------- Telegram
def kirim_telegram(teks):
    token, chat_id = os.environ.get("TELEGRAM_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not token or not chat_id:
        print("[!] TELEGRAM_TOKEN / TELEGRAM_CHAT_ID belum diisi, pesan tidak terkirim.")
        return False
    data = urllib.parse.urlencode({"chat_id": chat_id, "text": teks, "parse_mode": "HTML",
                                   "disable_web_page_preview": "true"}).encode()
    try:
        # Jangan cetak URL-nya: di dalamnya ada token.
        return bool(ambil_json(f"https://api.telegram.org/bot{token}/sendMessage", data=data).get("ok"))
    except Exception as e:
        print(f"[!] Kirim Telegram gagal: {type(e).__name__} {getattr(e, 'code', '')}")
        return False


def tampilkan_chat_id():
    token = os.environ.get("TELEGRAM_TOKEN")
    if not token:
        sys.exit("Isi dulu TELEGRAM_TOKEN.")
    hasil = ambil_json(f"https://api.telegram.org/bot{token}/getUpdates").get("result", [])
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


def simpan(berkas, isi):
    FOLDER_DATA.mkdir(exist_ok=True)
    berkas.write_text(json.dumps(isi, indent=1, sort_keys=True, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    args = set(sys.argv[1:])
    if "--chat-id" in args:
        return tampilkan_chat_id()
    kering, tes = "--kering" in args, "--tes" in args

    sekarang = datetime.now(timezone.utc)
    riwayat = baca(BERKAS_RIWAYAT, {"diperbarui": None, "koin": {}})
    status = baca(BERKAS_STATUS, {"koin": {}})

    perbarui_riwayat(riwayat, sekarang)
    simpan(BERKAS_RIWAYAT, riwayat)

    harga, sumber = ambil_harga()
    if not harga:
        sys.exit("[!] Tidak ada harga yang berhasil diambil.")
    fg = ambil_fear_greed()

    gagal_kirim = False
    for sym in KOIN:
        if sym not in harga:
            continue
        # Status baru disimpan setelah pesannya terkirim, supaya peringatan yang gagal terkirim diulang.
        st = copy.deepcopy(status["koin"].get(sym) or status_awal(sekarang.year))
        rk = riwayat["koin"].get(sym, {})
        kejadian = periksa(sym, harga[sym], rk, st, sekarang)
        print(f"{sym:4} {uang(harga[sym]):>12}  {len(kejadian)} kejadian")
        if not (kejadian or tes):
            status["koin"][sym] = st
            continue
        pesan = susun_pesan(sym, harga[sym], kejadian, rk, st, fg, sekarang, sumber)
        if kering:
            print("-" * 60 + "\n" + pesan + "\n" + "-" * 60)
        elif kirim_telegram(pesan):
            status["koin"][sym] = st
        else:
            gagal_kirim = True

    if not (kering or tes):
        simpan(BERKAS_STATUS, status)
    if gagal_kirim:
        sys.exit(1)


if __name__ == "__main__":
    main()
