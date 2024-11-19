import json
import threading
import paho.mqtt.client as mqtt

# Define broker details
BROKER = "homeassistant.local"  # Replace with your broker IP
PORT = 1883
USERNAME = "zektor"  # Replace with your MQTT username
PASSWORD = "command"  # Replace with your MQTT password
FOREST_TOPIC = "forest/activity"  # Example topic


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


# Callback for when the client connects
def on_connect(client, userdata, flags, rc, properties=None):
    print("Connecting...")
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

    print(f"Received message: {message.payload.decode()} on topic {message.topic}")


# Initialize MQTT client
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


def start_session():
    """Start a new session by placing it in Stage 1 if available."""
    global next_session_id
    session_id = f"session{next_session_id}"
    if stage_map[1] is not None:
        return f"Stage 1 is occupied by {stage_map[1]}. Cannot start a new session."
    sessions[session_id] = {"current_stage": 1, "score": 0}
    stage_map[1] = session_id
    active_sessions.append(session_id)
    next_session_id += 1
    return f"Session {session_id} started in Stage 1."


def progress_session(session_id):
    """Progress a specific session to the next stage if possible."""
    if session_id not in sessions:
        return f"Session {session_id} does not exist."
    if session_id not in active_sessions:
        return (
            f"Session {session_id} is not active or has already completed all stages."
        )

    current_stage = sessions[session_id]["current_stage"]
    next_stage = current_stage + 1

    if next_stage > 6:
        # Move session to completed
        stage_map[current_stage] = None
        active_sessions.remove(session_id)
        completed_sessions.append(session_id)
        return f"Session {session_id} has completed all stages."

    if stage_map[next_stage] is not None:
        return f"Stage {next_stage} is occupied by {stage_map[next_stage]}. Cannot progress Session {session_id}."

    # Progress the session
    stage_map[current_stage] = None
    stage_map[next_stage] = session_id
    sessions[session_id]["current_stage"] = next_stage
    return f"Session {session_id} progressed to Stage {next_stage}."


def update_score(session_id, score_change):
    """Update the score for a session."""
    if session_id not in sessions:
        return f"Session {session_id} does not exist."
    sessions[session_id]["score"] += score_change
    return f"Session {session_id}'s score updated to {sessions[session_id]['score']}."


def get_status():
    """Get the current status of all stages, active sessions, and completed sessions."""
    return {
        "stage_map": stage_map,
        "active_sessions": active_sessions,
        "completed_sessions": completed_sessions,
        "sessions": sessions,
    }


def handle_command(command):
    """Handle commands from the terminal."""
    global next_session_id
    parts = command.strip().split()
    action = parts[0].lower()

    if action == "start":
        return start_session()
    elif action == "progress":
        if len(parts) < 2:
            return "Invalid command. Use: progress <session_id>"
        session_id = parts[1]
        return progress_session(session_id)
    elif action == "update_score":
        if len(parts) < 3:
            return "Invalid command. Use: update_score <session_id> <score_change>"
        session_id = parts[1]
        try:
            score_change = int(parts[2])
            return update_score(session_id, score_change)
        except ValueError:
            return "Invalid score_change value. Must be an integer."
    elif action == "status":
        return json.dumps(get_status(), indent=2)
    elif action == "exit":
        return "exit"
    else:
        return f"Unknown command: {action}"


if __name__ == "__main__":
    print("Escape Room Game Controller")
    print(
        "Type 'start' to start a session, 'progress <session_id>' to progress a session,"
    )
    print(
        "'update_score <session_id> <score_change>' to update a score, 'status' for status, and 'exit' to quit."
    )
    print()

    while True:
        command = input("Enter command: ")
        result = handle_command(command)
        if result == "exit":
            print("Exiting program.")
            break
        print(result)
