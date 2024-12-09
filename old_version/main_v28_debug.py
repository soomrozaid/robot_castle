import json
import threading
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
import os
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide")

@st.cache_resource
def load_config():
    print("Loading config...")
    with open("config.json") as f:
        return json.load(f)

config = load_config()
ENVIRONMENT = os.getenv("ENVIRONMENT", "production")
print(f"ENVIRONMENT: {ENVIRONMENT}")

mqtt_config = config.get(ENVIRONMENT, config["production"])
MQTT_ENABLED = mqtt_config.get("ENABLED", False)
BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]

print("MQTT Enabled:", MQTT_ENABLED)
print("Broker:", BROKER, "Port:", PORT)

STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}
print("STAGE_TOPICS:", STAGE_TOPICS)

DATA_FILE = f"sessions_data_{ENVIRONMENT}.json"
print("DATA_FILE:", DATA_FILE)

@st.cache_resource
def load_static_data():
    print("Loading scores and progression rules...")
    with open("scores.json") as f:
        topic_values = json.load(f)
    with open("progression.json") as f:
        progression_rules = json.load(f)
    print("Scores loaded:", topic_values)
    print("Progression rules loaded:", progression_rules)
    return topic_values, progression_rules

topic_values, progression_rules = load_static_data()

# A global structure for pending messages
@st.cache_resource
def get_message_queue():
    print("Initializing message_queue...")
    return {
        "lock": threading.Lock(),
        "pending_messages": []
    }

message_queue = get_message_queue()

# Initialize persistent data in session state if not present
if "mqtt_data" not in st.session_state:
    print("Initializing mqtt_data in session_state")
    st.session_state.mqtt_data = {
        "stage_map": {i: None for i in range(1, 7)},
        "sessions": {},
        "active_sessions": [],
        "completed_sessions": [],
        "next_session_id": 1,
    }
else:
    print("mqtt_data already initialized in session_state")

def load_data():
    print("Attempting to load existing sessions data...")
    try:
        with open(DATA_FILE, "r") as file:
            data = json.load(file)
            st.session_state.mqtt_data["stage_map"] = {int(k): v for k, v in data["stage_map"].items()}
            st.session_state.mqtt_data["sessions"] = data["sessions"]
            st.session_state.mqtt_data["active_sessions"] = data["active_sessions"]
            st.session_state.mqtt_data["completed_sessions"] = data["completed_sessions"]
            st.session_state.mqtt_data["next_session_id"] = data["next_session_id"]
        print("Data loaded from file:", data)
    except FileNotFoundError:
        print("No existing data file found, starting fresh.")

def save_data():
    data = {
        "stage_map": {str(k): v for k, v in st.session_state.mqtt_data["stage_map"].items()},
        "sessions": st.session_state.mqtt_data["sessions"],
        "active_sessions": st.session_state.mqtt_data["active_sessions"],
        "completed_sessions": st.session_state.mqtt_data["completed_sessions"],
        "next_session_id": st.session_state.mqtt_data["next_session_id"],
    }
    with open(DATA_FILE, "w") as file:
        json.dump(data, file, indent=2)
    print("Data saved:", data)

load_data()

def handle_received_message(topic, payload):
    print(f"handle_received_message called with topic={topic}, payload={payload}")
    stage_name_to_int = {
        "forest": 1,
        "hallway": 2,
        "electricity": 3,
        "zektor": 4,
        "pixels": 5,
        "final": 6
    }

    # Progression logic
    for stage_name, data in progression_rules["stage_progression"].items():
        trig_topic = data.get("trigger_topic")
        trig_message = data.get("trigger_message")
        if trig_topic and trig_message and topic == trig_topic and payload == trig_message:
            print(f"Progression trigger matched: {stage_name}, topic={topic}, payload={payload}")
            current_stage = stage_name_to_int[stage_name]
            session_id = st.session_state.mqtt_data["stage_map"].get(current_stage)
            print(f"Current stage int: {current_stage}, session_id={session_id}")
            if session_id:
                next_stage_name = data.get("next_stage")
                print(f"Next stage name: {next_stage_name}")
                if next_stage_name:
                    next_stage = stage_name_to_int[next_stage_name]
                    blocking_stages = progression_rules["blocking_rules"].get(stage_name, [])
                    print(f"Blocking stages for {stage_name}: {blocking_stages}")
                    blocked = False
                    for blocking_stage_name in blocking_stages:
                        blocking_stage = stage_name_to_int[blocking_stage_name]
                        if st.session_state.mqtt_data["stage_map"].get(blocking_stage):
                            print(f"Blocked by stage {blocking_stage_name} (stage {blocking_stage})")
                            blocked = True
                            break
                    if not blocked:
                        print(f"Progressing session {session_id} from stage {current_stage} to {next_stage}")
                        st.session_state.mqtt_data["stage_map"][current_stage] = None
                        st.session_state.mqtt_data["stage_map"][next_stage] = session_id
                        st.session_state.mqtt_data["sessions"][session_id]["current_stage"] = next_stage
                        save_data()
            # Stop checking progression once matched
            break

    # Scoring logic
    for stg, topics in STAGE_TOPICS.items():
        if topic in topics:
            session_id = st.session_state.mqtt_data["stage_map"].get(stg)
            print(f"Scoring logic: topic={topic}, stage={stg}, session_id={session_id}")
            if session_id and topic in topic_values:
                score_data = topic_values[topic]
                old_score = st.session_state.mqtt_data["sessions"][session_id]["score"]
                if payload == "positive":
                    increment_value = score_data.get("positive", 0)
                    st.session_state.mqtt_data["sessions"][session_id]["score"] += increment_value
                    print(f"Incremented score of {session_id} by {increment_value}, old_score={old_score}, new_score={st.session_state.mqtt_data['sessions'][session_id]['score']}")
                elif payload == "negative":
                    decrement_value = score_data.get("negative", 0)
                    st.session_state.mqtt_data["sessions"][session_id]["score"] += decrement_value
                    print(f"Decremented score of {session_id} by {decrement_value}, old_score={old_score}, new_score={st.session_state.mqtt_data['sessions'][session_id]['score']}")
                save_data()
            break

def process_pending_messages():
    with message_queue["lock"]:
        if not message_queue["pending_messages"]:
            print("No pending messages to process.")
            return
        local_messages = message_queue["pending_messages"][:]
        message_queue["pending_messages"].clear()

    print(f"Processing {len(local_messages)} pending messages...")
    for (topic, payload) in local_messages:
        print("Processing message:", topic, payload)
        handle_received_message(topic, payload)
    print("Finished processing pending messages.")

def on_connect(client, userdata, flags, rc, properties=None):
    print("on_connect called, rc=", rc)
    if rc == 0:
        print("Connected successfully, subscribing to topics...")
        subscribed = set()
        
        # Subscribe to stage topics
        for topics in STAGE_TOPICS.values():
            for t in topics:
                if t not in subscribed:
                    client.subscribe(t)
                    subscribed.add(t)
                    print("Subscribed to stage topic:", t)

        # Subscribe to progression trigger topics
        for stage_name, data in progression_rules["stage_progression"].items():
            trigger_topic = data.get("trigger_topic")
            if trigger_topic and trigger_topic not in subscribed:
                client.subscribe(trigger_topic)
                subscribed.add(trigger_topic)
                print("Subscribed to progression trigger topic:", trigger_topic)

    else:
        print("Connection failed with code", rc)


def on_message(client, userdata, message):
    payload = message.payload.decode().lower()
    print(f"on_message received: topic={message.topic}, payload={payload}")
    with message_queue["lock"]:
        message_queue["pending_messages"].append((message.topic, payload))
    print("Message appended to pending_messages")

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
        print("MQTT disabled, simulating no messages.")
        return None

client = init_mqtt_client()

# Process any pending messages right at start of run
print("Processing pending messages at start...")
process_pending_messages()

# Build UI
st.title("Zektor Game Controller")

print("Building UI...")

st.subheader("Start New Session")
with st.form("start_session_form"):
    session_name = st.text_input("Session Name", value=f"Session {st.session_state.mqtt_data['next_session_id']}")
    submitted = st.form_submit_button("Start Session")
    if submitted and session_name:
        print("Starting new session:", session_name)
        if st.session_state.mqtt_data["stage_map"][1] is not None or st.session_state.mqtt_data["stage_map"][2] is not None:
            print("Cannot start session, hallway not cleared.")
            st.error("Cannot start a new session until 'hallway' is cleared.")
        else:
            session_id = f"session{st.session_state.mqtt_data['next_session_id']}"
            st.session_state.mqtt_data["sessions"][session_id] = {
                "name": session_name,
                "current_stage": 1,
                "score": 0,
                "start_time": datetime.now().isoformat(),
            }
            st.session_state.mqtt_data["stage_map"][1] = session_id
            st.session_state.mqtt_data["active_sessions"].append(session_id)
            st.session_state.mqtt_data["next_session_id"] += 1
            save_data()
            st.success(f"Session '{session_name}' started in Stage 1.")

st.subheader("Game Status")
cols = st.columns(6)

stage_themes = {
    1: {"name": "Forest", "color": "#228B22"},
    2: {"name": "Hallway", "color": "#FFD700"},
    3: {"name": "Electricity", "color": "#1E90FF"},
    4: {"name": "Zektor", "color": "#8A2BE2"},
    5: {"name": "Pixels", "color": "#FF4500"},
    6: {"name": "Final Stage", "color": "#FF1493"},
}

for i, col in enumerate(cols, start=1):
    theme = stage_themes.get(i, {})
    stage_name = theme.get("name", f"Stage {i}")
    bg_color = theme.get("color", "#f0f0f0")

    col.markdown(f"<div style='background-color:{bg_color}; padding: 10px;'>", unsafe_allow_html=True)
    col.markdown(f"### {stage_name}")

    session_id = st.session_state.mqtt_data["stage_map"].get(i)

    if session_id:
        session = st.session_state.mqtt_data["sessions"][session_id]
        session_name = session.get("name", session_id)
        session_score = session["score"]

        session_card = col.container()
        with session_card:
            col.markdown(f"<h5>{session_name}</h5>", unsafe_allow_html=True)
            col.markdown(f"<p style='color: #555; margin-bottom: 0px;'>{session_id}</p>", unsafe_allow_html=True)
            col.markdown("<hr style='margin: 15px 0;'>", unsafe_allow_html=True)

            btn_col1, score_col, btn_col2 = col.columns([1,1,1])
            with btn_col1:
                if st.button("➖", key=f"dec_{session_id}"):
                    old_score = session["score"]
                    session["score"] -= 1
                    print(f"Manual decrement score for {session_id} from {old_score} to {session['score']}")
                    save_data()
            with score_col:
                col.markdown(f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>", unsafe_allow_html=True)
            with btn_col2:
                if st.button("➕", key=f"inc_{session_id}"):
                    old_score = session["score"]
                    session["score"] += 1
                    print(f"Manual increment score for {session_id} from {old_score} to {session['score']}")
                    save_data()

    else:
        col.write("No session")

    col.markdown("</div>", unsafe_allow_html=True)

st.subheader("Progress Sessions")

if st.session_state.mqtt_data["active_sessions"]:
    with st.form("progress_form"):
        session_to_progress = st.selectbox("Select Session to Progress", options=st.session_state.mqtt_data["active_sessions"])
        submitted = st.form_submit_button("Progress Session")
        if submitted and session_to_progress:
            current_stage = st.session_state.mqtt_data["sessions"][session_to_progress]["current_stage"]
            next_stage = current_stage + 1
            print(f"Manually progressing {session_to_progress} from {current_stage} to {next_stage}")

            if next_stage > 6:
                st.session_state.mqtt_data["stage_map"][current_stage] = None
                st.session_state.mqtt_data["active_sessions"].remove(session_to_progress)
                st.session_state.mqtt_data["completed_sessions"].append(session_to_progress)
                print(f"{session_to_progress} completed all stages.")
                st.success(f"Session '{session_to_progress}' has completed all stages.")
            elif st.session_state.mqtt_data["stage_map"].get(next_stage) is None:
                st.session_state.mqtt_data["stage_map"][current_stage] = None
                st.session_state.mqtt_data["stage_map"][next_stage] = session_to_progress
                st.session_state.mqtt_data["sessions"][session_to_progress]["current_stage"] = next_stage
                print(f"{session_to_progress} progressed to stage {next_stage}")
                st.success(f"Session '{session_to_progress}' progressed to stage {next_stage}.")
            else:
                print(f"Cannot progress {session_to_progress}, next_stage={next_stage} occupied.")
                st.error(f"Stage {next_stage} is occupied. Cannot progress session '{session_to_progress}'.")
            save_data()
else:
    st.write("No active sessions to progress.")

st.subheader("Sessions Summary")
st.write("**Active Sessions:**")
if st.session_state.mqtt_data["active_sessions"]:
    active_sessions_data = {
        s_id: st.session_state.mqtt_data["sessions"][s_id]
        for s_id in st.session_state.mqtt_data["active_sessions"]
    }
    st.json(active_sessions_data)
else:
    st.write("No active sessions.")

st.write("**Completed Sessions:**")
if st.session_state.mqtt_data["completed_sessions"]:
    completed_sessions_data = {
        s_id: st.session_state.mqtt_data["sessions"][s_id]
        for s_id in st.session_state.mqtt_data["completed_sessions"]
    }
    st.json(completed_sessions_data)
else:
    st.write("No completed sessions.")

print("Setting up autorefresh...")
st_autorefresh(interval=5000, key="datarefresh")
print("End of script execution cycle.")
