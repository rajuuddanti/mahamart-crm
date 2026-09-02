import os
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

# --- PAGE SETUP & MOBILE-FIRST RESPONSIVE CSS ---
st.set_page_config(page_title="MahaMart Feedback CRM", layout="wide")

hide_st_style = """
    <style>
    /* Hide Streamlit default headers & footers */
    footer {visibility: hidden !important;}
    [data-testid="stViewerBadge"], #viewerBadge {
        opacity: 0 !important;
        pointer-events: none !important;
        z-index: -9999 !important;
        cursor: default !important;
    }
    
    /* MOBILE UI OPTIMIZATIONS (Applies under 768px screen width) */
    @media (max-width: 768px) {
        .block-container {
            padding-left: 0.5rem !important;
            padding-right: 0.5rem !important;
            padding-top: 0.5rem !important;
        }
        
        [data-testid="stMetricValue"] {
            font-size: 1.1rem !important;
        }
        [data-testid="stMetricLabel"] {
            font-size: 0.75rem !important;
        }
        
        .stButton button, .stDownloadButton button {
            width: 100% !important;
            min-height: 46px !important;
            font-size: 0.95rem !important;
            margin-top: 0.2rem !important;
            margin-bottom: 0.2rem !important;
        }
        
        .stSelectbox, .stDateInput, .stTextArea {
            width: 100% !important;
        }
        
        [data-testid="stDataFrame"] {
            width: 100% !important;
            overflow-x: auto !important;
            -webkit-overflow-scrolling: touch;
        }
        
        .streamlit-expanderHeader {
            font-size: 0.85rem !important;
            padding: 0.5rem !important;
            line-height: 1.3 !important;
        }
    }
    </style>
    """
st.markdown(hide_st_style, unsafe_allow_html=True)

st.title("🗣️ MahaMart Customer Feedback & Service CRM")

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

# --- GLOBAL VARIABLES (PURE DATE ONLY) ---
today_date = datetime.now().date()
current_date_str = today_date.strftime('%Y-%m-%d')

# ==========================================
# SERVER-SIDE FETCHING FUNCTIONS
# ==========================================

@st.cache_data(ttl=3600, show_spinner=False)
def get_active_stores():
    try:
        res = supabase.rpc("get_distinct_locations").execute()
        if res.data:
            stores = [r['location'] for r in res.data if r.get('location')]
            return ["All Stores"] + sorted(stores)
    except Exception:
        pass
    
    return [
        "All Stores", "Burugupally", "Choppadandi", "Dharmaram", "Ellanthakunta", 
        "Gangadhara", "Gangadhara New", "Gharshakurthy", "Gopalrao Pet", "Koheda", 
        "MALLIAL", "PEGADAPALLY NEW", "PEGADAPALLY OLD", "Raikal", "vemulawada", "Vidya Nagar"
    ]

@st.cache_data(ttl=60, show_spinner=False)
def get_call_logs_by_range(start_d, end_d, store_filter="All Stores", type_filter="All Types"):
    start_str = start_d.strftime("%Y-%m-%d")
    end_str = end_d.strftime("%Y-%m-%d")
    
    query = supabase.table("call_logs").select("*") \
        .gte("call_date", start_str) \
        .lte("call_date", end_str)
        
    if store_filter != "All Stores":
        query = query.ilike("location", store_filter.strip())
        
    if type_filter != "All Types":
        query = query.eq("outreach_type", type_filter)
        
    response = query.execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['call_date'] = pd.to_datetime(df['call_date'], errors='coerce').dt.date
        df['display_time'] = df['call_date'].astype(str)
        if 'customer_name' not in df.columns:
            df['customer_name'] = 'Guest'
        else:
            df['customer_name'] = df['customer_name'].fillna('Guest')
        if 'feedback_type' not in df.columns:
            df['feedback_type'] = 'General'
        if 'location' not in df.columns:
            df['location'] = 'Unassigned'
        else:
            df['location'] = df['location'].fillna('Unassigned')
        if 'outreach_type' not in df.columns:
            df['outreach_type'] = 'Daily High Value'
        else:
            df['outreach_type'] = df['outreach_type'].fillna('Daily High Value')
    return df

@st.cache_data(ttl=300, show_spinner=False)
def get_bills_by_single_date(target_d, store_filter="All Stores"):
    target_str = target_d.strftime("%Y-%m-%d")
    query = supabase.table("bills").select("customer_name, customer_code, net_sales, bill_date, location") \
        .eq("bill_date", target_str)
        
    if store_filter != "All Stores":
        query = query.ilike("location", store_filter.strip())
        
    response = query.execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['bill_date'] = pd.to_datetime(df['bill_date']).dt.date
        df['customer_code'] = df['customer_code'].fillna("No Mobile").astype(str).str.strip()
        df = df[(df['customer_code'] != "No Mobile") & (df['customer_code'] != "nan") & (df['customer_code'] != "")]
        df['customer_name'] = df['customer_name'].fillna("Guest").astype(str).str.strip()
        df['net_sales'] = pd.to_numeric(df['net_sales'], errors='coerce').fillna(0)
        
        summary = df.groupby(['customer_code', 'customer_name', 'location']).agg(
            last_bill_amount=('net_sales', 'sum'),
            last_billed_date=('bill_date', 'max')
        ).reset_index()
        summary['days_inactive'] = summary['last_billed_date'].apply(lambda d: (today_date - d).days)
        
        return summary.sort_values(by="last_bill_amount", ascending=False).head(40)
        
    return pd.DataFrame()

@st.cache_data(ttl=60, show_spinner=False)
def get_retention_customers(store_filter="All Stores", min_days=45, max_days=60):
    try:
        res = supabase.rpc("get_retention_targets", {
            "p_store": store_filter,
            "p_min_days": min_days,
            "p_max_days": max_days
        }).execute()
        
        if res.data:
            df = pd.DataFrame(res.data)
            df['last_billed_date'] = pd.to_datetime(df['last_billed_date']).dt.date
            df['last_bill_amount'] = pd.to_numeric(df['last_bill_amount'], errors='coerce').fillna(0)
            return df
    except Exception as e:
        st.error(f"Retention RPC Error: {e}")
        
    return pd.DataFrame()

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
        cdf['display_time'] = cdf['call_date'].astype(str)
        cdf['parsed_date'] = pd.to_datetime(cdf['call_date'], errors='coerce').dt.date
        if 'customer_name' not in cdf.columns:
            cdf['customer_name'] = 'Guest'
        if 'feedback_type' not in cdf.columns:
            cdf['feedback_type'] = 'General'
        if 'location' not in cdf.columns:
            cdf['location'] = 'Unassigned'
        if 'outreach_type' not in cdf.columns:
            cdf['outreach_type'] = 'Daily High Value'
    else:
        cdf = pd.DataFrame(columns=['mobile_number', 'customer_name', 'call_date', 'display_time', 'parsed_date', 'status', 'feedback_type', 'comments', 'location', 'outreach_type'])
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
                
                df_up['bill_date'] = pd.to_datetime(df_up['bill_date'], errors='coerce').dt.strftime('%Y-%m-%d')
                df_up['location'] = df_up['location'].fillna("Unknown").astype(str).str.strip()
                df_up['pos_machineno'] = df_up['pos_machineno'].fillna("").astype(str).str.replace(r'\.0$', '', regex=True).str.strip()
                df_up['billno'] = df_up['billno'].astype(str).str.strip()
                df_up['customer_name'] = df_up['customer_name'].fillna("Guest").astype(str).str.strip()
                df_up['net_sales'] = pd.to_numeric(df_up['net_sales'], errors='coerce').fillna(0)
                df_up['sold_qty'] = pd.to_numeric(df_up['sold_qty'], errors='coerce').fillna(0)
                
                df_up['customer_code'] = df_up['customer_code'].fillna("No Mobile").astype(str)
                df_up['customer_code'] = df_up['customer_code'].str.replace(r'\.0$', '', regex=True).str.strip()
                df_up.loc[df_up['customer_code'].isin(["", "nan", "NaN"]), 'customer_code'] = "No Mobile"

                clean_df = df_up[['bill_date', 'location', 'pos_machineno', 'billno', 'customer_code', 'customer_name', 'net_sales', 'sold_qty']].copy()
                clean_df = clean_df.dropna(subset=['bill_date'])

                records = clean_df.to_dict(orient='records')
                total_recs = len(records)

                chunk_size = 500
                progress_bar = st.sidebar.progress(0)
                
                for i in range(0, total_recs, chunk_size):
                    chunk = records[i:i + chunk_size]
                    supabase.table("bills").insert(chunk).execute()
                    progress_bar.progress(min(1.0, (i + chunk_size) / total_recs))

                st.sidebar.success(f"✅ {total_recs:,} rows uploaded successfully!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"❌ Upload Error: {e}")

# 3. DELETE WRONG UPLOADS
st.sidebar.markdown("---")
st.sidebar.subheader("🗑️ Delete Wrong Upload")
delete_date = st.sidebar.date_input("Select Bill Date to Delete", value=today_date, key="del_date_input")

if st.sidebar.button("❌ Delete Bills for Selected Date"):
    try:
        formatted_del_date = delete_date.strftime("%Y-%m-%d")
        supabase.table("bills").delete().eq("bill_date", formatted_del_date).execute()
        st.sidebar.success(f"✅ Deleted all bills for {formatted_del_date}!")
        st.cache_data.clear()
        st.rerun()
    except Exception as e:
        st.sidebar.error(f"❌ Delete Error: {e}")

# 4. GLOBAL DASHBOARD CONTROLS
st.sidebar.markdown("---")
st.sidebar.subheader("Dashboard Controls")

stores_list = get_active_stores()
selected_store = st.sidebar.selectbox("Select Store", stores_list, key="global_store_select")

st.sidebar.markdown("**Analytics & Audit Filters:**")
outreach_filter = st.sidebar.selectbox(
    "Outreach Strategy Filter", 
    ["All Types", "Daily High Value", "Retention Target"],
    key="global_outreach_filter"
)

col_s1, col_s2 = st.sidebar.columns(2)
start_date = col_s1.date_input("From Date:", value=today_date, key="analytics_from_date")
end_date = col_s2.date_input("To Date:", value=today_date, key="analytics_to_date")

# ==========================================
# OVERVIEW METRICS
# ==========================================
range_calls_df = get_call_logs_by_range(start_date, end_date, selected_store, outreach_filter)

total_calls = len(range_calls_df)
answered_df = range_calls_df[range_calls_df['status'] == 'Answered'] if not range_calls_df.empty else pd.DataFrame()
complaints_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Complaint', na=False)]) if not answered_df.empty else 0
good_service_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Good Service', na=False)]) if not answered_df.empty else 0
suggestions_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Suggestion', na=False)]) if not answered_df.empty else 0

st.markdown(f"### 📊 Call Summary Range: **{start_date.strftime('%d %b %Y')}** to **{end_date.strftime('%d %b %Y')}**")
kpi1, kpi2, kpi3, kpi4, kpi5 = st.columns(5)
kpi1.metric("📞 Total Calls", f"{total_calls:,}")
kpi2.metric("✅ Answered Calls", f"{len(answered_df):,}")
kpi3.metric("🟢 Good Service", f"{good_service_cnt:,}")
kpi4.metric("🔴 Complaints", f"{complaints_cnt:,}")
kpi5.metric("🟡 Suggestions", f"{suggestions_cnt:,}")

st.markdown("---")

# ==========================================
# TABS SETUP
# ==========================================
tab1, tab2, tab3 = st.tabs(["📞 Customer Calling List", "🏬 Store Feedback Analytics", "📜 Call & Feedback Audit"])

# TAB 1: DUAL-MODE CALLING LIST
with tab1:
    st.header("🎯 Customer Outreach & Calling Queue")
    
    call_type = st.radio(
        "Select Outreach Strategy:",
        ["📅 Daily High Value Shoppers (By Bill Date)", "⏳ Automated Retention Targets (By Inactivity)"],
        horizontal=True,
        key="main_call_strategy"
    )
    
    if call_type == "📅 Daily High Value Shoppers (By Bill Date)":
        current_outreach_tag = "Daily High Value"
        target_bill_date = st.date_input(
            "Select Bill Date to Target:",
            value=today_date - timedelta(days=1),
            key="daily_calling_bill_date"
        )
        st.caption(f"Showing top 40 spenders who shopped on **{target_bill_date.strftime('%d %b %Y')}**.")
        
        with st.spinner(f"Fetching shoppers for {target_bill_date}..."):
            display_df = get_bills_by_single_date(target_bill_date, selected_store)
            
    else:
        current_outreach_tag = "Retention Target"
        retention_bucket = st.radio(
            "Select Inactivity Window:", 
            ["⚠️ 45 - 60 Days Inactive", "🚨 60 - 90 Days Inactive", "🔴 90+ Days Inactive"], 
            horizontal=True, 
            key="ret_bucket"
        )
        
        if retention_bucket == "⚠️ 45 - 60 Days Inactive":
            min_d, max_d = 45, 60
        elif retention_bucket == "🚨 60 - 90 Days Inactive":
            min_d, max_d = 60, 90
        else:
            min_d, max_d = 90, 365
            
        st.caption(f"Calculated automatically relative to Today's Date ({today_date.strftime('%d %b %Y')}). Capped at top 40.")
        
        with st.spinner(f"Fetching churn-risk shoppers for {retention_bucket}..."):
            display_df = get_retention_customers(selected_store, min_days=min_d, max_days=max_d)

    st.markdown("### 👇 Click customer to log call status & feedback")
    
    if not display_df.empty:
        mobs_to_render = display_df['customer_code'].tolist()
        calls_df = get_calls_for_mobiles(mobs_to_render)
        
        for index, row in display_df.iterrows():
            mob = str(row['customer_code'])
            cust_name = str(row.get('customer_name', 'Guest'))
            cust_store = str(row['location'])
            cust_calls = pd.DataFrame() if calls_df.empty else calls_df[calls_df['mobile_number'].astype(str) == mob]
            call_status_label = "Never Called"
            is_recently_answered = False
            
            if not cust_calls.empty:
                latest_call = cust_calls.iloc[-1]
                fb_tag = f" | {latest_call.get('feedback_type', '')}" if latest_call['status'] == 'Answered' else ""
                call_status_label = f"Last Called: {latest_call.get('display_time', '')} ({latest_call['status']}{fb_tag})"
                call_d = latest_call.get('parsed_date')
                if latest_call['status'] == 'Answered' and call_d and call_d < today_date and call_d >= (today_date - timedelta(days=30)):
                    is_recently_answered = True
            
            last_bill_amt = row.get('last_bill_amount', 0)
            last_billed_str = row['last_billed_date'].strftime('%d %b %Y')
            days_inactive = row['days_inactive']
            
            header_title = f"{cust_name} | 📱 {mob} | Last Bill: {format_inr(last_bill_amt)} | Last Billed: {last_billed_str} ({days_inactive} days ago) | [{call_status_label}]"
            
            with st.expander(header_title):
                st.markdown(f"🗓️ **Last Visit Details:** Customer last shopped at **{cust_store}** on **{last_billed_str}** (**{days_inactive} days ago**).")
                
                if not cust_calls.empty:
                    st.info(f"📞 **Last Call Outcome:** {latest_call.get('display_time', '')} | Status: **{latest_call['status']}** | Type: **{latest_call.get('outreach_type', 'Daily High Value')}** | Feedback: **{latest_call.get('feedback_type', 'N/A')}**")
                    if latest_call['comments']:
                        st.write(f"💬 *Remarks:* {latest_call['comments']}")
                    st.dataframe(cust_calls[['display_time', 'location', 'outreach_type', 'status', 'feedback_type', 'comments']].rename(columns={'display_time': 'call_date'}).iloc[::-1], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ No past calls recorded for this customer.")
                
                if is_recently_answered:
                    st.warning("🚫 **Calling Locked:** Customer gave feedback within the last 30 days.")
                else:
                    st.markdown("**📝 Record New Call & Feedback**")
                    c_status = st.selectbox("Call Connection Status", ["Answered", "Not Answered", "Switched Off", "Not Reachable"], key=f"status_{mob}_{index}")
                    
                    c_feedback = "N/A"
                    if c_status == "Answered":
                        c_feedback = st.selectbox(
                            "Customer Feedback Category", 
                            ["🟢 Good Service", "🔴 Complaint", "🟡 Suggestion", "🔵 General Feedback / Inquiry"], 
                            key=f"fb_{mob}_{index}"
                        )
                        
                    c_comments = st.text_area("Detailed Customer Remarks / Notes", key=f"comm_{mob}_{index}")
                    
                    if st.button("Save Feedback", key=f"btn_{mob}_{index}"):
                        supabase.table("call_logs").insert({
                            "mobile_number": mob,
                            "customer_name": cust_name,
                            "location": cust_store,
                            "outreach_type": current_outreach_tag,
                            "status": c_status,
                            "feedback_type": c_feedback,
                            "comments": c_comments,
                            "call_date": current_date_str
                        }).execute()
                        st.success(f"Feedback logged for {cust_name} ({cust_store})!")
                        st.cache_data.clear() 
                        st.rerun()
    else:
        st.write("No customers found for the selected criteria.")

# TAB 2: STORE FEEDBACK ANALYTICS
with tab2:
    st.header(f"🏬 Store Analytics ({start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')})")
    st.caption(f"Filtered by Outreach Strategy: **{outreach_filter}**")
    
    if not range_calls_df.empty:
        st.markdown("### 📊 Store Call Connection Breakdown")
        store_calls = range_calls_df.groupby(['location', 'status']).size().unstack(fill_value=0).reset_index()
        for col in ["Answered", "Not Answered", "Not Reachable", "Switched Off"]:
            if col not in store_calls.columns: store_calls[col] = 0
            
        st.dataframe(store_calls, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### 💬 Answered Calls Feedback Breakdown")
        answered_calls_df = range_calls_df[range_calls_df['status'] == 'Answered']
        
        if not answered_calls_df.empty:
            feedback_summary = answered_calls_df.groupby(['location', 'feedback_type']).size().unstack(fill_value=0).reset_index()
            st.dataframe(feedback_summary, use_container_width=True, hide_index=True)
            
            analytics_csv = feedback_summary.to_csv(index=False).encode('utf-8')
            st.download_button(
                label="📥 Export Analytics Summary CSV",
                data=analytics_csv,
                file_name=f"Analytics_Summary_{start_date}_to_{end_date}.csv",
                mime="text/csv",
                key="dl_analytics_summary"
            )
        else:
            st.info("No answered calls logged within this date range.")
    else:
        st.info("No call logs found for the selected date range.")

# TAB 3: AUDIT
with tab3:
    st.header(f"📜 Call & Feedback Audit Log ({start_date.strftime('%d %b %Y')} to {end_date.strftime('%d %b %Y')})")
    st.caption(f"Filtered by Outreach Strategy: **{outreach_filter}**")
    
    if not range_calls_df.empty:
        audit_df = range_calls_df[['display_time', 'customer_name', 'mobile_number', 'location', 'outreach_type', 'status', 'feedback_type', 'comments']].sort_values(by="display_time", ascending=False)
        audit_df.columns = ['Date', 'Customer Name', 'Mobile Number', 'Store Location', 'Outreach Strategy', 'Status', 'Feedback Category', 'Customer Remarks']
        
        st.dataframe(audit_df, use_container_width=True, hide_index=True)
        
        audit_csv = audit_df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="📥 Export Call Audit Log CSV",
            data=audit_csv,
            file_name=f"Call_Audit_Log_{start_date}_to_{end_date}.csv",
            mime="text/csv",
            key="dl_audit_log"
        )
    else:
        st.info("No call audit records found for this date range.")