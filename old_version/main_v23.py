import json
import threading
from queue import Queue
import os
from flask import Flask, jsonify, request, render_template
import paho.mqtt.client as mqtt
from datetime import datetime

# Flask application
app = Flask(__name__)

# MQTT configurations
with open("config.json") as config_file:
    config = json.load(config_file)

ENVIRONMENT = os.getenv("ENVIRONMENT", "development")
mqtt_config = config.get(ENVIRONMENT, config["development"])
BROKER = mqtt_config["BROKER"]
PORT = mqtt_config["PORT"]
USERNAME = mqtt_config["USERNAME"]
PASSWORD = mqtt_config["PASSWORD"]
MQTT_ENABLED = mqtt_config.get("ENABLED", False)

STAGE_TOPICS = {int(k): v for k, v in mqtt_config["STAGE_TOPICS"].items()}

# Scoring and progression rules
topic_values = json.load(open("scores.json", "r"))
progression_rules = json.load(open("progression.json", "r"))

# Thread-safe data structures
data_lock = threading.Lock()
message_queue = Queue()
mqtt_data = {
    "stage_map": {i: None for i in range(1, 7)},  # Stages 1-6
    "sessions": {},
    "active_sessions": [],
    "completed_sessions": [],
    "next_session_id": 1,
}

# MQTT client
client = None


# MQTT callbacks
def on_connect(client, userdata, flags, rc):
    if rc == 0:
        print("Connected to MQTT broker!")
        subscribed_topics = set()

        # Subscribe to topics
        for topics in STAGE_TOPICS.values():
            for topic in topics:
                if topic not in subscribed_topics:
                    client.subscribe(topic)
                    subscribed_topics.add(topic)
                    print(f"Subscribed to stage topic: {topic}")

        for stage, data in progression_rules["stage_progression"].items():
            trigger_topic = data.get("trigger_topic")
            if trigger_topic and trigger_topic not in subscribed_topics:
                client.subscribe(trigger_topic)
                subscribed_topics.add(trigger_topic)
                print(f"Subscribed to progression topic: {trigger_topic}")

        for topic in topic_values.keys():
            if topic not in subscribed_topics:
                client.subscribe(topic)
                subscribed_topics.add(topic)
                print(f"Subscribed to scoring topic: {topic}")
    else:
        print(f"Failed to connect to MQTT broker. Code: {rc}")


def on_message(client, userdata, message):
    topic = message.topic
    payload = message.payload.decode().lower()
    message_queue.put((topic, payload))
    print(f"Added to queue: topic={topic}, payload={payload}")


def init_mqtt_client():
    global client
    if MQTT_ENABLED:
        client = mqtt.Client()
        client.username_pw_set(USERNAME, PASSWORD)
        client.on_connect = on_connect
        client.on_message = on_message
        client.connect(BROKER, PORT)
        threading.Thread(target=client.loop_forever, daemon=True).start()
        print("MQTT client initialized.")
    else:
        print("MQTT is disabled.")


# Background thread to process the message queue
def process_message_queue():
    while True:
        while not message_queue.empty():
            topic, payload = message_queue.get()
            print(f"Processing: topic={topic}, payload={payload}")

            # Progression logic
            for stage, data in progression_rules["stage_progression"].items():
                if topic == data["trigger_topic"] and payload == data["trigger_message"]:
                    with data_lock:
                        session_id = mqtt_data["stage_map"].get(stage)
                        if session_id:
                            next_stage = data["next_stage"]
                            blocking_stages = progression_rules["blocking_rules"].get(stage, [])
                            for blocking_stage in blocking_stages:
                                if mqtt_data["stage_map"].get(blocking_stage):
                                    print(f"Cannot progress session '{session_id}' due to blocking stage.")
                                    return
                            mqtt_data["stage_map"][stage] = None
                            mqtt_data["stage_map"][next_stage] = session_id
                            mqtt_data["sessions"][session_id]["current_stage"] = next_stage
                            print(f"Session '{session_id}' progressed to stage {next_stage}.")
                            return

            # Scoring logic
            for stage, topics in STAGE_TOPICS.items():
                if topic in topics:
                    with data_lock:
                        session_id = mqtt_data["stage_map"].get(stage)
                        if session_id:
                            if topic in topic_values:
                                score_change = topic_values[topic].get(payload, 0)
                                mqtt_data["sessions"][session_id]["score"] += score_change
                                print(f"Updated score for session {session_id}: {score_change}")


# Flask routes
@app.route("/")
def index():
    return render_template("index.html")


@app.route("/sessions", methods=["GET"])
def get_sessions():
    with data_lock:
        return jsonify({
            "active_sessions": mqtt_data["active_sessions"],
            "completed_sessions": mqtt_data["completed_sessions"],
            "next_session_id": mqtt_data["next_session_id"],
        })


@app.route("/start_session", methods=["POST"])
def start_session():
    session_name = request.json.get("session_name")
    with data_lock:
        if mqtt_data["stage_map"][1] is not None:
            return jsonify({"error": "Hallway is occupied!"}), 400
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
    return jsonify({"success": True, "session_id": session_id})


@app.route("/status", methods=["GET"])
def get_status():
    with data_lock:
        return jsonify(mqtt_data)


# Start Flask app and MQTT
if __name__ == "__main__":
    init_mqtt_client()
    threading.Thread(target=process_message_queue, daemon=True).start()
    app.run(host="0.0.0.0", port=5500)
