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
