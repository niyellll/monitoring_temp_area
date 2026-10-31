"""
Dashboard Monitoring Temperature Area - Unit WCP/AC Koridor
Input manual dari checklist harian (belum ada sensor / BMS).

Jalankan:  streamlit run app.py
"""
import os
from datetime import date, datetime, time, timedelta

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

DATA_FILE = "data_checklist.csv"

COLUMNS = [
    "waktu", "unit", "zona", "lantai",
    "suhu_koridor", "suhu_supply", "suhu_return",
    "status", "petugas", "catatan",
]

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


# ------------------------------------------------------------------
# DATA
# ------------------------------------------------------------------
def buat_data_contoh() -> pd.DataFrame:
    """Data contoh 7 hari x 3 kali cek x 8 unit (untuk prototipe)."""
    rng = np.random.default_rng(42)
    rows = []
    hari_ini = date.today()
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
                if r < 0.04:
                    status = "FAULT"
                elif r < 0.08:
                    status = "OFF"
                else:
                    status = "ON"

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


def muat_data() -> pd.DataFrame:
    if not os.path.exists(DATA_FILE):
        df = buat_data_contoh()
        df.to_csv(DATA_FILE, index=False)
        return df
    df = pd.read_csv(DATA_FILE, parse_dates=["waktu"])
    for c in COLUMNS:
        if c not in df.columns:
            df[c] = np.nan
    df["catatan"] = df["catatan"].fillna("")
    return df[COLUMNS]


def simpan_data(df: pd.DataFrame) -> None:
    df.to_csv(DATA_FILE, index=False)


def tambah_delta_t(df: pd.DataFrame) -> pd.DataFrame:
    df = df.copy()
    df["delta_t"] = (df["suhu_return"] - df["suhu_supply"]).round(1)
    return df


def evaluasi_alarm(row, t_min, t_max, dt_min) -> str:
    """Kembalikan teks alarm untuk satu baris (string kosong = normal)."""
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

menu = st.sidebar.radio(
    "Menu", ["📊 Dashboard", "📝 Input Checklist", "🗂️ Data & Ekspor"]
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

df_all = muat_data()


# ------------------------------------------------------------------
# HALAMAN: INPUT CHECKLIST
# ------------------------------------------------------------------
if menu == "📝 Input Checklist":
    st.title("📝 Input Checklist Harian")
    st.caption("Isi hasil pengecekan lapangan. Data tersimpan otomatis ke CSV.")

    with st.form("form_checklist", clear_on_submit=True):
        c1, c2, c3 = st.columns(3)
        tgl = c1.date_input("Tanggal", date.today())
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
            baru = pd.DataFrame([{
                "waktu": datetime.combine(tgl, jam),
                "unit": unit, "zona": zona, "lantai": lantai,
                "suhu_koridor": s_koridor,
                "suhu_supply": s_supply,
                "suhu_return": s_return,
                "status": status,
                "petugas": petugas.strip(),
                "catatan": catatan.strip(),
            }])
            simpan_data(pd.concat([df_all, baru], ignore_index=True))
            st.success(f"Data {unit} pukul {jam:%H:%M} berhasil disimpan.")
            st.rerun()

    st.subheader("5 input terakhir")
    st.dataframe(
        df_all.sort_values("waktu", ascending=False).head(5),
        width='stretch', hide_index=True,
    )


# ------------------------------------------------------------------
# HALAMAN: DATA & EKSPOR
# ------------------------------------------------------------------
elif menu == "🗂️ Data & Ekspor":
    st.title("🗂️ Data & Ekspor")

    st.subheader("Edit / hapus data")
    st.caption("Ubah nilai langsung di tabel, hapus baris dengan memilihnya lalu tekan Delete, lalu klik Simpan.")
    edited = st.data_editor(
        df_all.sort_values("waktu", ascending=False).reset_index(drop=True),
        num_rows="dynamic", width='stretch', key="editor",
    )
    c1, c2, c3 = st.columns(3)
    if c1.button("💾 Simpan perubahan", type="primary"):
        edited["waktu"] = pd.to_datetime(edited["waktu"])
        simpan_data(edited[COLUMNS])
        st.success("Perubahan disimpan.")
        st.rerun()

    c2.download_button(
        "⬇️ Unduh CSV",
        df_all.to_csv(index=False).encode("utf-8"),
        file_name="data_checklist_wcp.csv",
        mime="text/csv",
    )

    st.divider()
    st.subheader("Impor / reset")
    up = st.file_uploader("Unggah CSV (format kolom sama)", type="csv")
    if up is not None and st.button("Gunakan file ini"):
        d = pd.read_csv(up, parse_dates=["waktu"])
        if set(COLUMNS).issubset(d.columns):
            simpan_data(d[COLUMNS])
            st.success("Data diganti dengan file yang diunggah.")
            st.rerun()
        else:
            st.error(f"Kolom harus ada: {', '.join(COLUMNS)}")

    if st.button("🔄 Reset ke data contoh"):
        simpan_data(buat_data_contoh())
        st.rerun()


# ------------------------------------------------------------------
# HALAMAN: DASHBOARD
# ------------------------------------------------------------------
else:
    st.title("📊 Dashboard Monitoring Temperature Area")
    st.caption(
        "Unit WCP/AC koridor · data dari checklist harian manual "
        "(area belum memakai AC central/chiller)"
    )

    if df_all.empty:
        st.info("Belum ada data. Isi dulu lewat menu **Input Checklist**.")
        st.stop()

    df_all = tambah_delta_t(df_all)

    # ---- Filter
    f1, f2, f3 = st.columns([2, 1, 1])
    tgl_min = df_all["waktu"].min().date()
    tgl_max = df_all["waktu"].max().date()
    rentang = f1.date_input(
        "Rentang tanggal", (tgl_min, tgl_max),
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

    if isinstance(rentang, tuple) and len(rentang) == 2:
        awal, akhir = rentang
    else:
        awal = akhir = rentang if not isinstance(rentang, tuple) else rentang[0]

    df = df_all[
        (df_all["waktu"].dt.date >= awal)
        & (df_all["waktu"].dt.date <= akhir)
        & (df_all["lantai"].isin(lantai_pilih))
        & (df_all["zona"].isin(zona_pilih))
    ]
    if df.empty:
        st.warning("Tidak ada data untuk filter yang dipilih.")
        st.stop()

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
    tren = (
        df.groupby(["waktu", "zona", "lantai"], as_index=False)["suhu_koridor"]
        .mean()
    )
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
    st.plotly_chart(fig, width='stretch')

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
        figdt.update_layout(
            height=340, yaxis_title="ΔT (°C)", margin=dict(t=30, b=10)
        )
        st.plotly_chart(figdt, width='stretch')

    with g2:
        st.subheader("Komposisi status")
        status_count = (
            df.groupby("status").size().reset_index(name="jumlah")
        )
        figpie = px.pie(
            status_count, names="status", values="jumlah", hole=0.5,
            color="status",
            color_discrete_map={"ON": "#2e7d32", "OFF": "#9e9e9e", "FAULT": "#c62828"},
        )
        figpie.update_layout(height=340, margin=dict(t=30, b=10))
        st.plotly_chart(figpie, width='stretch')

    # ---- Heatmap
    st.subheader("Heatmap suhu koridor per unit")
    pivot = df.pivot_table(
        index="unit", columns=df["waktu"].dt.strftime("%d/%m %H:%M"),
        values="suhu_koridor", aggfunc="mean",
    )
    pivot = pivot[sorted(pivot.columns, key=lambda s: datetime.strptime(s, "%d/%m %H:%M").replace(year=2000))]
    fighm = px.imshow(
        pivot, aspect="auto", color_continuous_scale="RdYlBu_r",
        labels=dict(color="°C", x="Waktu", y="Unit"),
    )
    fighm.update_layout(height=340, margin=dict(t=10, b=10))
    st.plotly_chart(fighm, width='stretch')

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
    st.dataframe(tabel, width='stretch', hide_index=True)

    st.download_button(
        "⬇️ Unduh data terfilter (CSV)",
        df.to_csv(index=False).encode("utf-8"),
        file_name="monitoring_wcp_terfilter.csv",
        mime="text/csv",
    )
