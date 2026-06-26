import streamlit as st
import pandas as pd
import plotly.express as px

st.set_page_config(page_title="Dashboard Line Haul", layout="wide")

SHEET_ID = "1cQsjx6UZV4rJphWvwthS5DrPhztekXAH6XtDyFIquzA"
EXCEL_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"

st.title("Dashboard Line Haul")

@st.cache_data(ttl=300)
def load_data():
    # 1. Kunci baris kedua sebagai header asli
    all_sheets = pd.read_excel(EXCEL_URL, header=1, sheet_name=None)
    
    df_list = []
    for sheet_name, df_sheet in all_sheets.items():
        clean_sheet_name = sheet_name.strip().upper()
        
        if clean_sheet_name in ["DATA ALL", "MASTER KOORDINAT"]:
            continue 
            
        # Biarkan membaca seluruh kolom di sini agar koordinatnya ikut terbawa
        df_sheet["NAMA SHEET"] = clean_sheet_name
        df_list.append(df_sheet)
        
    if not df_list:
        return pd.DataFrame()
        
    df = pd.concat(df_list, ignore_index=True)

    # Bersihkan nama kolom
    df.columns = (
        df.columns
        .astype(str)
        .str.strip()
        .str.upper()
        .str.replace("_", " ")
        .str.replace("/", " ")
        .str.replace(".", "", regex=False)
        .str.replace("(", "", regex=False)
        .str.replace(")", "", regex=False)
    )

    # Bersihkan spasi data teks
    for col in df.select_dtypes(include=["object", "str"]).columns:
        df[col] = df[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)

    return df

df = load_data()

# =====================
# SIDEBAR: FILTER DATA
# =====================
st.sidebar.header("Filter Coverage")

filtered_df = df.copy()

# Kita langsung tentukan nama kolomnya berdasarkan format tabel Anda
COL_ORIGIN = "NAMA ORIGIN"
COL_DEST = "NAMA TUJUAN"
COL_STATUS = "FLOW POSITIVE NEGATIVE"
COL_PROV = "PROVINSI"
COL_TLC_ORIGIN = "TLC ORIGIN"
COL_TLC_DEST = "TLC TUJUAN"
COL_WILAYAH = "NAMA SHEET"

# 1. Filter Asal (Origin)
if COL_ORIGIN in filtered_df.columns:
    selected_origin = st.sidebar.multiselect(
        "Pilih Origin",
        sorted(filtered_df[COL_ORIGIN].dropna().unique())
    )
    if selected_origin:
        filtered_df = filtered_df[filtered_df[COL_ORIGIN].isin(selected_origin)]

# 2. Filter Tujuan (Destination)
if COL_DEST in filtered_df.columns:
    selected_dest = st.sidebar.multiselect(
        "Pilih Tujuan",
        sorted(filtered_df[COL_DEST].dropna().unique())
    )
    if selected_dest:
        filtered_df = filtered_df[filtered_df[COL_DEST].isin(selected_dest)]

# 3. Filter Status
if COL_STATUS in filtered_df.columns:
    selected_status = st.sidebar.multiselect(
        "Pilih Status",
        sorted(filtered_df[COL_STATUS].dropna().unique())
    )
    if selected_status:
        filtered_df = filtered_df[filtered_df[COL_STATUS].isin(selected_status)]

# 4. Filter TLC Origin
if COL_TLC_ORIGIN in filtered_df.columns:
    selected_tlc_origin = st.sidebar.multiselect(
        "Pilih TLC Origin",
        sorted(filtered_df[COL_TLC_ORIGIN].dropna().unique())
    )
    if selected_tlc_origin:
        filtered_df = filtered_df[filtered_df[COL_TLC_ORIGIN].isin(selected_tlc_origin)]

# 5. Filter TLC Tujuan
if COL_TLC_DEST in filtered_df.columns:
    selected_tlc_dest = st.sidebar.multiselect(
        "Pilih TLC Tujuan",
        sorted(filtered_df[COL_TLC_DEST].dropna().unique())
    )
    if selected_tlc_dest:
        filtered_df = filtered_df[filtered_df[COL_TLC_DEST].isin(selected_tlc_dest)]

# 6. Filter Wilayah / Sheet
if COL_WILAYAH in filtered_df.columns:
    selected_wilayah = st.sidebar.multiselect(
        "Pilih Wilayah",
        sorted(filtered_df[COL_WILAYAH].dropna().unique())
    )
    if selected_wilayah:
        filtered_df = filtered_df[filtered_df[COL_WILAYAH].isin(selected_wilayah)]
        
# =====================
# KPI & METRIK
# =====================
st.subheader("Ringkasan Line Haul")

kpi1, kpi2, kpi3 = st.columns(3)

kpi1.metric("Total Pengiriman / Baris", len(filtered_df))

if COL_ORIGIN in filtered_df.columns:
    kpi2.metric("Jumlah Origin Aktif", filtered_df[COL_ORIGIN].nunique())
else:
    kpi2.metric("Jumlah Origin Aktif", "-")

if COL_DEST in filtered_df.columns:
    kpi3.metric("Jumlah Destination Aktif", filtered_df[COL_DEST].nunique())
else:
    kpi3.metric("Jumlah Destination Aktif", "-")


# =====================
# GRAFIK CAKUPAN AREA (COVERAGE)
# =====================
st.subheader("Analisis Cakupan Area (Coverage)")

# Membuat dua kolom agar grafik bersebelahan
col_chart1, col_chart2 = st.columns(2)

# --- Grafik 1: Jumlah Rute per Provinsi ---
if COL_PROV in filtered_df.columns:
    prov_coverage = (
        filtered_df
        .groupby(COL_PROV)
        .size()
        .reset_index(name="JUMLAH_RUTE")
        .sort_values("JUMLAH_RUTE", ascending=False)
    )

    fig_prov = px.bar(
        prov_coverage,
        x="JUMLAH_RUTE",
        y=COL_PROV,
        orientation="h",
        title="Total Rute Line Haul per Provinsi Asal",
        color="JUMLAH_RUTE",
        color_continuous_scale="Blues" # Memberikan gradasi warna
    )
    
    fig_prov.update_layout(yaxis=dict(autorange="reversed"))
    col_chart1.plotly_chart(fig_prov, width="stretch")

# --- Grafik 2: Top Origin Jangkauan Terluas ---
if COL_ORIGIN in filtered_df.columns and COL_DEST in filtered_df.columns:
    origin_reach = (
        filtered_df
        .groupby(COL_ORIGIN)[COL_DEST]
        .nunique() # Menghitung berapa banyak kota tujuan BEDA yang dicover
        .reset_index(name="JUMLAH_DESTINASI")
        .sort_values("JUMLAH_DESTINASI", ascending=False)
        .head(5)
    )

    fig_origin = px.bar(
        origin_reach,
        x="JUMLAH_DESTINASI",
        y=COL_ORIGIN,
        orientation="h",
        title="Top 5 Origin dengan Jangkauan Tujuan Terbanyak",
        color="JUMLAH_DESTINASI",
        color_continuous_scale="Teal"
    )
    
    fig_origin.update_layout(yaxis=dict(autorange="reversed"))
    col_chart2.plotly_chart(fig_origin, width="stretch")


# =====================
# GRAFIK STATUS
# =====================
if COL_STATUS in filtered_df.columns:
    st.subheader("Distribusi Status")

    status_df = (
        filtered_df
        .groupby(COL_STATUS)
        .size()
        .reset_index(name="TOTAL")
        .sort_values("TOTAL", ascending=False)
    )

    fig_status = px.pie(
        status_df,
        names=COL_STATUS,
        values="TOTAL",
        title="Proporsi Status Line Haul",
        hole=0.4 # Membuatnya menjadi Donut Chart agar lebih modern
    )

    st.plotly_chart(fig_status, width="stretch")

# =====================
# DATA DETAIL
# =====================
st.subheader("Data Detail")

# 🔥 POTONG VISUAL DI SINI: Tampilkan hanya dari kolom pertama sampai MINIMUM LOADMENT KG
if "MINIMUM LOADMENT KG" in filtered_df.columns:
    idx_last = filtered_df.columns.get_loc("MINIMUM LOADMENT KG")
    # Hanya mengambil kolom indeks 0 sampai kolom MINIMUM LOADMENT KG saja
    display_df = filtered_df.iloc[:, :idx_last+1]
else:
    # Fallback jika nama kolom tidak pas, hapus manual kolom penunjang peta
    display_df = filtered_df.drop(columns=["NAMA SHEET", "LATITUDE ORIGIN", "LONGITUDE ORIGIN", "TIPE", "COLOR"], errors="ignore")

# Tampilkan tabel yang sudah bersih dan rapi
st.dataframe(display_df, width="stretch")

# Tombol download juga hanya mendownload data bersih (Kolom A sampai V)
csv = display_df.to_csv(index=False).encode("utf-8")

st.download_button(
    label="Download Data Terfilter (CSV)",
    data=csv,
    file_name="linehaul_filtered.csv",
    mime="text/csv"
)

# =====================
# PETA INTERAKTIF (MODE AMAN, INTERAKTIF & GARIS KONDISIONAL V2)
# =====================
st.subheader("Peta Persebaran Titik & Rute Line Haul")

# 1. Pastikan semua kolom koordinat asal dan tujuan sudah masuk ke memori
filtered_df.columns = filtered_df.columns.str.strip().str.upper()

required_coords = ["LATITUDE ORIGIN", "LONGITUDE ORIGIN", "LATITUDE TUJUAN", "LONGITUDE TUJUAN"]

if all(c in filtered_df.columns for c in required_coords):
    df_map = filtered_df.copy()

    # 2. Paksa bersihkan koma dan ubah semua koordinat menjadi angka desimal (float)
    for col in required_coords:
        df_map[col] = df_map[col].astype(str).str.strip().str.replace(",", ".", regex=False)
        df_map[col] = pd.to_numeric(df_map[col], errors='coerce')
    
    # 3. Buang baris jika ada salah satu koordinat yang kosong atau gagal VLOOKUP
    df_clean = df_map.dropna(subset=required_coords).copy()

    # UBAH NAMA KOLOM: Menjadi singkat tanpa spasi agar aman dieksekusi JavaScript Pydeck
    df_clean = df_clean.rename(columns={
        "LATITUDE ORIGIN": "from_lat",
        "LONGITUDE ORIGIN": "from_lng",
        "LATITUDE TUJUAN": "to_lat",
        "LONGITUDE TUJUAN": "to_lng"
    })

    # Deteksi status operasional untuk pewarnaan titik pin peta
    status_col = "STATUS ORIGIN" if "STATUS ORIGIN" in df_clean.columns else ("STATUS TUJUAN" if "STATUS TUJUAN" in df_clean.columns else None)
    if status_col:
        df_clean["TIPE"] = df_clean[status_col].astype(str).str.strip().str.upper()
    else:
        df_clean["TIPE"] = "TIDAK DIKETAHUI"

    # 4. Render Peta Jika Data Valid Tersedia
    if not df_clean.empty:
        import pydeck as pdk
        
        # Fungsi Logika Pewarnaan Titik Pin Lokasi Asal (Origin)
        def assign_color(status_val):
            status_str = str(status_val)
            if "HUB UTAMA" in status_str:
                return [255, 50, 50, 210]       # 🔴 Merah untuk Hub Utama
            elif "SUB HUB" in status_str:
                return [255, 165, 0, 210]      # 🟡 Oranye untuk Sub Hub
            elif "KABUPATEN" in status_str or "DROPING" in status_str or "DROPPING" in status_str:
                return [50, 205, 50, 210]      # 🟢 Hijau untuk Kabupaten Penerusan
            else:
                return [0, 120, 255, 210]      # 🔵 Biru (Tipe Lainnya)

        df_clean["COLOR"] = df_clean["TIPE"].apply(assign_color)

        # 🔵 LAYER 1: Menggambar Titik Lokasi Asal / Origin (Selalu Muncul)
        scatterplot_layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_clean,
            get_position=["from_lng", "from_lat"], 
            get_fill_color="COLOR",
            get_radius=8000,            
            radius_min_pixels=6,        
            radius_max_pixels=15,       
            pickable=True,             
        )

        # ⚪ LAYER BARU: Menggambar Titik Lokasi Tujuan / Destination (Hanya Muncul Saat DI-FILTER)
        dest_scatterplot_layer = pdk.Layer(
            "ScatterplotLayer",
            data=df_clean,
            get_position=["to_lng", "to_lat"], 
            get_fill_color=[70, 80, 95, 220],             # Warna abu-abu kebiruan gelap yang netral dan bersih
            get_radius=6000,                              # Sedikit lebih kecil dari titik asal agar proporsional
            radius_min_pixels=5,        
            radius_max_pixels=12,       
            pickable=True,             
        )

        # 🛣️ LAYER 3: Menggambar Garis Penghubung Rute (Hanya Muncul Saat DI-FILTER)
        line_layer = pdk.Layer(
            "LineLayer",
            data=df_clean,
            get_source_position=["from_lng", "from_lat"], 
            get_target_position=["to_lng", "to_lat"],     
            get_color=[30, 144, 255, 150],                # Warna garis biru muda transparan
            get_width=3,                                  
            pickable=False,                               
        )

        # 🔥 LOGIKA KONDISIONAL TAMPILAN
        # Jika sedang memfilter (jumlah baris data menyusut), tampilkan Titik Asal + Titik Tujuan + Garis Rute
        if len(filtered_df) < len(df):
            layers_to_render = [scatterplot_layer, dest_scatterplot_layer, line_layer]
            info_rute = "*Garis biru menunjukkan rute aktif, titik abu-abu gelap menunjukkan lokasi kota tujuan.*"
        else:
            # Jika TIDAK memfilter, biarkan tampilan persis seperti sebelumnya (Hanya titik asal, jangan diubah)
            layers_to_render = [scatterplot_layer]
            info_rute = "*Garis rute dan titik tujuan disembunyikan otomatis agar peta tidak ruwet. Gunakan filter di sidebar untuk melihat jalur.*"

        # Mengatur center kamera peta berdasarkan rata-rata sebaran koordinat aktif
        mid_lat = df_clean["from_lat"].mean()
        mid_lon = df_clean["from_lng"].mean()

        # Render Peta Dinamis
        st.pydeck_chart(pdk.Deck(
            layers=layers_to_render, 
            initial_view_state=pdk.ViewState(
                latitude=mid_lat, 
                longitude=mid_lon, 
                zoom=5, 
                pitch=0
            ),
            map_style="light", 
            tooltip={
                "html": "<b>Origin:</b> {NAMA ORIGIN} <br/><b>Tujuan:</b> {NAMA TUJUAN} <br/><b>Status Origin:</b> {TIPE}",
                "style": {"backgroundColor": "black", "color": "white"}
            }
        ))
        
        # Informasi Legenda Visual Dashboard
        st.markdown(f"""
        **Legenda Status Titik Peta:** 🔴 **Hub Utama** | 🟡 **Sub Hub** | 🟢 **Kabupaten Penerusan (Droping)** | ⚫ **Titik Tujuan** {info_rute}
        """)
        
        st.success(f"✔️ Berhasil memplot {len(df_clean)} data pada peta.")
    else:
        st.error("❌ Data koordinat kosong setelah dibersihkan.")
else:
    st.error("❌ Kolom koordinat belum lengkap di file spreadsheet Anda.")