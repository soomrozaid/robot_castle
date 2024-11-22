# Zektor Game Controller

Welcome to the Zektor Game Controller! This application is designed to manage and monitor sessions for the Zektor escape room game. It allows game masters to start new sessions, track progress through different stages, adjust scores, and view active and completed sessions—all through a user-friendly interface.

## Screenshots:

### Dashboard
![Zektor Dashboard](<Screenshot 2024-11-22 at 2.44.26 AM.png>)

### Game Control (Progress Groups through Games)
![Progress Group](<Screenshot 2024-11-22 at 2.44.48 AM.png>)

### Session Summary
![Session Summary](<Screenshot 2024-11-22 at 2.45.00 AM.png>)

## Table of Contents

- [Overview]()
- [Installation]()
- [Running the Application]()
- [How It Works]()
- [Configuration]()
- [Data Persistence]()

## Overview

The Zektor Game Controller is a web-based tool that helps manage escape room sessions. It provides the following features:

- __Start New Sessions:__ Begin a new game session and place it in the first stage if available.
- __Progress Sessions:__ Move sessions through different stages as players advance in the game.
- __Score Management:__ Adjust the score for each session with simple increment and decrement buttons.
- __Session Monitoring:__ View active sessions, completed sessions, and their details in real-time.
- __Stage Visualization:__ See which sessions are in which stages with color-coded displays.

## Installation

Follow these steps to set up the application:

1. Clone the Repository:
```bash
  git clone https://github.com/yourusername/zektor-game-controller.git
  cd zektor-game-controller
```
2. Create a Virtual Environment (Optional but Recommended):
```bash
python -m venv venv
```
3. Activate the Virtual Environment:
  - On Windows:
    ```bash
    venv\Scripts\activate
    ```
  - On macOS and Linux:
    ```bash
    source venv/bin/activate
    ```
4. Install the Required Dependencies:
Make sure you have Python installed (version 3.7 or higher).

```bash
pip install -r requirements.txt
```

## Running the Application

1. Ensure Configuration Files are in Place:

  - `config.json`: Contains settings for connecting to the MQTT broker.
  - `sessions_data.json`: Stores session data persistently (automatically created if not present).
2. Start the Streamlit Application:

  ```bash
  streamlit run main_v13.py
  ```
3. Access the Application:
  
    Open your web browser and navigate to the URL provided by Streamlit (usually `http://localhost:8501`).

## How It Works

The Zektor Game Controller provides an interactive dashboard for managing escape room sessions. Here's a simple overview:

- User Interface:
  - Start New Session: Enter a session name to begin a new game. The session is placed in Stage 1 if it's available.
  - Game Status: Visual representation of stages and sessions. Each stage is color-coded and displays the session currently in it.
  - Session Cards: Show session details, including name, ID, current score, and buttons to adjust the score.
  - Progress Sessions: Select an active session to move it to the next stage.
  - Sessions Summary: View lists of active and completed sessions along with their details.
- Stages:
  
  There are five stages in the game:
  1. Forest (Green)
  2. Statue (Gold)
  3. Electricity (Blue)
  4. Zektor (Purple)
  5. Lava Floor (Red)
- Session Management:
  - Sessions progress from Stage 1 to Stage 5.
  - Only one session can occupy a stage at a time.
  - Scores can be adjusted using the increment (➕) and decrement (➖) buttons.
  - Completed sessions are moved to the completed list after finishing Stage 5.
- Real-Time Updates:
  - The dashboard auto-refreshes every 5 seconds to reflect the latest data.
  - Scores and session statuses update in real-time.

## Configuration

The application uses a `config.json` file for configuration settings, particularly for MQTT connectivity (if used):

```json
{
  "development": {
    "BROKER": "127.0.0.1",
    "PORT": 1883,
    "USERNAME": "local_username",
    "PASSWORD": "local_password",
    "TOPIC": "test/forest/activity",
    "ENABLED": false
  },
  "production": {
    "BROKER": "homeassistant.local",
    "PORT": 1883,
    "USERNAME": "zektor",
    "PASSWORD": "command",
    "TOPIC": "forest/activity",
    "ENABLED": true
  }
}
```
- __MQTT_ENABLED:__ Set to `true` or `false` to enable or disable MQTT functionality.
- __BROKER and PORT:__ Address and port of the MQTT broker.
- __USERNAME and PASSWORD:__ Credentials for MQTT authentication.
- __TOPIC:__ The MQTT topic to subscribe to for messages.
_Note:_ If you are not using MQTT, you can keep `ENABLED` set to `false`.

## Data Persistence

The application stores session data in `sessions_data.json` to maintain state between restarts. This file includes:

- __stage_map:__ Current sessions occupying each stage.
- __sessions:__ Detailed information about each session.
- __active_sessions:__ List of currently active session IDs.
- __completed_sessions:__ List of completed session IDs.
- __next_session_id:__ Counter for assigning new session IDs.
Example  `sessions_data.json`:

```json
{
  "stage_map": {
    "1": null,
    "2": "session3",
    "3": null,
    "4": null,
    "5": null
  },
  "sessions": {
    "session1": {
      "current_stage": 5,
      "score": 3,
      "start_time": "2024-11-21T23:55:36.029531"
    },
    "session2": {
      "current_stage": 5,
      "score": 8,
      "start_time": "2024-11-22T00:03:19.364637"
    },
    "session3": {
      "name": "Kool Kidz",
      "current_stage": 2,
      "score": 14,
      "start_time": "2024-11-22T00:31:23.127035"
    }
  },
  "active_sessions": [
    "session3"
  ],
  "completed_sessions": [
    "session1",
    "session2"
  ],
  "next_session_id": 4
}
```
_Note:_ It's recommended not to manually edit this file to prevent data corruption.

---

Enjoy managing your Zektor escape room sessions with ease!

