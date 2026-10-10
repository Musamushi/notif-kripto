"""Strategi tambahan untuk pantau.py. Semua ambang di sini berasal dari uji data CoinMarketCap 2017-2026.

- Zona harga murah/mahal per koin (laporan /siklus berupa gambar).
- PASAR ANJLOK: BTC turun >= 40% dari harga tertinggi 12 bulan (pulih bila kembali di atas -35%).
  Selama pasar anjlok: BELI UTAMA saat koin masuk zona murah EKSTREM, lengkap dengan perkiraan
  masih bisa turun (pasti kena -12% / estimasi -49% / rendah -75%, dari 15 kasus sejak 2018).
- Jual: masuk zona mahal (Aman/Estimasi/Tinggi), euforia volume (hanya di zona mahal),
  sell the news (kalender acara, H-7 bila harga sudah naik >= 30% dalam 60 hari).
  JUAL KUAT (menyentuh Peak tahunan di zona mahal) ditempelkan ke laporan Low/Peak lewat keterangan_zona().
- Kasus khusus koin: turun >= 25% lebih dalam dari BTC dalam 7 hari + volume >= 2x (XRP-SEC 2020, SOL-FTX 2022).
- Kesehatan jaringan bulanan: penggunaan (TVL DefiLlama dalam jumlah koin) turun >= 30% dalam 12 bulan.
- Ringkasan mingguan: Senin pagi WIB.

pantau.py memanggil pasang() sekali, siapkan() sebelum laporan Low/Peak, lalu jalankan() sesudahnya.
"""
import html
import json
import math
import re
from datetime import date, datetime, timedelta

P = None  # modul pantau; diisi pasang()

# ---------------------------------------------------------------- Pengaturan
# Tahun puncak tiap siklus & kapan puncaknya dianggap sudah lewat (±21 bulan sesudah halving).
SIKLUS = [
    {"nama": "2017", "tahun": (2017, 2018), "selesai": date(2018, 4, 10)},
    {"nama": "2021", "tahun": (2020, 2021), "selesai": date(2022, 2, 8)},
    {"nama": "2025", "tahun": (2024, 2025), "selesai": date(2026, 1, 20)},
    {"nama": "2029", "tahun": (2028, 2029), "selesai": date(2030, 1, 15)},  # perkiraan: halving ±Apr 2028
]
# (dasar, puncak) siklus BTC yang sudah selesai; tambahkan siklus 2029 bila sudah lewat.
BTC_SEJARAH = [(171.51, 20089), (3191, 68790), (15599, 126198)]
MURAH_ALT = (0.30, 0.20, 0.12)   # x puncak siklus terakhir koin itu: Aman, Estimasi, Ekstrem
MURAH_BTC = (1.00, 0.81, 0.70)   # x puncak siklus SEBELUMNYA (BTC)
MAHAL = (0.85, 1.00, 1.07)       # x perkiraan puncak berikut: Aman, Estimasi, Tinggi
TINGKAT_MURAH = ("Aman", "Estimasi", "Ekstrem")
TINGKAT_MAHAL = ("Aman", "Estimasi", "Tinggi")
JARAK_ULANG_ZONA = 0.10          # tingkat zona mahal aktif lagi setelah harga menjauh 10%
ANJLOK_MULAI, ANJLOK_PULIH = -0.40, -0.35
TURUN_LAGI = (("pasti kena", -0.12, "terjadi di semua 15 kasus"),   # 15 kasus sejak 2018
              ("estimasi", -0.49, "kasus tengah"),
              ("rendah", -0.75, "±1 dari 4 kasus"))
EUFORIA_VOLUME, EUFORIA_NAIK = 2.5, 0.50
KASUS_SELISIH, KASUS_VOLUME = 0.25, 2.0
SELL_NEWS_NAIK = 0.30
JEDA_ULANG_HARI = 30
JARINGAN_TURUN = -0.30
# Nama jaringan di DefiLlama. XRP sengaja ditulis manual: simbol XRP di DefiLlama menunjuk "XRPL EVM".
RANTAI = {"ETH": "Ethereum", "SOL": "Solana", "ADA": "Cardano", "XRP": "XRPL", "XLM": "Stellar"}
TANPA_RANTAI = {"BTC", "LTC"}    # TVL DeFi tidak mencerminkan penggunaan koin ini
KATA_BURUK = re.compile(r"lawsuit|\bsue[sd]?\b|SEC (charges|sues)|\bcharged\b|\bhack|exploit|drain|stolen|delist|"
                        r"bankrupt|insolven|halt(s|ed)? (withdraw|trading|network|block)|outage|fraud|collapse", re.I)
ACARA_AWAL = [
    {"tanggal": "2026-10-31", "koin": "SOL", "nama": "Upgrade Alpenglow (Agave 4.3)", "perkiraan": True},
    {"tanggal": "2026-12-10", "koin": "ETH", "nama": "Upgrade Glamsterdam", "perkiraan": True},
    {"tanggal": "2027-01-31", "koin": "ADA", "nama": "Hard fork Dijkstra", "perkiraan": True},
    {"tanggal": "2027-07-28", "koin": "LTC", "nama": "Halving LTC", "perkiraan": True},
    {"tanggal": "2028-04-17", "koin": "BTC", "nama": "Halving BTC", "perkiraan": True},
]

ZONA = {}     # sym -> zona hasil hitung_zona() untuk run ini
HARIAN = {}   # sym -> [(datetime, close)] 365 hari, bila sudah diambil di run ini


def pasang(modul_pantau):
    global P
    P = modul_pantau


def berkas_acara():
    return P.FOLDER_DATA / "acara.json"


# ---------------------------------------------------------------- Zona
def puncak_siklus(rk, siklus):
    """(nilai, tanggal) Peak tertinggi di tahun-tahun puncak siklus itu, dari riwayat Low/Peak tahunan."""
    calon = [(rk[str(t)]["peak"], rk[str(t)]["peak_tgl"]) for t in siklus["tahun"]
             if rk.get(str(t)) and not rk[str(t)].get("kosong")]
    return max(calon) if calon else None


def dasar_antara(rk, sesudah, sampai, tambahan=()):
    """Low tahunan terendah yang tanggalnya > sesudah dan <= sampai (tanggal iso), plus nilai tambahan."""
    calon = [e["low"] for e in rk.values() if not e.get("kosong") and sesudah < e["low_tgl"] <= sampai]
    calon += [x for x in tambahan if x]
    return min(calon) if calon else None


def siklus_aktif(hari):
    """(siklus terakhir yang puncaknya sudah lewat, siklus sebelumnya)."""
    selesai = [s for s in SIKLUS if s["selesai"] <= hari]
    return selesai[-1], (selesai[-2] if len(selesai) > 1 else None)


def rumus_btc():
    """Puncak = a x Dasar^k dari siklus BTC yang sudah selesai (cocok ±3% untuk 2017/2021/2025)."""
    lx = [math.log(d) for d, _ in BTC_SEJARAH]; ly = [math.log(p) for _, p in BTC_SEJARAH]
    mx, my = sum(lx) / len(lx), sum(ly) / len(ly)
    k = sum((a - mx) * (b - my) for a, b in zip(lx, ly)) / sum((a - mx) ** 2 for a in lx)
    return math.exp(my - k * mx), k


def hitung_zona(sym, rk, hari, harga, low_teramati=None, susut=None):
    """Zona murah [Aman, Estimasi, Ekstrem] & mahal [Aman, Estimasi, Tinggi]; None bila data belum cukup."""
    s, s_lalu = siklus_aktif(hari)
    pk = puncak_siklus(rk, s)
    pk_lalu = puncak_siklus(rk, s_lalu) if s_lalu else None
    if not pk:
        return None
    dasar = dasar_antara(rk, pk[1], hari.isoformat(), (harga, low_teramati))
    if sym == "BTC":
        if not pk_lalu:
            return None
        a, k = rumus_btc()
        est = a * dasar ** k
        return {"puncak": pk[0], "puncak_tgl": pk[1], "siklus": s["nama"], "dasar": dasar,
                "murah": [pk_lalu[0] * f for f in MURAH_BTC], "mahal": [est * f for f in MAHAL],
                "susut": (est / dasar) / (BTC_SEJARAH[-1][1] / BTC_SEJARAH[-1][0])}
    murah = [pk[0] * f for f in MURAH_ALT]
    kelipatan = None
    if pk_lalu:
        b0 = dasar_antara(rk, pk_lalu[1], pk[1])
        kelipatan = pk[0] / b0 if b0 else None
    cara_b = pk[0]                                    # puncak siklus terakhir sering jadi "atap"
    cara_a = min(dasar * kelipatan * (susut or 0.5), 2 * pk[0]) if kelipatan else cara_b
    aman = max(min(cara_a, cara_b) * MAHAL[0], murah[0] * 1.5)   # zona mahal minimal 50% di atas zona murah
    est = max(math.sqrt(cara_a * cara_b), aman * 1.15)
    return {"puncak": pk[0], "puncak_tgl": pk[1], "siklus": s["nama"], "dasar": dasar, "murah": murah,
            "mahal": [aman, est, max(cara_a, cara_b, est) * MAHAL[2]]}


def posisi(z, harga):
    """('murah', i) / ('mahal', i) / ('normal', None)."""
    if harga <= z["murah"][0]:
        return "murah", max(i for i, x in enumerate(z["murah"]) if harga <= x)
    if harga >= z["mahal"][0]:
        return "mahal", max(i for i, x in enumerate(z["mahal"]) if harga >= x)
    return "normal", None


def label_posisi(z, harga):
    jenis, i = posisi(z, harga)
    if jenis == "murah":
        return f"murah {TINGKAT_MURAH[i]}"
    if jenis == "mahal":
        return f"mahal {TINGKAT_MAHAL[i]}"
    return "normal"


def keterangan_zona(sym, harga, kejadian):
    """(awalan JUAL KUAT, baris zona) untuk ditempel ke laporan Low/Peak lama."""
    z = ZONA.get(sym)
    if not z:
        return "", ""
    jenis, _ = posisi(z, harga)
    awalan = ""
    if jenis == "mahal" and any("Peak" in k["teks"] for k in kejadian):
        awalan = ("⚠️ <b>JUAL KUAT</b> · menyentuh Peak tahunan saat di zona mahal "
                  "(historis 84% turun dalam 90 hari)\n\n")
    return awalan, f"📍 Zona: <b>{label_posisi(z, harga)}</b>"


# ---------------------------------------------------------------- Data harian
def ambil_metrik(id_koin, sekarang):
    """Ringkasan candle harian ±400 hari: Mayer, volume, kenaikan, tertinggi 12 bulan."""
    q = P.ambil_candle(id_koin, int(sekarang.timestamp()))
    baris = [(date.fromisoformat(x["timeOpen"][:10]), x["quote"]["high"], x["quote"]["low"], x["quote"]["close"],
              x["quote"].get("volume") or 0) for x in q]
    baris = [b for b in baris if b[0] < sekarang.date()]   # hanya hari yang sudah selesai
    c = [b[3] for b in baris]; v = [b[4] for b in baris]; n = len(c)

    def naik(h):
        return c[-1] / c[-1 - h] - 1 if n > h else None

    def rasio(baru, lama):
        return (sum(v[-baru:]) / baru) / (sum(v[-baru - lama:-baru]) / lama) if n >= baru + lama and sum(v[-baru - lama:-baru]) else None

    metrik = {"hari": baris[-1][0].isoformat(), "tutup": c[-1],
              "mayer": c[-1] / (sum(c[-200:]) / 200) if n >= 200 else None,
              "naik7": naik(7), "naik30": naik(30), "naik60": naik(60),
              "vol7_90": rasio(7, 90), "vol7_365": rasio(7, 365),
              "tinggi12": max(b[1] for b in baris[-365:]), "tutup365": c[-366] if n > 365 else None}
    return metrik, [(datetime(b[0].year, b[0].month, b[0].day), b[3]) for b in baris[-365:]]


def harian(sym, koin, sekarang):
    if sym not in HARIAN:
        k = koin.get(sym) or P.KOIN_AWAL.get(sym)
        HARIAN[sym] = P.ambil_harian(k["id"], sekarang) if k else []
    return HARIAN[sym]


def siapkan(koin, harga, riwayat, status, sekarang):
    """Perbarui ringkasan harian (sekali sehari) dan hitung zona semua koin untuk run ini."""
    st = status.setdefault("strategi", {})
    daftar = list(koin) + ([] if "BTC" in koin else ["BTC"])   # BTC selalu dibutuhkan (pasar anjlok, rumus)
    if "BTC" not in riwayat["koin"]:
        P.perbarui_riwayat(riwayat, {"BTC": P.KOIN_AWAL["BTC"]}, sekarang)
    kemarin = (sekarang.date() - timedelta(days=1)).isoformat()
    metrik = st.setdefault("metrik", {})
    for sym in list(metrik):
        if sym not in daftar:
            metrik.pop(sym)
    kurang = st.get("metrik_hari", "") < kemarin or any(s not in metrik for s in daftar)
    if kurang and st.get("metrik_dicoba", "") < (sekarang - timedelta(hours=1)).isoformat():
        st["metrik_dicoba"] = sekarang.isoformat()
        for sym in daftar:
            k = koin.get(sym) or P.KOIN_AWAL.get(sym)
            try:
                metrik[sym], HARIAN[sym] = ambil_metrik(k["id"], sekarang)
            except Exception as e:
                print(f"[!] Data harian {sym} gagal: {e}")
        if all(s in metrik for s in daftar):
            st["metrik_hari"] = min(metrik[s]["hari"] for s in daftar)

    ZONA.clear()
    hari = sekarang.date()
    btc_harga = harga.get("BTC") or metrik.get("BTC", {}).get("tutup")
    z_btc = None
    if btc_harga and riwayat["koin"].get("BTC"):
        z_btc = hitung_zona("BTC", riwayat["koin"]["BTC"], hari, btc_harga,
                            ((status["koin"].get("BTC") or {}).get("low_teramati") or [None])[0])
    for sym in koin:
        h = harga.get(sym)
        rk = riwayat["koin"].get(sym)
        if not (h and rk):
            continue
        teramati = (status["koin"].get(sym) or {}).get("low_teramati") or [None]
        z = z_btc if sym == "BTC" else hitung_zona(sym, rk, hari, h, teramati[0], z_btc and z_btc["susut"])
        if z:
            ZONA[sym] = z
    st["zona"] = {s: {k: (round(v, 8) if isinstance(v, float) else [round(x, 8) for x in v] if isinstance(v, list) else v)
                      for k, v in z.items()} for s, z in ZONA.items()}


# ---------------------------------------------------------------- Pesan & gambar
def rp(x):
    """Rupiah ringkas untuk gambar: Rp27.346, Rp44,6 jt, Rp1,48 M."""
    return P.rupiah_ringkas(x * P.KURS_IDR[0]) if P.KURS_IDR else "-"


def gambar_koin(sym, koin, harga, sekarang, lencana, warna, baris_ekstra=(), catatan=""):
    z = ZONA.get(sym)
    if not z:
        return None
    return P.buat_grafik("grafik_zona", sym, harga, z, harian(sym, koin, sekarang), lencana, warna, list(baris_ekstra),
                         catatan, P.uang, rp, P.BULAN, TINGKAT_MURAH, TINGKAT_MAHAL)


def baris_fg_mayer(sym, fg, metrik):
    ekstra = []
    if fg:
        ekstra.append(("Fear & Greed", f"{fg['skor']}/100", fg["nama"]))
    mb = metrik.get("BTC", {}).get("mayer"); mk = metrik.get(sym, {}).get("mayer")
    if mb and mk:
        ekstra.append(("Mayer BTC · koin", f"{mb:.2f} · {mk:.2f}", "harga dibagi rata-rata 200 hari"))
    return ekstra


def kirim(judul, png, kering, berkas):
    return P.kirim_laporan(judul, "", png, kering, berkas)


def tabel_semua(koin, harga, sekarang, judul, subjudul, tambahan, catatan, anjlok=False):
    kolom = [("Koin", 0.05, "left"), ("Sekarang", 0.34, "right"),
             ("Beli utama (Ekstrem)" if anjlok else "Murah (Ekstrem)", 0.58, "right"),
             ("Jarak" if anjlok else "Mahal (estimasi)", 0.78, "right"), ("Posisi", 0.96, "right")]
    baris = []
    for sym in koin:
        z = ZONA.get(sym); h = harga.get(sym)
        if not (z and h):
            baris.append([(sym, None, True), ("data belum cukup", "#475569", False), ("", None, False), ("", None, False),
                          ("", None, False)])
            continue
        jenis, _ = posisi(z, h)
        warna = {"murah": "#16a34a", "mahal": "#dc2626"}.get(jenis, "#475569")
        eks = z["murah"][2]
        baris.append([(sym, None, True), (f"{P.uang(h)}\n{rp(h)}", None, False),
                      (f"{P.uang(eks)}\n{rp(eks)}", "#16a34a", False),
                      (f"{(eks / h - 1) * 100:+.0f}%", "#16a34a", True) if anjlok else
                      (f"{P.uang(z['mahal'][1])}\n{rp(z['mahal'][1])}", "#dc2626", False),
                      (label_posisi(z, h).replace(" ", "\n"), warna, True)])
    return P.buat_grafik("grafik_tabel", judul, subjudul, kolom, baris, catatan, tambahan)


# ---------------------------------------------------------------- Acara (sell the news)
def baca_acara():
    try:
        return json.loads(berkas_acara().read_text(encoding="utf-8"))
    except FileNotFoundError:
        return [dict(a) for a in ACARA_AWAL]


def simpan_acara(acara):
    acara.sort(key=lambda a: a["tanggal"])
    P.FOLDER_DATA.mkdir(exist_ok=True)
    berkas_acara().write_text(json.dumps(acara, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def teks_acara(acara, hari, batas_hari=None):
    mendatang = [a for a in acara if a["tanggal"] >= hari.isoformat()
                 and (batas_hari is None or a["tanggal"] <= (hari + timedelta(days=batas_hari)).isoformat())]
    return [f"{a['tanggal']}{' (perkiraan)' if a.get('perkiraan') else ''} · {a['koin']} · {a['nama']}" for a in mendatang]


def perintah_acara(argumen, hari):
    """/acara, /acara tambah 2027-07-28 LTC Halving LTC, /acara hapus 3. Mengembalikan teks balasan."""
    acara = baca_acara()
    if not argumen:
        daftar = teks_acara(acara, hari)
        if not daftar:
            return "Belum ada acara mendatang. Tambah: /acara tambah 2027-07-28 LTC Halving LTC"
        return ("<b>Acara mendatang</b> (sell the news dicek H-7)\n" +
                "\n".join(f"{i}. {html.escape(t)}" for i, t in enumerate(daftar, 1)) +
                "\n\nTambah: /acara tambah YYYY-MM-DD KOIN nama acara\nHapus: /acara hapus NOMOR")
    aksi = argumen[0].lower()
    if aksi == "tambah" and len(argumen) >= 4:
        try:
            tgl = date.fromisoformat(argumen[1])
        except ValueError:
            return "Format tanggal harus YYYY-MM-DD, contoh: /acara tambah 2027-07-28 LTC Halving LTC"
        baru = {"tanggal": tgl.isoformat(), "koin": argumen[2].upper(), "nama": " ".join(argumen[3:]), "perkiraan": False}
        acara.append(baru)
        simpan_acara(acara)
        return f"✅ Acara ditambahkan: {html.escape(baru['tanggal'])} · {html.escape(baru['koin'])} · {html.escape(baru['nama'])}"
    if aksi == "hapus" and len(argumen) == 2 and argumen[1].isdigit():
        mendatang = [a for a in acara if a["tanggal"] >= hari.isoformat()]
        i = int(argumen[1]) - 1
        if not 0 <= i < len(mendatang):
            return "Nomor acara tidak ada. Lihat daftarnya dengan /acara"
        acara.remove(mendatang[i])
        simpan_acara(acara)
        return f"🗑 Acara dihapus: {html.escape(mendatang[i]['nama'])}"
    return "Contoh: /acara · /acara tambah 2027-07-28 LTC Halving LTC · /acara hapus 2"


# ---------------------------------------------------------------- Jaringan & berita
def berita_buruk(id_koin, jumlah=3):
    """Judul berita CoinMarketCap terbaru yang mengandung kata kunci buruk: [(judul, url)]."""
    try:
        data = P.ambil_json(f"https://api.coinmarketcap.com/content/v3/news?coins={id_koin}&page=1&size=40")["data"]
    except Exception as e:
        print(f"[!] Berita gagal: {e}")
        return []
    hasil = [(b["meta"]["title"], b["meta"].get("sourceUrl", "")) for b in data if KATA_BURUK.search(b["meta"]["title"])]
    return hasil[:jumlah]


_RANTAI_LLAMA = None


def nama_rantai(sym):
    global _RANTAI_LLAMA
    if sym in TANPA_RANTAI:
        return None
    if sym in RANTAI:
        return RANTAI[sym]
    if _RANTAI_LLAMA is None:
        try:
            _RANTAI_LLAMA = {c.get("tokenSymbol"): c["name"] for c in P.ambil_json("https://api.llama.fi/v2/chains")}
        except Exception:
            _RANTAI_LLAMA = {}
    return _RANTAI_LLAMA.get(sym)


def penggunaan_jaringan(sym, metrik):
    """Perubahan TVL dalam JUMLAH KOIN selama 12 bulan (bebas dari efek naik-turun harga), atau None."""
    rantai = nama_rantai(sym)
    m = metrik.get(sym) or {}
    if not (rantai and m.get("tutup365")):
        return None
    data = P.ambil_json(f"https://api.llama.fi/v2/historicalChainTvl/{rantai.replace(' ', '%20')}")
    if len(data) < 370:
        return None
    sekarang_tvl = data[-1]["tvl"]
    target = data[-1]["date"] - 365 * 86400
    lalu_tvl = min(data, key=lambda x: abs(x["date"] - target))["tvl"]
    if not lalu_tvl:
        return None
    return {"rantai": rantai, "tvl": sekarang_tvl, "tvl_lalu": lalu_tvl,
            "asli": (sekarang_tvl / m["tutup"]) / (lalu_tvl / m["tutup365"]) - 1,
            "dolar": sekarang_tvl / lalu_tvl - 1, "harga": m["tutup"] / m["tutup365"] - 1}


# ---------------------------------------------------------------- Pemeriksaan utama
def jalankan(koin, harga, riwayat, status, fg, sekarang, kering, tes, antrean):
    """Kirim semua sinyal strategi. Mengembalikan True bila ada pesan yang gagal terkirim."""
    st = status.setdefault("strategi", {})
    metrik = st.get("metrik", {})
    hari = sekarang.date()
    gagal = False
    ekstra_umum = {sym: baris_fg_mayer(sym, fg, metrik) for sym in koin}
    jaringan = st.setdefault("jaringan", {"bulan": "", "melemah": {}})

    # 1) Pasar anjlok / pulih
    an = st.setdefault("anjlok", {"aktif": False, "beli": []})
    btc = harga.get("BTC") or metrik.get("BTC", {}).get("tutup")
    tinggi = max(metrik.get("BTC", {}).get("tinggi12") or 0, btc or 0)
    turun = btc / tinggi - 1 if btc and tinggi else 0
    if not an["aktif"] and turun <= ANJLOK_MULAI:
        judul = (f"🚨 <b>PASAR ANJLOK</b>: BTC {P.usd_idr(btc)} turun {turun * 100:.0f}% dari tertinggi 12 bulan\n"
                 "Sinyal BELI UTAMA aktif saat koin masuk zona murah Ekstrem.")
        png = tabel_semua(koin, harga, sekarang, "Pasar anjlok: batas beli utama",
                          f"BTC {P.uang(btc)} ({turun * 100:.0f}% dari tertinggi 12 bulan)", [],
                          "Historis: harga masih turun lagi median -44% setelah sinyal Ekstrem; untuk jangka 1 tahun+. "
                          "Bukan saran keuangan.", anjlok=True)
        if kirim(judul, png, kering, "pasar_anjlok.png"):
            an.update(aktif=True, mulai=hari.isoformat(), beli=[])
        else:
            gagal = True
    elif an["aktif"] and turun >= ANJLOK_PULIH:
        if kirim(f"✅ <b>PASAR PULIH</b>: BTC {P.usd_idr(btc)} ({turun * 100:.0f}% dari tertinggi 12 bulan). "
                 "Sinyal beli utama berhenti.", None, kering, "-"):
            an["aktif"] = False
        else:
            gagal = True

    harian_baru = st.get("cek_harian") != st.get("metrik_hari")
    for sym in koin:
        z = ZONA.get(sym); h = harga.get(sym); m = metrik.get(sym, {})
        if not (z and h):
            continue
        melemah = jaringan["melemah"].get(sym)
        catatan_jaringan = ([("Jaringan", "MELEMAH", f"penggunaan {melemah * 100:+.0f}% dalam 12 bulan")] if melemah else [])

        # 2) BELI UTAMA: pasar anjlok + zona murah Ekstrem (sekali per koin per masa anjlok)
        if an["aktif"] and h <= z["murah"][2] and sym not in an["beli"]:
            turun_lagi = [] if sym == "BTC" else [
                (f"Masih bisa turun · {nama}", f"{P.uang(z['murah'][2] * (1 + p))} · {rp(z['murah'][2] * (1 + p))}",
                 f"{p * 100:.0f}% di bawah Ekstrem; {ket}") for nama, p, ket in TURUN_LAGI]
            png = gambar_koin(sym, koin, h, sekarang, "BELI UTAMA", "#16a34a",
                              turun_lagi + ekstra_umum[sym] + catatan_jaringan,
                              "Tingkat Ekstrem saat pasar anjlok (2018-2026): 63% naik dalam 180 hari, median +48% dalam "
                              "1 tahun, tapi masih turun lagi median -44%. Cicil di beberapa harga. Bukan saran keuangan.")
            judul = (f"🟢🟢 <b>BELI UTAMA · {sym}</b>: masuk zona murah Ekstrem saat pasar anjlok\n{P.usd_idr(h)}"
                     + ("\n⚠️ Jaringan melemah: koin ini bisa terus ditinggalkan" if melemah else ""))
            if kirim(judul, png, kering, f"beli_{sym}.png"):
                an["beli"].append(sym)
            else:
                gagal = True

        # 3) Zona mahal per tingkat (patokan baru = catat diam-diam)
        zm = st.setdefault("mahal", {}).get(sym)
        if not zm or zm.get("ref") != z["puncak_tgl"]:
            st["mahal"][sym] = {"ref": z["puncak_tgl"], "sudah": [i for i, x in enumerate(z["mahal"]) if h >= x]}
        else:
            baru = [i for i, x in enumerate(z["mahal"]) if h >= x and i not in zm["sudah"]]
            zm["sudah"] = [i for i in zm["sudah"] if h > z["mahal"][i] * (1 - JARAK_ULANG_ZONA)]
            if baru:
                i = max(baru)
                png = gambar_koin(sym, koin, h, sekarang, f"MAHAL {TINGKAT_MAHAL[i].upper()}", "#dc2626",
                                  ekstra_umum[sym], "Zona mahal: ±67% arah benar (turun dalam 90 hari) di simulasi "
                                  "2024-2026. Pertimbangkan jual sebagian. Bukan saran keuangan.")
                if kirim(f"🔴 <b>ZONA MAHAL {TINGKAT_MAHAL[i]} · {sym}</b>: {P.usd_idr(h)} ≥ {P.usd_idr(z['mahal'][i])}",
                         png, kering, f"mahal_{sym}.png"):
                    zm["sudah"] = sorted(set(zm["sudah"]) | set(range(i + 1)))
                else:
                    gagal = True

        if not harian_baru or not m:
            continue
        jenis, _ = posisi(z, h)
        terakhir = st.setdefault("terakhir", {}).setdefault(sym, {})

        def boleh(kunci):
            return terakhir.get(kunci, "") < (hari - timedelta(days=JEDA_ULANG_HARI)).isoformat()

        # 4) Euforia: volume melonjak + harga naik tajam, hanya di zona mahal
        if (jenis == "mahal" and (m.get("vol7_365") or 0) >= EUFORIA_VOLUME and (m.get("naik30") or 0) >= EUFORIA_NAIK
                and boleh("euforia")):
            png = gambar_koin(sym, koin, h, sekarang, "EUFORIA", "#f59e0b",
                              [("Volume 7 hari", f"{m['vol7_365']:.1f}x", "dibanding rata-rata setahun"),
                               ("Naik 30 hari", f"{m['naik30'] * 100:+.0f}%", "")] + ekstra_umum[sym],
                              "Euforia di zona mahal: LTC Des 2024 (-21% sebulan kemudian), ADA Des 2024 (-34% dalam "
                              "90 hari). Bukan saran keuangan.")
            if kirim(f"🔥 <b>EUFORIA · {sym}</b> di zona mahal: pembeli kalap, puncak bisa dekat\n{P.usd_idr(h)}",
                     png, kering, f"euforia_{sym}.png"):
                terakhir["euforia"] = hari.isoformat()
            else:
                gagal = True

        # 5) Kasus khusus koin: anjlok jauh lebih dalam dari BTC + volume tinggi
        b7 = metrik.get("BTC", {}).get("naik7")
        if (sym != "BTC" and m.get("naik7") is not None and b7 is not None and m["naik7"] - b7 <= -KASUS_SELISIH
                and (m.get("vol7_90") or 0) >= KASUS_VOLUME and boleh("kasus")):
            berita = berita_buruk((koin.get(sym) or {}).get("id"))
            daftar = "\n".join(f'• <a href="{html.escape(u)}">{html.escape(j)}</a>' for j, u in berita) or \
                     "• (belum ada judul berita dengan kata kunci kasus; cek berita koin ini)"
            png = gambar_koin(sym, koin, h, sekarang, "KASUS KHUSUS", "#dc2626",
                              [("Koin 7 hari", f"{m['naik7'] * 100:+.0f}%", f"BTC {b7 * 100:+.0f}%"),
                               ("Volume 7 hari", f"{m['vol7_90']:.1f}x", "dibanding 90 hari sebelumnya")] + ekstra_umum[sym],
                              "Pola serupa: XRP gugatan SEC Des 2020 (tertinggal -47% dari BTC dalam 90 hari), SOL runtuhnya "
                              "FTX Nov 2022. Bukan saran keuangan.")
            judul = (f"🚨 <b>KASUS KHUSUS · {sym}</b>: {m['naik7'] * 100:+.0f}% dalam 7 hari, BTC {b7 * 100:+.0f}% · "
                     f"volume {m['vol7_90']:.1f}x\n{P.usd_idr(h)}\nBerita terkait:\n{daftar}")
            if kirim(judul, png, kering, f"kasus_{sym}.png"):
                terakhir["kasus"] = hari.isoformat()
            else:
                gagal = True

        # 6) Sell the news: H-7 sampai hari acara, bila harga sudah naik >= 30% dalam 60 hari
        for a in baca_acara():
            sisa = (date.fromisoformat(a["tanggal"]) - hari).days
            kunci = f"acara {a['tanggal']} {a['nama']}"
            if a["koin"] != sym or not 0 <= sisa <= 7 or terakhir.get(kunci) or (m.get("naik60") or 0) < SELL_NEWS_NAIK:
                continue
            png = P.buat_grafik("grafik_acara", sym, a["nama"], date.fromisoformat(a["tanggal"]), sisa, h,
                                harian(sym, koin, sekarang), m["naik60"], m.get("vol7_90") or 0,
                                P.uang, rp, P.BULAN, a.get("perkiraan"))
            if kirim(f"🔔 <b>WASPADA SELL THE NEWS · {sym}</b>: {html.escape(a['nama'])} {sisa} hari lagi, harga sudah "
                     f"naik {m['naik60'] * 100:+.0f}% dalam 60 hari\n{P.usd_idr(h)}", png, kering, f"acara_{sym}.png"):
                terakhir[kunci] = hari.isoformat()
            else:
                gagal = True

    # 7) Kesehatan jaringan: sebulan sekali, pesan hanya bila status berubah
    bulan = hari.strftime("%Y-%m")
    if harian_baru and jaringan["bulan"] != bulan:
        hasil = {}
        for sym in koin:
            try:
                r = penggunaan_jaringan(sym, metrik)
            except Exception as e:
                print(f"[!] TVL {sym} gagal: {e}")
                r = None
            if r:
                hasil[sym] = r
        berubah = [s for s, r in hasil.items() if (r["asli"] <= JARINGAN_TURUN) != bool(jaringan["melemah"].get(s))]
        if berubah:
            kolom = [("Koin", 0.05, "left"), ("TVL dolar", 0.40, "right"), ("Harga", 0.58, "right"),
                     ("Penggunaan asli", 0.80, "right"), ("Status", 0.96, "right")]
            baris = [[(s, None, True), (f"{r['dolar'] * 100:+.0f}%", None, False), (f"{r['harga'] * 100:+.0f}%", None, False),
                      (f"{r['asli'] * 100:+.0f}%", "#dc2626" if r["asli"] <= JARINGAN_TURUN else "#16a34a", True),
                      ("MELEMAH" if r["asli"] <= JARINGAN_TURUN else "sehat",
                       "#dc2626" if r["asli"] <= JARINGAN_TURUN else "#16a34a", True)] for s, r in hasil.items()]
            png = P.buat_grafik("grafik_tabel", "Kesehatan jaringan (12 bulan)",
                                "Penggunaan asli = TVL DefiLlama dihitung dalam jumlah koin (bebas efek harga)",
                                kolom, baris, "Melemah = penggunaan turun >= 30% dalam 12 bulan. Bukan saran keuangan.", [])
            teks = "\n".join(f"{'⚠️' if hasil[s]['asli'] <= JARINGAN_TURUN else '✅'} {s}: penggunaan jaringan "
                             f"{hasil[s]['asli'] * 100:+.0f}% dalam 12 bulan" for s in berubah)
            if kirim(f"📉 <b>KESEHATAN JARINGAN</b>\n{teks}", png, kering, "jaringan.png"):
                for s in berubah:
                    jaringan["melemah"][s] = hasil[s]["asli"] if hasil[s]["asli"] <= JARINGAN_TURUN else None
                jaringan["bulan"] = bulan
            else:
                gagal = True
        else:
            jaringan["bulan"] = bulan
    if harian_baru:
        st["cek_harian"] = st.get("metrik_hari")

    # 8) Ringkasan mingguan (Senin mulai 07:00 WIB) dan permintaan /siklus
    wib = sekarang.astimezone(P.WIB)
    minggu = wib.strftime("%G-W%V")
    mingguan = wib.weekday() == 0 and wib.hour >= 7 and st.get("mingguan") != minggu
    if mingguan or "#siklus" in antrean or tes:
        tambahan = [(("PASAR ANJLOK" if an["aktif"] else "Pasar normal") +
                     f" · BTC {turun * 100:.0f}% dari tertinggi 12 bulan (anjlok bila <= -40%)",
                     "#dc2626" if an["aktif"] else "#475569")]
        acara = teks_acara([a for a in baca_acara() if a["koin"] in koin or a["koin"] == "BTC"], hari, 30)
        tambahan += [("Acara 30 hari ke depan:", "#1e293b")] + [(f"  {t}", "#475569") for t in acara] if acara else \
            [("Acara 30 hari ke depan: tidak ada", "#475569")]
        lemah = [s for s, v in jaringan["melemah"].items() if v and s in koin]
        if lemah:
            tambahan.append((f"Jaringan melemah: {', '.join(lemah)}", "#dc2626"))
        png = tabel_semua(koin, harga, sekarang, "Ringkasan mingguan" if mingguan else "Zona harga semua koin",
                          f"{wib:%d-%m-%Y %H:%M} WIB · kurs 1 USD = {P.rupiah(P.KURS_IDR[0]) if P.KURS_IDR else '-'}",
                          tambahan, "Zona murah Ekstrem = batas BELI UTAMA saat pasar anjlok. Bukan saran keuangan.")
        judul = "🗓 <b>Ringkasan mingguan</b>" if mingguan else "📊 <b>Zona harga semua koin</b>"
        if kirim(judul, png, kering, "ringkasan.png"):
            if mingguan:
                st["mingguan"] = minggu
        else:
            gagal = True
    for permintaan in sorted(x for x in antrean if x.startswith("#siklus:")):
        sym = permintaan.split(":", 1)[1]
        if sym not in koin or sym not in ZONA:
            P.kirim_teks(f"Zona {html.escape(sym)} belum tersedia (koin tidak dipantau atau data belum cukup).")
            continue
        h = harga[sym]
        png = gambar_koin(sym, koin, h, sekarang, label_posisi(ZONA[sym], h).upper(), "#475569",
                          ekstra_umum[sym], "Bukan saran keuangan.")
        kirim(f"📊 <b>Zona harga {sym}</b>", png, kering, f"zona_{sym}.png")
    return gagal
