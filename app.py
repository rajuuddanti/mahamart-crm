import os
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

# --- PAGE SETUP ---
st.set_page_config(page_title="MahaMart Feedback CRM", layout="wide")

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

# --- GLOBAL VARIABLES ---
today_date = datetime.today().date()
current_date_str = today_date.strftime('%Y-%m-%d')
current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

# ==========================================
# FAST SERVER-SIDE FETCHING FUNCTIONS
# ==========================================

@st.cache_data(ttl=300, show_spinner=False)
def get_active_stores():
    """Fetches unique stores by inspecting recent bills from latest date in DB."""
    try:
        latest_res = supabase.table("bills").select("bill_date").order("bill_date", desc=True).limit(1).execute()
        if latest_res.data:
            max_d = pd.to_datetime(latest_res.data[0]['bill_date']).date()
            min_d = max_d - timedelta(days=60)
            
            res = supabase.table("bills").select("location") \
                .gte("bill_date", min_d.strftime("%Y-%m-%d")) \
                .lte("bill_date", max_d.strftime("%Y-%m-%d")) \
                .limit(5000).execute()
                
            if res.data:
                df = pd.DataFrame(res.data)
                stores = df['location'].dropna().str.strip().unique().tolist()
                stores = [s for s in stores if s and s != "nan"]
                return ["All Stores"] + sorted(stores)
    except Exception:
        pass
    return ["All Stores"]

@st.cache_data(ttl=60, show_spinner=False)
def get_call_logs_by_date(target_d):
    """Fetches call logs for a single target date."""
    target_str = target_d.strftime("%Y-%m-%d")
    response = supabase.table("call_logs").select("*") \
        .eq("call_date", target_str) \
        .execute()
    
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['call_date'] = pd.to_datetime(df['call_date'], errors='coerce').dt.date
        df['display_time'] = df['call_time'].fillna(df['call_date'].astype(str))
        if 'feedback_type' not in df.columns:
            df['feedback_type'] = 'General'
    return df

@st.cache_data(ttl=300, show_spinner=False)
def get_bills_by_single_date(target_d, store_filter="All Stores"):
    """Fetches bills for ONE SINGLE target date for maximum performance."""
    target_str = target_d.strftime("%Y-%m-%d")
    query = supabase.table("bills").select("customer_name, customer_code, net_sales, bill_date, location") \
        .eq("bill_date", target_str)
        
    if store_filter != "All Stores":
        query = query.eq("location", store_filter)
        
    response = query.execute()
    df = pd.DataFrame(response.data)
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
        if 'feedback_type' not in cdf.columns:
            cdf['feedback_type'] = 'General'
    else:
        cdf = pd.DataFrame(columns=['mobile_number', 'call_date', 'call_time', 'display_time', 'parsed_date', 'status', 'feedback_type', 'comments'])
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

                chunk_size = 2000
                for i in range(0, total_recs, chunk_size):
                    chunk = records[i:i + chunk_size]
                    supabase.table("bills").insert(chunk).execute()

                st.sidebar.success(f"✅ {total_recs:,} rows uploaded successfully!")
                st.cache_data.clear()
                st.rerun()
            except Exception as e:
                st.sidebar.error(f"❌ Upload Error: {e}")

# 3. DELETE WRONG UPLOAD
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

st.sidebar.markdown("---")
st.sidebar.subheader("Dashboard Controls")
stores_list = get_active_stores()
selected_store = st.sidebar.selectbox("Select Store", stores_list)

# RESTRICTED SINGLE DATE FILTER FOR CALL LOGS
target_call_date = st.sidebar.date_input(
    "Select Target Call Date:", 
    value=today_date,
    key="target_call_date"
)

# ==========================================
# OVERVIEW METRICS
# ==========================================
all_calls_df = get_call_logs_by_date(target_call_date)

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
    filtered_calls_df = pd.DataFrame(columns=['id', 'mobile_number', 'call_date', 'status', 'feedback_type', 'comments', 'call_time', 'location'])

total_calls = len(filtered_calls_df)
answered_df = filtered_calls_df[filtered_calls_df['status'] == 'Answered']
complaints_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Complaint', na=False)])
good_service_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Good Service', na=False)])
suggestions_cnt = len(answered_df[answered_df['feedback_type'].str.contains('Suggestion', na=False)])

st.markdown(f"### 📊 Call Summary for Date: **{target_call_date.strftime('%d %b %Y')}**")
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
tab1, tab2, tab3 = st.tabs(["📞 Feedback Calling List", "🏬 Store Feedback Analytics", "📜 Call & Feedback Audit"])

# TAB 1: SINGLE-DATE TARGET CALLING LIST
with tab1:
    st.header("🎯 Customer Calling & Feedback Logging")
    
    st.subheader("High Value Shoppers by Single Date")
    single_bill_date = st.date_input("Select Shopping Date:", value=today_date - timedelta(days=1), key="single_bill_date")
        
    with st.spinner(f"Fetching shoppers for {single_bill_date}..."):
        base_df = get_bills_by_single_date(single_bill_date, selected_store)
        
    if not base_df.empty:
        base_df = base_df[(base_df['customer_code'] != "No Mobile") & (base_df['customer_code'] != "nan")]
        display_df = base_df.groupby(['customer_code', 'customer_name']).agg(
            total_spent=('net_sales', 'sum'),
            last_visit=('bill_date', 'max')
        ).reset_index().sort_values(by="total_spent", ascending=False).head(50)
    else:
        display_df = pd.DataFrame()

    st.markdown("### 👇 Click customer to log call status & feedback")
    
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
                fb_tag = f" | {latest_call.get('feedback_type', '')}" if latest_call['status'] == 'Answered' else ""
                call_status_label = f"Last Called: {latest_call.get('display_time', '')} ({latest_call['status']}{fb_tag})"
                call_d = latest_call.get('parsed_date')
                if latest_call['status'] == 'Answered' and call_d and call_d < today_date and call_d >= (today_date - timedelta(days=30)):
                    is_recently_answered = True
            
            header_title = f"{row['customer_name']} | 📱 {mob} | Spent: {format_inr(row['total_spent'])} | Date: {row['last_visit']} | [{call_status_label}]"
            
            with st.expander(header_title):
                if not cust_calls.empty:
                    st.info(f"📞 **Last Call Outcome:** {latest_call.get('display_time', '')} | Status: **{latest_call['status']}** | Feedback: **{latest_call.get('feedback_type', 'N/A')}**")
                    if latest_call['comments']:
                        st.write(f"💬 *Remarks:* {latest_call['comments']}")
                    st.dataframe(cust_calls[['display_time', 'status', 'feedback_type', 'comments']].rename(columns={'display_time': 'call_date_time'}).iloc[::-1], use_container_width=True, hide_index=True)
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
                            "status": c_status,
                            "feedback_type": c_feedback,
                            "comments": c_comments,
                            "call_date": current_date_str,
                            "call_time": current_time_str
                        }).execute()
                        st.success("Feedback logged successfully!")
                        st.cache_data.clear() 
                        st.rerun()
    else:
        st.write("No customers found for this specific date.")

# TAB 2: STORE FEEDBACK ANALYTICS (SINGLE DATE)
with tab2:
    st.header(f"🏬 Store Feedback Summary for {target_call_date.strftime('%d %b %Y')}")
    
    if not all_calls_df.empty:
        st.markdown("### 📊 Store Call Connection Breakdown")
        store_calls = all_calls_df.groupby(['location', 'status']).size().unstack(fill_value=0).reset_index()
        for col in ["Answered", "Not Answered", "Not Reachable", "Switched Off"]:
            if col not in store_calls.columns: store_calls[col] = 0
        st.dataframe(store_calls, use_container_width=True, hide_index=True)
        
        st.markdown("---")
        st.markdown("### 💬 Answered Calls Feedback Breakdown")
        answered_calls_df = all_calls_df[all_calls_df['status'] == 'Answered']
        
        if not answered_calls_df.empty:
            feedback_summary = answered_calls_df.groupby(['location', 'feedback_type']).size().unstack(fill_value=0).reset_index()
            st.dataframe(feedback_summary, use_container_width=True, hide_index=True)
        else:
            st.info("No answered calls logged on this date.")
    else:
        st.info("No call logs found for the selected date.")

# TAB 3: AUDIT
with tab3:
    st.header(f"📜 Call & Feedback Audit Log for {target_call_date.strftime('%d %b %Y')}")
    if not filtered_calls_df.empty:
        audit_df = filtered_calls_df[['display_time', 'mobile_number', 'location', 'status', 'feedback_type', 'comments']].sort_values(by="display_time", ascending=False)
        audit_df.columns = ['Date & Time', 'Mobile Number', 'Store Location', 'Status', 'Feedback Category', 'Customer Remarks']
        st.dataframe(audit_df, use_container_width=True, hide_index=True)
    else:
        st.info("No call audit records found for this date.")