# Monitoring Suhu Koridor — Lippo Plaza Sidoarjo

Aplikasi Streamlit untuk checklist suhu koridor lantai GF dan UG.

## Sumber data
- **Demo:** data simulasi terpisah dalam session; tidak menjadi data operasional.
- **Data Real (Google Sheets):** tersedia otomatis jika `gcp_service_account` dan `sheets` telah dikonfigurasi di Streamlit secrets. Data input disimpan di Google Sheets.
- **Data Real (SQLite lokal):** pilihan tetap tersedia tanpa Google Sheets. Input disimpan dalam file `monitoring_suhu.db` (atau lokasi yang disetel lewat `TEMP_AREA_DB`).

**Penting:** File SQLite di Streamlit Community Cloud bersifat sementara dan dapat hilang saat aplikasi restart atau redeploy. Jangan mengandalkan mode SQLite Cloud untuk histori operasional permanen. Unduh CSV secara berkala; untuk penyimpanan persisten daring, aktifkan Google Sheets atau jalankan aplikasi pada server dengan disk persisten.

## Menjalankan
```bash
pip install -r requirements.txt
streamlit run app.py
```

Data Real berisi input pemeriksaan petugas; aplikasi tidak membaca sensor secara otomatis.
