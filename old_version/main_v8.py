import json
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st  # Streamlit import
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
    """Handle incoming MQTT messages for the session in stage 1"""
    if message.topic == FOREST_TOPIC:
        point = message.payload.decode().lower()

        # Acquire lock for thread-safe operations
        with data_lock:
            # Get the session that's currently in stage 1
            session_in_stage1 = st.session_state.stage_map[1]

            if session_in_stage1:
                if point == "increment":
                    result = update_score(session_in_stage1, 1)
                    print(result)
                elif point == "decrement":
                    result = update_score(session_in_stage1, -1)
                    print(result)

                # Print current session status
                if session_in_stage1 in st.session_state.sessions:
                    print(
                        f"Current score for {session_in_stage1} (Stage 1): {st.session_state.sessions[session_in_stage1]['score']}"
                    )
            else:
                print("No session currently in Stage 1")

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
def start_session():
    """Start a new session by placing it in Stage 1 if available."""
    with data_lock:
        session_id = f"session{st.session_state.next_session_id}"
        if st.session_state.stage_map[1] is not None:
            return f"Stage 1 is occupied by {st.session_state.stage_map[1]}. Cannot start a new session."
        st.session_state.sessions[session_id] = {
            "current_stage": 1,
            "score": 0,
            "start_time": datetime.now().isoformat(),
        }
        st.session_state.stage_map[1] = session_id
        st.session_state.active_sessions.append(session_id)
        st.session_state.next_session_id += 1

        # Save data after starting session
        save_data()
    return f"Session {session_id} started in Stage 1."


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
            return f"Session {session_id} has completed all stages."

        if st.session_state.stage_map[next_stage] is not None:
            return f"Stage {next_stage} is occupied by {st.session_state.stage_map[next_stage]}. Cannot progress Session {session_id}."

        # Progress the session
        st.session_state.stage_map[current_stage] = None
        st.session_state.stage_map[next_stage] = session_id
        st.session_state.sessions[session_id]["current_stage"] = next_stage

        # Save data after progressing session
        save_data()
        return f"Session {session_id} progressed to Stage {next_stage}."


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
st.title("Escape Room Game Controller")

# Start Session Button
if st.button("Start Session"):
    result = start_session()
    st.success(result)

# Display stages in real-time
status = get_status()

st.subheader("Stage Status")

# Create columns for stages
cols = st.columns(5)

for i, col in enumerate(cols, start=1):
    with col:
        st.markdown(f"### Stage {i}")
        session_id = status["stage_map"].get(i)
        if session_id:
            st.write(f"Session: {session_id}")
            st.write(f"Score: {status['sessions'][session_id]['score']}")
            # Add buttons to simulate MQTT messages
            if not MQTT_ENABLED and i == 1:
                increment = st.button(
                    f"Increment Score ({session_id})", key=f"inc_{session_id}"
                )
                decrement = st.button(
                    f"Decrement Score ({session_id})", key=f"dec_{session_id}"
                )
                if increment:
                    result = update_score(session_id, 1)
                    st.success(result)
                if decrement:
                    result = update_score(session_id, -1)
                    st.success(result)
        else:
            st.write("No session")

# Progress Sessions (for testing purposes)
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
st.write(st.session_state.active_sessions)
st.write("**Completed Sessions:**")
st.write(st.session_state.completed_sessions)

# Auto-refresh the page every 5 seconds
from streamlit_autorefresh import st_autorefresh

# Auto-refresh the page every 5 seconds
st_autorefresh(interval=5000, key="datarefresh")