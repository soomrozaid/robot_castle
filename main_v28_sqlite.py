import json
import threading
import paho.mqtt.client as mqtt
import streamlit as st
from datetime import datetime
import os
import sqlite3
from contextlib import contextmanager
from streamlit_autorefresh import st_autorefresh

st.set_page_config(layout="wide")

@st.cache_resource
def load_config():
    with open("config.json") as f:
        return json.load(f)

config = load_config()
ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
mqtt_config = config.get(ENVIRONMENT, config["development"])
MQTT_ENABLED = mqtt_config.get("ENABLED", False)
BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]

STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}

DB_FILE = f"sessions_data_{ENVIRONMENT}.db"

@st.cache_resource
def load_static_data():
    with open("scores.json") as f:
        topic_values = json.load(f)
    with open("progression.json") as f:
        progression_rules = json.load(f)
    return topic_values, progression_rules

topic_values, progression_rules = load_static_data()

@contextmanager
def get_db():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

def init_db():
    with get_db() as conn:
        cursor = conn.cursor()
        
        # Stage map table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS stage_map (
                stage_number INTEGER PRIMARY KEY,
                session_id TEXT
            )
        """)
        
        # Sessions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS sessions (
                session_id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                current_stage INTEGER NOT NULL,
                score INTEGER NOT NULL DEFAULT 0,
                start_time TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'active'
            )
        """)
        
        # Config table for next_session_id
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS config (
                key TEXT PRIMARY KEY,
                value INTEGER
            )
        """)
        
        # Initialize stage map if empty
        cursor.execute("SELECT COUNT(*) FROM stage_map")
        if cursor.fetchone()[0] == 0:
            for i in range(1, 7):
                cursor.execute("INSERT INTO stage_map (stage_number, session_id) VALUES (?, NULL)", (i,))
        
        # Initialize next_session_id if empty
        cursor.execute("SELECT value FROM config WHERE key = 'next_session_id'")
        if cursor.fetchone() is None:
            cursor.execute("INSERT INTO config (key, value) VALUES ('next_session_id', 1)")
        
        conn.commit()

init_db()

# A global structure for pending messages
@st.cache_resource
def get_message_queue():
    return {
        "lock": threading.Lock(),
        "pending_messages": []
    }

message_queue = get_message_queue()

def get_stage_map():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT stage_number, session_id FROM stage_map")
        return {row['stage_number']: row['session_id'] for row in cursor.fetchall()}

def get_session(session_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions WHERE session_id = ?", (session_id,))
        row = cursor.fetchone()
        if row:
            return dict(row)
        return None

def get_all_sessions():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM sessions")
        return {row['session_id']: dict(row) for row in cursor.fetchall()}

def get_active_sessions():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id FROM sessions WHERE status = 'active'")
        return [row['session_id'] for row in cursor.fetchall()]

def get_completed_sessions():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT session_id FROM sessions WHERE status = 'completed'")
        return [row['session_id'] for row in cursor.fetchall()]

def get_next_session_id():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM config WHERE key = 'next_session_id'")
        return cursor.fetchone()['value']

def increment_next_session_id():
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE config SET value = value + 1 WHERE key = 'next_session_id'")
        conn.commit()

def update_stage_map(stage_number, session_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE stage_map SET session_id = ? WHERE stage_number = ?", (session_id, stage_number))
        conn.commit()

def update_session_stage(session_id, new_stage):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET current_stage = ? WHERE session_id = ?", (new_stage, session_id))
        conn.commit()

def update_session_score(session_id, score_change):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET score = score + ? WHERE session_id = ?", (score_change, session_id))
        conn.commit()

def set_session_score(session_id, score):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET score = ? WHERE session_id = ?", (score, session_id))
        conn.commit()

def complete_session(session_id):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE sessions SET status = 'completed' WHERE session_id = ?", (session_id,))
        conn.commit()

def create_session(session_id, name, current_stage, score, start_time):
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO sessions (session_id, name, current_stage, score, start_time, status)
            VALUES (?, ?, ?, ?, ?, 'active')
        """, (session_id, name, current_stage, score, start_time))
        conn.commit()

def handle_received_message(topic, payload):
    stage_name_to_int = {
        "forest": 1,
        "hallway": 2,
        "electricity": 3,
        "zektor": 4,
        "pixels": 5,
        "final": 6
    }

    # Handle progression logic
    for stage_name, data in progression_rules["stage_progression"].items():
        trig_topic = data.get("trigger_topic")
        trig_message = data.get("trigger_message")
        if trig_topic and trig_message and topic == trig_topic and payload == trig_message:
            current_stage = stage_name_to_int[stage_name]
            stage_map = get_stage_map()
            session_id = stage_map.get(current_stage)
            
            if session_id:
                next_stage_name = data.get("next_stage")
                if next_stage_name:
                    next_stage = stage_name_to_int[next_stage_name]

                    # Check blocking rules
                    blocking_stages = progression_rules["blocking_rules"].get(stage_name, [])
                    blocked = False
                    for blocking_stage_name in blocking_stages:
                        blocking_stage = stage_name_to_int[blocking_stage_name]
                        if stage_map.get(blocking_stage):
                            blocked = True
                            break
                    
                    if not blocked:
                        # Progress the session
                        update_stage_map(current_stage, None)
                        update_stage_map(next_stage, session_id)
                        update_session_stage(session_id, next_stage)
            break

    # Handle scoring logic
    for stg, topics in STAGE_TOPICS.items():
        if topic in topics:
            stage_map = get_stage_map()
            session_id = stage_map.get(stg)
            if session_id and topic in topic_values:
                score_data = topic_values[topic]
                if payload == "positive":
                    increment_value = score_data.get("positive", 0)
                    update_session_score(session_id, increment_value)
                elif payload == "negative":
                    decrement_value = score_data.get("negative", 0)
                    update_session_score(session_id, decrement_value)
            break

def process_pending_messages():
    with message_queue["lock"]:
        if not message_queue["pending_messages"]:
            return
        local_messages = message_queue["pending_messages"][:]
        message_queue["pending_messages"].clear()

    for (topic, payload) in local_messages:
        handle_received_message(topic, payload)

# MQTT callbacks
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully, subscribing to topics...")
        subscribed = set()
        
        for topics in STAGE_TOPICS.values():
            for t in topics:
                if t not in subscribed:
                    client.subscribe(t)
                    subscribed.add(t)
                    print("Subscribed to stage topic:", t)

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
    with message_queue["lock"]:
        message_queue["pending_messages"].append((message.topic, payload))

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
        st.warning("MQTT disabled, simulating no messages.")
        return None

client = init_mqtt_client()

process_pending_messages()

# Build UI
st.title("Zektor Game Controller")

st.subheader("Start New Session")
with st.form("start_session_form"):
    next_id = get_next_session_id()
    session_name = st.text_input("Session Name", value=f"Session {next_id}")
    submitted = st.form_submit_button("Start Session")
    if submitted and session_name:
        stage_map = get_stage_map()
        if stage_map[1] is not None or stage_map[2] is not None:
            st.error("Cannot start a new session until 'hallway' is cleared.")
        else:
            session_id = f"session{next_id}"
            create_session(session_id, session_name, 1, 0, datetime.now().isoformat())
            update_stage_map(1, session_id)
            increment_next_session_id()
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

stage_map = get_stage_map()

for i, col in enumerate(cols, start=1):
    theme = stage_themes.get(i, {})
    stage_name = theme.get("name", f"Stage {i}")
    bg_color = theme.get("color", "#f0f0f0")

    col.markdown(f"<div style='background-color:{bg_color}; padding: 10px;'>", unsafe_allow_html=True)
    col.markdown(f"### {stage_name}")

    session_id = stage_map.get(i)

    if session_id:
        session = get_session(session_id)
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
                    update_session_score(session_id, -1)
            with score_col:
                st.markdown(f"<p style='text-align:center; font-size:24px; margin: 0;'>{session_score}</p>", unsafe_allow_html=True)
            with btn_col2:
                if st.button("➕", key=f"inc_{session_id}"):
                    update_session_score(session_id, 1)
    else:
        col.write("No session")

    col.markdown("</div>", unsafe_allow_html=True)

st.subheader("Progress Sessions")

active_sessions = get_active_sessions()

if active_sessions:
    with st.form("progress_form"):
        session_to_progress = st.selectbox("Select Session to Progress", options=active_sessions)
        submitted = st.form_submit_button("Progress Session")
        if submitted and session_to_progress:
            session = get_session(session_to_progress)
            current_stage = session["current_stage"]
            next_stage = current_stage + 1

            if next_stage > 6:
                update_stage_map(current_stage, None)
                complete_session(session_to_progress)
                st.success(f"Session '{session_to_progress}' has completed all stages.")
            else:
                stage_map = get_stage_map()
                if stage_map.get(next_stage) is None:
                    update_stage_map(current_stage, None)
                    update_stage_map(next_stage, session_to_progress)
                    update_session_stage(session_to_progress, next_stage)
                    st.success(f"Session '{session_to_progress}' progressed to stage {next_stage}.")
                else:
                    st.error(f"Stage {next_stage} is occupied. Cannot progress session '{session_to_progress}'.")
else:
    st.write("No active sessions to progress.")

st.subheader("Sessions Summary")
st.write("**Active Sessions:**")
active_sessions = get_active_sessions()
if active_sessions:
    active_sessions_data = {s_id: get_session(s_id) for s_id in active_sessions}
    st.json(active_sessions_data)
else:
    st.write("No active sessions.")

st.write("**Completed Sessions:**")
completed_sessions = get_completed_sessions()
if completed_sessions:
    completed_sessions_data = {s_id: get_session(s_id) for s_id in completed_sessions}
    st.json(completed_sessions_data)
else:
    st.write("No completed sessions.")

st_autorefresh(interval=5000, key="datarefresh")
