import json
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
from threading import Lock

# Define broker details
BROKER = "homeassistant.local"  # Replace with your broker IP
PORT = 1883
USERNAME = "zektor"  # Replace with your MQTT username
PASSWORD = "command"  # Replace with your MQTT password
FOREST_TOPIC = "forest/activity"  # Example topic

# Lock for thread-safe operations
data_lock = Lock()

# Data Structures
stage_map = {
    i: None for i in range(1, 7)
}  # Tracks stage occupancy: {stage_id: session_id}
sessions = (
    {}
)  # Tracks session details: {session_id: {"current_stage": stage, "score": score}}
active_sessions = []  # Tracks active session IDs
completed_sessions = []  # Tracks completed session IDs
next_session_id = 1  # Auto-incrementing session ID

# Persistent Data File
DATA_FILE = "sessions_data.json"


# Load data from JSON file if it exists
def load_data():
    global stage_map, sessions, active_sessions, completed_sessions, next_session_id
    try:
        with open(DATA_FILE, "r") as file:
            data = json.load(file)
            stage_map = data["stage_map"]
            sessions = data["sessions"]
            active_sessions = data["active_sessions"]
            completed_sessions = data["completed_sessions"]
            next_session_id = data["next_session_id"]
    except FileNotFoundError:
        # File doesn't exist, proceed with defaults
        pass


# Save data to JSON file
def save_data():
    data = {
        "stage_map": stage_map,
        "sessions": sessions,
        "active_sessions": active_sessions,
        "completed_sessions": completed_sessions,
        "next_session_id": next_session_id,
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
            session_in_stage1 = stage_map[1]

            if session_in_stage1:
                if point == "increment":
                    result = update_score(session_in_stage1, 1)
                    print(result)
                elif point == "decrement":
                    result = update_score(session_in_stage1, -1)
                    print(result)

                # Print current session status
                if session_in_stage1 in sessions:
                    print(
                        f"Current score for {session_in_stage1} (Stage 1): {sessions[session_in_stage1]['score']}"
                    )
            else:
                print("No session currently in Stage 1")

            # Save data after processing message
            save_data()

    print(f"Received message: {message.payload.decode()} on topic {message.topic}")


# Initialize MQTT client
def init_mqtt_client():
    client = mqtt.Client(protocol=mqtt.MQTTv5)
    client.username_pw_set(USERNAME, PASSWORD)
    client.on_connect = on_connect
    client.on_message = on_message

    # Connect to broker
    client.connect(BROKER, PORT)

    # Start MQTT loop in a separate thread
    mqtt_thread = threading.Thread(target=client.loop_forever)
    mqtt_thread.daemon = True
    mqtt_thread.start()
    return client


def start_session():
    """Start a new session by placing it in Stage 1 if available."""
    global next_session_id
    with data_lock:
        session_id = f"session{next_session_id}"
        if stage_map[1] is not None:
            return f"Stage 1 is occupied by {stage_map[1]}. Cannot start a new session."
        sessions[session_id] = {
            "current_stage": 1,
            "score": 0,
            "start_time": datetime.now().isoformat(),
        }
        stage_map[1] = session_id
        active_sessions.append(session_id)
        next_session_id += 1

        # Save data after starting session
        save_data()
    return f"Session {session_id} started in Stage 1."


def progress_session(session_id):
    """Progress a specific session to the next stage if possible."""
    with data_lock:
        if session_id not in sessions:
            return f"Session {session_id} does not exist."
        if session_id not in active_sessions:
            return f"Session {session_id} is not active or has already completed all stages."

        current_stage = sessions[session_id]["current_stage"]
        next_stage = current_stage + 1

        if next_stage > 6:
            # Move session to completed
            stage_map[current_stage] = None
            active_sessions.remove(session_id)
            completed_sessions.append(session_id)

            # Save data after completing session
            save_data()
            return f"Session {session_id} has completed all stages."

        if stage_map[next_stage] is not None:
            return f"Stage {next_stage} is occupied by {stage_map[next_stage]}. Cannot progress Session {session_id}."

        # Progress the session
        stage_map[current_stage] = None
        stage_map[next_stage] = session_id
        sessions[session_id]["current_stage"] = next_stage

        # Save data after progressing session
        save_data()
        return f"Session {session_id} progressed to Stage {next_stage}."


def update_score(session_id, score_change):
    """Update the score for a session."""
    with data_lock:
        if session_id not in sessions:
            return f"Session {session_id} does not exist."
        sessions[session_id]["score"] += score_change

        # Save data after updating score
        save_data()
        return (
            f"Session {session_id}'s score updated to {sessions[session_id]['score']}."
        )


def get_status():
    """Get the current status of all stages, active sessions, and completed sessions."""
    with data_lock:
        return {
            "stage_map": stage_map,
            "active_sessions": active_sessions,
            "completed_sessions": completed_sessions,
            "sessions": sessions,
        }


# Initialize MQTT client
client = init_mqtt_client()

# Load data from file
load_data()

# Streamlit UI
st.set_page_config(layout="wide")
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
            st.write(f"Score: {sessions[session_id]['score']}")
        else:
            st.write("No session")

# Progress Sessions (for testing purposes)
st.subheader("Progress Sessions")

with st.form("progress_form"):
    session_to_progress = st.selectbox(
        "Select Session to Progress", options=active_sessions
    )
    submitted = st.form_submit_button("Progress Session")
    if submitted and session_to_progress:
        result = progress_session(session_to_progress)
        st.success(result)

# Display Active and Completed Sessions
st.subheader("Sessions Summary")
st.write("**Active Sessions:**")
st.write(active_sessions)
st.write("**Completed Sessions:**")
st.write(completed_sessions)
