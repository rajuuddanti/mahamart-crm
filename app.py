import os
import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

# --- PAGE SETUP ---
st.set_page_config(page_title="MahaMart CRM", layout="wide")

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

st.title("📊 MahaMart CRM & Performance Dashboard")

# --- INDIAN CURRENCY FORMATTER FUNCTION ---
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

@st.cache_data(ttl=86400, show_spinner=False)
def get_active_stores():
    """Grabs recent records to dynamically find active store names."""
    response = supabase.table("bills").select("store").order("bill_date", desc=True).limit(5000).execute()
    if response.data:
        stores = pd.DataFrame(response.data)['store'].dropna().unique().tolist()
        return ["All Stores"] + sorted(stores)
    return ["All Stores"]

@st.cache_data(ttl=300, show_spinner=False)
def get_bills_by_date(start_d, end_d, store_filter="All Stores"):
    """Fetches bills ONLY for the selected date range & store."""
    all_bills = []
    start = 0
    step = 1000
    while True:
        query = supabase.table("bills").select("customer_name, mobile_number, total_bill_value, bill_date, bill_no, qty, accumulated_points, redeem_points, store") \
            .gte("bill_date", start_d.strftime("%Y-%m-%d")) \
            .lte("bill_date", end_d.strftime("%Y-%m-%d"))
            
        if store_filter != "All Stores":
            query = query.eq("store", store_filter)
            
        response = query.range(start, start + step - 1).execute()
        
        data = response.data
        if not data: break
        all_bills.extend(data)
        if len(data) < step: break
        start += step
        
    df = pd.DataFrame(all_bills)
    if not df.empty:
        df['bill_date'] = pd.to_datetime(df['bill_date']).dt.date
        df['mobile_number'] = df['mobile_number'].fillna("No Mobile").astype(str).str.strip()
        df.loc[df['mobile_number'] == "", 'mobile_number'] = "No Mobile"
        df['customer_name'] = df['customer_name'].fillna("Guest").astype(str).str.strip()
        df['total_bill_value'] = pd.to_numeric(df['total_bill_value'], errors='coerce').fillna(0)
        df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
        df['accumulated_points'] = pd.to_numeric(df['accumulated_points'], errors='coerce').fillna(0)
        df['redeem_points'] = pd.to_numeric(df['redeem_points'], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=60, show_spinner=False)
def search_customer_db(query, store_filter="All Stores"):
    """Searches directly in Supabase."""
    db_query = supabase.table("bills").select("customer_name, mobile_number, total_bill_value, bill_date, bill_no, qty, accumulated_points, redeem_points, store") \
        .or_(f"mobile_number.ilike.%{query}%,customer_name.ilike.%{query}%")
        
    if store_filter != "All Stores":
        db_query = db_query.eq("store", store_filter)
        
    response = db_query.limit(1000).execute()
        
    df = pd.DataFrame(response.data)
    if not df.empty:
        df['bill_date'] = pd.to_datetime(df['bill_date']).dt.date
        df['mobile_number'] = df['mobile_number'].fillna("No Mobile").astype(str).str.strip()
        df['customer_name'] = df['customer_name'].fillna("Guest").astype(str).str.strip()
        df['total_bill_value'] = pd.to_numeric(df['total_bill_value'], errors='coerce').fillna(0)
        df['qty'] = pd.to_numeric(df['qty'], errors='coerce').fillna(0)
    return df

@st.cache_data(ttl=60, show_spinner=False)
def get_calls_for_mobiles(mobile_list):
    """Fetches call logs ONLY for the specific customers currently on screen."""
    if not mobile_list: return pd.DataFrame()
    
    all_calls = []
    for i in range(0, len(mobile_list), 100):
        chunk = mobile_list[i:i+100]
        resp = supabase.table("call_logs").select("*").in_("mobile_number", chunk).execute()
        if resp.data:
            all_calls.extend(resp.data)
            
    cdf = pd.DataFrame(all_calls)
    if not cdf.empty:
        if 'call_time' in cdf.columns:
            cdf['display_time'] = cdf['call_time'].fillna(cdf['call_date'])
        else:
            cdf['display_time'] = cdf['call_date']
        cdf['parsed_date'] = pd.to_datetime(cdf['call_date'], errors='coerce').dt.date
    else:
        cdf = pd.DataFrame(columns=['mobile_number', 'call_date', 'call_time', 'display_time', 'parsed_date', 'status', 'comments'])
    return cdf

# --- SIDEBAR FILTERS ---
st.sidebar.header("Global Filters")
stores_list = get_active_stores()
selected_store = st.sidebar.selectbox("Select Store", stores_list)

# ==========================================
# TABS SETUP
# ==========================================
tab1, tab2 = st.tabs(["📞 Telecalling", "🔍 Customer Detail"])

# ==========================================
# TAB 1: TELECALLING
# ==========================================
with tab1:
    st.header("Telecalling Lists")
    
    call_mode = st.radio("Select Calling Module:", ["🏆 Top 40 Customers", "⚠️ Retention Calling"], horizontal=True, key="t1_mode")
    display_df = pd.DataFrame()
    calls_df = pd.DataFrame()
    
    if call_mode == "🏆 Top 40 Customers":
        st.subheader("Highest Value Customers")
        top40_dates = st.date_input("Select Date Range (Defaults to Today):", value=(today_date,), key="top40_dates")
        
        if len(top40_dates) == 2:
            start_d, end_d = top40_dates
        else:
            start_d = end_d = top40_dates[0]
            
        with st.spinner(f"Fetching bills for {selected_store}..."):
            base_df = get_bills_by_date(start_d, end_d, selected_store)
            
        if not base_df.empty:
            base_df = base_df[(base_df['mobile_number'] != "No Mobile") & (base_df['mobile_number'] != "nan")]
            top40_summary = base_df.groupby(['mobile_number', 'customer_name']).agg(
                total_spent=('total_bill_value', 'sum'),
                last_visit=('bill_date', 'max')
            ).reset_index()
            
            display_df = top40_summary.sort_values(by="total_spent", ascending=False).head(40)
            
    else:
        st.subheader("Customers at Risk of Churn")
        retention_filter = st.selectbox("Days Since Last Visit:", ["45-60 Days", "60-90 Days", "90+ Days"], key="t1_ret_filter")
        
        if retention_filter == "45-60 Days":
            start_d = today_date - timedelta(days=60)
            end_d = today_date - timedelta(days=45)
        elif retention_filter == "60-90 Days":
            start_d = today_date - timedelta(days=90)
            end_d = today_date - timedelta(days=61)
        else:
            start_d = today_date - timedelta(days=365)
            end_d = today_date - timedelta(days=91)

        with st.spinner(f"Finding churn customers for {selected_store}..."):
            base_df = get_bills_by_date(start_d, end_d, selected_store)
            
        if not base_df.empty:
            base_df = base_df[(base_df['mobile_number'] != "No Mobile") & (base_df['mobile_number'] != "nan")]
            retention_summary = base_df.groupby(['mobile_number', 'customer_name']).agg(
                total_spent=('total_bill_value', 'sum'),
                last_visit=('bill_date', 'max')
            ).reset_index()
            
            potential_churn_mobs = retention_summary['mobile_number'].tolist()
            calls_for_churn = get_calls_for_mobiles(potential_churn_mobs)
            if not calls_for_churn.empty:
                called_numbers = calls_for_churn['mobile_number'].unique()
                retention_summary = retention_summary[~retention_summary['mobile_number'].isin(called_numbers)]
            
            display_df = retention_summary.sort_values(by="total_spent", ascending=False).head(100)

    st.markdown("### 👇 Click on a customer to expand details")
    
    if not display_df.empty:
        mobs_to_render = display_df['mobile_number'].tolist()
        calls_df = get_calls_for_mobiles(mobs_to_render)
        
        for index, row in display_df.iterrows():
            mob = str(row['mobile_number'])
            
            cust_calls = pd.DataFrame() if calls_df.empty else calls_df[calls_df['mobile_number'].astype(str) == mob]
            call_status_label = "Never Called"
            is_recently_answered = False
            
            if not cust_calls.empty:
                latest_call = cust_calls.iloc[-1]
                display_time_str = str(latest_call.get('display_time', ''))
                call_status_label = f"Last Called: {display_time_str} ({latest_call['status']})"
                
                call_d = latest_call.get('parsed_date')
                if latest_call['status'] == 'Answered' and call_d and call_d < today_date and call_d >= (today_date - timedelta(days=30)):
                    is_recently_answered = True
            
            spent_inr = format_inr(row['total_spent'])
            header_title = f"{row['customer_name']} | 📱 {mob} | Spent: {spent_inr} | Last Visit: {row['last_visit']} | [{call_status_label}]"
            
            with st.expander(header_title):
                if not cust_calls.empty:
                    last_call_time = str(latest_call.get('display_time', ''))
                    call_d = latest_call.get('parsed_date', today_date)
                    days_since_call = (today_date - call_d).days if call_d else 0
                    st.info(f"📞 **Call History Summary:** Last called **{days_since_call} days ago** on **{last_call_time}** | Status: **{latest_call['status']}**")
                    if latest_call['comments']:
                        st.write(f"💬 *Last Comments:* {latest_call['comments']}")
                    
                    st.markdown("**Complete Call History Log (All Past Entries):**")
                    log_view = cust_calls[['display_time', 'status', 'comments']].rename(columns={'display_time': 'call_date_time'})
                    st.dataframe(log_view.iloc[::-1], use_container_width=True, hide_index=True)
                else:
                    st.info("ℹ️ No previous calls logged for this customer yet.")
                
                if is_recently_answered:
                    st.warning("🚫 **Calling Locked:** This customer was successfully answered within the last 30 days. New logging blocked.")
                else:
                    st.markdown("**📝 Log a New Call**")
                    c_status = st.selectbox("Call Status", ["Answered", "Not Answered", "Switched Off", "Not Reachable"], key=f"status_{mob}_{index}")
                    c_comments = st.text_area("Customer Comments", key=f"comm_{mob}_{index}")
                    
                    if st.button("Save Call Log", key=f"btn_{mob}_{index}"):
                        supabase.table("call_logs").insert({
                            "mobile_number": mob,
                            "status": c_status,
                            "comments": c_comments,
                            "call_date": current_date_str,
                            "call_time": current_time_str
                        }).execute()
                        st.success("Call saved successfully with exact time!")
                        st.cache_data.clear() 
                        st.rerun()
    else:
        st.write("No customers found for this criteria.")

# ==========================================
# TAB 2: CUSTOMER DETAIL
# ==========================================
with tab2:
    st.header("🔍 Customer Lookup & Master History")
    
    search_query = st.text_input("🔍 Search by Name (e.g. Guest) or Mobile Number:", key="t2_search")
    
    if not search_query:
        t2_dates = st.date_input("Select Date Range (Defaults to Today. Limits to Top 100):", value=(today_date,), key="t2_dates")
        if len(t2_dates) == 2:
            start_d2, end_d2 = t2_dates
        else:
            start_d2 = end_d2 = t2_dates[0]
            
        with st.spinner(f"Fetching top bills for {selected_store}..."):
            result_df = get_bills_by_date(start_d2, end_d2, selected_store)
        limit_msg = " (Showing Top 100 by Spend for selected date. Use search bar to find specific people!)"
    else:
        with st.spinner(f"Searching database in {selected_store}..."):
            result_df = search_customer_db(search_query, selected_store)
        limit_msg = ""
        
    if not result_df.empty:
        st.markdown(f"### 👇 Click on a customer below to view full history{limit_msg}")
        
        search_summary = result_df.groupby(['mobile_number', 'customer_name']).agg(
            total_spent=('total_bill_value', 'sum'),
            visits=('bill_no', 'nunique'),
            acc_points=('accumulated_points', 'sum'),
            red_points=('redeem_points', 'sum')
        ).reset_index().sort_values(by="total_spent", ascending=False).head(100)
        
        mobs_to_lookup = search_summary['mobile_number'].tolist()
        calls_df_lookup = get_calls_for_mobiles(mobs_to_lookup)
            
        for index, row in search_summary.iterrows():
            mob = str(row['mobile_number'])
            c_name = str(row['customer_name'])
            display_mob = mob if mob != "No Mobile" else "No Phone Number"
            
            cust_calls = pd.DataFrame() if calls_df_lookup.empty else calls_df_lookup[calls_df_lookup['mobile_number'].astype(str) == mob]
            call_status_label = "Never Called"
            if not cust_calls.empty:
                latest_call = cust_calls.iloc[-1]
                display_time_str = str(latest_call.get('display_time', ''))
                call_status_label = f"Last Called: {display_time_str} ({latest_call['status']})"
                
            spent_inr = format_inr(row['total_spent'])
            header_title = f"{c_name} | 📱 {display_mob} | Spent: {spent_inr} | [{call_status_label}]"
            
            with st.expander(header_title):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Spent", format_inr(row['total_spent']))
                c2.metric("Store Visits", row['visits'])
                c3.metric("Earned Points", int(row['acc_points']))
                c4.metric("Redeemed Points", int(row['red_points']))
                
                st.markdown("**🛒 Bill History**")
                cust_bills = result_df[(result_df['mobile_number'].astype(str) == mob) & (result_df['customer_name'].astype(str) == c_name)]
                
                # RESTORED QTY COLUMN HERE
                table_bills = cust_bills[['bill_date', 'store', 'bill_no', 'qty', 'total_bill_value', 'accumulated_points', 'redeem_points']].copy()
                table_bills['total_bill_value'] = table_bills['total_bill_value'].apply(lambda x: format_inr(x))
                st.dataframe(table_bills.sort_values(by="bill_date", ascending=False), use_container_width=True, hide_index=True)
                
                st.markdown("**📞 Call History (All Past Entries)**")
                if not cust_calls.empty:
                    log_view = cust_calls[['display_time', 'status', 'comments']].rename(columns={'display_time': 'call_date_time'})
                    st.dataframe(log_view.iloc[::-1], use_container_width=True, hide_index=True)
                else:
                    st.info("No calls logged for this customer yet.")
    else:
        st.warning("No records found.")