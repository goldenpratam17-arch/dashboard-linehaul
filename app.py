import streamlit as st
import pandas as pd
import plotly.express as px
import pydeck as pdk 
import requests      
import math          

st.set_page_config(page_title="Dashboard Line Haul", layout="wide")

SHEET_ID = "1cQsjx6UZV4rJphWvwthS5DrPhztekXAH6XtDyFIquzA"
EXCEL_URL = f"https://docs.google.com/spreadsheets/d/{SHEET_ID}/export?format=xlsx"

@st.cache_data(ttl=300)
def load_data():
    all_sheets = pd.read_excel(EXCEL_URL, header=1, sheet_name=None)
    df_list = []
    for sheet_name, df_sheet in all_sheets.items():
        clean_sheet_name = sheet_name.strip().upper()
        if clean_sheet_name in ["DATA ALL", "MASTER KOORDINAT"]:
            continue 
        df_sheet["NAMA SHEET"] = clean_sheet_name
        df_list.append(df_sheet)
        
    if not df_list: return pd.DataFrame()
    df = pd.concat(df_list, ignore_index=True)

    df.columns = (
        df.columns.astype(str).str.strip().str.upper()
        .str.replace("_", " ").str.replace("/", " ").str.replace(".", "", regex=False)
        .str.replace("(", "", regex=False).str.replace(")", "", regex=False)
    )

    for col in df.select_dtypes(include=["object", "str"]).columns:
        df[col] = df[col].astype(str).str.strip().str.replace(r"\s+", " ", regex=True)
    return df

df = load_data()

# ==========================================================================
# 🧭 SIDEBAR: NAVIGASI UTAMA & FILTER TERPUSAT
# ==========================================================================
st.sidebar.title("LINE HAUL SYSTEM")

# 1. Widget Menu Pilihan Halaman
menu_terpilih = st.sidebar.radio(
    "Pilih Halaman Menu:",
    ["🏠 Home & Ringkasan Data", "📊 Analisis Jaringan & SLA", "🗺️ Peta Interaktif Line Haul"]
)

st.sidebar.write("---")

# 2. Memasukkan Widget Filter ke dalam Expander
with st.sidebar.expander("🛠️ Filter Data (Coverage)", expanded=False):
    COL_ORIGIN = "NAMA ORIGIN"
    COL_DEST = "NAMA TUJUAN"
    COL_STATUS = "FLOW POSITIVE NEGATIVE"
    COL_PROV = "PROVINSI"
    COL_TLC_ORIGIN = "TLC ORIGIN"
    COL_TLC_DEST = "TLC TUJUAN"
    COL_WILAYAH = "NAMA SHEET"

    selected_origin = st.multiselect("Pilih Origin", sorted(df[COL_ORIGIN].dropna().unique())) if COL_ORIGIN in df.columns else []
    selected_dest = st.multiselect("Pilih Tujuan", sorted(df[COL_DEST].dropna().unique())) if COL_DEST in df.columns else []
    selected_status = st.multiselect("Pilih Status", sorted(df[COL_STATUS].dropna().unique())) if COL_STATUS in df.columns else []
    selected_tlc_origin = st.multiselect("Pilih TLC Origin", sorted(df[COL_TLC_ORIGIN].dropna().unique())) if COL_TLC_ORIGIN in df.columns else []
    selected_tlc_dest = st.multiselect("Pilih TLC Tujuan", sorted(df[COL_TLC_DEST].dropna().unique())) if COL_TLC_DEST in df.columns else []
    selected_wilayah = st.multiselect("Pilih Wilayah", sorted(df[COL_WILAYAH].dropna().unique())) if COL_WILAYAH in df.columns else []

# ==========================================================================
# LOGIKA PEMROSESAN DATA (DFS & BFS ADAPTIF DUA ARAH)
# ==========================================================================
def find_all_paths(data, start, end, origin_col, dest_col, max_depth=5):
    graph = {}
    clean_pairs = data[[origin_col, dest_col]].dropna().drop_duplicates()
    for _, row in clean_pairs.iterrows():
        o = str(row[origin_col]).strip().upper()
        d = str(row[dest_col]).strip().upper()
        if o not in graph: graph[o] = []
        if d not in graph[o]: graph[o].append(d)
        if d not in graph: graph[d] = []
        if o not in graph[d]: graph[d].append(o)
        
    all_paths = []
    def dfs(node, target, path):
        if len(path) > max_depth: return
        if node == target:
            all_paths.append(list(path))
            return
        for neighbor in graph.get(node, []):
            if neighbor not in path:
                path.append(neighbor)
                dfs(neighbor, target, path)
                path.pop()
    dfs(start, end, [start])
    return all_paths

filtered_df = df.copy()
is_multi_hop = False
is_wilayah_search = False 
top_2_jalur = []
tabel_rute_data = []

col_harga = "HARGA" if "HARGA" in df.columns else next((c for c in df.columns if any(k in c for k in ["HARGA", "TARIF", "BIAYA"])), None)
col_jarak = "JARAK" if "JARAK" in df.columns else next((c for c in df.columns if any(k in c for k in ["JARAK", "KM", "DIST"])), None)
col_sla = "SLA HARI" if "SLA HARI" in df.columns else next((c for c in df.columns if any(k in c for k in ["SLA", "HARI", "LEAD"])), None)

def extract_numeric(raw_val, is_sla_col=False):
    if pd.isna(raw_val): return 0.0
    val_str = str(raw_val).strip().upper()
    if val_str in ["NAN", "NONE", "", "-", "NULL"]: return 0.0
    val_str = val_str.replace("RP", "").replace("KM", "").replace("HARI", "").replace("DAYS", "").replace(" ", "")
    if val_str.count('.') > 1: val_str = val_str.replace('.', '') 
    if '.' in val_str and ',' in val_str: val_str = val_str.replace('.', '').replace(',', '.') 
    if ',' in val_str and '.' not in val_str:
        if len(val_str.split(',')[-1]) == 3 and not is_sla_col: val_str = val_str.replace(',', '') 
        else: val_str = val_str.replace(',', '.') 
    if '.' in val_str and ',' not in val_str:
        if len(val_str.split('.')[-1]) == 3 and not is_sla_col: val_str = val_str.replace('.', '') 
    parsed = pd.to_numeric(val_str, errors='coerce')
    return float(parsed) if not pd.isna(parsed) else 0.0

def haversine_distance(lat1, lon1, lat2, lon2):
    R = 6371.0
    lat1, lon1, lat2, lon2 = map(math.radians, [lat1, lon1, lat2, lon2])
    dlat = lat2 - lat1
    dlon = lon2 - lon1
    a = math.sin(dlat / 2)**2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2)**2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
    return R * c

def get_route_metrics_multimodal(jalur_kota, df_master):
    total_jarak_km = 0.0
    total_waktu_jam = 0.0
    list_moda = [] 
    COL_VIA = "VIA"
    
    for i in range(len(jalur_kota) - 1):
        kota_asal = jalur_kota[i]
        kota_tujuan = jalur_kota[i+1]
        
        row_seg = df_master[(df_master[COL_ORIGIN].astype(str).str.upper() == kota_asal) & (df_master[COL_DEST].astype(str).str.upper() == kota_tujuan)]
        is_reversed_leg = False
        
        if row_seg.empty:
            row_seg = df_master[(df_master[COL_ORIGIN].astype(str).str.upper() == kota_tujuan) & (df_master[COL_DEST].astype(str).str.upper() == kota_asal)]
            is_reversed_leg = True
        
        if not row_seg.empty:
            if not is_reversed_leg:
                lat_origin = pd.to_numeric(str(row_seg["LATITUDE ORIGIN"].iloc[0]).replace(',', '.'), errors='coerce')
                lng_origin = pd.to_numeric(str(row_seg["LONGITUDE ORIGIN"].iloc[0]).replace(',', '.'), errors='coerce')
                lat_dest = pd.to_numeric(str(row_seg["LATITUDE TUJUAN"].iloc[0]).replace(',', '.'), errors='coerce')
                lng_dest = pd.to_numeric(str(row_seg["LONGITUDE TUJUAN"].iloc[0]).replace(',', '.'), errors='coerce')
            else:
                lat_origin = pd.to_numeric(str(row_seg["LATITUDE TUJUAN"].iloc[0]).replace(',', '.'), errors='coerce')
                lng_origin = pd.to_numeric(str(row_seg["LONGITUDE TUJUAN"].iloc[0]).replace(',', '.'), errors='coerce')
                lat_dest = pd.to_numeric(str(row_seg["LATITUDE ORIGIN"].iloc[0]).replace(',', '.'), errors='coerce')
                lng_dest = pd.to_numeric(str(row_seg["LONGITUDE ORIGIN"].iloc[0]).replace(',', '.'), errors='coerce')
            
            via_mode = str(row_seg[COL_VIA].iloc[0]).strip().upper() if COL_VIA in row_seg.columns else "DARAT"
            if via_mode in ["NAN", "NONE", ""]: via_mode = "DARAT"
            list_moda.append(via_mode)
            
            if pd.isna(lat_origin) or pd.isna(lng_origin) or pd.isna(lat_dest) or pd.isna(lng_dest): continue
            
            seg_jarak = 0.0
            seg_kecepatan = 60.0 
            
            if "DARAT" in via_mode:
                seg_kecepatan = 60.0
                try:
                    url = f"http://router.project-osrm.org/route/v1/driving/{lng_origin},{lat_origin};{lng_dest},{lat_dest}?overview=false"
                    response = requests.get(url, timeout=5).json()
                    if response.get("code") == "Ok": seg_jarak = response["routes"][0]["distance"] / 1000.0
                    else: seg_jarak = haversine_distance(lat_origin, lng_origin, lat_dest, lng_dest)
                except: seg_jarak = haversine_distance(lat_origin, lng_origin, lat_dest, lng_dest)
            elif "LAUT" in via_mode:
                seg_kecepatan = 25.0 
                seg_jarak = haversine_distance(lat_origin, lng_origin, lat_dest, lng_dest)
            elif "UDARA" in via_mode:
                seg_kecepatan = 500.0 
                seg_jarak = haversine_distance(lat_origin, lng_origin, lat_dest, lng_dest)
            else:
                seg_kecepatan = 60.0
                seg_jarak = haversine_distance(lat_origin, lng_origin, lat_dest, lng_dest)
                
            total_jarak_km += seg_jarak
            total_waktu_jam += (seg_jarak / seg_kecepatan)
                
    sla_hari = math.ceil(total_waktu_jam / 12.0) if total_waktu_jam > 0 else 0
    string_moda = f"FULL {list_moda[0]}" if len(set(list_moda)) == 1 and len(list_moda) > 0 else (" ➡️ ".join(list_moda) if list_moda else "TIDAK DIKETAHUI")
    return total_jarak_km, sla_hari, string_moda

start_node = None
if len(selected_origin) == 1: start_node = str(selected_origin[0]).strip().upper()
elif len(selected_tlc_origin) == 1:
    matching_names = df[df[COL_TLC_ORIGIN] == selected_tlc_origin[0]][COL_ORIGIN].dropna().unique()
    if len(matching_names) > 0: start_node = str(matching_names[0]).strip().upper()

end_nodes_candidate = []
if len(selected_dest) == 1: end_nodes_candidate = [str(selected_dest[0]).strip().upper()]
elif len(selected_tlc_dest) == 1:
    matching_names = df[df[COL_TLC_DEST] == selected_tlc_dest[0]][COL_DEST].dropna().unique()
    end_nodes_candidate = [str(n).strip().upper() for n in matching_names]

if start_node and len(selected_wilayah) > 0 and not selected_dest and not selected_tlc_dest:
    is_wilayah_search = True
    matching_dests = df[df[COL_WILAYAH].isin(selected_wilayah)][COL_DEST].dropna().unique()
    end_nodes_candidate = [str(n).strip().upper() for n in matching_dests]

if start_node and end_nodes_candidate:
    if is_wilayah_search:
        # 🟢 MODE A: EKSEKUSI JARINGAN MAKRO REGIONAL
        is_multi_hop = True
        
        graph_bfs = {}
        clean_pairs = df[[COL_ORIGIN, COL_DEST]].dropna().drop_duplicates()
        for _, row in clean_pairs.iterrows():
            o = str(row[COL_ORIGIN]).strip().upper()
            d = str(row[COL_DEST]).strip().upper()
            if o not in graph_bfs: graph_bfs[o] = []
            if d not in graph_bfs[o]: graph_bfs[o].append(d)
            if d not in graph_bfs: graph_bfs[d] = []
            if o not in graph_bfs[d]: graph_bfs[d].append(o)
        
        shortest_paths = {start_node: [start_node]}
        queue_bfs = [[start_node]]
        while queue_bfs:
            current_path = queue_bfs.pop(0)
            current_node = current_path[-1]
            for neighbor in graph_bfs.get(current_node, []):
                if neighbor not in shortest_paths:
                    new_path = current_path + [neighbor]
                    shortest_paths[neighbor] = new_path
                    queue_bfs.append(new_path)
        
        jalur_wilayah_total = []
        for candidate in end_nodes_candidate:
            if candidate in shortest_paths:
                jalur_wilayah_total.append(shortest_paths[candidate])
        
        COL_ARMADA = "KEPEMILIKAN ARMADA"
        for jalur in jalur_wilayah_total:
            total_jarak, total_sla, moda_pengiriman = get_route_metrics_multimodal(jalur, df)
            is_full_inhouse = True
            
            for i in range(len(jalur) - 1):
                s_start, s_end = jalur[i], jalur[i+1]
                row_seg = df[(df[COL_ORIGIN].astype(str).str.upper() == s_start) & (df[COL_DEST].astype(str).str.upper() == s_end)]
                if row_seg.empty:
                    row_seg = df[(df[COL_ORIGIN].astype(str).str.upper() == s_end) & (df[COL_DEST].astype(str).str.upper() == s_start)]
                    
                if not row_seg.empty and COL_ARMADA in df.columns:
                    status_armada = str(row_seg[COL_ARMADA].iloc[0]).strip().upper()
                    if "INHOUSE SAPX" not in status_armada:
                        is_full_inhouse = False
                        break
                else:
                    is_full_inhouse = False
                    break
                    
            string_tampilan_harga = f"Rp {(total_jarak / 8.0) * 7000.0:,.0f}" if is_full_inhouse and total_jarak > 0 else "HARGA VENDOR"
            
            tabel_rute_data.append({
                "Tujuan": f"📍 Ke {jalur[-1]}",
                "Jalur Distribusi": " ➡️ ".join(jalur),
                "Moda Pengiriman": moda_pengiriman,
                "Total Jarak": f"{total_jarak:,.0f} KM" if total_jarak > 0 else "0 KM (Cek Koordinat)",
                "Total Biaya/Tarif": string_tampilan_harga,
                "Total SLA": f"SLA {total_sla}" if total_sla > 0 else "SLA 0"
            })
        
        unique_segments = set()
        for jalur in jalur_wilayah_total:
            for i in range(len(jalur) - 1): unique_segments.add((jalur[i], jalur[i+1]))
        
        route_rows = []
        for seg_start, seg_end in unique_segments:
            matched_row = df[(df[COL_ORIGIN].astype(str).str.upper() == seg_start) & (df[COL_DEST].astype(str).str.upper() == seg_end)].copy()
            if matched_row.empty:
                inverse_row = df[(df[COL_ORIGIN].astype(str).str.upper() == seg_end) & (df[COL_DEST].astype(str).str.upper() == seg_start)].copy()
                if not inverse_row.empty:
                    orig_name, dest_name = inverse_row[COL_ORIGIN].iloc[0], inverse_row[COL_DEST].iloc[0]
                    lat_org, lng_org = inverse_row["LATITUDE ORIGIN"].iloc[0], inverse_row["LONGITUDE ORIGIN"].iloc[0]
                    lat_dst, lng_dst = inverse_row["LATITUDE TUJUAN"].iloc[0], inverse_row["LONGITUDE TUJUAN"].iloc[0]
                    inverse_row[COL_ORIGIN], inverse_row[COL_DEST] = dest_name, orig_name
                    inverse_row["LATITUDE ORIGIN"], inverse_row["LONGITUDE ORIGIN"] = lat_dst, lng_dst
                    inverse_row["LATITUDE TUJUAN"], inverse_row["LONGUSH TUJUAN"] = lat_org, lng_org
                    route_rows.append(inverse_row.head(1))
            else:
                route_rows.append(matched_row.head(1))
        
        if route_rows: filtered_df = pd.concat(route_rows, ignore_index=True)
    
    else:
        # 🔵 MODE B: PENCARIAN SPECIFIC RUTE TUNGGAL (KOTA KE KOTA)
        semua_jalur = []
        for candidate in end_nodes_candidate:
            paths = find_all_paths(df, start_node, candidate, COL_ORIGIN, COL_DEST)
            if paths: semua_jalur.extend(paths)
                
        if semua_jalur:
            is_multi_hop = True
            semua_jalur = sorted(semua_jalur, key=len)
            top_2_jalur = semua_jalur[:2]
            COL_ARMADA = "KEPEMILIKAN ARMADA"
            
            for idx, jalur in enumerate(top_2_jalur, 1):
                total_jarak, total_sla, moda_pengiriman = get_route_metrics_multimodal(jalur, df)
                is_full_inhouse = True
                    
                for i in range(len(jalur) - 1):
                    s_start, s_end = jalur[i], jalur[i+1]
                    # ✔️ FIXED: Menghapus warning pemanggilan ganda 'df_master' di baris 316
                    row_seg = df[(df[COL_ORIGIN].astype(str).str.upper() == s_start) & (df[COL_DEST].astype(str).str.upper() == s_end)]
                    if row_seg.empty:
                        row_seg = df[(df[COL_ORIGIN].astype(str).str.upper() == s_end) & (df[COL_DEST].astype(str).str.upper() == s_start)]
                        
                    if not row_seg.empty and COL_ARMADA in df.columns:
                        status_armada = str(row_seg[COL_ARMADA].iloc[0]).strip().upper()
                        if "INHOUSE SAPX" not in status_armada: 
                            is_full_inhouse = False
                            break
                    else:
                        is_full_inhouse = False
                        break
                
                string_tampilan_harga = f"Rp {(total_jarak / 8.0) * 7000.0:,.0f}" if is_full_inhouse and total_jarak > 0 else "HARGA VENDOR"
                tabel_rute_data.append({
                    "Tujuan": f"Alternatif Rute {idx}",
                    "Jalur Distribusi": " ➡️ ".join(jalur),
                    "Moda Pengiriman": moda_pengiriman,
                    "Total Jarak": f"{total_jarak:,.0f} KM" if total_jarak > 0 else "0 KM (Cek Koordinat)",
                    "Total Biaya/Tarif": string_tampilan_harga,
                    "Total SLA": f"SLA {total_sla}" if total_sla > 0 else "SLA 0"
                })
            
            unique_segments = set()
            for jalur in top_2_jalur:
                for i in range(len(jalur) - 1): unique_segments.add((jalur[i], jalur[i+1]))
            
            route_rows = []
            for seg_start, seg_end in unique_segments:
                matched_row = df[(df[COL_ORIGIN].astype(str).str.upper() == seg_start) & (df[COL_DEST].astype(str).str.upper() == seg_end)].copy()
                if matched_row.empty:
                    inverse_row = df[(df[COL_ORIGIN].astype(str).str.upper() == seg_end) & (df[COL_DEST].astype(str).str.upper() == seg_start)].copy()
                    if not inverse_row.empty:
                        orig_name, dest_name = inverse_row[COL_ORIGIN].iloc[0], inverse_row[COL_DEST].iloc[0]
                        lat_org, lng_org = inverse_row["LATITUDE ORIGIN"].iloc[0], inverse_row["LONGITUDE ORIGIN"].iloc[0]
                        lat_dst, lng_dst = inverse_row["LATITUDE TUJUAN"].iloc[0], inverse_row["LONGITUDE TUJUAN"].iloc[0]
                        inverse_row[COL_ORIGIN], inverse_row[COL_DEST] = dest_name, orig_name
                        inverse_row["LATITUDE ORIGIN"], inverse_row["LONGITUDE ORIGIN"] = lat_dst, lng_dst
                        inverse_row["LATITUDE TUJUAN"], inverse_row["LONGITUDE TUJUAN"] = lat_org, lng_org
                        route_rows.append(inverse_row.head(1))
                else:
                    route_rows.append(matched_row.head(1))
                
            if route_rows:
                filtered_df = pd.concat(route_rows, ignore_index=True)
                if selected_status: filtered_df = filtered_df[filtered_df[COL_STATUS].isin(selected_status)]
                if selected_wilayah: filtered_df = filtered_df[filtered_df[COL_WILAYAH].isin(selected_wilayah)]
        else:
            st.sidebar.error(f"❌ Tidak ditemukan koneksi rute dari {start_node}")
            filtered_df = pd.DataFrame(columns=df.columns)
            is_multi_hop = True

if not is_multi_hop:
    if selected_origin: filtered_df = filtered_df[filtered_df[COL_ORIGIN].isin(selected_origin)]
    if selected_dest: filtered_df = filtered_df[filtered_df[COL_DEST].isin(selected_dest)]
    if selected_status: filtered_df = filtered_df[filtered_df[COL_STATUS].isin(selected_status)]
    if selected_tlc_origin: filtered_df = filtered_df[filtered_df[COL_TLC_ORIGIN].isin(selected_tlc_origin)]
    if selected_tlc_dest: filtered_df = filtered_df[filtered_df[COL_TLC_DEST].isin(selected_tlc_dest)]
    if selected_wilayah: filtered_df = filtered_df[filtered_df[COL_WILAYAH].isin(selected_wilayah)]

col_status_org = "STATUS ORIGIN" if "STATUS ORIGIN" in filtered_df.columns else None
col_status_dest = "STATUS TUJUAN" if "STATUS TUJUAN" in filtered_df.columns else None

# ==========================================================================
# 🏠 HALAMAN 1: HOME & DATA REKAPAN DETAIL
# ==========================================================================
if menu_terpilih == "🏠 Home & Ringkasan Data":
    st.title("Dashboard Line Haul — Logistik Regional")
    
    st.subheader("Ringkasan Line Haul")
    kpi1, kpi2, kpi3 = st.columns(3)
    
    nodes_data = []
    if col_status_org and COL_ORIGIN in filtered_df.columns:
        df_org = filtered_df[[COL_ORIGIN, col_status_org]].copy().rename(columns={COL_ORIGIN: "NAMA_TITIK", col_status_org: "STATUS_TITIK"})
        nodes_data.append(df_org)
    if col_status_dest and COL_DEST in filtered_df.columns:
        df_dest = filtered_df[[COL_DEST, col_status_dest]].copy().rename(columns={COL_DEST: "NAMA_TITIK", col_status_dest: "STATUS_TITIK"})
        nodes_data.append(df_dest)

    if nodes_data:
        df_all_nodes = pd.concat(nodes_data, ignore_index=True).drop_duplicates(subset=["NAMA_TITIK"])
        df_all_nodes["STATUS_TITIK"] = df_all_nodes["STATUS_TITIK"].astype(str).str.strip().str.upper()
        total_hub = df_all_nodes["STATUS_TITIK"].str.contains("HUB UTAMA").sum()
        total_sub_hub = df_all_nodes["STATUS_TITIK"].str.contains("SUB HUB").sum()
        total_kab = df_all_nodes["STATUS_TITIK"].str.contains("KABUPATEN|DROPING|DROPPING").sum()
    else:
        total_hub, total_sub_hub, total_kab = 0, 0, 0

    kpi1.metric("Total HUB Utama", total_hub)
    kpi2.metric("Total SUB HUB", total_sub_hub)
    kpi3.metric("Total Kabupaten Penerusan", total_kab)

    st.write("---")
    st.subheader("Data Detail Sheet")
    display_df = filtered_df.iloc[:, :filtered_df.columns.get_loc("MINIMUM LOADMENT KG")+1] if "MINIMUM LOADMENT KG" in filtered_df.columns else filtered_df.drop(columns=["NAMA SHEET", "LATITUDE ORIGIN", "LONGITUDE ORIGIN", "TIPE", "COLOR"], errors="ignore")
    st.dataframe(display_df, use_container_width=True)
    csv = display_df.to_csv(index=False).encode("utf-8")
    st.download_button(label="Download Data Terfilter (CSV)", data=csv, file_name="linehaul_filtered.csv", mime="text/csv")


# ==========================================================================
# 📊 HALAMAN 2: ANALISIS STRATEGIS & KLASTERISASI SLA
# ==========================================================================
elif menu_terpilih == "📊 Analisis Jaringan & SLA":
    st.title("📊 Modul Analisis Strategis Jaringan & Target SLA")
    
    st.subheader("Analisis Cakupan Area (Coverage)")
    col_chart1, col_chart2 = st.columns(2)

    if COL_PROV in filtered_df.columns:
        prov_coverage = filtered_df.groupby(COL_PROV).size().reset_index(name="JUMLAH_RUTE").sort_values("JUMLAH_RUTE", ascending=False)
        fig_prov = px.bar(prov_coverage, x="JUMLAH_RUTE", y=COL_PROV, orientation="h", title="Total Rute Line Haul per Provinsi Asal", color="JUMLAH_RUTE", color_continuous_scale="Blues")
        fig_prov.update_layout(yaxis=dict(autorange="reversed"))
        col_chart1.plotly_chart(fig_prov, use_container_width=True)

    if COL_ORIGIN in filtered_df.columns and COL_DEST in filtered_df.columns:
        origin_reach = filtered_df.groupby(COL_ORIGIN)[COL_DEST].nunique().reset_index(name="JUMLAH_DESTINASI").sort_values("JUMLAH_DESTINASI", ascending=False).head(5)
        fig_origin = px.bar(origin_reach, x="JUMLAH_DESTINASI", y=COL_ORIGIN, orientation="h", title="Top 5 Origin dengan Jangkauan Tujuan Terbanyak", color="JUMLAH_DESTINASI", color_continuous_scale="Teal")
        fig_origin.update_layout(yaxis=dict(autorange="reversed"))
        col_chart2.plotly_chart(fig_origin, use_container_width=True)

    if col_status_org and col_status_dest:
        df_alur = filtered_df[filtered_df[COL_STATUS].astype(str).str.strip().str.upper().str.contains("POSITIVE|DELIVERY", na=False)].copy() if COL_STATUS in filtered_df.columns else filtered_df.copy()
        df_alur["ALUR_JARINGAN"] = df_alur[col_status_org].astype(str).str.strip().str.upper() + " ➡️ " + df_alur[col_status_dest].astype(str).str.strip().str.upper()
        alur_dist = df_alur.groupby("ALUR_JARINGAN").size().reset_index(name="TOTAL_RUTE").sort_values("TOTAL_RUTE", ascending=False)
        alur_dist = alur_dist[alur_dist["TOTAL_RUTE"] > 0]
        
        fig_alur = px.bar(alur_dist, x="TOTAL_RUTE", y="ALUR_JARINGAN", orientation="h", title="Distribusi Karakteristik Aliran Jaringan (Hub & Spoke - Delivery Only)", color="TOTAL_RUTE", color_continuous_scale="Purples", labels={"TOTAL_RUTE": "Jumlah Rute", "ALUR_JARINGAN": "Jenis Koneksi Jalur"})
        fig_alur.update_layout(yaxis=dict(autorange="reversed"))
        st.plotly_chart(fig_alur, use_container_width=True)

    if COL_STATUS in filtered_df.columns:
        status_df = filtered_df.groupby(COL_STATUS).size().reset_index(name="TOTAL").sort_values("TOTAL", ascending=False)
        fig_status = px.pie(status_df, names=COL_STATUS, values="TOTAL", title="Proporsi Status Line Haul", hole=0.4)
        st.plotly_chart(fig_status, use_container_width=True)

    st.write("---")
    st.subheader("🎯 Analisis Validitas Akurasi SLA Publish (Multimoda)")
    
    if col_jarak and col_sla and col_jarak in filtered_df.columns and col_sla in filtered_df.columns:
        df_sla = filtered_df.copy()
        COL_VIA = "VIA" if "VIA" in df_sla.columns else None
        df_sla["SLA_EKSISTING_NUM"] = df_sla[col_sla].apply(lambda x: extract_numeric(x, is_sla_col=True))
        
        def hitung_sla_berdasarkan_via(row):
            jarak = extract_numeric(row[col_jarak])
            if jarak <= 0: return 0
            via_mode = str(row[COL_VIA]).strip().upper() if COL_VIA and not pd.isna(row[COL_VIA]) else "DARAT"
            kecepatan = 25.0 if "LAUT" in via_mode else (500.0 if "UDARA" in via_mode else 60.0)
            return math.ceil((jarak / kecepatan) / 12.0)
            
        df_sla["SLA_KALKULASI_SISTEM"] = df_sla.apply(hitung_sla_berdasarkan_via, axis=1)
        df_sla_valid = df_sla[df_sla["SLA_KALKULASI_SISTEM"] > 0].copy()
        
        if not df_sla_valid.empty:
            col_sla1, col_sla2 = st.columns(2)
            with col_sla1:
                def cek_kategori_gap(row):
                    eks = row["SLA_EKSISTING_NUM"]
                    kalk = row["SLA_KALKULASI_SISTEM"]
                    if eks == kalk: 
                        return "Sesuai Standar Fisik Jaringan"
                    elif eks < kalk: 
                        return "Over Promise (Eksisting Terlalu Cepat)"
                    else: 
                        return "Under Promise (Eksisting Terlalu Longgar)"
                    
                df_sla_valid["STATUS_GAP"] = df_sla_valid.apply(cek_kategori_gap, axis=1)
                gap_summary = df_sla_valid.groupby("STATUS_GAP").size().reset_index(name="TOTAL_RUTE")
            
                fig_gap = px.pie(
                    gap_summary, 
                    names="STATUS_GAP", 
                    values="TOTAL_RUTE", 
                    title="Proporsi Validitas Komitmen Waktu", 
                    hole=0.4, 
                    color="STATUS_GAP", 
                    color_discrete_map={
                        "Sesuai Standar Fisik Jaringan": "#2ECC71",          
                        "Over Promise (Eksisting Terlalu Cepat)": "#E74C3C",    
                        "Under Promise (Eksisting Terlalu Longgar)": "#F1C40F"  
                    }
                )
                event_gap = st.plotly_chart(fig_gap, on_select="rerun", use_container_width=True)
            
            with col_sla2:
                df_eks = df_sla_valid.groupby("SLA_EKSISTING_NUM").size().reset_index(name="Jumlah Rute").rename(columns={"SLA_EKSISTING_NUM": "SLA"})
                df_eks["Tipe SLA"] = "SLA Eksisting"
                df_kalk = df_sla_valid.groupby("SLA_KALKULASI_SISTEM").size().reset_index(name="Jumlah Rute").rename(columns={"SLA_KALKULASI_SISTEM": "SLA"})
                df_kalk["Tipe SLA"] = "SLA Usulan (Kalkulasi)"
                df_dist_plot = pd.concat([df_eks, df_kalk], ignore_index=True)
                df_dist_plot["SLA"] = "SLA " + df_dist_plot["SLA"].astype(int).astype(str)
                fig_dist = px.bar(df_dist_plot, x="SLA", y="Jumlah Rute", color="Tipe SLA", barmode="group", title="Distribusi Pergeseran Klaster SLA", color_discrete_sequence=["#34495E", "#9B59B6"], category_orders={"SLA": sorted(df_dist_plot["SLA"].unique())})
                st.plotly_chart(fig_dist, use_container_width=True)
            
            clicked_status = None
            if "points" in event_gap.selection and event_gap.selection["points"]:
                point_data = event_gap.selection["points"][0]
                if "label" in point_data: clicked_status = point_data["label"]
                elif "point_index" in point_data:
                    idx = point_data["point_index"]
                    if idx < len(gap_summary): clicked_status = gap_summary.iloc[idx]["STATUS_GAP"]
                
            opsi_dropdown = ["Tampilkan Semua Data Analisis"] + list(gap_summary["STATUS_GAP"].unique())
            status_terpilih = st.selectbox("🔍 Filter Detail Data Rute Berdasarkan Klaster:", opsi_dropdown, index=opsi_dropdown.index(clicked_status) if clicked_status in opsi_dropdown else 0)

            if status_terpilih != "Tampilkan Semua Data Analisis":
                df_click_detail = df_sla_valid[df_sla_valid["STATUS_GAP"] == status_terpilih].copy()
                kolom_tampil = [COL_ORIGIN, COL_DEST]
                if COL_VIA: kolom_tampil.append(COL_VIA)
                if col_jarak: kolom_tampil.append(col_jarak)
                kolom_tampil.extend([col_sla, "SLA_KALKULASI_SISTEM"])
            
                df_display_output = df_click_detail[kolom_tampil].rename(columns={col_sla: "SLA EKSISTING", "SLA_KALKULASI_SISTEM": "SLA TARGET FISIK"})
                st.dataframe(df_display_output, use_container_width=True)
            
            total_over = (df_sla_valid["STATUS_GAP"] == "Over Promise (Eksisting Terlalu Cepat)").sum()
            total_under = (df_sla_valid["STATUS_GAP"] == "Under Promise (Eksisting Terlalu Longgar)").sum()
        
            st.markdown("#### **Rekomendasi Kebijakan SLA Publish:**")
            if total_over > 0: st.error(f"⚠️ **Kritis Operasional:** Ditemukan **{total_over} rute** berstatus **Over Promise**. Target terlalu cepat dibanding batas fisik modanya. **Tindakan:** Segera naikkan SLA Publish.")
            if total_under > 0: st.warning(f"💡 **Peluang Komersial:** Ditemukan **{total_under} rute** berstatus **Under Promise**. SLA terlalu lambat/longgar. **Tindakan:** Pangkas SLA Publish agar lebih kompetitif.")


# ==========================================================================
# 🗺️ HALAMAN 3: PETA INTERAKTIF LINE HAUL (PYDECK LAYER) - UPGRADE VERSI 1
# ==========================================================================
elif menu_terpilih == "🗺️ Peta Interaktif Line Haul":
    st.title("🗺️ Peta Persebaran Titik & Rute Line Haul")
    
    # 🔴 UPGRADE 1: Bangun Master Node Registry (Untuk standarisasi status warna mutlak & koordinat)
    df_org_nodes = df[[COL_ORIGIN, "STATUS ORIGIN", "LATITUDE ORIGIN", "LONGITUDE ORIGIN"]].dropna().drop_duplicates(subset=[COL_ORIGIN]).rename(
        columns={COL_ORIGIN: "NAMA_TITIK", "STATUS ORIGIN": "STATUS_TITIK", "LATITUDE ORIGIN": "LAT", "LONGITUDE ORIGIN": "LNG"}
    )
    df_dst_nodes = df[[COL_DEST, "STATUS TUJUAN", "LATITUDE TUJUAN", "LONGITUDE TUJUAN"]].dropna().drop_duplicates(subset=[COL_DEST]).rename(
        columns={COL_DEST: "NAMA_TITIK", "STATUS TUJUAN": "STATUS_TITIK", "LATITUDE TUJUAN": "LAT", "LONGITUDE TUJUAN": "LNG"}
    )
    global_nodes = pd.concat([df_org_nodes, df_dst_nodes], ignore_index=True).drop_duplicates(subset=["NAMA_TITIK"])
    
    global_nodes["LAT"] = pd.to_numeric(global_nodes["LAT"].astype(str).str.strip().str.replace(",", ".", regex=False), errors='coerce')
    global_nodes["LNG"] = pd.to_numeric(global_nodes["LNG"].astype(str).str.strip().str.replace(",", ".", regex=False), errors='coerce')
    global_nodes = global_nodes.dropna(subset=["LAT", "LNG"])

    # 🔴 UPGRADE 2: Hitung jumlah jangkauan rute keluar unik untuk info Tooltip
    total_routes_map = df.groupby(COL_ORIGIN)[COL_DEST].nunique().to_dict()
    global_nodes["TOTAL_TUJUAN"] = global_nodes["NAMA_TITIK"].map(total_routes_map).fillna(0).astype(int)
    
    def get_label_tipe(status):
        st_str = str(status).upper()
        if "HUB UTAMA" in st_str: return "Hub Utama"
        elif "SUB HUB" in st_str: return "Sub Hub"
        elif "KABUPATEN" in st_str or "DROPING" in st_str or "DROPPING" in st_str: return "Kabupaten Penerusan"
        return "Titik Tujuan"
        
    def assign_node_color(status):
        st_str = str(status).upper()
        if "HUB UTAMA" in st_str: return [255, 50, 50, 230]       # Merah Mutlak
        elif "SUB HUB" in st_str: return [255, 165, 0, 230]       # Jingga Mutlak
        elif "KABUPATEN" in st_str or "DROPING" in st_str or "DROPPING" in st_str: return [50, 205, 50, 230] # Hijau Mutlak
        return [0, 120, 255, 230]                                 # Biru Titik Cabang Standard
        
    global_nodes["LBL_TIPE"] = global_nodes["STATUS_TITIK"].apply(get_label_tipe)
    global_nodes["COLOR"] = global_nodes["STATUS_TITIK"].apply(assign_node_color)
    
    filtered_df.columns = filtered_df.columns.str.strip().str.upper()
    required_coords = ["LATITUDE ORIGIN", "LONGITUDE ORIGIN", "LATITUDE TUJUAN", "LONGITUDE TUJUAN"]

    if all(c in filtered_df.columns for c in required_coords):
        if filtered_df.empty:
            st.warning(f"⚠️ Tidak ditemukan koneksi jaringan sama sekali untuk kriteria filter ini.")
        else:
            # Cari seluruh kota aktif di filter saat ini (baik sebagai asal maupun tujuan)
            active_cities = set(filtered_df[COL_ORIGIN].dropna().unique()).union(set(filtered_df[COL_DEST].dropna().unique()))
            df_active_nodes = global_nodes[global_nodes["NAMA_TITIK"].isin(active_cities)].copy()
            
            # Map koordinat garis rute
            coords_dict = global_nodes.set_index("NAMA_TITIK")[["LAT", "LNG"]].to_dict(orient="index")
            df_lines = filtered_df.copy()
            df_lines["from_lat"] = df_lines[COL_ORIGIN].map(lambda x: coords_dict.get(x, {}).get("LAT", None))
            df_lines["from_lng"] = df_lines[COL_ORIGIN].map(lambda x: coords_dict.get(x, {}).get("LNG", None))
            df_lines["to_lat"] = df_lines[COL_DEST].map(lambda x: coords_dict.get(x, {}).get("LAT", None))
            df_lines["to_lng"] = df_lines[COL_DEST].map(lambda x: coords_dict.get(x, {}).get("LNG", None))
            df_lines = df_lines.dropna(subset=["from_lat", "from_lng", "to_lat", "to_lng"])
            
            if not df_active_nodes.empty:
                # Plot Layer Tunggal untuk seluruh titik aktif (Warna Terkunci Mutlak)
                scatterplot_layer = pdk.Layer(
                    "ScatterplotLayer", 
                    data=df_active_nodes, 
                    get_position=["LNG", "LAT"], 
                    get_fill_color="COLOR", 
                    get_radius=8000, 
                    radius_min_pixels=6, 
                    radius_max_pixels=15, 
                    pickable=True
                )
                
                line_layer = pdk.Layer(
                    "LineLayer", 
                    data=df_lines, 
                    get_source_position=["from_lng", "from_lat"], 
                    get_target_position=["to_lng", "to_lat"], 
                    get_color=[30, 144, 255, 120], 
                    get_width=3
                )

                layers_to_render = [scatterplot_layer, line_layer] if (len(filtered_df) < len(df) or is_wilayah_search) else [scatterplot_layer]
                info_rute = "*Menampilkan peta jaringan terfilter.*" if (len(filtered_df) < len(df) or is_wilayah_search) else "*Garis rute otomatis disembunyikan agar peta tidak penuh. Gunakan filter untuk melihat jalur.*"

                # 🔴 UPGRADE 3: Modifikasi Tooltip sesuai template request user
                st.pydeck_chart(pdk.Deck(
                    layers=layers_to_render, 
                    initial_view_state=pdk.ViewState(latitude=df_active_nodes["LAT"].mean(), longitude=df_active_nodes["LNG"].mean(), zoom=5, pitch=0),
                    map_style="light", 
                    tooltip={
                        "html": "<b>{LBL_TIPE}:</b> {NAMA_TITIK} <br/><b>Tujuan:</b> {TOTAL_TUJUAN} Rute", 
                        "style": {"backgroundColor": "black", "color": "white"}
                    }
                ), use_container_width=True)
                
                st.markdown(f"**Legenda Titik Peta (Sesuai Status Master):** 🔴 **Hub Utama** | 🟡 **Sub Hub** | 🟢 **Kabupaten Penerusan** | 🔵 **Titik Cabang Jaringan** — {info_rute}")
                st.success(f"✔️ Berhasil memplot {len(df_active_nodes)} titik aktif dengan standarisasi warna status.")
                
                # 🔴 UPGRADE 4: Fitur Dropdown Eksplorasi Interaktif pengganti aksi Klik
                st.write("---")
                st.subheader("🔍 Eksplorasi Detail Titik Jaringan Logistik")
                pilihan_titik = sorted(list(df_active_nodes["NAMA_TITIK"].unique()))
                titik_terpilih = st.selectbox("Pilih salah satu titik di peta untuk melihat daftar tujuan keluarnya:", ["-- Pilih Titik Jaringan --"] + pilihan_titik)
                
                if titik_terpilih != "-- Pilih Titik Jaringan --":
                    # 1. Kumpulkan semua kandidat kolom yang ingin ditampilkan
                    kandidat_kolom = [COL_DEST, "STATUS TUJUAN", "STATUS ORIGIN", col_status_dest, col_jarak, col_sla]
                    
                    # 2. FILTER OTOMATIS: Hanya masukkan kolom yang BENAR-BENAR ada di file Excel kamu
                    kolom_tampil = [col for col in kandidat_kolom if col and col in df.columns]
                    
                    # 3. Buat list menjadi unik (menghindari kolom kembar)
                    kolom_tampil = list(dict.fromkeys(kolom_tampil))
                        
                    # 4. Eksekusi penarikan data dengan jaminan 100% anti-KeyError
                    df_dest_list = df[df[COL_ORIGIN] == titik_terpilih][kolom_tampil].drop_duplicates().reset_index(drop=True)
                    
                    if not df_dest_list.empty:
                        st.markdown(f"Berikut adalah daftar **{len(df_dest_list)} destinasi langsung** yang dilayani keluar dari **{titik_terpilih}**:")
                        st.dataframe(df_dest_list, use_container_width=True, hide_index=True)
                    else:
                        st.info(f"Titik **{titik_terpilih}** saat ini bertindak sebagai Spoke/Destinasi Akhir (not memiliki rute keluar lanjutan di database).")
                
                if is_multi_hop and tabel_rute_data:
                    st.write("---")
                    st.subheader("📋 Analisis Detail Rute Jaringan Distribusi Terfilter")
                    df_summary_tabel = pd.DataFrame(tabel_rute_data)
                    st.dataframe(df_summary_tabel, use_container_width=True, hide_index=True)
                    if not is_wilayah_search:
                        st.markdown("**Detail Alur Perjalanan Setiap Alternatif:**")
                        for item in tabel_rute_data: st.info(f"📍 **{item['Tujuan']}:** {item['Jalur Distribusi']}")
            else:
                st.error("❌ Data Koordinat Kosong di Spreadsheet Excel!")
                st.markdown("Algoritma berhasil menyusun rute, tetapi **kolom koordinat (Latitude/Longitude) masih kosong** untuk segmen rute di bawah ini. Silakan lengkapi di Excel Anda:")
                df_bolong = filtered_df[[COL_ORIGIN, COL_DEST, "NAMA SHEET"]].drop_duplicates()
                st.dataframe(df_bolong, use_container_width=True)
    else:
        st.error("❌ Kolom koordinat belum lengkap di file spreadsheet Anda.")
