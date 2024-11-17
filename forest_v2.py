import threading
import paho.mqtt.client as mqtt
import pygame
import time

# Define broker details
BROKER = "homeassistant.local"  # Replace with your broker IP
PORT = 1883
USERNAME = "zektor"  # Replace with your MQTT username
PASSWORD = "command"  # Replace with your MQTT password
TOPIC = "a35/col"  # Example topic

score = 1000

RED = "red"
GREEN = "green"

# Initialize pygame mixer
pygame.mixer.init()

# Preload sound into memory
point_sound = pygame.mixer.Sound("positive.wav")
penalty_sound = pygame.mixer.Sound("negative.wav")


def play_background_music():
    pygame.mixer.music.load("loop_forest.mp3")
    pygame.mixer.music.play(-1)  # Loop background music indefinitely


def play_sound(sound):
    # Play the sound effect
    sound.play()

    # Wait for the sound effect to finish playing
    while pygame.mixer.get_busy():
        time.sleep(0.1)


# Callback for when the client connects
def on_connect(client, userdata, flags, rc, properties=None):
    if rc == 0:
        print("Connected successfully!")
        client.subscribe(TOPIC)
        client.subscribe("archway/arch01/activity")
        print(f"Successfully subscribed to the {TOPIC}")
    else:
        print(f"Connection failed with code {rc}")


# Callback for when a message is received
def on_message(client, userdata, message):
    global score
    if message.topic == "archway/arch01/activity":
        point = message.payload.decode().lower()
        if point == "positive":
            play_sound(point_sound)
            score += 1
        elif point == "negative":
            play_sound(penalty_sound)
            score -= 1
    print(f"Current score: {score}")
    print(f"Received message: {message.payload.decode()} on topic {message.topic}")


# Function to handle user commands
def command_listener():
    while True:
        try:
            # Get user input
            user_input = input("Enter a topic and message (e.g., 'home/light ON'): ")

            # Parse input
            if user_input.lower() == "exit":
                print("Exiting...")
                client.disconnect()
                break

            topic, message = user_input.split(" ", 1)

            # Publish the message
            client.publish(topic, message)
            print(f"Published '{message}' to topic '{topic}'")
        except ValueError:
            print("Invalid input. Format: '<topic> <message>'")
        except Exception as e:
            print(f"Error: {e}")


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

# Start listening for commands
play_background_music()
command_listener()
