"""
Dashboard Monitoring Temperature Area - Unit WCP/AC Koridor
Input manual dari checklist harian, dengan 2 mode:
  - DEMO : data simulasi (tidak disimpan permanen)
  - LIVE : terhubung ke Google Sheets (data nyata, bisa auto-refresh)

Jalankan:  streamlit run app.py
"""
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ------------------------------------------------------------------
# KONFIGURASI
# ------------------------------------------------------------------
st.set_page_config(
    page_title="Monitoring WCP/AC Koridor",
    page_icon="🌡️",
    layout="wide",
)

WIB = ZoneInfo("Asia/Jakarta")

# Mode awal saat aplikasi dibuka: "demo" atau "live"
DEFAULT_MODE = "demo"
MODE_DEMO = "🧪 Demo (data contoh)"
MODE_LIVE = "🟢 Live (Google Sheets)"

COLUMNS = [
    "waktu", "unit", "zona", "lantai",
    "suhu_koridor", "suhu_supply", "suhu_return",
    "status", "petugas", "catatan",
]
NUM_COLS = ["suhu_koridor", "suhu_supply", "suhu_return"]
TEXT_COLS = ["unit", "zona", "lantai", "status", "petugas", "catatan"]
FMT_WAKTU = "%Y-%m-%d %H:%M:%S"

# Daftar unit -> (zona, lantai). Ubah sesuai kondisi lapangan.
UNITS = {
    "WCP-01": ("Koridor Utara", "Lantai 1"),
    "WCP-02": ("Koridor Utara", "Lantai 1"),
    "WCP-03": ("Koridor Selatan", "Lantai 1"),
    "WCP-04": ("Koridor Selatan", "Lantai 1"),
    "WCP-05": ("Koridor Utara", "Lantai 2"),
    "WCP-06": ("Koridor Utara", "Lantai 2"),
    "WCP-07": ("Koridor Selatan", "Lantai 2"),
    "WCP-08": ("Koridor Selatan", "Lantai 2"),
}

STATUS_OPTIONS = ["ON", "OFF", "FAULT"]
WAKTU_CEK = [time(9, 0), time(13, 0), time(17, 0)]


def sekarang() -> datetime:
    return datetime.now(WIB).replace(tzinfo=None)


# ------------------------------------------------------------------
# DATA CONTOH & PEMBERSIHAN
# ------------------------------------------------------------------
def buat_data_contoh() -> pd.DataFrame:
    """Data contoh 7 hari x 3 kali cek x 8 unit (untuk demo)."""
    rng = np.random.default_rng(42)
    rows = []
    hari_ini = sekarang().date()
    offset_jam = {9: 0.0, 13: 1.3, 17: 0.7}
    petugas = ["Andi", "Budi", "Citra"]

    for d in range(6, -1, -1):
        tgl = hari_ini - timedelta(days=d)
        for i, jam in enumerate([9, 13, 17]):
            for u, (zona, lantai) in UNITS.items():
                base = 25.0 + offset_jam[jam] + rng.normal(0, 0.5)
                if lantai == "Lantai 2":
                    base += 0.4
                r = rng.random()
                status = "FAULT" if r < 0.04 else "OFF" if r < 0.08 else "ON"

                if status == "ON":
                    koridor = base
                    supply = 15.5 + rng.normal(0, 0.8)
                    ret = supply + 6.0 + rng.normal(0, 1.0)
                    cat = ""
                elif status == "OFF":
                    koridor = base + 2.5
                    supply = koridor - 0.3
                    ret = koridor
                    cat = "Unit dimatikan"
                else:
                    koridor = base + 3.0
                    supply = koridor - 1.0
                    ret = koridor
                    cat = "Kompresor/pompa bermasalah"

                rows.append({
                    "waktu": datetime.combine(tgl, time(jam, 0)),
                    "unit": u, "zona": zona, "lantai": lantai,
                    "suhu_koridor": round(koridor, 1),
                    "suhu_supply": round(supply, 1),
                    "suhu_return": round(ret, 1),
                    "status": status,
                    "petugas": petugas[i],
                    "catatan": cat,
                })
    return pd.DataFrame(rows, columns=COLUMNS)


def bersihkan(df: pd.DataFrame) -> pd.DataFrame:
    """Samakan tipe data & buang baris yang tidak lengkap."""
    df = df.copy()
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df = df[COLUMNS]
    df["waktu"] = pd.to_datetime(df["waktu"], errors="coerce")
    for c in NUM_COLS:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    for c in TEXT_COLS:
        df[c] = df[c].fillna("").astype(str)
    df = df.dropna(subset=["waktu"] + NUM_COLS)
    return df.reset_index(drop=True)


def df_ke_values(df: pd.DataFrame) -> list:
    """DataFrame -> list of list untuk dikirim ke Google Sheets."""
    d = bersihkan(df)
    d["waktu"] = d["waktu"].dt.strftime(FMT_WAKTU)
    return d.astype(object).values.tolist()


# ------------------------------------------------------------------
# GOOGLE SHEETS (mode LIVE)
# ------------------------------------------------------------------
def live_tersedia() -> bool:
    try:
        return "gcp_service_account" in st.secrets and "sheets" in st.secrets
    except Exception:
        return False


@st.cache_resource(show_spinner=False)
def _worksheet():
    import gspread
    from google.oauth2.service_account import Credentials

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(
        dict(st.secrets["gcp_service_account"]), scopes=scopes
    )
    gc = gspread.authorize(creds)
    sh = gc.open_by_key(st.secrets["sheets"]["spreadsheet_id"])
    nama = st.secrets["sheets"].get("worksheet", "checklist")
    try:
        ws = sh.worksheet(nama)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=nama, rows=1000, cols=len(COLUMNS))

    header = ws.row_values(1)
    if not header:
        ws.update(values=[COLUMNS], range_name="A1")
    elif header != COLUMNS:
        raise ValueError(
            "Header sheet tidak sesuai. Baris 1 harus persis: " + ", ".join(COLUMNS)
        )
    return ws


@st.cache_data(ttl=10, show_spinner=False)
def _baca_live() -> pd.DataFrame:
    from gspread.utils import ValueRenderOption

    rec = _worksheet().get_all_records(value_render_option=ValueRenderOption.unformatted)
    return bersihkan(pd.DataFrame(rec, columns=COLUMNS))


def muat_data(live: bool) -> pd.DataFrame:
    if live:
        return _baca_live()
    if "demo_df" not in st.session_state:
        st.session_state["demo_df"] = buat_data_contoh()
    return st.session_state["demo_df"].copy()


def tambah_baris(live: bool, baris: dict) -> None:
    baru = pd.DataFrame([baris], columns=COLUMNS)
    if live:
        _worksheet().append_row(df_ke_values(baru)[0], value_input_option="RAW")
        _baca_live.clear()
    else:
        st.session_state["demo_df"] = pd.concat(
            [muat_data(False), baru], ignore_index=True
        )


def simpan_semua(live: bool, df: pd.DataFrame) -> None:
    """Timpa seluruh data dengan df."""
    if live:
        ws = _worksheet()
        ws.clear()
        ws.update(values=[COLUMNS] + df_ke_values(df), range_name="A1")
        _baca_live.clear()
    else:
        st.session_state["demo_df"] = bersihkan(df)


# ------------------------------------------------------------------
# LOGIKA ALARM
# ------------------------------------------------------------------
def tambah_delta_t(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["delta_t"] = (df["suhu_return"] - df["suhu_supply"]).round(1)
    return df


def evaluasi_alarm(row, t_min, t_max, dt_min) -> str:
    if row["status"] == "FAULT":
        return "🔴 Unit FAULT"
    if row["status"] == "OFF":
        return "⚪ Unit OFF"
    alarm = []
    if row["suhu_koridor"] > t_max:
        alarm.append("🟠 Terlalu panas")
    if row["suhu_koridor"] < t_min:
        alarm.append("🔵 Terlalu dingin")
    if row["delta_t"] < dt_min:
        alarm.append("🟡 ΔT rendah")
    return ", ".join(alarm) if alarm else "🟢 Normal"


# ------------------------------------------------------------------
# SIDEBAR
# ------------------------------------------------------------------
st.sidebar.title("🌡️ Monitoring WCP/AC")
st.sidebar.caption("Koridor Mall Lippo Plaza Sidoarjo")

LIVE_OK = live_tersedia()

if LIVE_OK:
    mode = st.sidebar.radio(
        "Sumber data", [MODE_DEMO, MODE_LIVE], key="mode",
        index=1 if DEFAULT_MODE == "live" else 0,
    )
else:
    mode = st.sidebar.radio("Sumber data", [MODE_DEMO], key="mode")
    st.sidebar.caption("Mode Live belum aktif: Google Sheets belum dikonfigurasi di *secrets*.")

LIVE = mode == MODE_LIVE

menu = st.sidebar.radio(
    "Menu", ["📊 Dashboard", "📝 Input Checklist", "🗂️ Data & Ekspor"], key="menu"
)

auto_refresh, interval = False, 30
if LIVE:
    st.sidebar.divider()
    st.sidebar.subheader("Pembaruan data")
    auto_refresh = st.sidebar.toggle("Auto-refresh dashboard", value=True)
    interval = st.sidebar.select_slider(
        "Interval (detik)", options=[10, 15, 30, 60, 120], value=30,
        disabled=not auto_refresh,
    )

st.sidebar.divider()
st.sidebar.subheader("Batas Alarm")
t_min, t_max = st.sidebar.slider(
    "Target suhu koridor (°C)", 20.0, 32.0, (24.0, 27.0), 0.5
)
dt_min = st.sidebar.number_input(
    "ΔT minimum (return − supply, °C)", 0.0, 15.0, 4.0, 0.5,
    help="Di bawah nilai ini, performa pendinginan unit dianggap menurun.",
)


def banner() -> None:
    if LIVE:
        st.success(
            f"🟢 **MODE LIVE** · terhubung ke Google Sheets · "
            f"diperbarui {sekarang():%H:%M:%S} WIB"
        )
    else:
        st.warning(
            "🧪 **MODE DEMO** · data di bawah adalah simulasi, bukan data hasil "
            "pengecekan lapangan. Input pada mode ini tidak disimpan permanen."
        )


def ambil_data() -> pd.DataFrame:
    try:
        return muat_data(LIVE)
    except Exception as e:  # koneksi/izin/format sheet
        st.error(
            "Gagal membaca Google Sheets. Cek *secrets*, ID spreadsheet, dan "
            "pastikan sheet sudah dibagikan ke email service account.\n\n"
            f"Detail: `{type(e).__name__}: {e}`"
        )
        st.stop()


# ------------------------------------------------------------------
# HALAMAN: INPUT CHECKLIST
# ------------------------------------------------------------------
def halaman_input() -> None:
    st.title("📝 Input Checklist Harian")
    banner()
    df_all = ambil_data()

    with st.form("form_checklist", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        tgl = c1.date_input("Tanggal", sekarang().date())
        jam = c2.selectbox(
            "Waktu cek", WAKTU_CEK, format_func=lambda t: t.strftime("%H:%M")
        )
        petugas = c3.text_input("Petugas")

        unit = st.selectbox("Unit WCP/AC", list(UNITS.keys()))
        zona, lantai = UNITS[unit]
        st.caption(f"Zona: **{zona}** · {lantai}")

        c4, c5, c6, c7 = st.columns(4)
        status = c4.selectbox("Status", STATUS_OPTIONS)
        s_koridor = c5.number_input("Suhu koridor (°C)", 10.0, 45.0, 25.0, 0.1)
        s_supply = c6.number_input("Suhu supply (°C)", 5.0, 40.0, 15.0, 0.1)
        s_return = c7.number_input("Suhu return (°C)", 5.0, 45.0, 22.0, 0.1)

        catatan = st.text_area("Catatan (opsional)")
        kirim = st.form_submit_button("💾 Simpan", type="primary")

    if kirim:
        if not petugas.strip():
            st.error("Nama petugas wajib diisi.")
        else:
            try:
                tambah_baris(LIVE, {
                    "waktu": datetime.combine(tgl, jam),
                    "unit": unit, "zona": zona, "lantai": lantai,
                    "suhu_koridor": s_koridor,
                    "suhu_supply": s_supply,
                    "suhu_return": s_return,
                    "status": status,
                    "petugas": petugas.strip(),
                    "catatan": catatan.strip(),
                })
                st.toast(f"Data {unit} pukul {jam:%H:%M} tersimpan.", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Gagal menyimpan: {type(e).__name__}: {e}")

    st.subheader("5 input terakhir")
    st.dataframe(
        df_all.sort_values("waktu", ascending=False).head(5),
        width="stretch", hide_index=True,
    )


# ------------------------------------------------------------------
# HALAMAN: DATA & EKSPOR
# ------------------------------------------------------------------
def halaman_data() -> None:
    st.title("🗂️ Data & Ekspor")
    banner()
    df_all = ambil_data()

    st.subheader("Edit / hapus data")
    st.caption(
        "Ubah nilai langsung di tabel, hapus baris dengan memilihnya lalu tekan "
        "Delete, kemudian klik Simpan."
        + (" **Di mode Live, ini menimpa isi Google Sheets.**" if LIVE else "")
    )
    edited = st.data_editor(
        df_all.sort_values("waktu", ascending=False).reset_index(drop=True),
        num_rows="dynamic", width="stretch", key="editor",
    )
    c1, c2, _ = st.columns([1, 1, 2])
    if c1.button("💾 Simpan perubahan", type="primary"):
        try:
            simpan_semua(LIVE, edited)
            st.toast("Perubahan disimpan.", icon="✅")
            st.rerun()
        except Exception as e:
            st.error(f"Gagal menyimpan: {type(e).__name__}: {e}")

    c2.download_button(
        "⬇️ Unduh CSV",
        df_all.to_csv(index=False).encode("utf-8"),
        file_name="data_checklist_wcp.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Impor / reset")

    up = st.file_uploader("Unggah CSV (kolom harus sama)", type="csv")
    ok = True
    if LIVE:
        ok = st.checkbox("Saya paham isi Google Sheets akan ditimpa file ini")
    if up is not None and st.button("Gunakan file ini", disabled=not ok):
        d = pd.read_csv(up)
        if set(COLUMNS).issubset(d.columns):
            try:
                simpan_semua(LIVE, d[COLUMNS])
                st.toast("Data diganti dengan file yang diunggah.", icon="✅")
                st.rerun()
            except Exception as e:
                st.error(f"Gagal menyimpan: {type(e).__name__}: {e}")
        else:
            st.error(f"Kolom harus ada: {', '.join(COLUMNS)}")

    if LIVE:
        if df_all.empty and st.button("🧪 Isi Google Sheets dengan data contoh"):
            simpan_semua(True, buat_data_contoh())
            st.rerun()
        elif not df_all.empty:
            st.caption("Tombol data contoh hanya muncul jika Google Sheets masih kosong.")
    else:
        if st.button("🔄 Reset ke data contoh"):
            st.session_state["demo_df"] = buat_data_contoh()
            st.rerun()


# ------------------------------------------------------------------
# HALAMAN: DASHBOARD (fragment -> bisa auto-refresh tanpa reload halaman)
# ------------------------------------------------------------------
_run_every = f"{interval}s" if (LIVE and auto_refresh) else None


@st.fragment(run_every=_run_every)
def halaman_dashboard() -> None:
    st.title("📊 Dashboard Monitoring Temperature Area")
    banner()
    st.caption(
        "Unit WCP/AC koridor · data dari checklist harian manual "
        "(area belum memakai AC central/chiller)"
    )

    df_all = ambil_data()
    if df_all.empty:
        st.info("Belum ada data. Isi dulu lewat menu **Input Checklist**.")
        return

    df_all = tambah_delta_t(df_all)

    # ---- Filter
    f1, f2, f3 = st.columns([2, 1, 1])
    tgl_min = df_all["waktu"].min().date()
    tgl_max = df_all["waktu"].max().date()
    rentang = f1.date_input(
        "Rentang tanggal",
        (max(tgl_min, tgl_max - timedelta(days=6)), tgl_max),
        min_value=tgl_min, max_value=tgl_max,
    )
    lantai_pilih = f2.multiselect(
        "Lantai", sorted(df_all["lantai"].unique()),
        default=sorted(df_all["lantai"].unique()),
    )
    zona_pilih = f3.multiselect(
        "Zona", sorted(df_all["zona"].unique()),
        default=sorted(df_all["zona"].unique()),
    )

    if isinstance(rentang, (tuple, list)):
        if len(rentang) == 0:
            awal, akhir = tgl_min, tgl_max
        else:
            awal, akhir = rentang[0], rentang[-1]
    else:
        awal = akhir = rentang

    df = df_all[
        (df_all["waktu"].dt.date >= awal)
        & (df_all["waktu"].dt.date <= akhir)
        & (df_all["lantai"].isin(lantai_pilih))
        & (df_all["zona"].isin(zona_pilih))
    ]
    if df.empty:
        st.warning("Tidak ada data untuk filter yang dipilih.")
        return

    # ---- Kondisi terbaru tiap unit
    terbaru = (
        df.sort_values("waktu").groupby("unit").tail(1).sort_values("unit").copy()
    )
    terbaru["alarm"] = terbaru.apply(
        evaluasi_alarm, axis=1, args=(t_min, t_max, dt_min)
    )

    unit_aktif = int((terbaru["status"] == "ON").sum())
    unit_fault = int((terbaru["status"] == "FAULT").sum())
    jml_alarm = int((~terbaru["alarm"].str.contains("Normal")).sum())
    df_on = df[df["status"] == "ON"]
    rata_suhu = df["suhu_koridor"].mean()
    rata_dt = df_on["delta_t"].mean() if not df_on.empty else float("nan")
    pct_target = (
        ((df["suhu_koridor"] >= t_min) & (df["suhu_koridor"] <= t_max)).mean() * 100
    )

    # ---- KPI
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Rata-rata suhu koridor", f"{rata_suhu:.1f} °C")
    k2.metric("Unit aktif (terbaru)", f"{unit_aktif}/{len(terbaru)}")
    k3.metric("Unit FAULT", unit_fault)
    k4.metric("Rata-rata ΔT (unit ON)", f"{rata_dt:.1f} °C")
    k5.metric("Waktu dalam target", f"{pct_target:.0f}%")

    if jml_alarm:
        st.warning(f"⚠️ {jml_alarm} unit memerlukan perhatian pada pengecekan terakhir.")
    else:
        st.success("✅ Semua unit normal pada pengecekan terakhir.")

    st.divider()

    # ---- Tren suhu per zona
    st.subheader("Tren suhu koridor")
    tren = df.groupby(["waktu", "zona", "lantai"], as_index=False)["suhu_koridor"].mean()
    tren["zona_lantai"] = tren["zona"] + " · " + tren["lantai"]
    fig = px.line(
        tren, x="waktu", y="suhu_koridor", color="zona_lantai", markers=True,
        labels={"waktu": "Waktu", "suhu_koridor": "Suhu (°C)", "zona_lantai": "Zona"},
    )
    fig.add_hrect(
        y0=t_min, y1=t_max, fillcolor="green", opacity=0.08, line_width=0,
        annotation_text="Target", annotation_position="top left",
    )
    fig.update_layout(height=380, legend_title_text="", margin=dict(t=30, b=10))
    st.plotly_chart(fig, width="stretch")

    # ---- ΔT dan status
    g1, g2 = st.columns([3, 2])

    with g1:
        st.subheader("ΔT tiap unit (pengecekan terakhir)")
        warna = terbaru["status"].map(
            {"ON": "#2e7d32", "OFF": "#9e9e9e", "FAULT": "#c62828"}
        )
        figdt = go.Figure(
            go.Bar(x=terbaru["unit"], y=terbaru["delta_t"], marker_color=warna,
                   text=terbaru["delta_t"], textposition="outside")
        )
        figdt.add_hline(
            y=dt_min, line_dash="dash", line_color="orange",
            annotation_text=f"Min ΔT {dt_min}°C",
        )
        figdt.update_layout(height=340, yaxis_title="ΔT (°C)", margin=dict(t=30, b=10))
        st.plotly_chart(figdt, width="stretch")

    with g2:
        st.subheader("Komposisi status")
        status_count = df.groupby("status").size().reset_index(name="jumlah")
        figpie = px.pie(
            status_count, names="status", values="jumlah", hole=0.5,
            color="status",
            color_discrete_map={"ON": "#2e7d32", "OFF": "#9e9e9e", "FAULT": "#c62828"},
        )
        figpie.update_layout(height=340, margin=dict(t=30, b=10))
        st.plotly_chart(figpie, width="stretch")

    # ---- Heatmap
    st.subheader("Heatmap suhu koridor per unit")
    pivot = df.pivot_table(
        index="unit", columns="waktu", values="suhu_koridor", aggfunc="mean"
    )
    pivot.columns = [c.strftime("%d/%m %H:%M") for c in pivot.columns]
    fighm = px.imshow(
        pivot, aspect="auto", color_continuous_scale="RdYlBu_r",
        labels=dict(color="°C", x="Waktu", y="Unit"),
    )
    fighm.update_layout(height=340, margin=dict(t=10, b=10))
    st.plotly_chart(fighm, width="stretch")

    # ---- Tabel status
    st.subheader("Status unit terbaru")
    tabel = terbaru[
        ["unit", "zona", "lantai", "waktu", "status", "suhu_koridor",
         "suhu_supply", "suhu_return", "delta_t", "alarm", "catatan"]
    ].rename(columns={
        "unit": "Unit", "zona": "Zona", "lantai": "Lantai", "waktu": "Cek terakhir",
        "status": "Status", "suhu_koridor": "Koridor (°C)",
        "suhu_supply": "Supply (°C)", "suhu_return": "Return (°C)",
        "delta_t": "ΔT (°C)", "alarm": "Kondisi", "catatan": "Catatan",
    })
    st.dataframe(tabel, width="stretch", hide_index=True)

    st.download_button(
        "⬇️ Unduh data terfilter (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name="monitoring_wcp_terfilter.csv",
        mime="text/csv",
    )


# ------------------------------------------------------------------
# ROUTER
# ------------------------------------------------------------------
if menu == "📝 Input Checklist":
    halaman_input()
elif menu == "🗂️ Data & Ekspor":
    halaman_data()
else:
    halaman_dashboard()
