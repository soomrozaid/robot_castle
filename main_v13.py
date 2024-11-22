import json
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
from threading import Lock
import os

# Set page configuration first
st.set_page_config(layout="wide")

# Load configurations
with open("config.json") as config_file:
    config = json.load(config_file)

# Determine the environment
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")

# Get the appropriate configuration
mqtt_config = config.get(ENVIRONMENT, config["development"])
MQTT_ENABLED = mqtt_config.get("ENABLED", False)  # Read from config

BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]
FOREST_TOPIC = mqtt_config["TOPIC"]

# Lock for thread-safe operations
data_lock = Lock()

# Persistent Data File
DATA_FILE = "sessions_data.json"

# Stage themes and colors
stage_themes = {
    1: {"name": "Forest", "color": "#228B22"},
    2: {"name": "Statue", "color": "#FFD700"},
    3: {"name": "Electricity", "color": "#1E90FF"},
    4: {"name": "Zektor", "color": "#8A2BE2"},
    5: {"name": "Lava Floor", "color": "#FF4500"},
}

# Initialize Streamlit session state
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.stage_map = {i: None for i in range(1, 6)}  # Stages 1-5
    st.session_state.sessions = {}
    st.session_state.active_sessions = []
    st.session_state.completed_sessions = []
    st.session_state.next_session_id = 1

    # Load data from file
    def load_data():
        try:
            with open(DATA_FILE, "r") as file:
                data = json.load(file)
                # Convert keys in stage_map to integers
                st.session_state.stage_map = {
                    int(k): v for k, v in data["stage_map"].items()
                }
                st.session_state.sessions = data["sessions"]
                st.session_state.active_sessions = data["active_sessions"]
                st.session_state.completed_sessions = data["completed_sessions"]
                st.session_state.next_session_id = data["next_session_id"]
        except FileNotFoundError:
            # File doesn't exist, proceed with defaults
            pass

    load_data()


# Save data to JSON file
def save_data():
    data = {
        "stage_map": {str(k): v for k, v in st.session_state.stage_map.items()},
        "sessions": st.session_state.sessions,
        "active_sessions": st.session_state.active_sessions,
        "completed_sessions": st.session_state.completed_sessions,
        "next_session_id": st.session_state.next_session_id,
    }
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=2)


# Callback for when the client connects
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully!")
        client.subscribe(FOREST_TOPIC)
        print(f"Successfully subscribed to the {FOREST_TOPIC}")
    else:
        print(f"Connection failed with code {rc}")


# Callback for when a message is received
def on_message(client, userdata, message):
    """Handle incoming MQTT messages for the sessions"""
    if message.topic == FOREST_TOPIC:
        point = message.payload.decode().lower()

        # Acquire lock for thread-safe operations
        with data_lock:
            # Apply score change to all active sessions
            for session_id in st.session_state.active_sessions:
                if point == "increment":
                    result = update_score(session_id, 1)
                    print(result)
                elif point == "decrement":
                    result = update_score(session_id, -1)
                    print(result)

            # Save data after processing message
            save_data()

    print(f"Received message: {message.payload.decode()} on topic {message.topic}")


# Initialize MQTT client as a singleton
@st.cache_resource
def init_mqtt_client():
    if MQTT_ENABLED:
        client = mqtt.Client(protocol=mqtt.MQTTv5)
        client.username_pw_set(USERNAME, PASSWORD)
        client.on_connect = on_connect
        client.on_message = on_message

        try:
            client.connect(BROKER, PORT)
            # Start MQTT loop in a separate thread
            mqtt_thread = threading.Thread(target=client.loop_forever)
            mqtt_thread.daemon = True
            mqtt_thread.start()
        except Exception as e:
            st.error(f"Failed to connect to MQTT broker at {BROKER}:{PORT}: {e}")
        return client
    else:
        st.warning("MQTT is disabled. Simulating MQTT messages.")
        return None  # No MQTT client when disabled


# Initialize MQTT client
client = init_mqtt_client()


# Define your functions
def start_session(name):
    """Start a new session by placing it in Stage 1 if available."""
    with data_lock:
        session_id = f"session{st.session_state.next_session_id}"
        if st.session_state.stage_map[1] is not None:
            return f"Stage 1 is occupied by {st.session_state.stage_map[1]}. Cannot start a new session."
        st.session_state.sessions[session_id] = {
            "name": name,
            "current_stage": 1,
            "score": 0,
            "start_time": datetime.now().isoformat(),
        }
        st.session_state.stage_map[1] = session_id
        st.session_state.active_sessions.append(session_id)
        st.session_state.next_session_id += 1

        # Save data after starting session
        save_data()
    return f"Session '{name}' ({session_id}) started in Stage 1."


def progress_session(session_id):
    """Progress a specific session to the next stage if possible."""
    with data_lock:
        if session_id not in st.session_state.sessions:
            return f"Session {session_id} does not exist."
        if session_id not in st.session_state.active_sessions:
            return f"Session {session_id} is not active or has already completed all stages."

        current_stage = st.session_state.sessions[session_id]["current_stage"]
        next_stage = current_stage + 1

        if next_stage > 5:
            # Move session to completed
            st.session_state.stage_map[current_stage] = None
            st.session_state.active_sessions.remove(session_id)
            st.session_state.completed_sessions.append(session_id)

            # Save data after completing session
            save_data()
            return f"Session '{st.session_state.sessions[session_id]['name']}' ({session_id}) has completed all stages."
        else:
            if st.session_state.stage_map[next_stage] is not None:
                return f"Stage {next_stage} is occupied by {st.session_state.stage_map[next_stage]}. Cannot progress Session {session_id}."

            # Progress the session
            st.session_state.stage_map[current_stage] = None
            st.session_state.stage_map[next_stage] = session_id
            st.session_state.sessions[session_id]["current_stage"] = next_stage

            # Save data after progressing session
            save_data()

            # Get the stage name
            stage_name = stage_themes[next_stage]["name"]

            return f"Session '{st.session_state.sessions[session_id]['name']}' ({session_id}) progressed to '{stage_name}'."


def update_score(session_id, score_change):
    """Update the score for a session."""
    with data_lock:
        if session_id not in st.session_state.sessions:
            return f"Session {session_id} does not exist."
        st.session_state.sessions[session_id]["score"] += score_change

        # Save data after updating score
        save_data()
        return f"Session {session_id}'s score updated to {st.session_state.sessions[session_id]['score']}."


def get_status():
    """Get the current status of all stages, active sessions, and completed sessions."""
    with data_lock:
        return {
            "stage_map": st.session_state.stage_map.copy(),
            "active_sessions": st.session_state.active_sessions.copy(),
            "completed_sessions": st.session_state.completed_sessions.copy(),
            "sessions": st.session_state.sessions.copy(),
        }


# Streamlit UI
st.title("Zektor Game Controller")

# Start Session Form
st.subheader("Start New Session")

with st.form("start_session_form"):
    session_name = st.text_input(
        "Session Name", value=f"Session {st.session_state.next_session_id}"
    )
    submitted = st.form_submit_button("Start Session")
    if submitted and session_name:
        result = start_session(session_name)
        st.success(result)

# Display stages in real-time
status = get_status()

st.subheader("Game Status")

# Create columns for stages
cols = st.columns(5)


for i, col in enumerate(cols, start=1):

    # Initialize a variable to store the success message
    success_message = None

    with col:
        # Get stage theme and color
        theme = stage_themes.get(i, {})
        stage_name = theme.get("name", f"Stage {i}")
        bg_color = theme.get("color", "#f0f0f0")

        # Apply background color
        stage_container = col.container()
        with stage_container:
            stage_container.markdown(
                f"<div style='background-color:{bg_color}; padding: 10px; border-radius: 5px;'>",
                unsafe_allow_html=True,
            )
            st.markdown(f"### {stage_name}")
            session_id = status["stage_map"].get(i)

            if session_id:
                session = status["sessions"][session_id]
                session_name = session.get("name", session_id)
                session_score = session["score"]

                # Display the session card
                session_card = st.container(border=True)
                with session_card:
                    # Title and subtitle
                    st.markdown(
                        f"<h5>{session_name}</h5>",
                        unsafe_allow_html=True,
                    )
                    st.markdown(
                        f"<p style=' color: #555; margin-bottom: 0px;'>{session_id}</p>",
                        unsafe_allow_html=True,
                    )
                    st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

                    # Arrange '-' button, score, '+' button
                    btn_col1, score_col, btn_col2 = st.columns([1, 2, 1])
                    with btn_col1:
                        if st.button("➖", key=f"dec_{session_id}"):
                            success_message = update_score(session_id, -1)
                            # st.success(success_message)
                    with score_col:
                        st.markdown(
                            f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>",
                            unsafe_allow_html=True,
                        )
                    with btn_col2:
                        if st.button("➕", key=f"inc_{session_id}"):
                            success_message = update_score(session_id, 1)
                            # st.success(result)
                    # st.markdown("</div>", unsafe_allow_html=True)  # Close session card

            else:
                st.write("No session")
            st.markdown("</div>", unsafe_allow_html=True)  # Close stage background div

    # Display the success message below the session card
    if success_message:
        st.markdown(
            f"""<p style='margin-top: 10px; width: 100%;background-color:#005500;
                                           color:white;
                                           font-size:18px;
                                           border-radius:3px;
                                           line-height:50px;
                                           padding-left:17px;
                                           opacity:0.8'>{success_message}</p>""",
            unsafe_allow_html=True,
        )

# Progress Sessions
st.subheader("Progress Sessions")

if st.session_state.active_sessions:
    with st.form("progress_form"):
        session_to_progress = st.selectbox(
            "Select Session to Progress", options=st.session_state.active_sessions
        )
        submitted = st.form_submit_button("Progress Session")
        if submitted and session_to_progress:
            result = progress_session(session_to_progress)
            st.success(result)
else:
    st.write("No active sessions to progress.")

# Display Active and Completed Sessions
st.subheader("Sessions Summary")
st.write("**Active Sessions:**")
if st.session_state.active_sessions:
    active_sessions_data = {
        session_id: st.session_state.sessions[session_id]
        for session_id in st.session_state.active_sessions
    }
    st.json(active_sessions_data)
else:
    st.write("No active sessions.")

st.write("**Completed Sessions:**")
if st.session_state.completed_sessions:
    completed_sessions_data = {
        session_id: st.session_state.sessions[session_id]
        for session_id in st.session_state.completed_sessions
    }
    st.json(completed_sessions_data)
else:
    st.write("No completed sessions.")

# Auto-refresh the page every 5 seconds
from streamlit_autorefresh import st_autorefresh

# Auto-refresh the page every 5 seconds
st_autorefresh(interval=5000, key="datarefresh")
