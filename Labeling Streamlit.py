import streamlit as st
import pandas as pd
from io import BytesIO
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from streamlit_oauth import OAuth2Component
import threading
import streamlit.components.v1 as components

# ==== CONFIG ====
AUTHORIZE_URL = st.secrets["google"]["authorize_url"]
TOKEN_URL = st.secrets["google"]["token_url"]
REFRESH_TOKEN_URL = st.secrets["google"]["refresh_token_url"]
REVOKE_TOKEN_URL = st.secrets["google"]["revoke_token_url"]
CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]
GA4_MEASUREMENT_ID = st.secrets["ga4"]["measurement_id"]
SCOPE = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email openid"

# ==== GOOGLE ANALYTICS SNIPPET ====
GA4_SNIPPET = f"""
<script async src="https://www.googletagmanager.com/gtag/js?id={GA4_MEASUREMENT_ID}"></script>
<script>
  window.dataLayer = window.dataLayer || [];
  function gtag(){{dataLayer.push(arguments);}}
  gtag('js', new Date());
  gtag('config', '{GA4_MEASUREMENT_ID}');
</script>
"""
st.markdown(f"<script>{GA4_SNIPPET}</script>", unsafe_allow_html=True)

# ==== OAUTH SETUP ====
oauth2 = OAuth2Component(CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, REFRESH_TOKEN_URL, REVOKE_TOKEN_URL)

if 'credentials' not in st.session_state:
    result = oauth2.authorize_button("Log in with Google", REDIRECT_URI, SCOPE)

    if result:
        token_data = result.get("token", {})
        access_token = token_data.get("access_token")

        if access_token:
            creds = Credentials(token=access_token)
            st.session_state["credentials"] = creds
            st.rerun()
        else:
            st.error("OAuth response missing 'access_token'. Full response:")
            st.json(result)

if 'credentials' in st.session_state:
    creds = st.session_state['credentials']
    drive_service = build('drive', 'v3', credentials=creds)
    user_info_service = build('oauth2', 'v2', credentials=creds)
    user_info = user_info_service.userinfo().get().execute()
    user_email = user_info['email']

    st.title(f"Dataset Labeling for {user_email}")

    st.markdown("""
    ### 📌 Instructions:
    - **Sign in with your UMD ID** to access the labeling tool.
    - **From the dropdown**, carefully select the correct file for your assigned task.
    - Each time you log in, the app will **automatically resume from the last company** where you left off.
    - **To label data**, click one of the buttons: **0 (Reject), 1 (Accept), or 9 (Unsure).**
    - **You can only do up to 20 'Unsure' (9) labels.**
    - **After that, you will only be able to label as 'Reject' (0) or 'Accept' (1).**
    - **For any queries about this web app, contact:**  
      - 📧 **Sai Shashank** (skudkuli@umd.edu)  
      - 📧 **Sarvagya Singh** (singh007@umd.edu)
    """)

    def fetch_drive_files(user_email):
        """List only user-specific CSV files"""
        files = drive_service.files().list(
            q="mimeType='text/csv' and trashed=false",
            fields='files(id, name)'
        ).execute()
        return {file['name']: file['id'] for file in files.get('files', [])}

    @st.cache_data(show_spinner=False)
    def load_csv_cached(file_id, user_email):
        metadata = drive_service.files().get(fileId=file_id, fields="owners").execute()
        owners = [o['emailAddress'] for o in metadata['owners']]
        if user_email not in owners:
            st.error("⛔ You do not own this file.")
            st.stop()
        file_content = drive_service.files().get_media(fileId=file_id).execute()
        return pd.read_csv(BytesIO(file_content))

    def save_to_drive(file_id, data):
        """Upload CSV back to Google Drive"""
        updated_csv = BytesIO()
        data.to_csv(updated_csv, index=False)
        updated_csv.seek(0)
        drive_service.files().update(
            fileId=file_id,
            media_body=MediaIoBaseUpload(updated_csv, mimetype='text/csv')
        ).execute()

    files = fetch_drive_files(user_email)
    selected_file_name = st.selectbox("Select your CSV file:", options=files.keys())

    if selected_file_name:
        file_id = files[selected_file_name]
        data = load_csv_cached(file_id, user_email)

        label_col = "RA_AI_Labels"
        if label_col not in data.columns:
            data[label_col] = None

        last_filled_index = data[label_col].last_valid_index()
        if "current_index" not in st.session_state:
            st.session_state["current_index"] = 0 if last_filled_index is None else last_filled_index + 1

        current_index = st.session_state["current_index"]
        unsure_count = (data[label_col] == 9).sum()

        if current_index < len(data):
            row = data.iloc[current_index]
            st.subheader(f"{row['TITLE']}")
            st.write(f"**Company:** {row['COMPANY_NAME']}")
            st.write("**Job Description:**")
            st.write(row["cleaned_jd"])
            st.write("---")

            radio_options = [0, 1] + ([9] if unsure_count < 20 else [])
            selected_label = st.radio(
                "Label this job:",
                options=radio_options,
                horizontal=True,
                key=f"radio_{current_index}"
            )

            if st.button("Submit Label"):
                data.at[current_index, label_col] = selected_label
                st.session_state["current_index"] += 1
                threading.Thread(target=save_to_drive, args=(file_id, data), daemon=True).start()
                st.success(f"Row {current_index} labeled successfully.")
                st.rerun()

        st.progress(current_index / len(data))
        st.write(f"✅ Labeled: {current_index} / {len(data)}")
        st.write(f"⚠️ Unsure Labels Used: {unsure_count}/20")

    else:
        st.info("Please select a file to begin labeling.")