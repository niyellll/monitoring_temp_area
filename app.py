"""
Dashboard Monitoring Temperature Area - Unit WCP/AC Koridor
Input manual dari checklist harian, dengan 2 mode:
  - DEMO : data simulasi (tidak disimpan permanen)
  - LIVE : terhubung ke Google Sheets (data nyata, bisa auto-refresh)

Jalankan:  streamlit run app.py
"""
from datetime import date, datetime, time, timedelta
import os
import sqlite3
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
MODE_LIVE = "🟢 Data Real (input lapangan)"

COLUMNS = [
    "waktu", "unit", "zona", "lantai",
    "suhu_koridor", "suhu_supply", "suhu_return",
    "status", "petugas", "catatan",
]
NUM_COLS = ["suhu_koridor", "suhu_supply", "suhu_return"]
TEXT_COLS = ["unit", "zona", "lantai", "status", "petugas", "catatan"]
FMT_WAKTU = "%Y-%m-%d %H:%M:%S"

# Daftar unit -> (zona, lantai). Ubah sesuai kondisi lapangan.
# Pembagian sementara: 4 unit GF dan 4 unit UG.
# Sesuaikan pemetaan ID unit setelah nomor fisik dikonfirmasi di lapangan.
UNITS = {
    "WCP-01": ("GF", "GF"),
    "WCP-02": ("GF", "GF"),
    "WCP-03": ("GF", "GF"),
    "WCP-04": ("GF", "GF"),
    "WCP-05": ("UG", "UG"),
    "WCP-06": ("UG", "UG"),
    "WCP-07": ("UG", "UG"),
    "WCP-08": ("UG", "UG"),
}

LANTAI = ["GF", "UG"]


def normalisasi_lantai(df: pd.DataFrame) -> pd.DataFrame:
    """Baca label lama tanpa mengubah data asli yang sudah tersimpan."""
    df = df.copy()
    lama = {"Lantai 1": "GF", "Lantai 2": "UG",
            "Lantai GF": "GF", "Lantai UG": "UG"}
    df["lantai"] = df["lantai"].replace(lama)
    # Format baru hanya mempunyai dua area; zona lama dikelompokkan per lantai.
    df["zona"] = df["lantai"]
    return df

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
                if lantai == "UG":
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
    return normalisasi_lantai(df.reset_index(drop=True))


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



def sqlite_path() -> str:
    return os.environ.get("TEMP_AREA_DB", "monitoring_suhu.db")


def sqlite_connect():
    con = sqlite3.connect(sqlite_path(), timeout=20)
    con.execute("PRAGMA busy_timeout = 20000")
    con.execute(
        "CREATE TABLE IF NOT EXISTS checklist ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "waktu TEXT NOT NULL, unit TEXT NOT NULL, zona TEXT, lantai TEXT, "
        "suhu_koridor REAL, suhu_supply REAL, suhu_return REAL, "
        "status TEXT, petugas TEXT, catatan TEXT)"
    )
    con.commit()
    return con


def _baca_sqlite() -> pd.DataFrame:
    with sqlite_connect() as con:
        return bersihkan(pd.read_sql_query(
            "SELECT " + ", ".join(COLUMNS) + " FROM checklist ORDER BY id", con
        ))


def _tambah_sqlite(baris: dict) -> None:
    values = df_ke_values(pd.DataFrame([baris], columns=COLUMNS))[0]
    with sqlite_connect() as con:
        con.execute(
            "INSERT INTO checklist (" + ", ".join(COLUMNS) + ") VALUES ("
            + ", ".join("?" for _ in COLUMNS) + ")", values
        )
        con.commit()


def _ganti_sqlite(df: pd.DataFrame) -> None:
    values = df_ke_values(df)
    with sqlite_connect() as con:
        con.execute("BEGIN IMMEDIATE")
        con.execute("DELETE FROM checklist")
        con.executemany(
            "INSERT INTO checklist (" + ", ".join(COLUMNS) + ") VALUES ("
            + ", ".join("?" for _ in COLUMNS) + ")", values
        )
        con.commit()


def muat_data(live: bool) -> pd.DataFrame:
    if live:
        return _baca_live() if LIVE_OK else _baca_sqlite()
    if "demo_df" not in st.session_state:
        st.session_state["demo_df"] = buat_data_contoh()
    return st.session_state["demo_df"].copy()


def tambah_baris(live: bool, baris: dict) -> None:
    baru = pd.DataFrame([baris], columns=COLUMNS)
    if live:
        if LIVE_OK:
            _worksheet().append_row(df_ke_values(baru)[0], value_input_option="RAW")
            _baca_live.clear()
        else:
            _tambah_sqlite(baris)
    else:
        st.session_state["demo_df"] = pd.concat(
            [muat_data(False), baru], ignore_index=True
        )


def simpan_semua(live: bool, df: pd.DataFrame) -> None:
    """Timpa seluruh data dengan df."""
    if live:
        if LIVE_OK:
            ws = _worksheet()
            ws.clear()
            ws.update(values=[COLUMNS] + df_ke_values(df), range_name="A1")
            _baca_live.clear()
        else:
            _ganti_sqlite(df)
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
st.sidebar.title("🌡️ Monitoring Suhu")
st.sidebar.caption("Lippo Plaza Sidoarjo · GF & UG")

LIVE_OK = live_tersedia()

mode = st.sidebar.radio(
    "Sumber data", [MODE_DEMO, MODE_LIVE], key="mode",
    index=1 if DEFAULT_MODE == "live" else 0,
)
if mode == MODE_LIVE:
    if LIVE_OK:
        st.sidebar.success("Penyimpanan: Google Sheets")
    else:
        st.sidebar.warning(
            "Penyimpanan: SQLite lokal. Di Streamlit Cloud, data dapat hilang "
            "saat restart atau deployment. Unduh CSV secara berkala."
        )

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
        if LIVE_OK:
            st.success("**DATA REAL** · Input pemeriksaan lapangan disimpan di Google Sheets.")
        else:
            st.warning(
                "**DATA REAL · SQLITE LOKAL** — Data berasal dari input petugas, "
                "bukan simulasi. Penyimpanan di Streamlit Community Cloud tidak "
                "dijamin permanen. Unduh CSV untuk backup secara berkala."
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
            "Gagal membaca data. Jika memakai Google Sheets, cek *secrets* dan "
            "pastikan akses service account sudah benar. Jika memakai SQLite, cek izin folder.\n\n"
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
        st.caption(f"Area monitoring: **Lantai {lantai}**")

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
        + (" **Menyimpan perubahan akan mengganti data real.**" if LIVE else "")
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
        ok = st.checkbox("Saya paham data real akan diganti dengan isi CSV ini")
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
        st.caption("Data simulasi hanya tersedia pada Mode Demo, tidak dimasukkan ke Data Real.")
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
    st.title("Monitoring Suhu Koridor")
    st.caption("Lippo Plaza Sidoarjo · Lantai GF & UG")
    banner()

    df_all = ambil_data()
    if df_all.empty:
        st.info("Belum ada data. Mulai dari menu Input Checklist.")
        return

    df_all = tambah_delta_t(df_all)
    tgl_min = df_all["waktu"].min().date()
    tgl_max = df_all["waktu"].max().date()
    col_tgl, col_lantai = st.columns([2, 1])
    rentang = col_tgl.date_input(
        "Periode", (max(tgl_min, tgl_max - timedelta(days=6)), tgl_max),
        min_value=tgl_min, max_value=tgl_max, key="filter_periode"
    )
    lantai_pilih = col_lantai.selectbox(
        "Tampilkan", ["Semua lantai", "GF", "UG"], key="filter_lantai"
    )
    if isinstance(rentang, (tuple, list)):
        if not rentang:
            st.info("Pilih tanggal awal dan akhir.")
            return
        awal, akhir = rentang[0], rentang[-1]
    else:
        awal = akhir = rentang

    df = df_all[
        (df_all["waktu"].dt.date >= awal)
        & (df_all["waktu"].dt.date <= akhir)
        & (df_all["lantai"].isin(LANTAI))
    ].copy()
    if lantai_pilih != "Semua lantai":
        df = df[df["lantai"] == lantai_pilih].copy()
    if df.empty:
        st.info("Tidak ada data untuk periode dan lantai ini.")
        return

    # Status menggunakan pemeriksaan TERAKHIR tiap unit, bukan rata-rata historis.
    terbaru = df.sort_values("waktu").groupby("unit").tail(1).copy()
    terbaru["alarm"] = terbaru.apply(
        evaluasi_alarm, axis=1, args=(t_min, t_max, dt_min)
    )
    pilihan = LANTAI if lantai_pilih == "Semua lantai" else [lantai_pilih]

    st.subheader("Ringkasan per lantai")
    kolom = st.columns(len(pilihan))
    for box, lantai in zip(kolom, pilihan):
        riwayat = df[df["lantai"] == lantai]
        cek = terbaru[terbaru["lantai"] == lantai]
        with box:
            with st.container(border=True):
                st.markdown(f"### Lantai {lantai}")
                if riwayat.empty or cek.empty:
                    st.caption("Belum ada pemeriksaan pada periode ini.")
                    continue
                # Suhu yang ditampilkan = pembacaan terbaru setiap unit.
                suhu = cek["suhu_koridor"].mean()
                normal = int((cek["alarm"] == "🟢 Normal").sum())
                fault = int((cek["status"] == "FAULT").sum())
                perlu = len(cek) - normal
                st.metric("Suhu rata-rata terbaru", f"{suhu:.1f} °C")
                st.caption(f"Target: {t_min:g}–{t_max:g} °C")
                a, b, c = st.columns(3)
                a.metric("Unit ON", int((cek["status"] == "ON").sum()))
                b.metric("FAULT", fault)
                c.metric("Perhatian", perlu)
                if perlu:
                    st.warning(f"{perlu} dari {len(cek)} unit perlu diperiksa.")
                else:
                    st.success("Semua unit dalam kondisi normal.")
                st.caption(f"Cek terakhir: {cek['waktu'].max():%d/%m/%Y %H:%M} WIB")

    st.subheader("Tren suhu harian")
    tren = df.copy()
    tren["tanggal"] = tren["waktu"].dt.date
    tren = tren.groupby(["tanggal", "lantai"], as_index=False)["suhu_koridor"].mean()
    fig = px.line(
        tren, x="tanggal", y="suhu_koridor", color="lantai", markers=True,
        category_orders={"lantai": LANTAI},
        color_discrete_map={"GF": "#15803d", "UG": "#2563eb"},
        labels={"tanggal": "Tanggal", "suhu_koridor": "Suhu (°C)", "lantai": "Lantai"},
    )
    fig.add_hrect(y0=t_min, y1=t_max, fillcolor="#16a34a", opacity=0.08,
                  line_width=0)
    fig.update_layout(
        height=340, margin=dict(l=10, r=10, t=20, b=10),
        legend_title_text="", hovermode="x unified",
        xaxis_title="", yaxis_title="Suhu (°C)",
    )
    st.plotly_chart(fig, width="stretch")
    st.caption("Garis menunjukkan rata-rata seluruh pemeriksaan per hari. "
               "Area berbayang menunjukkan rentang suhu target.")

    st.subheader("Status unit terakhir")
    tabel = terbaru.sort_values(["lantai", "unit"])[
        ["lantai", "unit", "waktu", "status", "suhu_koridor",
         "delta_t", "alarm", "catatan"]
    ].rename(columns={
        "lantai": "Lantai", "unit": "Unit", "waktu": "Terakhir dicek",
        "status": "Status", "suhu_koridor": "Suhu (°C)",
        "delta_t": "ΔT (°C)", "alarm": "Kondisi", "catatan": "Catatan",
    })
    st.dataframe(
        tabel, width="stretch", hide_index=True,
        column_config={"Terakhir dicek": st.column_config.DatetimeColumn(
            "Terakhir dicek", format="DD/MM/YYYY HH:mm"
        )},
    )
    with st.expander("Unduh data & informasi perhitungan"):
        st.caption("Ringkasan dihitung dari pemeriksaan terakhir tiap unit "
                   "pada periode terpilih. Grafik memakai rata-rata harian.")
        st.download_button(
            "Unduh data terfilter (CSV)",
            df.to_csv(index=False).encode("utf-8-sig"),
            file_name="monitoring_suhu_gf_ug.csv", mime="text/csv",
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
