import streamlit as st
import pandas as pd
from io import BytesIO
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from streamlit_oauth import OAuth2Component
import threading
import time

AUTHORIZE_URL = st.secrets["google"]["authorize_url"]
TOKEN_URL = st.secrets["google"]["token_url"]
REFRESH_TOKEN_URL = st.secrets["google"]["refresh_token_url"]
REVOKE_TOKEN_URL = st.secrets["google"]["revoke_token_url"]
CLIENT_ID = st.secrets["google"]["client_id"]
CLIENT_SECRET = st.secrets["google"]["client_secret"]
REDIRECT_URI = st.secrets["google"]["redirect_uri"]
SCOPE = "https://www.googleapis.com/auth/drive https://www.googleapis.com/auth/userinfo.email openid"

oauth2 = OAuth2Component(
    CLIENT_ID, CLIENT_SECRET, AUTHORIZE_URL, TOKEN_URL, REFRESH_TOKEN_URL, REVOKE_TOKEN_URL
)

def fetch_drive_files():
    files = drive_service.files().list(q="mimeType='text/csv' and trashed=false", fields='files(id, name)').execute()
    return {file['name']: file['id'] for file in files.get('files', [])}


def save_to_drive(file_id, data):
    updated_csv = BytesIO()
    data.to_csv(updated_csv, index=False)
    updated_csv.seek(0)
    drive_service.files().update(
        fileId=file_id,
        media_body=MediaIoBaseUpload(updated_csv, mimetype='text/csv')
    ).execute()

if 'credentials' not in st.session_state:
    result = oauth2.authorize_button(
        "Log in with Google", REDIRECT_URI, SCOPE,
        extras_params={"access_type": "offline", "prompt": "consent"}
    )

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

    files = fetch_drive_files()
    selected_file_name = st.selectbox("Select a CSV file:", options=files.keys())
    if st.session_state.get("selected_file") != selected_file_name:
        # Clear session state related to previous file
        st.session_state["selected_file"] = selected_file_name
        st.session_state.pop("data", None)
        st.session_state.pop("file_id", None)
        st.session_state.pop("current_index", None)
        st.rerun()


    if selected_file_name:
        file_id = files[selected_file_name]

        @st.cache_data(show_spinner=False)
        def load_csv(file_id: str, user_email: str, cache_buster=None) -> pd.DataFrame:
            file_content = drive_service.files().get_media(fileId=file_id).execute()
            return pd.read_csv(BytesIO(file_content))

        if "data" not in st.session_state or st.session_state.get("file_id") != file_id:
            st.session_state["data"] = load_csv(file_id, user_email, cache_buster=time.time())
            st.session_state["file_id"] = file_id

        data = st.session_state["data"]

        user_label_column = f"RA_AI_Labels"
        if user_label_column not in data.columns:
            data[user_label_column] = None

        last_filled_index = data[user_label_column].last_valid_index()
        if "current_index" not in st.session_state:
            st.session_state["current_index"] = 0 if last_filled_index is None else last_filled_index + 1

        current_index = st.session_state["current_index"]

        unsure_count = (data[user_label_column] == 9).sum()
        accept_count = (data[user_label_column] == 1).sum()
        reject_count = (data[user_label_column] == 0).sum()

        if current_index < len(data):
            current_row = data.iloc[current_index]
            st.write(f"### {current_row['TITLE']}")
            st.write(f"**Company:** {current_row['COMPANY_NAME']}")
            st.write(f"**Job Description:**")
            st.write(current_row["cleaned_jd"])
            st.write("---")

            label = st.radio("Enter Label:", options=[0, 1] + ([9] if unsure_count < 20 else []), horizontal=True)

            if st.button("Submit Label"):
                st.session_state["current_index"] = current_index + 1
                data.at[current_index, user_label_column] = label
                threading.Thread(target=save_to_drive, args=(file_id, data), daemon=True).start()
                st.success(f"Row {current_index} labeled successfully.")
                st.rerun()

        st.progress((current_index) / len(data))
        st.write(
            f"✅ You have labeled {current_index} out of {len(data)} rows ({round((current_index) / len(data) * 100)}% complete)."
        )
        st.write(f"⚠️ Unsure Count: {unsure_count}/20")
        st.write(f"🤖 AI (1) Count: {accept_count}")
        st.write(f"❌ Not AI (0) Count: {reject_count}")
    else:
        st.info("Please select a file to start labeling.")
