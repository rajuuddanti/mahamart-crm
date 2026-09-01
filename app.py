import os
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

# --- PAGE SETUP ---
st.set_page_config(page_title="MahaMart Telecalling CRM", layout="wide")

hide_st_style = """
            <style>
            footer {visibility: hidden !important;}
            [data-testid="stViewerBadge"], #viewerBadge {
                opacity: 0 !important;
                pointer-events: none !important;
                z-index: -9999 !important;
                cursor: default !important;
            }
            </style>
            """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("📞 MahaMart Telecalling & Retention CRM")

# --- INDIAN CURRENCY FORMATTER ---
def format_inr(amount):
    if pd.isna(amount):
        return "₹0.00"
    s = f"{amount:.2f}"
    parts = s.split(".")
    integer_part = parts[0]
    decimal_part = parts[1]
    
    if len(integer_part) <= 3:
        result = integer_part
    else:
        last_three = integer_part[-3:]
        remaining = integer_part[:-3]
        groups = []
        while len(remaining) > 0:
            groups.insert(0, remaining[-2:])
            remaining = remaining[:-2]
        result = ",".join(groups) + "," + last_three
    return f"₹{result}.{decimal_part}"

# --- DATABASE CONNECTION ---
@st.cache_resource
def init_connection():
    url = os.environ.get("SUPABASE_URL") or st.secrets["SUPABASE_URL"]
    key = os.environ.get("SUPABASE_KEY") or st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- GLOBAL VARIABLES ---
today_date = datetime.today().date()
current_date_str = today_date.strftime('%Y-%m-%d')
current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ==========================================
# SERVER-SIDE FETCHING FUNCTIONS
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_active_stores():
    try:
        response = supabase.table("bills").select("location").order("bill_date", desc=True).limit(2000).execute()
        if response.data:
            stores = pd.DataFrame(response.data)['location'].dropna().unique().tolist()
            return ["All Stores"] + sorted(stores)
    except Exception:
        pass
    return ["All Stores"]

@st.cache_data(ttl=60, show_spinner=False)
def get_all_call_logs():
    response = supabase.table("call_logs").select("*").execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['call_date'] = pd.to_datetime(df['call_date'], errors='coerce').dt.date
        df['display_time'] = df['call_time'].fillna(df['call_date'].astype(str))
    return df

@st.cache_data(ttl=300, show_spinner=False)
def get_bills_by_date(start_d, end_d, store_filter="All Stores"):
    all_bills = []
    start = 0
    step = 1000
    while True:
        query = supabase.table("bills").select("customer_name, customer_code, net_sales, bill_date, location") \
            .gte("bill_date", start_d.strftime("%Y-%m-%d")) \
            .lte("bill_date", end_d.strftime("%Y-%m-%d"))
            
        if store_filter != "All Stores":
            query = query.eq("location", store_filter)
            
        response = query.range(start, start + step - 1).execute()
        
        data = response.data
        if not data: break
        all_bills.extend(data)
        if len(data) < step: break
        start += step
        
    df = pd.DataFrame(all_bills)
    if not df.empty:
        df['bill_date'] = pd.to_datetime(df['bill_date']).dt.date
        df['customer_code'] = df['customer_code'].fillna("No Mobile").astype(str).str.strip()
        df.loc[df['customer_code'] == "", 'customer_code'] = "No Mobile"
        df['customer_name'] = df['customer_name'].fillna("Guest").astype(str).str.strip()
        df['net_sales'] = pd.to_numeric(df['net_sales'], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=60, show_spinner=False)
def get_calls_for_mobiles(mobile_list):
    if not mobile_list: return pd.DataFrame()
    
    all_calls = []
    for i in range(0, len(mobile_list), 100):
        chunk = mobile_list[i:i+100]
        resp = supabase.table("call_logs").select("*").in_("mobile_number", chunk).execute()
        if resp.data:
            all_calls.extend(resp.data)
            
    cdf = pd.DataFrame(all_calls)
    if not cdf.empty:
        cdf['display_time'] = cdf['call_time'].fillna(cdf['call_date'])
        cdf['parsed_date'] = pd.to_datetime(cdf['call_date'], errors='coerce').dt.date
    else:
        cdf = pd.DataFrame(columns=['mobile_number', 'call_date', 'call_time', 'display_time', 'parsed_date', 'status', 'comments'])
    return cdf

# --- SIDEBAR CONTROLS & WEB UPLOADER ---
st.sidebar.header("⚙️ Controls & Upload")

# 1. DOWNLOAD TEMPLATE
st.sidebar.subheader("📋 Download Template")
template_df = pd.DataFrame(columns=[
    'bill_date', 'location', 'pos_machineno', 'billno', 
    'customer_code', 'customer_name', 'net_sales', 'sold_qty'
])
template_df.loc[0] = ['31-Aug-26', 'Gopalrao Pet', '29', '28931', '9963440259', 'Srinivas', '365.17', '4.0']
template_csv = template_df.to_csv(index=False).encode('utf-8')

st.sidebar.download_button(
    label="📥 Download CSV Template",
    data=template_csv,
    file_name="Customer_Bill_Report_Template.csv",
    mime="text/csv"
)

st.sidebar.markdown("---")

# 2. FILE UPLOADER
st.sidebar.subheader("📤 Upload Daily CSV")
uploaded_file = st.sidebar.file_uploader("Choose CSV File", type=["csv"])

if uploaded_file is not None:
    if st.sidebar.button("🚀 Upload to Database"):
        with st.spinner("Uploading data using exact CSV headers..."):
            try:
                df_up = pd.read_csv(uploaded_file)
                
                # Format bill_date (supports '31-Aug-26' or '2026-08-31')
                df_up['bill_date'] = pd.to_datetime(df_up['bill_date'], errors='coerce').dt.strftime('%Y-%m-%d')
                
                # Format text fields
                df_up['location'] = df_up['location'].fillna("Unknown").astype(str).str.strip()
                df_up['pos_machineno'] = df_up['pos_machineno'].fillna("").astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                df_up['billno'] = df_up['billno'].astype(str).str.strip()
                df_up['customer_name'] = df_up['customer_name'].fillna("Guest").astype(str).str.strip()
                df_up['net_sales'] = pd.to_numeric(df_up['net_sales'], errors='coerce').fillna(0)
                df_up['sold_qty'] = pd.to_numeric(df_up['sold_qty'], errors='coerce').fillna(0)
                
                # Clean customer_code (mobile)
                df_up['customer_code'] = df_up['customer_code'].fillna("No Mobile").astype(str)
                df_up['customer_code'] = df_up['customer_code'].str.replace(r'\.0$', '', regex=True).str.strip()
                df_up.loc[df_up['customer_code'].isin(["", "nan", "NaN"]), 'customer_code'] = "No Mobile"

                # Keep exact headers
                clean_df = df_up[['bill_date', 'location', 'pos_machineno', 'billno', 'customer_code', 'customer_name', 'net_sales', 'sold_qty']].copy()
                clean_df = clean_df.dropna(subset=['bill_date'])

                records = clean_df.to_dict(orient='records')
                total_recs = len(records)

                chunk_size = 2000
                for i in range(0, total_recs, chunk_size):
                    chunk = records[i:i + chunk_size]
                    supabase.table("bills").insert(chunk).execute()

                st.sidebar.success(f"✅ {total_recs:,} rows uploaded successfully!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"❌ Upload Error: {e}")

st.sidebar.markdown("---")
st.sidebar.subheader("Filter Dashboard")
stores_list = get_active_stores()
selected_store = st.sidebar.selectbox("Select Store", stores_list)

# ==========================================
# OVERVIEW METRICS
# ==========================================
all_calls_df = get_all_call_logs()

if not all_calls_df.empty:
    mobs = all_calls_df['mobile_number'].unique().tolist()
    bills_for_calls = supabase.table("bills").select("customer_code, location").in_("customer_code", mobs[:500]).execute()
    if bills_for_calls.data:
        store_map = pd.DataFrame(bills_for_calls.data).drop_duplicates(subset=['customer_code']).set_index('customer_code')['location'].to_dict()
        all_calls_df['location'] = all_calls_df['mobile_number'].map(store_map).fillna("Unassigned")
    else:
        all_calls_df['location'] = "Unassigned"
        
    if selected_store != "All Stores":
        filtered_calls_df = all_calls_df[all_calls_df['location'] == selected_store]
    else:
        filtered_calls_df = all_calls_df
else:
    filtered_calls_df = pd.DataFrame(columns=['id', 'mobile_number', 'call_date', 'status', 'comments', 'call_time', 'location'])

total_calls = len(filtered_calls_df)
answered_calls = len(filtered_calls_df[filtered_calls_df['status'] == 'Answered'])
not_answered_calls = len(filtered_calls_df[filtered_calls_df['status'] == 'Not Answered'])
not_reachable_calls = len(filtered_calls_df[filtered_calls_df['status'] == 'Not Reachable'])
switched_off_calls = len(filtered_calls_df[filtered_calls_df['status'] == 'Switched Off'])

st.markdown("### 📊 Overall Telecalling Performance")
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("📞 Total Calls", f"{total_calls:,}")
kpi2.metric("✅ Answered", f"{answered_calls:,}")
kpi3.metric("❌ Not Answered", f"{not_answered_calls:,}")
kpi4.metric("📵 Not Reachable", f"{not_reachable_calls:,}")
kpi5.metric("📴 Switched Off", f"{switched_off_calls:,}")

st.markdown("---")

# ==========================================
# TABS SETUP
# ==========================================
tab1, tab2, tab3 = st.tabs(["📞 Retention & Calling List", "🏬 Store-Wise Analytics", "📜 Call History Audit"])

# TAB 1: RETENTION
with tab1:
    st.header("🎯 Customer Calling Lists")
    call_mode = st.radio("Select Module:", ["🏆 Top Spenders", "⚠️ Retention Calling"], horizontal=True, key="t1_mode")
    display_df = pd.DataFrame()
    
    if call_mode == "🏆 Top Spenders":
        st.subheader("Highest Value Customers")
        top40_dates = st.date_input("Select Date Range:", value=(today_date - timedelta(days=7), today_date), key="top40_dates")
        start_d, end_d = (top40_dates[0], top40_dates[1]) if len(top40_dates) == 2 else (top40_dates[0], top40_dates[0])
            
        with st.spinner(f"Fetching spenders for {selected_store}..."):
            base_df = get_bills_by_date(start_d, end_d, selected_store)
            
        if not base_df.empty:
            base_df = base_df[(base_df['customer_code'] != "No Mobile") & (base_df['customer_code'] != "nan")]
            display_df = base_df.groupby(['customer_code', 'customer_name']).agg(
                total_spent=('net_sales', 'sum'),
                last_visit=('bill_date', 'max')
            ).reset_index().sort_values(by="total_spent", ascending=False).head(40)
            
    else:
        st.subheader("Retention Targets (Churn Risk)")
        retention_filter = st.selectbox("Inactivity Window:", ["45-60 Days", "60-90 Days", "90+ Days"], key="t1_ret_filter")
        
        if retention_filter == "45-60 Days":
            start_d, end_d = today_date - timedelta(days=60), today_date - timedelta(days=45)
        elif retention_filter == "60-90 Days":
            start_d, end_d = today_date - timedelta(days=90), today_date - timedelta(days=61)
        else:
            start_d, end_d = today_date - timedelta(days=365), today_date - timedelta(days=91)

        with st.spinner(f"Finding retention targets for {selected_store}..."):
            base_df = get_bills_by_date(start_d, end_d, selected_store)
            
        if not base_df.empty:
            base_df = base_df[(base_df['customer_code'] != "No Mobile") & (base_df['customer_code'] != "nan")]
            retention_summary = base_df.groupby(['customer_code', 'customer_name']).agg(
                total_spent=('net_sales', 'sum'),
                last_visit=('bill_date', 'max')
            ).reset_index()
            
            potential_churn_mobs = retention_summary['customer_code'].tolist()
            calls_for_churn = get_calls_for_mobiles(potential_churn_mobs)
            if not calls_for_churn.empty:
                called_numbers = calls_for_churn['mobile_number'].unique()
                retention_summary = retention_summary[~retention_summary['customer_code'].isin(called_numbers)]
            
            display_df = retention_summary.sort_values(by="total_spent", ascending=False).head(100)

    st.markdown("### 👇 Click customer to view history & log call outcome")
    
    if not display_df.empty:
        mobs_to_render = display_df['customer_code'].tolist()
        calls_df = get_calls_for_mobiles(mobs_to_render)
        
        for index, row in display_df.iterrows():
            mob = str(row['customer_code'])
            cust_calls = pd.DataFrame() if calls_df.empty else calls_df[calls_df['mobile_number'].astype(str) == mob]
            call_status_label = "Never Called"
            is_recently_answered = False
            
            if not cust_calls.empty:
                latest_call = cust_calls.iloc[-1]
                call_status_label = f"Last Called: {latest_call.get('display_time', '')} ({latest_call['status']})"
                call_d = latest_call.get('parsed_date')
                if latest_call['status'] == 'Answered' and call_d and call_d < today_date and call_d >= (today_date - timedelta(days=30)):
                    is_recently_answered = True
            
            header_title = f"{row['customer_name']} | 📱 {mob} | Spent: {format_inr(row['total_spent'])} | Last Visit: {row['last_visit']} | [{call_status_label}]"
            
            with st.expander(header_title):
                if not cust_calls.empty:
                    st.info(f"📞 **Last Call:** {latest_call.get('display_time', '')} | Outcome: **{latest_call['status']}**")
                    if latest_call['comments']:
                        st.write(f"💬 *Remarks:* {latest_call['comments']}")
                    st.dataframe(cust_calls[['display_time', 'status', 'comments']].rename(columns={'display_time': 'call_date_time'}).iloc[::-1], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ No call history recorded for this customer yet.")
                
                if is_recently_answered:
                    st.warning("🚫 **Calling Locked:** Customer answered within last 30 days.")
                else:
                    st.markdown("**📝 Log Call Outcome**")
                    c_status = st.selectbox("Outcome", ["Answered", "Not Answered", "Switched Off", "Not Reachable"], key=f"status_{mob}_{index}")
                    c_comments = st.text_area("Remarks", key=f"comm_{mob}_{index}")
                    
                    if st.button("Save Call Outcome", key=f"btn_{mob}_{index}"):
                        supabase.table("call_logs").insert({
                            "mobile_number": mob,
                            "status": c_status,
                            "comments": c_comments,
                            "call_date": current_date_str,
                            "call_time": current_time_str
                        }).execute()
                        st.success("Saved!")
                        st.cache_data.clear() 
                        st.rerun()
    else:
        st.write("No customers found.")

# TAB 2: STORE ANALYTICS
with tab2:
    st.header("🏬 Store-Wise Performance")
    if not all_calls_df.empty:
        store_summary = all_calls_df.groupby(['location', 'status']).size().unstack(fill_value=0).reset_index()
        for col in ["Answered", "Not Answered", "Not Reachable", "Switched Off"]:
            if col not in store_summary.columns: store_summary[col] = 0
                
        store_summary['Total Calls'] = store_summary["Answered"] + store_summary["Not Answered"] + store_summary["Not Reachable"] + store_summary["Switched Off"]
        store_summary['Answer Rate (%)'] = (store_summary["Answered"] / store_summary['Total Calls'] * 100).round(1).astype(str) + "%"
        
        st.dataframe(store_summary[['location', 'Total Calls', 'Answered', 'Not Answered', 'Not Reachable', 'Switched Off', 'Answer Rate (%)']], use_container_width=True, hide_index=True)
        st.bar_chart(store_summary.set_index('location')[["Answered", "Not Answered", "Not Reachable", "Switched Off"]])
    else:
        st.info("No calls logged yet.")

# TAB 3: AUDIT
with tab3:
    st.header("📜 Complete Call Audit Log")
    if not filtered_calls_df.empty:
        audit_df = filtered_calls_df[['display_time', 'mobile_number', 'location', 'status', 'comments']].sort_values(by="display_time", ascending=False)
        audit_df.columns = ['Date & Time', 'Mobile Number', 'Store Location', 'Status', 'Comments']
        st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.info("No records found.")