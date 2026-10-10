"""Gambar grafik PNG untuk pesan Telegram (dipanggil dari pantau.py)."""
import io

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.patheffects as pe  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.ticker import FuncFormatter, NullFormatter  # noqa: E402

HIJAU, MERAH, ABU, BIRU, ORANYE, TEKS, REDUP = (
    "#16a34a", "#dc2626", "#94a3b8", "#2563eb", "#f59e0b", "#1e293b", "#475569")
plt.rcParams.update({"font.size": 12, "axes.edgecolor": "#cbd5e1", "axes.labelcolor": TEKS,
                     "xtick.color": TEKS, "ytick.color": TEKS, "font.family": "DejaVu Sans"})
SUMBU_USD = FuncFormatter(lambda v, _: "$" + (f"{v:,.0f}" if v >= 1000 else f"{v:.6f}".rstrip("0").rstrip(".")))
GARIS_PUTIH = [pe.withStroke(linewidth=3.5, foreground="white")]


def _sumbu_bulan(ax, bulan, tiap=1):
    ax.xaxis.set_major_locator(mdates.MonthLocator(bymonthday=1, interval=tiap))
    ax.xaxis.set_major_formatter(FuncFormatter(
        lambda v, _: f"{bulan[mdates.num2date(v).month - 1]} {mdates.num2date(v):%y}"))


def _rapikan(ax):
    for s in ("top", "right"):
        ax.spines[s].set_visible(False)


def _png(fig):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor="white")
    plt.close(fig)
    return buf.getvalue()


def grafik_koin(sym, harga, level, ditandai, tahun_ini, harian, terdekat, uang, bulan):
    """level: [(tahun, low, low_tgl, peak, peak_tgl)] terbaru dulu; harian: [(datetime, close)];
    terdekat: (bawah, atas), masing-masing (nama, nilai) atau None."""
    level = level[::-1]
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(9, 11.25), dpi=120, gridspec_kw={"height_ratios": [3, 2]})
    fig.suptitle(f"{sym}  {uang(harga)}  ·  Low & Peak per tahun", fontsize=17, fontweight="bold",
                 color=TEKS, y=0.985)

    # Atas: rentang Low-Peak tiap tahun
    for i, (tahun, lo, _, hi, _) in enumerate(level):
        warna = ORANYE if tahun in ditandai else BIRU if tahun == tahun_ini else ABU
        a1.plot([i, i], [lo, hi], color=warna, linewidth=14, solid_capstyle="butt", alpha=0.9)
        a1.text(i, hi * 1.12, uang(hi), ha="center", va="bottom", fontsize=9.5, color=HIJAU, fontweight="bold",
                zorder=7, path_effects=GARIS_PUTIH)
        a1.text(i, lo / 1.12, uang(lo), ha="center", va="top", fontsize=9.5, color=MERAH, fontweight="bold",
                zorder=7, path_effects=GARIS_PUTIH)
    a1.axhline(harga, color=MERAH, linestyle="--", linewidth=1.8)
    a1.text(-0.6, harga * 1.06, f"Sekarang {uang(harga)}", ha="left", va="bottom", color=MERAH,
            fontsize=11, fontweight="bold", zorder=6, path_effects=GARIS_PUTIH)
    a1.set_yscale("log")
    a1.yaxis.set_major_formatter(SUMBU_USD)
    a1.yaxis.set_minor_formatter(NullFormatter())
    a1.set_xticks(range(len(level)), [str(t[0]) for t in level])
    if level:
        a1.set_ylim(min(min(t[1] for t in level), harga) / 2.2, max(max(t[3] for t in level), harga) * 2.2)
    a1.set_xlim(-0.7, len(level) - 0.3)
    a1.grid(axis="y", color="#e2e8f0", linewidth=0.8)
    a1.set_title("Batang = rentang harga setahun (bawah = Low, atas = Peak)", fontsize=11, color=REDUP, loc="left")
    _rapikan(a1)

    # Bawah: harga 1 tahun terakhir dan level terdekat
    if harian:
        tgl, tutup = zip(*harian)
        a2.plot(tgl, tutup, color=BIRU, linewidth=2)
        a2.scatter([tgl[-1]], [harga], color=MERAH, zorder=5, s=40)
        # Label level bawah ditulis di bawah garisnya, level atas di atas garisnya, supaya tidak bertumpuk
        for x, warna, posisi in zip(terdekat, (MERAH, HIJAU), ("top", "bottom")):
            if x:
                a2.axhline(x[1], color=warna, linestyle=":", linewidth=1.6)
                a2.text(tgl[0], x[1], f" {x[0]}  {uang(x[1])} ({(x[1] / harga - 1) * 100:+.1f}%)",
                        va=posisi, color=warna, fontsize=10.5, fontweight="bold", path_effects=GARIS_PUTIH)
        a2.yaxis.set_major_formatter(SUMBU_USD)
        _sumbu_bulan(a2, bulan, tiap=2)
    else:
        a2.text(0.5, 0.5, "Data harian tidak tersedia", ha="center", va="center", transform=a2.transAxes,
                color=REDUP)
        a2.set_xticks([])
        a2.set_yticks([])
    a2.grid(color="#e2e8f0", linewidth=0.8)
    a2.set_title("Harga 1 tahun terakhir dan level terdekat", fontsize=11, color=REDUP, loc="left")
    _rapikan(a2)

    fig.text(0.99, 0.005, "Sumber: CoinMarketCap (data harian)", ha="right", fontsize=9, color="#64748b")
    fig.tight_layout(rect=(0, 0.01, 1, 0.97))
    return _png(fig)


ZONA_FG = [(0, 25, "#fecaca", "Extreme Fear"), (25, 45, "#fed7aa", "Fear"), (45, 55, "#e2e8f0", "Neutral"),
           (55, 76, "#bbf7d0", "Greed"), (76, 100, "#86efac", "Extreme Greed")]


def grafik_fg(riwayat, skor, nama, skor_lalu, sumber, bulan):
    """riwayat: [(datetime, skor)] urut waktu."""
    fig, ax = plt.subplots(figsize=(9, 6), dpi=120)
    judul = f"Fear & Greed  {skor}/100 ({nama})"
    if skor_lalu is not None:
        judul += f"  ·  {skor - skor_lalu:+d} poin"
    fig.suptitle(judul, fontsize=17, fontweight="bold", color=TEKS, y=0.98)
    for bawah, atas, warna, label in ZONA_FG:
        ax.axhspan(bawah, atas, color=warna, alpha=0.55, linewidth=0)
        ax.text(1.005, (bawah + atas) / 2, label, transform=ax.get_yaxis_transform(), va="center",
                fontsize=9.5, color=REDUP)
    if riwayat:
        tgl, nilai = zip(*riwayat)
        ax.plot(tgl, nilai, color=TEKS, linewidth=2)
        ax.scatter([tgl[-1]], [skor], color=MERAH, zorder=5, s=50)
        ax.annotate(str(skor), (tgl[-1], skor), textcoords="offset points", xytext=(-6, 10), ha="right",
                    fontsize=13, fontweight="bold", color=MERAH, path_effects=GARIS_PUTIH)
        if skor_lalu is not None:
            ax.axhline(skor_lalu, color=REDUP, linestyle="--", linewidth=1.3)
            ax.text(tgl[0], skor_lalu, f" terakhir dilaporkan: {skor_lalu}", va="bottom", fontsize=10,
                    color=REDUP, path_effects=GARIS_PUTIH)
        _sumbu_bulan(ax, bulan)
    ax.set_ylim(0, 100)
    ax.set_yticks([0, 25, 45, 55, 75, 100])
    ax.set_title("90 hari terakhir", fontsize=11, color=REDUP, loc="left")
    _rapikan(ax)
    fig.text(0.99, 0.01, f"Sumber: {sumber}", ha="right", fontsize=9, color="#64748b")
    fig.tight_layout(rect=(0, 0.02, 0.9, 0.95))
    return _png(fig)


def _sumbu_harga(ax, uang):
    ax.set_yscale("log")
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: uang(v)))
    ax.yaxis.set_minor_formatter(NullFormatter())


def grafik_zona(sym, harga, z, harian, lencana, warna_lencana, ekstra, catatan, uang, rp, bulan,
                tingkat_murah, tingkat_mahal):
    """Laporan zona satu koin: kepala, grafik 1 tahun berpita zona, tabel tingkat murah/mahal, baris tambahan.
    ekstra: [(label, nilai, keterangan)]."""
    baris_tabel = 2 + len(tingkat_murah) + len(tingkat_mahal) + (1 + len(ekstra) if ekstra else 0)
    tinggi = 6.6 + 0.42 * baris_tabel + 0.6
    fig = plt.figure(figsize=(9, tinggi), dpi=120)
    y = lambda inci: 1 - inci / tinggi  # noqa: E731
    fig.text(0.05, y(0.35), sym, fontsize=24, fontweight="bold", color=TEKS, va="top")
    fig.text(0.05, y(0.85), f"Sekarang {uang(harga)}  ≈  {rp(harga)}", fontsize=14, color=TEKS, va="top")
    fig.text(0.95, y(0.35), lencana, fontsize=14, fontweight="bold", color="white", ha="right", va="top",
             bbox=dict(boxstyle="round,pad=0.45", facecolor=warna_lencana, edgecolor="none"))

    ax = fig.add_axes([0.11, y(5.7), 0.80, 4.2 / tinggi])
    m, k = z["murah"], z["mahal"]
    semua = [harga]
    if harian:
        tgl, tutup = zip(*harian)
        ax.plot(tgl, tutup, color=BIRU, linewidth=1.8)
        ax.scatter([tgl[-1]], [harga], color=MERAH, s=55, zorder=5)
        semua += list(tutup)
    ax.axhspan(m[2], m[0], color=HIJAU, alpha=0.13, linewidth=0)
    ax.axhspan(k[0], k[2], color=MERAH, alpha=0.10, linewidth=0)
    for v, w, label in ((m[2], HIJAU, "Ekstrem"), (k[1], MERAH, "estimasi puncak")):
        ax.axhline(v, color=w, linestyle="--", linewidth=1.2)
        ax.text(0.01, v, f" {label} {uang(v)}", transform=ax.get_yaxis_transform(), color=w, fontsize=10,
                fontweight="bold", va="bottom", path_effects=GARIS_PUTIH)
    batas = semua + list(m) + list(k)
    ax.set_ylim(min(batas) / 1.25, max(batas) * 1.25)
    _sumbu_harga(ax, uang)
    if harian:
        _sumbu_bulan(ax, bulan, tiap=2)
    ax.text(1.01, (m[0] * m[2]) ** 0.5, "MURAH", transform=ax.get_yaxis_transform(), color=HIJAU, fontsize=10,
            fontweight="bold", va="center")
    ax.text(1.01, (k[0] * k[2]) ** 0.5, "MAHAL", transform=ax.get_yaxis_transform(), color=MERAH, fontsize=10,
            fontweight="bold", va="center")
    ax.grid(color="#e2e8f0", linewidth=0.8)
    _rapikan(ax)

    pos = [6.2]

    def judul(teks, warna):
        fig.patches.append(plt.Rectangle((0.05, y(pos[0] + 0.18)), 0.90, 0.36 / tinggi, transform=fig.transFigure,
                                         facecolor=warna, alpha=0.12, edgecolor="none"))
        fig.text(0.07, y(pos[0]), teks, fontsize=12.5, fontweight="bold", color=warna, va="center")
        pos[0] += 0.42

    def baris(label, nilai, ket, warna):
        fig.text(0.09, y(pos[0]), label, fontsize=12, color=TEKS, va="center")
        fig.text(0.64, y(pos[0]), nilai, fontsize=12, color=TEKS, fontweight="bold", ha="right", va="center")
        fig.text(0.66, y(pos[0]), ket, fontsize=10, color=warna, va="center")
        pos[0] += 0.42

    judul("ZONA MURAH · perkiraan dasar", HIJAU)
    for nama, v in zip(tingkat_murah, m):
        baris(nama, f"{uang(v)} · {rp(v)}", f"{(v / harga - 1) * 100:+.0f}% dari sekarang", HIJAU)
    judul("ZONA MAHAL · perkiraan puncak siklus berikut", MERAH)
    for nama, v in zip(tingkat_mahal, k):
        baris(nama, f"{uang(v)} · {rp(v)}", f"{(v / harga - 1) * 100:+.0f}% dari sekarang", MERAH)
    if ekstra:
        judul("KETERANGAN", REDUP)
        for label, nilai, ket in ekstra:
            baris(label, nilai, ket, REDUP)
    fig.text(0.05, 0.3 / tinggi, catatan, fontsize=9, color=REDUP, wrap=True)
    return _png(fig)


def grafik_tabel(judul, subjudul, kolom, baris, catatan, tambahan=()):
    """Tabel sebagai gambar. kolom: [(judul, x, ha)]; baris: [[(teks, warna, tebal), ...]]; tambahan: [(teks, warna)]."""
    tambahan = list(tambahan or [])
    tinggi = 1.75 + 0.62 * len(baris) + 0.36 * len(tambahan) + 0.7
    fig = plt.figure(figsize=(9, tinggi), dpi=120)
    y = lambda inci: 1 - inci / tinggi  # noqa: E731
    fig.text(0.05, y(0.42), judul, fontsize=17, fontweight="bold", color=TEKS, va="center")
    if subjudul:
        fig.text(0.05, y(0.82), subjudul, fontsize=10.5, color=REDUP, va="center")
    for teks, x, ha in kolom:
        fig.text(x, y(1.35), teks, fontsize=10.5, color=REDUP, fontweight="bold", ha=ha, va="center")
    for i, sel in enumerate(baris):
        yy = 1.95 + 0.62 * i
        if i % 2 == 0:
            fig.patches.append(plt.Rectangle((0.03, y(yy + 0.31)), 0.94, 0.62 / tinggi, transform=fig.transFigure,
                                             facecolor="#f1f5f9", edgecolor="none"))
        for (teks, warna, tebal), (_, x, ha) in zip(sel, kolom):
            fig.text(x, y(yy), teks, fontsize=11.5, color=warna or TEKS, fontweight="bold" if tebal else "normal",
                     ha=ha, va="center", linespacing=1.15)
    yy = 1.95 + 0.62 * len(baris) + 0.1
    for teks, warna in tambahan:
        fig.text(0.05, y(yy), teks, fontsize=10.5, color=warna or TEKS, va="center")
        yy += 0.36
    fig.text(0.05, 0.22 / tinggi, catatan, fontsize=9, color=REDUP)
    return _png(fig)


def grafik_acara(sym, nama_acara, tgl_acara, sisa, harga, harian, naik60, vol, uang, rp, bulan, perkiraan=False):
    """Peringatan sell the news: harga 120 hari, garis acara, perkiraan pola 30 hari sesudah acara."""
    from datetime import datetime, timedelta
    fig = plt.figure(figsize=(9, 10.2), dpi=120)
    fig.text(0.05, 0.965, f"{sym} · {nama_acara}", fontsize=18, fontweight="bold", color=TEKS, va="top")
    fig.text(0.05, 0.925, f"Acara {'±' if perkiraan else ''}{tgl_acara:%d-%m-%Y} · {sisa} hari lagi · "
             f"{uang(harga)} ≈ {rp(harga)}", fontsize=12.5, color=REDUP, va="top")
    fig.text(0.95, 0.965, "WASPADA", fontsize=14, fontweight="bold", color="white", ha="right", va="top",
             bbox=dict(boxstyle="round,pad=0.45", facecolor=MERAH, edgecolor="none"))
    ax = fig.add_axes([0.11, 0.45, 0.82, 0.42])
    lalu = harian[-120:] if harian else []
    if lalu:
        tgl, tutup = zip(*lalu)
        ax.plot(tgl, tutup, color=BIRU, linewidth=2)
        ax.scatter([tgl[-1]], [harga], color=MERAH, s=55, zorder=5)
    t_acara = datetime(tgl_acara.year, tgl_acara.month, tgl_acara.day)
    hasil30 = (-0.11, -0.22, -0.51)
    x = [lalu[-1][0] if lalu else t_acara, t_acara + timedelta(days=30)]
    for p, gaya, lebar in zip(hasil30, ("--", "-", "--"), (1.2, 2.2, 1.2)):
        ax.plot(x, [harga, harga * (1 + p)], color=MERAH, linestyle=gaya, linewidth=lebar, alpha=0.8)
    ax.fill_between(x, [harga, harga * (1 + hasil30[0])], [harga, harga * (1 + hasil30[2])], color=MERAH, alpha=0.08)
    ax.axvline(t_acara, color=ORANYE, linewidth=2)
    ax.text(t_acara, 1.01, " acara", transform=ax.get_xaxis_transform(), color=ORANYE, fontsize=11, fontweight="bold")
    _sumbu_harga(ax, uang)
    _sumbu_bulan(ax, bulan)
    ax.grid(color="#e2e8f0", linewidth=0.8)
    _rapikan(ax)
    baris = [("Kenaikan 60 hari", f"{naik60 * 100:+.0f}%", "syarat waspada ≥ +30%"),
             ("Volume 7 hari", f"{vol:.1f}x", "dibanding 90 hari sebelumnya")]
    baris += [(f"Perkiraan 30 hari · {n}", f"{uang(harga * (1 + p))} · {rp(harga * (1 + p))}", f"{p * 100:+.0f}%")
              for n, p in zip(("aman", "estimasi", "ekstrem"), hasil30)]
    yy = 0.37
    for label, nilai, ket in baris:
        fig.text(0.07, yy, label, fontsize=12, color=TEKS)
        fig.text(0.64, yy, nilai, fontsize=12, color=MERAH, fontweight="bold", ha="right")
        fig.text(0.66, yy, ket, fontsize=10.5, color=REDUP)
        yy -= 0.045
    fig.text(0.07, yy - 0.01, "Pola historis: pertimbangkan jual sebagian SEBELUM acara.\n8 dari 9 kasus serupa sejak 2017 "
             "turun dalam 30 hari (rata-rata -18%; 90 hari -30%).", fontsize=12, color=TEKS, va="top", linespacing=1.5)
    fig.text(0.05, 0.02, "Pola dari 21 acara terjadwal 2017-2025 (sampel kecil). Bukan saran keuangan · CoinMarketCap",
             fontsize=9, color=REDUP)
    return _png(fig)
