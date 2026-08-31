import streamlit as st
import pandas as pd
from supabase import create_client
from datetime import datetime, timedelta

# --- PAGE SETUP ---
st.set_page_config(page_title="MahaMart CRM", layout="wide")
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
    url = st.secrets["SUPABASE_URL"]
    key = st.secrets["SUPABASE_KEY"]
    return create_client(url, key)

supabase = init_connection()

# --- FETCH DATA (WITH PAGINATION & CACHING) ---
@st.cache_data(ttl=600, show_spinner="Downloading records from Supabase... (Takes a few seconds)")
def load_data():
    all_bills = []
    start = 0
    step = 1000
    
    while True:
        response = supabase.table("bills").select("*").range(start, start + step - 1).execute()
        data = response.data
        if not data:
            break
        all_bills.extend(data)
        if len(data) < step:
            break
        start += step
        
    bills_df = pd.DataFrame(all_bills)
    
    if not bills_df.empty:
        bills_df['bill_date'] = pd.to_datetime(bills_df['bill_date']).dt.date
        bills_df = bills_df.dropna(subset=['bill_date'])
        
        bills_df['mobile_number'] = bills_df['mobile_number'].fillna("No Mobile").astype(str).str.strip()
        bills_df.loc[bills_df['mobile_number'] == "", 'mobile_number'] = "No Mobile"
        
        bills_df['customer_name'] = bills_df['customer_name'].fillna("Guest").astype(str).str.strip()
        bills_df.loc[bills_df['customer_name'] == "", 'customer_name'] = "Guest"
        
        bills_df['total_bill_value'] = pd.to_numeric(bills_df['total_bill_value'], errors='coerce').fillna(0)
        bills_df['qty'] = pd.to_numeric(bills_df['qty'], errors='coerce').fillna(0)
        bills_df['accumulated_points'] = pd.to_numeric(bills_df['accumulated_points'], errors='coerce').fillna(0)
        bills_df['redeem_points'] = pd.to_numeric(bills_df['redeem_points'], errors='coerce').fillna(0)
    
    calls_response = supabase.table("call_logs").select("*").execute()
    calls_df = pd.DataFrame(calls_response.data)
    
    if not calls_df.empty:
        if 'call_time' in calls_df.columns:
            calls_df['display_time'] = calls_df['call_time'].fillna(calls_df['call_date'])
        else:
            calls_df['display_time'] = calls_df['call_date']
            
        calls_df['parsed_date'] = pd.to_datetime(calls_df['call_date'], errors='coerce').dt.date
    else:
        calls_df = pd.DataFrame(columns=['mobile_number', 'call_date', 'call_time', 'display_time', 'parsed_date', 'status', 'comments'])
        
    return bills_df, calls_df

bills_df, calls_df = load_data()

if bills_df.empty:
    st.warning("No data found in the database. Please check your Supabase table.")
    st.stop()

# --- GLOBAL VARIABLES ---
today_date = datetime.today().date()
current_date_str = today_date.strftime('%Y-%m-%d')
current_time_str = datetime.now().strftime('%Y-%m-%d %H:%M:%S')

global_min_date = bills_df['bill_date'].min()
global_max_date = bills_df['bill_date'].max()

if pd.isnull(global_min_date) or pd.isnull(global_max_date):
    default_dates = (today_date,)
elif global_min_date == global_max_date:
    default_dates = (global_min_date,)
else:
    default_dates = (global_min_date, global_max_date)

# --- SIDEBAR FILTERS ---
st.sidebar.header("Global Filters")
stores = ["All Stores"] + list(bills_df['store'].dropna().unique())
selected_store = st.sidebar.selectbox("Select Store", stores)

if selected_store != "All Stores":
    store_df = bills_df[bills_df['store'] == selected_store]
else:
    store_df = bills_df

# ==========================================
# TABS SETUP
# ==========================================
tab1, tab2 = st.tabs(["📞 Telecalling", "🔍 Customer Detail"])

# ==========================================
# TAB 1: TELECALLING
# ==========================================
with tab1:
    st.header("Telecalling Lists")
    
    call_base_df = store_df[(store_df['mobile_number'] != "No Mobile") & (store_df['mobile_number'] != "nan")]
    
    call_mode = st.radio("Select Calling Module:", ["🏆 Top 40 Customers", "⚠️ Retention Calling"], horizontal=True, key="t1_mode")
    display_df = pd.DataFrame()
    
    if call_mode == "🏆 Top 40 Customers":
        st.subheader("Highest Value Customers")
        
        top40_dates = st.date_input("Select Date Range (Top 40):", value=default_dates, key="top40_dates")
        
        if len(top40_dates) == 2:
            start_d, end_d = top40_dates
        elif len(top40_dates) == 1:
            start_d = end_d = top40_dates[0]
        else:
            start_d = end_d = today_date
            
        filtered_call_df = call_base_df[(call_base_df['bill_date'] >= start_d) & (call_base_df['bill_date'] <= end_d)]
        
        top40_summary = filtered_call_df.groupby(['mobile_number', 'customer_name']).agg(
            total_spent=('total_bill_value', 'sum'),
            last_visit=('bill_date', 'max')
        ).reset_index()
        
        display_df = top40_summary.sort_values(by="total_spent", ascending=False).head(40)
            
    else:
        st.subheader("Customers at Risk of Churn (Calculated from Today)")
        
        retention_summary = call_base_df.groupby(['mobile_number', 'customer_name']).agg(
            total_spent=('total_bill_value', 'sum'),
            last_visit=('bill_date', 'max')
        ).reset_index()
        
        retention_summary['days_since_visit'] = (today_date - retention_summary['last_visit']).apply(lambda x: x.days)
        
        retention_filter = st.selectbox("Days Since Last Visit:", ["45-60 Days", "60-90 Days", "90+ Days"], key="t1_ret_filter")
        if retention_filter == "45-60 Days":
            display_df = retention_summary[(retention_summary['days_since_visit'] >= 45) & (retention_summary['days_since_visit'] <= 60)]
        elif retention_filter == "60-90 Days":
            display_df = retention_summary[(retention_summary['days_since_visit'] > 60) & (retention_summary['days_since_visit'] <= 90)]
        else:
            display_df = retention_summary[retention_summary['days_since_visit'] > 90]

    st.markdown("### 👇 Click on a customer to expand details")
    if not display_df.empty:
        for index, row in display_df.iterrows():
            mob = str(row['mobile_number'])
            
            cust_calls = calls_df[calls_df['mobile_number'].astype(str) == mob]
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
                    st.warning("🚫 **Calling Locked:** This customer was successfully answered within the last 30 days (prior to today). New call logging is blocked to prevent spamming.")
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
    
    t2_dates = st.date_input("Select Date Range (Lookup Data):", value=default_dates, key="t2_dates")
    
    if len(t2_dates) == 2:
        start_d2, end_d2 = t2_dates
    elif len(t2_dates) == 1:
        start_d2 = end_d2 = t2_dates[0]
    else:
        start_d2 = end_d2 = today_date
        
    t2_df = store_df[(store_df['bill_date'] >= start_d2) & (store_df['bill_date'] <= end_d2)]
    
    search_query = st.text_input("🔍 Search by Name (e.g. Guest) or Mobile Number:", key="t2_search")
    
    if search_query:
        mask = t2_df['mobile_number'].astype(str).str.contains(search_query, na=False, case=False) | \
               t2_df['customer_name'].astype(str).str.contains(search_query, na=False, case=False)
        result_df = t2_df[mask]
        limit_msg = ""
    else:
        result_df = t2_df
        limit_msg = " (Showing Top 100 by Spend. Use search bar to find guests or others!)"
        
    if not result_df.empty:
        st.markdown(f"### 👇 Click on a customer below to view full history{limit_msg}")
        
        search_summary = result_df.groupby(['mobile_number', 'customer_name']).agg(
            total_spent=('total_bill_value', 'sum'),
            visits=('bill_no', 'nunique'),
            acc_points=('accumulated_points', 'sum'),
            red_points=('redeem_points', 'sum')
        ).reset_index().sort_values(by="total_spent", ascending=False)
        
        if not search_query:
            search_summary = search_summary.head(100)
            
        for index, row in search_summary.iterrows():
            mob = str(row['mobile_number'])
            c_name = str(row['customer_name'])
            
            display_mob = mob if mob != "No Mobile" else "No Phone Number"
            
            cust_calls = calls_df[calls_df['mobile_number'].astype(str) == mob]
            call_status_label = "Never Called"
            if not cust_calls.empty:
                latest_call = cust_calls.iloc[-1]
                display_time_str = str(latest_call.get('display_time', ''))
                call_status_label = f"Last Called: {display_time_str} ({latest_call['status']})"
                
            spent_inr = format_inr(row['total_spent'])
            header_title = f"{c_name} | 📱 {display_mob} | Spent: {spent_inr} | [{call_status_label}]"
            
            with st.expander(header_title):
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Spent (in date range)", format_inr(row['total_spent']))
                c2.metric("Store Visits", row['visits'])
                c3.metric("Earned Points", int(row['acc_points']))
                c4.metric("Redeemed Points", int(row['red_points']))
                
                st.markdown("**🛒 Bill History**")
                cust_bills = result_df[(result_df['mobile_number'].astype(str) == mob) & (result_df['customer_name'].astype(str) == c_name)]
                
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