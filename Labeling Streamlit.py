import streamlit as st
import pandas as pd
from io import BytesIO
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
from streamlit_oauth import OAuth2Component

CLIENT_ID = st.secrets["client_id"]
CLIENT_SECRET = st.secrets["client_secret"]
REDIRECT_URI = st.secrets["redirect_uri"]
SCOPE = "https://www.googleapis.com/auth/drive.file https://www.googleapis.com/auth/userinfo.email"

oauth2 = OAuth2Component(
    CLIENT_ID, CLIENT_SECRET, REDIRECT_URI,
    AUTHORIZE_ENDPOINT="https://accounts.google.com/o/oauth2/auth",
    TOKEN_ENDPOINT="https://oauth2.googleapis.com/token"
)

if 'credentials' not in st.session_state:
    result = oauth2.authorize_button("Log in with Google", REDIRECT_URI, SCOPE=SCOPE)
    if result:
        creds = Credentials(token=result["access_token"])
        st.session_state['credentials'] = creds

if 'credentials' in st.session_state:
    creds = st.session_state['credentials']
    drive_service = build('drive', 'v3', credentials=creds)
    user_info_service = build('oauth2', 'v2', credentials=creds)
    user_info = user_info_service.userinfo().get().execute()

    st.title(f"Dataset Labeling for {user_info['email']}")

    # Fetch CSV files from Google Drive
    def fetch_drive_files():
        files = drive_service.files().list(q="mimeType='text/csv'", fields='files(id, name)').execute()
        return {file['name']: file['id'] for file in files.get('files', [])}

    files = fetch_drive_files(service=drive_service)
    selected_file_name = st.selectbox("Select a CSV file:", options=files.keys())

    if selected_file_name:
        file_id = files[selected_file_name]
        file_content = drive_service.files().get_media(fileId=file_id).execute()
        data = pd.read_csv(BytesIO(file_content))

        if 'current_index' not in st.session_state:
            st.session_state['current_index'] = 0

        if st.session_state['current_index'] < len(data):
            current_row = data.iloc[st.session_state['current_index']]
            st.write(current_row)

            label = st.radio("Enter Label:", options=[0, 1, 9], horizontal=True)

            if st.button("Submit Label"):
                data.at[st.session_state['current_index'], 'Label'] = label
                st.session_state['current_index'] += 1

                # Save updated CSV back to Drive
                updated_csv = BytesIO()
                data.to_csv(updated_csv, index=False)
                updated_csv.seek(0)

                drive_service.files().update(
                    fileId=file_id,
                    media_body=MediaIoBaseUpload(updated_csv, mimetype='text/csv')
                ).execute()

                st.success(f"Row {st.session_state['current_index']} labeled successfully.")
                st.experimental_rerun()

        st.progress((st.session_state['current_index'] + 1) / len(data))
    else:
        st.info("Please select a file to start labeling.")