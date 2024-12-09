import json
import threading
import time
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
from threading import Lock
import os
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide")

with open("config.json") as config_file:
    config = json.load(config_file)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
mqtt_config = config.get(ENVIRONMENT, config["development"])
MQTT_ENABLED = mqtt_config.get("ENABLED", False)
BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]

STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}

data_lock = Lock()
DATA_FILE = f"sessions_data_{ENVIRONMENT}.json"

stage_themes = {
    1: {"name": "Forest", "color": "#228B22"},
    2: {"name": "Hallway", "color": "#FFD700"},
    3: {"name": "Electricity", "color": "#1E90FF"},
    4: {"name": "Zektor", "color": "#8A2BE2"},
    5: {"name": "Pixels", "color": "#FF4500"},
    6: {"name": "Final Stage", "color": "#FF1493"},
}

mqtt_data = {
    "stage_map": {i: None for i in range(1, 7)},
    "sessions": {},
    "active_sessions": [],
    "completed_sessions": [],
    "next_session_id": 1,
}

def sync_data_to_session_state():
    with data_lock:
        st.session_state.stage_map = mqtt_data["stage_map"].copy()
        st.session_state.sessions = mqtt_data["sessions"].copy()
        st.session_state.active_sessions = mqtt_data["active_sessions"][:]
        st.session_state.completed_sessions = mqtt_data["completed_sessions"][:]
        st.session_state.next_session_id = mqtt_data["next_session_id"]

def load_data():
    try:
        with open(DATA_FILE, "r") as file:
            data = json.load(file)
            with data_lock:
                mqtt_data["stage_map"] = {int(k): v for k, v in data["stage_map"].items()}
                mqtt_data["sessions"] = data["sessions"]
                mqtt_data["active_sessions"] = data["active_sessions"]
                mqtt_data["completed_sessions"] = data["completed_sessions"]
                mqtt_data["next_session_id"] = data["next_session_id"]
    except FileNotFoundError:
        pass

def save_data():
    with data_lock:
        data = {
            "stage_map": {str(k): v for k, v in mqtt_data["stage_map"].items()},
            "sessions": mqtt_data["sessions"],
            "active_sessions": mqtt_data["active_sessions"],
            "completed_sessions": mqtt_data["completed_sessions"],
            "next_session_id": mqtt_data["next_session_id"],
        }
        with open(DATA_FILE, "w") as file:
            json.dump(data, file, indent=2)

load_data()

def load_topic_values(file_path="scores.json"):
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        st.error(f"Topic values file {file_path} not found.")
        return {}

topic_values = load_topic_values()

dynamic_topics = list(topic_values.keys())

def load_progression_rules(file_path="progression.json"):
    try:
        with open(file_path, "r") as file:
            return json.load(file)
    except FileNotFoundError:
        st.error(f"Progression rules file {file_path} not found.")
        return {}

progression_rules = load_progression_rules()

def handle_received_message(topic, payload):
    # Progression logic
    for stage, data in progression_rules["stage_progression"].items():
        if topic == data.get("trigger_topic") and payload == data.get("trigger_message"):
            with data_lock:
                session_id = mqtt_data["stage_map"].get(stage)
                if session_id:
                    next_stage = data.get("next_stage")
                    blocking_stages = progression_rules["blocking_rules"].get(stage, [])
                    for blocking_stage in blocking_stages:
                        if mqtt_data["stage_map"].get(blocking_stage):
                            return
                    mqtt_data["stage_map"][stage] = None
                    mqtt_data["stage_map"][next_stage] = session_id
                    mqtt_data["sessions"][session_id]["current_stage"] = next_stage
                    save_data()
                    sync_data_to_session_state()

    # Scoring logic
    for stg, topics in STAGE_TOPICS.items():
        if topic in topics:
            with data_lock:
                session_id = mqtt_data["stage_map"].get(stg)
                if session_id and topic in topic_values:
                    topic_score = topic_values[topic]
                    if payload == "positive":
                        increment_value = topic_score.get("positive", 0)
                        mqtt_data["sessions"][session_id]["score"] += increment_value
                    elif payload == "negative":
                        decrement_value = topic_score.get("negative", 0)
                        mqtt_data["sessions"][session_id]["score"] += decrement_value
                    save_data()
                    sync_data_to_session_state()
                    break

def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully!")
        subscribed_topics = set()
        for topics in STAGE_TOPICS.values():
            for topic in topics:
                if topic not in subscribed_topics:
                    client.subscribe(topic)
                    subscribed_topics.add(topic)
                    print(f"Subscribed to stage topic: {topic}")

        for stage, progression_data in progression_rules["stage_progression"].items():
            trigger_topic = progression_data.get("trigger_topic")
            if trigger_topic and trigger_topic not in subscribed_topics:
                client.subscribe(trigger_topic)
                subscribed_topics.add(trigger_topic)
                print(f"Subscribed to progression trigger topic: {trigger_topic}")

        for topic in topic_values.keys():
            if topic not in subscribed_topics:
                client.subscribe(topic)
                subscribed_topics.add(topic)
                print(f"Subscribed to scoring topic: {topic}")
    else:
        print(f"Connection failed with code {rc}")

def on_message(client, userdata, message):
    topic = message.topic
    payload = message.payload.decode().lower()
    print(f"Received message: topic={topic}, payload={payload}")
    handle_received_message(topic, payload)

@st.cache_resource
def init_mqtt_client():
    if MQTT_ENABLED:
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
        with data_lock:
            if mqtt_data["stage_map"][1] is not None or mqtt_data["stage_map"][2] is not None:
                st.error("Cannot start a new session until 'hallway' is cleared.")
            else:
                session_id = f"session{mqtt_data['next_session_id']}"
                mqtt_data["sessions"][session_id] = {
                    "name": session_name,
                    "current_stage": 1,
                    "score": 0,
                    "start_time": datetime.now().isoformat(),
                }
                mqtt_data["stage_map"][1] = session_id
                mqtt_data["active_sessions"].append(session_id)
                mqtt_data["next_session_id"] += 1
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
                        with data_lock:
                            mqtt_data["sessions"][session_id]["score"] -= 1
                            save_data()
                            sync_data_to_session_state()
                with score_col:
                    st.markdown(f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>", unsafe_allow_html=True)
                with btn_col2:
                    if st.button("➕", key=f"inc_{session_id}"):
                        with data_lock:
                            mqtt_data["sessions"][session_id]["score"] += 1
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
            with data_lock:
                current_stage = mqtt_data["sessions"][session_to_progress]["current_stage"]
                next_stage = current_stage + 1

                if next_stage > 6:
                    mqtt_data["stage_map"][current_stage] = None
                    mqtt_data["active_sessions"].remove(session_to_progress)
                    mqtt_data["completed_sessions"].append(session_to_progress)
                    st.success(f"Session '{session_to_progress}' has completed all stages.")
                elif mqtt_data["stage_map"].get(next_stage) is None:
                    mqtt_data["stage_map"][current_stage] = None
                    mqtt_data["stage_map"][next_stage] = session_to_progress
                    mqtt_data["sessions"][session_to_progress]["current_stage"] = next_stage
                    st.success(f"Session '{session_to_progress}' progressed to stage {next_stage}.")
                else:
                    st.error(f"Stage {next_stage} is occupied. Cannot progress session '{session_to_progress}'.")
                save_data()
                sync_data_to_session_state()
else:
    st.write("No active sessions to progress.")

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

st_autorefresh(interval=5000, key="datarefresh")
sync_data_to_session_state()
