import json
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
import os
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide")

print("Loading configuration...")
with open("config.json") as config_file:
    config = json.load(config_file)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
print(f"Environment: {ENVIRONMENT}")

mqtt_config = config.get(ENVIRONMENT, config["development"])
MQTT_ENABLED = mqtt_config.get("ENABLED", False)
BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]

STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}
print("Stage topics loaded:", STAGE_TOPICS)

DATA_FILE = f"sessions_data_{ENVIRONMENT}.json"
print(f"Data file: {DATA_FILE}")

stage_themes = {
    1: {"name": "Forest", "color": "#228B22"},
    2: {"name": "Hallway", "color": "#FFD700"},
    3: {"name": "Electricity", "color": "#1E90FF"},
    4: {"name": "Zektor", "color": "#8A2BE2"},
    5: {"name": "Pixels", "color": "#FF4500"},
    6: {"name": "Final Stage", "color": "#FF1493"},
}

@st.cache_resource
def get_shared_data():
    # This dictionary remains persistent across Streamlit reruns.
    # It contains a lock and a list for pending messages.
    from threading import Lock
    return {
        "lock": Lock(),
        "pending_messages": [],
        "mqtt_data": {
            "stage_map": {i: None for i in range(1, 7)},
            "sessions": {},
            "active_sessions": [],
            "completed_sessions": [],
            "next_session_id": 1,
        }
    }

shared_data = get_shared_data()

def sync_data_to_session_state():
    with shared_data["lock"]:
        st.session_state.stage_map = shared_data["mqtt_data"]["stage_map"].copy()
        st.session_state.sessions = shared_data["mqtt_data"]["sessions"].copy()
        st.session_state.active_sessions = shared_data["mqtt_data"]["active_sessions"][:]
        st.session_state.completed_sessions = shared_data["mqtt_data"]["completed_sessions"][:]
        st.session_state.next_session_id = shared_data["mqtt_data"]["next_session_id"]
    print("sync_data_to_session_state: updated Streamlit session state.")

def load_data():
    print("Attempting to load data from file:", DATA_FILE)
    try:
        with open(DATA_FILE, "r") as file:
            data = json.load(file)
            with shared_data["lock"]:
                shared_data["mqtt_data"]["stage_map"] = {int(k): v for k, v in data["stage_map"].items()}
                shared_data["mqtt_data"]["sessions"] = data["sessions"]
                shared_data["mqtt_data"]["active_sessions"] = data["active_sessions"]
                shared_data["mqtt_data"]["completed_sessions"] = data["completed_sessions"]
                shared_data["mqtt_data"]["next_session_id"] = data["next_session_id"]
            print("Data loaded successfully:", data)
    except FileNotFoundError:
        print("No existing data file found, starting fresh.")

def save_data():
    with shared_data["lock"]:
        data = {
            "stage_map": {str(k): v for k, v in shared_data["mqtt_data"]["stage_map"].items()},
            "sessions": shared_data["mqtt_data"]["sessions"],
            "active_sessions": shared_data["mqtt_data"]["active_sessions"],
            "completed_sessions": shared_data["mqtt_data"]["completed_sessions"],
            "next_session_id": shared_data["mqtt_data"]["next_session_id"],
        }
        with open(DATA_FILE, "w") as file:
            json.dump(data, file, indent=2)
    print("Data saved to file:", data)

load_data()

def load_topic_values(file_path="scores.json"):
    print("Loading scores from:", file_path)
    try:
        with open(file_path, "r") as file:
            tv = json.load(file)
            print("Scores loaded:", tv)
            return tv
    except FileNotFoundError:
        st.error(f"Topic values file {file_path} not found.")
        return {}

topic_values = load_topic_values()

def load_progression_rules(file_path="progression.json"):
    print("Loading progression rules from:", file_path)
    try:
        with open(file_path, "r") as file:
            pr = json.load(file)
            print("Progression rules loaded:", pr)
            return pr
    except FileNotFoundError:
        st.error(f"Progression rules file {file_path} not found.")
        return {}

progression_rules = load_progression_rules()

def process_pending_messages():
    with shared_data["lock"]:
        if not shared_data["pending_messages"]:
            print("No pending messages to process.")
            return
        local_messages = shared_data["pending_messages"][:]
        shared_data["pending_messages"].clear()

    print(f"Processing {len(local_messages)} pending messages...")
    for (topic, payload) in local_messages:
        print("Processing message:", topic, payload, repr(payload))
        handle_received_message(topic, payload)

    print("Finished processing pending messages.")
    sync_data_to_session_state()

def handle_received_message(topic, payload):
    print(f"handle_received_message called with topic={topic}, payload={payload}")

    # Check progression logic
    for stage, data in progression_rules["stage_progression"].items():
        trig_topic = data.get("trigger_topic")
        trig_message = data.get("trigger_message")
        if topic == trig_topic and payload == trig_message:
            print(f"Match progression trigger: {stage}, moving to next stage...")
            with shared_data["lock"]:
                session_id = shared_data["mqtt_data"]["stage_map"].get(stage)
                if session_id:
                    next_stage = data.get("next_stage")
                    blocking_stages = progression_rules["blocking_rules"].get(stage, [])
                    for blocking_stage in blocking_stages:
                        if shared_data["mqtt_data"]["stage_map"].get(blocking_stage):
                            print(f"Blocking stage {blocking_stage} active, cannot progress {session_id}.")
                            return
                    shared_data["mqtt_data"]["stage_map"][stage] = None
                    shared_data["mqtt_data"]["stage_map"][next_stage] = session_id
                    shared_data["mqtt_data"]["sessions"][session_id]["current_stage"] = next_stage
                    print(f"Session {session_id} progressed to {next_stage}.")
                    save_data()

    # Scoring logic
    scored = False
    for stg, topics in STAGE_TOPICS.items():
        if topic in topics:
            with shared_data["lock"]:
                session_id = shared_data["mqtt_data"]["stage_map"].get(stg)
                print(f"Found topic in stage {stg}, session_id={session_id}, topic_values keys={list(topic_values.keys())}")
                if session_id and topic in topic_values:
                    topic_score = topic_values[topic]
                    print(f"Current score for {session_id} before: {shared_data['mqtt_data']['sessions'][session_id]['score']}")
                    if payload == "positive":
                        increment_value = topic_score.get("positive", 0)
                        shared_data["mqtt_data"]["sessions"][session_id]["score"] += increment_value
                        print(f"Incremented score by {increment_value} for {session_id}")
                        scored = True
                    elif payload == "negative":
                        decrement_value = topic_score.get("negative", 0)
                        shared_data["mqtt_data"]["sessions"][session_id]["score"] += decrement_value
                        print(f"Decremented score by {decrement_value} for {session_id}")
                        scored = True
                    else:
                        print(f"Payload '{payload}' didn't match 'positive' or 'negative'.")

                    if scored:
                        print(f"New score for {session_id}: {shared_data['mqtt_data']['sessions'][session_id]['score']}")
                        save_data()
                else:
                    print(f"No session in stage {stg} or no scoring config for topic {topic}.")
            break
    if not scored:
        print("No scoring updates were made.")

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully!")
        subscribed_topics = set()
        for topics in STAGE_TOPICS.values():
            for t in topics:
                if t not in subscribed_topics:
                    client.subscribe(t)
                    subscribed_topics.add(t)
                    print(f"Subscribed to stage topic: {t}")

        for stage, progression_data in progression_rules["stage_progression"].items():
            trigger_topic = progression_data.get("trigger_topic")
            if trigger_topic and trigger_topic not in subscribed_topics:
                client.subscribe(trigger_topic)
                subscribed_topics.add(trigger_topic)
                print(f"Subscribed to progression trigger topic: {trigger_topic}")

        for t in topic_values.keys():
            if t not in subscribed_topics:
                client.subscribe(t)
                subscribed_topics.add(t)
                print(f"Subscribed to scoring topic: {t}")
    else:
        print(f"Connection failed with code {rc}")

def on_message(client, userdata, message):
    topic = message.topic
    raw_payload = message.payload
    payload = message.payload.decode().lower()
    print(f"on_message received: topic={topic}, payload={payload}, raw={raw_payload}")
    with shared_data["lock"]:
        shared_data["pending_messages"].append((topic, payload))

@st.cache_resource
def init_mqtt_client():
    if MQTT_ENABLED:
        print("Initializing MQTT client...")
        client = mqtt.Client(protocol=mqtt.MQTTv5)
        client.username_pw_set(USERNAME, PASSWORD)
        client.on_connect = on_connect
        client.on_message = on_message

        try:
            client.connect(BROKER, PORT)
            mqtt_thread = threading.Thread(target=client.loop_forever)
            mqtt_thread.daemon = True
            mqtt_thread.start()
        except Exception as e:
            st.error(f"Failed to connect to MQTT broker at {BROKER}:{PORT}: {e}")
        return client
    else:
        st.warning("MQTT is disabled. Simulating MQTT messages.")
        return None

client = init_mqtt_client()

st.title("Zektor Game Controller")
sync_data_to_session_state()

st.subheader("Start New Session")
with st.form("start_session_form"):
    session_name = st.text_input("Session Name", value=f"Session {st.session_state.next_session_id}")
    submitted = st.form_submit_button("Start Session")
    if submitted and session_name:
        with shared_data["lock"]:
            if shared_data["mqtt_data"]["stage_map"][1] is not None or shared_data["mqtt_data"]["stage_map"][2] is not None:
                st.error("Cannot start a new session until 'hallway' is cleared.")
            else:
                session_id = f"session{shared_data['mqtt_data']['next_session_id']}"
                shared_data["mqtt_data"]["sessions"][session_id] = {
                    "name": session_name,
                    "current_stage": 1,
                    "score": 0,
                    "start_time": datetime.now().isoformat(),
                }
                shared_data["mqtt_data"]["stage_map"][1] = session_id
                shared_data["mqtt_data"]["active_sessions"].append(session_id)
                shared_data["mqtt_data"]["next_session_id"] += 1
                print(f"New session started: {session_id}")
                save_data()
                st.success(f"Session '{session_name}' started in Stage 1.")
                sync_data_to_session_state()

st.subheader("Game Status")
cols = st.columns(6)

for i, col in enumerate(cols, start=1):
    with col:
        theme = stage_themes.get(i, {})
        stage_name = theme.get("name", f"Stage {i}")
        bg_color = theme.get("color", "#f0f0f0")
        col.markdown(f"<div style='background-color:{bg_color}; padding: 10px;'>", unsafe_allow_html=True)
        st.markdown(f"### {stage_name}")

        session_id = st.session_state.stage_map.get(i)
        if session_id:
            session = st.session_state.sessions[session_id]
            session_name = session.get("name", session_id)
            session_score = session["score"]

            session_card = col.container()
            with session_card:
                st.markdown(f"<h5>{session_name}</h5>", unsafe_allow_html=True)
                st.markdown(f"<p style='color: #555; margin-bottom: 0px;'>{session_id}</p>", unsafe_allow_html=True)
                st.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

                btn_col1, score_col, btn_col2 = st.columns([1, 1, 1])
                with btn_col1:
                    if st.button("➖", key=f"dec_{session_id}"):
                        with shared_data["lock"]:
                            shared_data["mqtt_data"]["sessions"][session_id]["score"] -= 1
                            print(f"Manually decremented score for {session_id}, new score: {shared_data['mqtt_data']['sessions'][session_id]['score']}")
                            save_data()
                            sync_data_to_session_state()
                with score_col:
                    st.markdown(f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>", unsafe_allow_html=True)
                with btn_col2:
                    if st.button("➕", key=f"inc_{session_id}"):
                        with shared_data["lock"]:
                            shared_data["mqtt_data"]["sessions"][session_id]["score"] += 1
                            print(f"Manually incremented score for {session_id}, new score: {shared_data['mqtt_data']['sessions'][session_id]['score']}")
                            save_data()
                            sync_data_to_session_state()
        else:
            st.write("No session")
        st.markdown("</div>", unsafe_allow_html=True)

if "messages" in st.session_state and st.session_state["messages"]:
    st.subheader("Messages")
    for msg in st.session_state["messages"]:
        st.success(msg)
    st.session_state["messages"].clear()

st.subheader("Progress Sessions")

if st.session_state.active_sessions:
    with st.form("progress_form"):
        session_to_progress = st.selectbox("Select Session to Progress", options=st.session_state.active_sessions)
        submitted = st.form_submit_button("Progress Session")
        if submitted and session_to_progress:
            with shared_data["lock"]:
                current_stage = shared_data["mqtt_data"]["sessions"][session_to_progress]["current_stage"]
                next_stage = current_stage + 1
                print(f"Attempting to progress {session_to_progress} from {current_stage} to {next_stage}...")

                if next_stage > 6:
                    shared_data["mqtt_data"]["stage_map"][current_stage] = None
                    shared_data["mqtt_data"]["active_sessions"].remove(session_to_progress)
                    shared_data["mqtt_data"]["completed_sessions"].append(session_to_progress)
                    print(f"Session {session_to_progress} completed all stages.")
                    st.success(f"Session '{session_to_progress}' has completed all stages.")
                elif shared_data["mqtt_data"]["stage_map"].get(next_stage) is None:
                    shared_data["mqtt_data"]["stage_map"][current_stage] = None
                    shared_data["mqtt_data"]["stage_map"][next_stage] = session_to_progress
                    shared_data["mqtt_data"]["sessions"][session_to_progress]["current_stage"] = next_stage
                    print(f"Session {session_to_progress} progressed to stage {next_stage}.")
                    st.success(f"Session '{session_to_progress}' progressed to stage {next_stage}.")
                else:
                    print(f"Stage {next_stage} is occupied, cannot progress {session_to_progress}.")
                    st.error(f"Stage {next_stage} is occupied. Cannot progress session '{session_to_progress}'.")
                save_data()
                sync_data_to_session_state()
else:
    st.write("No active sessions to progress.")

st.subheader("Sessions Summary")
st.write("**Active Sessions:**")
if st.session_state.active_sessions:
    active_sessions_data = {
        s_id: st.session_state.sessions[s_id]
        for s_id in st.session_state.active_sessions
    }
    st.json(active_sessions_data)
else:
    st.write("No active sessions.")

st.write("**Completed Sessions:**")
if st.session_state.completed_sessions:
    completed_sessions_data = {
        s_id: st.session_state.sessions[s_id]
        for s_id in st.session_state.completed_sessions
    }
    st.json(completed_sessions_data)
else:
    st.write("No completed sessions.")

print("Running autorefresh...")
st_autorefresh(interval=5000, key="datarefresh")

# Process pending messages in the main thread
process_pending_messages()

sync_data_to_session_state()
print("End of main script execution cycle.")
