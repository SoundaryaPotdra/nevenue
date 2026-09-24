import os
from datetime import datetime, date, timedelta, timezone

import requests
import pandas as pd
import streamlit as st
from dotenv import load_dotenv


# ============================================================
# CONFIGURATION
# ============================================================

load_dotenv()

SHOPIFY_STORE = os.getenv("SHOPIFY_STORE")
SHOPIFY_CLIENT_ID = os.getenv("SHOPIFY_CLIENT_ID")
SHOPIFY_CLIENT_SECRET = os.getenv("SHOPIFY_CLIENT_SECRET")

SHOPIFY_API_VERSION = "2026-07"

if not SHOPIFY_STORE or not SHOPIFY_CLIENT_ID or not SHOPIFY_CLIENT_SECRET:
    st.error(
        "Shopify credentials are missing. "
        "Please add SHOPIFY_STORE, SHOPIFY_CLIENT_ID, "
        "and SHOPIFY_CLIENT_SECRET to your .env file."
    )
    st.stop()

SHOPIFY_URL = (
    f"https://{SHOPIFY_STORE}/admin/api/"
    f"{SHOPIFY_API_VERSION}/graphql.json"
)


# ============================================================
# PAGE CONFIG
# ============================================================

st.set_page_config(
    page_title="Shopify Unfulfilled Orders",
    page_icon="📦",
    layout="wide",
)


# ============================================================
# CUSTOM CSS
# ============================================================

st.markdown(
    """
    <style>

    .main-title {
        font-size: 32px;
        font-weight: 700;
        margin-bottom: 5px;
    }

    .subtitle {
        color: #777;
        font-size: 15px;
        margin-bottom: 25px;
    }

    .metric-card {
        padding: 20px;
        border-radius: 12px;
        border: 1px solid #e5e5e5;
        background: white;
        text-align: center;
    }

    .metric-title {
        font-size: 14px;
        color: #666;
    }

    .metric-number {
        font-size: 32px;
        font-weight: 700;
        margin-top: 5px;
    }

    .section-title {
        font-size: 22px;
        font-weight: 650;
        margin-top: 35px;
        margin-bottom: 5px;
    }

    .section-description {
        color: #777;
        font-size: 14px;
        margin-bottom: 15px;
    }

    </style>
    """,
    unsafe_allow_html=True,
)

def get_shopify_access_token():
    url = f"https://{SHOPIFY_STORE}/admin/oauth/access_token"

    payload = {
        "client_id": SHOPIFY_CLIENT_ID,
        "client_secret": SHOPIFY_CLIENT_SECRET,
        "grant_type": "client_credentials",
    }

    response = requests.post(url, json=payload, timeout=30)

    if response.status_code != 200:
        raise Exception(
            f"Could not get Shopify access token: "
            f"{response.status_code} - {response.text}"
        )

    data = response.json()

    return data["access_token"]

# ============================================================
# SHOPIFY GRAPHQL REQUEST
# ============================================================

def shopify_graphql(query, variables=None):
    access_token = get_shopify_access_token()

    shopify_graphql_url = (
        f"https://{SHOPIFY_STORE}/admin/api/{SHOPIFY_API_VERSION}/graphql.json"
    )

    response = requests.post(
        shopify_graphql_url,
        headers={
            "X-Shopify-Access-Token": access_token,
            "Content-Type": "application/json",
        },
        json={
            "query": query,
            "variables": variables or {},
        },
        timeout=30,
    )

    if response.status_code != 200:
        raise Exception(
            f"Shopify API HTTP error {response.status_code}: {response.text}"
        )

    result = response.json()

    # GraphQL-level errors
    if "errors" in result:
        raise Exception(f"Shopify GraphQL error: {result['errors']}")

    # Make sure Shopify returned the expected data object
    if "data" not in result:
        raise Exception(
            f"Shopify response did not contain 'data': {result}"
        )

    return result["data"]


# ============================================================
# FETCH UNFULFILLED ORDERS
# ============================================================

@st.cache_data(ttl=300)
def fetch_unfulfilled_orders():
    """
    Retrieves all currently unfulfilled orders.

    Pagination is handled automatically.
    """

    query = """
    query GetUnfulfilledOrders(
        $first: Int!
        $after: String
        $query: String!
    ) {
        orders(
            first: $first
            after: $after
            query: $query
            sortKey: CREATED_AT
            reverse: true
        ) {
            edges {
                cursor
                node {
                    id
                    name
                    createdAt

                    displayFulfillmentStatus
                    displayFinancialStatus

                    totalPriceSet {
                        shopMoney {
                            amount
                            currencyCode
                        }
                    }

                    customer {
                        firstName
                        lastName
                        email
                        phone
                    }

                    shippingAddress {
                        address1
                        address2
                        city
                        province
                        zip
                        country
                    }
                }
            }

            pageInfo {
                hasNextPage
                endCursor
            }
        }
    }
    """

    orders = []
    cursor = None

    while True:

        variables = {
            "first": 100,
            "after": cursor,
            "query": "fulfillment_status:unfulfilled",
        }

        data = shopify_graphql(
            query,
            variables
        )

        connection = data["orders"]

        for edge in connection["edges"]:

            order = edge["node"]

            customer = order.get("customer")

            if customer:
                first_name = customer.get("firstName") or ""
                last_name = customer.get("lastName") or ""

                customer_name = (
                    f"{first_name} {last_name}"
                ).strip()

                if not customer_name:
                    customer_name = "Guest"
            else:
                customer_name = "Guest"

            total_price = order["totalPriceSet"]["shopMoney"]

            shipping = order.get("shippingAddress")

            if shipping:
                address_parts = [
                    shipping.get("address1"),
                    shipping.get("address2"),
                    shipping.get("city"),
                    shipping.get("province"),
                    shipping.get("zip"),
                    shipping.get("country"),
                ]

                address = ", ".join(
                    part for part in address_parts if part
                )
            else:
                address = ""

            created_at = datetime.fromisoformat(
                order["createdAt"].replace("Z", "+00:00")
            )

            orders.append(
                {
                    "order_id": order["id"],
                    "order_number": order["name"],
                    "created_at": created_at,
                    "customer_name": customer_name,
                    "email": (
                        customer.get("email")
                        if customer
                        else ""
                    ),
                    "phone": (
                        customer.get("phone")
                        if customer
                        else ""
                    ),
                    "amount": float(
                        total_price["amount"]
                    ),
                    "currency": total_price["currencyCode"],
                    "fulfillment_status": (
                        order["displayFulfillmentStatus"]
                    ),
                    "financial_status": (
                        order["displayFinancialStatus"]
                    ),
                    "address": address,
                }
            )

        if not connection["pageInfo"]["hasNextPage"]:
            break

        cursor = connection["pageInfo"]["endCursor"]

    return orders


# ============================================================
# CONVERT ORDERS TO DATAFRAME
# ============================================================

def prepare_dataframe(orders):

    if not orders:
        return pd.DataFrame(
            columns=[
                "order_number",
                "customer_name",
                "email",
                "phone",
                "created_at",
                "days_pending",
                "amount",
                "currency",
                "fulfillment_status",
                "financial_status",
                "address",
            ]
        )

    df = pd.DataFrame(orders)

    now = datetime.now(timezone.utc)

    df["days_pending"] = (
        now - df["created_at"]
    ).dt.total_seconds() / 86400

    df["days_pending"] = (
        df["days_pending"]
        .clip(lower=0)
        .astype(int)
    )

    df["order_date"] = (
        df["created_at"]
        .dt.strftime("%d %b %Y")
    )

    df["amount_display"] = df.apply(
        lambda row:
        f"{row['currency']} {row['amount']:,.2f}",
        axis=1
    )

    df = df.sort_values(
        by="days_pending",
        ascending=False
    )

    return df


# ============================================================
# DISPLAY ORDER TABLE
# ============================================================

def display_orders(df):

    if df.empty:
        st.info("No unfulfilled orders found in this period.")
        return

    display_df = df[
        [
            "order_number",
            "customer_name",
            "email",
            "phone",
            "order_date",
            "days_pending",
            "amount_display",
            "fulfillment_status",
        ]
    ].copy()

    display_df.columns = [
        "Order",
        "Customer",
        "Email",
        "Phone",
        "Order Date",
        "Days Pending",
        "Amount",
        "Status",
    ]

    st.dataframe(
        display_df,
        use_container_width=True,
        hide_index=True,
        column_config={
            "Order": st.column_config.TextColumn(
                "Order",
                width="small",
            ),

            "Customer": st.column_config.TextColumn(
                "Customer",
                width="medium",
            ),

            "Email": st.column_config.TextColumn(
                "Email",
                width="medium",
            ),

            "Phone": st.column_config.TextColumn(
                "Phone",
                width="medium",
            ),

            "Order Date": st.column_config.TextColumn(
                "Order Date",
                width="small",
            ),

            "Days Pending": st.column_config.NumberColumn(
                "Days Pending",
                width="small",
            ),

            "Amount": st.column_config.TextColumn(
                "Amount",
                width="small",
            ),

            "Status": st.column_config.TextColumn(
                "Status",
                width="small",
            ),
        },
    )


# ============================================================
# HEADER
# ============================================================

st.markdown(
    '<div class="main-title">'
    '📦 Unfulfilled Orders Dashboard'
    '</div>',
    unsafe_allow_html=True,
)

st.markdown(
    '<div class="subtitle">'
    'Monitor orders that are still waiting for fulfillment.'
    '</div>',
    unsafe_allow_html=True,
)


# ============================================================
# SIDEBAR / DATE FILTER
# ============================================================

st.sidebar.header("Date Filter")

filter_type = st.sidebar.radio(
    "Select period",
    [
        "All Unfulfilled",
        "Last 3 Days",
        "Last 5 Days",
        "Last 7 Days",
        "Custom Range",
    ],
)

today = date.today()

if filter_type == "Custom Range":

    custom_start = st.sidebar.date_input(
        "From",
        value=today - timedelta(days=7),
    )

    custom_end = st.sidebar.date_input(
        "To",
        value=today,
    )

    if custom_start > custom_end:
        st.sidebar.error(
            "Start date cannot be after end date."
        )
        st.stop()

else:
    custom_start = None
    custom_end = None


# ============================================================
# REFRESH BUTTON
# ============================================================

if st.sidebar.button(
    "🔄 Refresh Shopify Data",
    use_container_width=True,
):
    st.cache_data.clear()
    st.rerun()


# ============================================================
# FETCH DATA
# ============================================================

try:

    with st.spinner("Fetching orders from Shopify..."):

        orders = fetch_unfulfilled_orders()

        df = prepare_dataframe(orders)

except Exception as e:

    st.error(
        "Unable to retrieve data from Shopify."
    )

    st.exception(e)

    st.stop()


# ============================================================
# TOTAL UNFULFILLED
# ============================================================

total_unfulfilled = len(df)


# ============================================================
# TOP METRIC
# ============================================================

st.markdown(
    """
    <div class="metric-card">
        <div class="metric-title">
            TOTAL CURRENTLY UNFULFILLED
        </div>
        <div class="metric-number">
            """
    + f"{total_unfulfilled:,}"
    + """
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)


# ============================================================
# CREATE AGE GROUPS
# ============================================================

last_3_days = df[
    df["days_pending"] >= 3
].copy()

last_5_days = df[
    df["days_pending"] >= 5
].copy()

last_7_days = df[
    df["days_pending"] >= 7
].copy()


# ============================================================
# SUMMARY CARDS
# ============================================================

st.markdown("### Order Aging")

col1, col2, col3 = st.columns(3)

with col1:

    st.metric(
        "Unfulfilled 3+ Days",
        f"{len(last_3_days):,}",
    )

with col2:

    st.metric(
        "Unfulfilled 5+ Days",
        f"{len(last_5_days):,}",
    )

with col3:

    st.metric(
        "Unfulfilled 7+ Days",
        f"{len(last_7_days):,}",
    )


# ============================================================
# CUSTOM DATE FILTER
# ============================================================

if filter_type == "Custom Range":

    start_datetime = datetime.combine(
        custom_start,
        datetime.min.time(),
    ).replace(tzinfo=timezone.utc)

    end_datetime = datetime.combine(
        custom_end,
        datetime.max.time(),
    ).replace(tzinfo=timezone.utc)

    custom_df = df[
        (df["created_at"] >= start_datetime)
        & (df["created_at"] <= end_datetime)
    ].copy()

    st.markdown(
        f"""
        <div class="section-title">
            Custom Date Range
        </div>

        <div class="section-description">
            {custom_start.strftime('%d %b %Y')}
            →
            {custom_end.strftime('%d %b %Y')}
            ·
            {len(custom_df):,} orders
        </div>
        """,
        unsafe_allow_html=True,
    )

    display_orders(custom_df)


# ============================================================
# 7+ DAYS
# ============================================================

st.markdown(
    f"""
    <div class="section-title">
        🔴 Unfulfilled for 7+ Days
    </div>

    <div class="section-description">
        {len(last_7_days):,} orders have remained unfulfilled
        for at least 7 days.
    </div>
    """,
    unsafe_allow_html=True,
)

display_orders(last_7_days)


# ============================================================
# 5+ DAYS
# ============================================================

st.markdown(
    f"""
    <div class="section-title">
        🟠 Unfulfilled for 5+ Days
    </div>

    <div class="section-description">
        {len(last_5_days):,} orders have remained unfulfilled
        for at least 5 days.
    </div>
    """,
    unsafe_allow_html=True,
)

display_orders(last_5_days)


# ============================================================
# 3+ DAYS
# ============================================================

st.markdown(
    f"""
    <div class="section-title">
        🟡 Unfulfilled for 3+ Days
    </div>

    <div class="section-description">
        {len(last_3_days):,} orders have remained unfulfilled
        for at least 3 days.
    </div>
    """,
    unsafe_allow_html=True,
)

display_orders(last_3_days)


# ============================================================
# FOOTER
# ============================================================

st.markdown("---")

st.caption(
    "Data retrieved from Shopify Admin API."
)