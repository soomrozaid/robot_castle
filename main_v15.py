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

# Get per-stage topics from the config
STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}

# Lock for thread-safe operations
data_lock = Lock()

# Persistent Data File per environment
DATA_FILE = f"sessions_data_{ENVIRONMENT}.json"

# Stage themes and colors
stage_themes = {
    1: {"name": "Forest", "color": "#228B22"},
    2: {"name": "Statue", "color": "#FFD700"},
    3: {"name": "Electricity", "color": "#1E90FF"},
    4: {"name": "Zektor", "color": "#8A2BE2"},
    5: {"name": "Lava Floor", "color": "#FF4500"},
    6: {"name": "Final Stage", "color": "#FF1493"},
}

# Initialize Streamlit session state
if "initialized" not in st.session_state:
    st.session_state.initialized = True
    st.session_state.stage_map = {i: None for i in range(1, 7)}  # Stages 1-6
    st.session_state.sessions = {}
    st.session_state.active_sessions = []
    st.session_state.completed_sessions = []
    st.session_state.next_session_id = 1
    st.session_state.messages = []  # Initialize messages list

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
        for topic in STAGE_TOPICS.values():
            client.subscribe(topic)
            print(f"Successfully subscribed to topic {topic}")
    else:
        print(f"Connection failed with code {rc}")


# Callback for when a message is received
def on_message(client, userdata, message):
    """Handle incoming MQTT messages for the sessions"""
    topic = message.topic
    payload = message.payload.decode().lower()

    # Find the stage corresponding to the topic
    stage = None
    for s, t in STAGE_TOPICS.items():
        if t == topic:
            stage = s
            break
    if stage is None:
        print(f"Received message on unknown topic: {topic}")
        return

    # Acquire lock for thread-safe operations
    with data_lock:
        session_id = st.session_state.stage_map.get(stage)
        if session_id is not None:
            if payload == "increment":
                result = update_score(session_id, 1)
                print(result)
            elif payload == "decrement":
                result = update_score(session_id, -1)
                print(result)
            elif payload == "unlock":
                result = auto_progress_session(session_id)
                print(result)
        else:
            print(f"No session in stage {stage}, message ignored.")

    # Save data after processing message
    save_data()

    print(f"Received message: {payload} on topic {topic}")


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

        if next_stage > 6:
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


def auto_progress_session(session_id):
    """Automatically progress a session to the next stage if gate is unlocked and next stage is unoccupied."""
    with data_lock:
        if session_id not in st.session_state.sessions:
            return f"Session {session_id} does not exist."
        if session_id not in st.session_state.active_sessions:
            return f"Session {session_id} is not active or has already completed all stages."

        current_stage = st.session_state.sessions[session_id]["current_stage"]
        next_stage = current_stage + 1

        if next_stage > 6:
            # Move session to completed
            st.session_state.stage_map[current_stage] = None
            st.session_state.active_sessions.remove(session_id)
            st.session_state.completed_sessions.append(session_id)

            # Save data after completing session
            save_data()
            return f"Session '{st.session_state.sessions[session_id]['name']}' ({session_id}) has completed all stages."
        else:
            if st.session_state.stage_map[next_stage] is not None:
                return f"Cannot progress Session {session_id} to Stage {next_stage} because it is occupied by {st.session_state.stage_map[next_stage]}."

            # Progress the session
            st.session_state.stage_map[current_stage] = None
            st.session_state.stage_map[next_stage] = session_id
            st.session_state.sessions[session_id]["current_stage"] = next_stage

            # Save data after progressing session
            save_data()

            # Get the stage name
            stage_name = stage_themes[next_stage]["name"]

            return f"Session '{st.session_state.sessions[session_id]['name']}' ({session_id}) automatically progressed to '{stage_name}'."


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


def simulate_message(stage, payload):
    """Simulate receiving a message for testing when MQTT is disabled."""
    # Acquire lock for thread-safe operations
    with data_lock:
        session_id = st.session_state.stage_map.get(stage)
        if session_id is not None:
            if payload == "increment":
                result = update_score(session_id, 1)
            elif payload == "decrement":
                result = update_score(session_id, -1)
            elif payload == "unlock":
                result = auto_progress_session(session_id)
        else:
            result = f"No session in stage {stage}, message ignored."

        # Save data after processing message
        save_data()

    # Append the result to messages
    st.session_state["messages"].append(result)


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
cols = st.columns(6)

for i, col in enumerate(cols, start=1):

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
                    btn_col1, score_col, btn_col2 = st.columns([1, 1, 1])
                    with btn_col1:
                        if st.button("➖", key=f"dec_{session_id}"):
                            result = update_score(session_id, -1)
                            st.session_state["messages"].append(result)
                    with score_col:
                        st.markdown(
                            f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>",
                            unsafe_allow_html=True,
                        )
                    with btn_col2:
                        if st.button("➕", key=f"inc_{session_id}"):
                            result = update_score(session_id, 1)
                            st.session_state["messages"].append(result)

                # Display gate status
                gate_status = "Disabled" if session_id else "Enabled"
                st.markdown(f"**Gate Status:** {gate_status}")

                # Simulate MQTT messages when MQTT is disabled
                # if not MQTT_ENABLED:
                #     st.markdown("<hr>", unsafe_allow_html=True)
                #     st.markdown("**Simulate Actions**")
                #     if st.button("Simulate Increment", key=f"sim_inc_{i}"):
                #         simulate_message(i, "increment")
                #     if st.button("Simulate Decrement", key=f"sim_dec_{i}"):
                #         simulate_message(i, "decrement")
                #     if st.button("Simulate Unlock", key=f"sim_unlock_{i}"):
                #         simulate_message(i, "unlock")

            else:
                st.write("No session")
                # Display gate status
                gate_status = "Enabled"
                st.markdown(f"**Gate Status:** {gate_status}")
            st.markdown("</div>", unsafe_allow_html=True)  # Close stage background div

# Display messages
if st.session_state["messages"]:
    st.subheader("Messages")
    for msg in st.session_state["messages"]:
        st.success(msg)
    # Clear messages after displaying
    st.session_state["messages"].clear()

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
