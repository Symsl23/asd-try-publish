# Fixed version of your Streamlit face attendance system with proper session_state handling
# and persistent class folder management

import streamlit as st
import face_recognition
import pandas as pd
import pickle
import io
import datetime
import gspread
import plotly.express as px
from google.oauth2.service_account import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaIoBaseUpload
import os

# === Setup ===
CLASS_FOLDERS_FILE = "class_folders.pkl"
DEFAULT_CLASS_LIST = [
    "BVI3114 TECHNOLOGY SYSTEM OPTIMIZATION II",
    "BVI3124 APPLICATION SYSTEM DEVELOPMENT II",
    "UHF1111 MANDARIN FOR BEGINNERS",
    "BVI2254 CAPSTONE TECHNOPRENEUR I",
    "BVI3215 SYSTEM INTEGRATION DESIGNING",
    "ULE1362 ENGLISH FOR VOCATIONAL PURPOSES"
]

# === Google Auth Setup ===
SCOPE = ["https://www.googleapis.com/auth/drive", "https://spreadsheets.google.com/feeds"]
creds = Credentials.from_service_account_file(".streamlit/secret2.toml", scopes=SCOPE)
client = gspread.authorize(creds)
spreadsheet_url = "https://docs.google.com/spreadsheets/d/1KCA9QkzY9YTa46Ebz0etWbutWyGSx0Wmrdlrk6vtdGM"
drive_service = build("drive", "v3", credentials=creds)
PARENT_FOLDER_ID = "1_nqo09S2_8pxS9mVvdwwXO1IfVGD1vn7"

# === Load known faces ===
try:
    with open("known_faces.pkl", "rb") as f:
        known_data = pickle.load(f)
        known_faces = known_data["encodings"]
        known_metadata = known_data["metadata"]
except FileNotFoundError:
    known_faces = []
    known_metadata = []

# === Load class folders into session_state ===
if "class_folders" not in st.session_state:
    if os.path.exists(CLASS_FOLDERS_FILE):
        with open(CLASS_FOLDERS_FILE, "rb") as f:
            st.session_state.class_folders = pickle.load(f)
    else:
        st.session_state.class_folders = {}

    for cls in DEFAULT_CLASS_LIST:
        if cls not in st.session_state.class_folders:
            folder_id = drive_service.files().create(
                body={
                    'name': cls,
                    'mimeType': 'application/vnd.google-apps.folder',
                    'parents': [PARENT_FOLDER_ID]
                },
                fields='id'
            ).execute()["id"]
            st.session_state.class_folders[cls] = folder_id

    with open(CLASS_FOLDERS_FILE, "wb") as f:
        pickle.dump(st.session_state.class_folders, f)

# === Cached Google Sheets reader ===
@st.cache_data(ttl=30)
def get_class_data(class_name):
    try:
        worksheet = client.open_by_url(spreadsheet_url).worksheet(class_name)
        data = worksheet.get_all_records()
        return pd.DataFrame(data)
    except gspread.exceptions.WorksheetNotFound:
        return pd.DataFrame()

# === Streamlit UI ===
st.title("🎓 Student Face Attendance System")
tab1, tab2, tab3 = st.tabs(["🧑‍🎓 Register Face", "📝 Submit Attendance", "🛠️ Admin Panel"])

# === Tab 1: Registration ===
with tab1:
    st.subheader("Register Your Face")
    with st.form("register_form"):
        reg_name = st.text_input("Full Name")
        reg_id = st.text_input("Student ID")
        reg_email = st.text_input("Email")
        reg_phone = st.text_input("Phone Number")
        reg_img = st.camera_input("Capture Your Face")
        reg_submit = st.form_submit_button("Register")

        if reg_submit:
            if not reg_name or not reg_id or not reg_email or not reg_phone:
                st.error("❗ Please fill in all fields.")
            elif not reg_img:
                st.error("❗ Please capture a face image.")
            elif "@" not in reg_email or "." not in reg_email:
                st.error("❗ Invalid email.")
            elif not reg_phone.isdigit() or len(reg_phone) < 10 or len(reg_phone) > 15:
                st.error("❗ Invalid phone number.")
            else:
                image = face_recognition.load_image_file(io.BytesIO(reg_img.getvalue()))
                encodings = face_recognition.face_encodings(image)
                if not encodings:
                    st.error("❌ No face detected.")
                else:
                    known_faces.append(encodings[0])
                    known_metadata.append({"name": reg_name, "student_id": reg_id, "email": reg_email, "phone": reg_phone})
                    with open("known_faces.pkl", "wb") as f:
                        pickle.dump({"encodings": known_faces, "metadata": known_metadata}, f)
                    st.success(f"✅ {reg_name} registered successfully!")

# === Tab 2: Attendance ===
with tab2:
    st.subheader("Submit Attendance")
    selected_class = st.selectbox("Select Class", list(st.session_state.class_folders.keys()))
    face_img = st.camera_input("Capture Your Face")

    if face_img:
        image = face_recognition.load_image_file(io.BytesIO(face_img.getvalue()))
        encodings = face_recognition.face_encodings(image)
        if not encodings:
            st.error("❌ No face detected.")
        elif not known_faces:
            st.error("⚠️ No registered faces found.")
        else:
            face_encoding = encodings[0]
            distances = face_recognition.face_distance(known_faces, face_encoding)
            min_distance = min(distances)
            best_match_index = distances.tolist().index(min_distance)
            if min_distance < 0.45:
                matched = known_metadata[best_match_index]
                timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
                filename = f"{matched['name']}_{matched['student_id']}_{selected_class}_{timestamp.replace(':', '-')}.jpg"
                media = MediaIoBaseUpload(io.BytesIO(face_img.getvalue()), mimetype="image/jpeg")
                uploaded = drive_service.files().create(
                    body={"name": filename, "parents": [st.session_state.class_folders[selected_class]]},
                    media_body=media,
                    fields="id"
                ).execute()
                file_url = f"https://drive.google.com/file/d/{uploaded['id']}/view"

                try:
                    sheet = client.open_by_url(spreadsheet_url).worksheet(selected_class)
                except gspread.exceptions.WorksheetNotFound:
                    sheet = client.open_by_url(spreadsheet_url).add_worksheet(title=selected_class, rows="100", cols="20")
                    sheet.append_row(["Timestamp", "Name", "Student ID", "Email", "Phone", "Class", "Status", "Image URL"])

                sheet.append_row([
                    timestamp,
                    matched['name'],
                    matched['student_id'],
                    matched.get('email', ''),
                    matched.get('phone', ''),
                    selected_class,
                    "Present",
                    file_url
                ])
                st.success(f"✅ Attendance submitted for {matched['name']} ({matched['student_id']})")
            else:
                st.error("❌ Face not recognized.")

with tab3:
    st.subheader("Admin Panel")
    admin_code = st.text_input("Enter Admin Code", type="password")
    
    if admin_code == "admin123":
        st.success("Access granted ✅")

        st.markdown("### ➕ Add New Class")
        new_class = st.text_input("Class Name")
        if st.button("Add Class"):
            if new_class.strip() == "":
                st.error("Class name cannot be empty.")
            elif new_class in st.session_state.class_folders:
                st.warning("Class already exists.")
            else:
                folder_id = drive_service.files().create(
                    body={
                        'name': new_class,
                        'mimeType': 'application/vnd.google-apps.folder',
                        'parents': [PARENT_FOLDER_ID]
                    },
                    fields='id'
                ).execute()['id']
                st.session_state.class_folders[new_class] = folder_id
                with open(CLASS_FOLDERS_FILE, "wb") as f:
                    pickle.dump(st.session_state.class_folders, f)
                st.success(f"Class '{new_class}' added.")

        st.markdown("### ➖ Remove Class")
        if st.session_state.class_folders:
            class_to_remove = st.selectbox("Class to remove", list(st.session_state.class_folders.keys()))
            if st.button("Remove Class"):
                del st.session_state.class_folders[class_to_remove]
                with open(CLASS_FOLDERS_FILE, "wb") as f:
                    pickle.dump(st.session_state.class_folders, f)
                st.success(f"Class '{class_to_remove}' removed.")
        else:
            st.info("No classes available to remove.")

        st.markdown("---")
        st.markdown("### 📊 Attendance Dashboard")
        selected = st.selectbox("Select class", list(st.session_state.class_folders.keys()))
        df = get_class_data(selected)
        if df.empty:
            st.info("No data yet.")
        else:
            date = st.date_input("Filter by date", datetime.date.today())
            filtered_df = df[df['Timestamp'].str.startswith(str(date))]
            if filtered_df.empty:
                st.warning("No data for selected date.")
            else:
                counts = filtered_df.groupby(["Student ID", "Name"]).size().reset_index(name="Count")
                st.markdown("**Top 3 Attendees**")
                st.table(counts.sort_values("Count", ascending=False).head(3))
                st.markdown("**Low Attendance**")
                st.table(counts.sort_values("Count").head(3))
                st.plotly_chart(px.pie(counts, names="Name", values="Count", title="Attendance Pie Chart"))

        st.markdown("---")
        st.markdown("### 📥 Download Attendance Data as CSV")

        download_class = st.selectbox("Select class to download", list(st.session_state.class_folders.keys()), key="download_class")
        download_date = st.date_input("Select date", value=datetime.date.today(), key="download_date")

        if st.button("Download CSV"):
            df = get_class_data(download_class)
            if df.empty:
                st.warning("No attendance data for selected class.")
            else:
                filtered_df = df[df['Timestamp'].str.startswith(str(download_date))]
                if filtered_df.empty:
                    st.warning("No data for selected date.")
                else:
                    csv_buffer = io.StringIO()
                    filtered_df.to_csv(csv_buffer, index=False)
                    csv_data = csv_buffer.getvalue().encode('utf-8')

                    st.download_button(
                        label=f"Download {download_class} attendance for {download_date}",
                        data=csv_data,
                        file_name=f"{download_class}_attendance_{download_date}.csv",
                        mime="text/csv"
                    )
    else:
        if admin_code:
            st.warning("Enter valid admin code.")

