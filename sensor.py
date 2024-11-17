import machine
import time

import paho.mqtt.client as mqtt

# WiFi and MQTT settings
SSID = "your-SSID"
PASSWORD = "your-PASSWORD"
MQTT_BROKER = "your-mqtt-broker-ip"
MQTT_TOPIC = "sensor/motion"

# Pin configuration
TRIG_PIN = 5
ECHO_PIN = 18


# Setup WiFi
def connect_wifi():
    import network

    wlan = network.WLAN(network.STA_IF)
    wlan.active(True)
    wlan.connect(SSID, PASSWORD)
    while not wlan.isconnected():
        time.sleep(0.5)
    print("Connected to WiFi:", wlan.ifconfig())


# Initialize MQTT client
def init_mqtt():
    client = mqtt.Client()
    ("ESP32", MQTT_BROKER)
    client.connect()
    print("Connected to MQTT Broker")
    return client


# Measure distance
def measure_distance():
    trig = machine.Pin(TRIG_PIN, machine.Pin.OUT)
    echo = machine.Pin(ECHO_PIN, machine.Pin.IN)

    # Send a 10us pulse to trigger
    trig.off()
    time.sleep_us(2)
    trig.on()
    time.sleep_us(10)
    trig.off()

    # Measure echo pulse duration
    while echo.value() == 0:
        start = time.ticks_us()
    while echo.value() == 1:
        end = time.ticks_us()

    # Calculate distance in cm
    duration = time.ticks_diff(end, start)
    distance = (duration / 2) / 29.1  # Speed of sound: 343m/s or 29.1us/cm
    return distance


# Main function
def main():
    connect_wifi()
    client = init_mqtt()

    while True:
        distance = measure_distance()
        print("Distance:", distance, "cm")

        # If object is closer than 50 cm, send MQTT message
        if distance < 50:  # Adjust threshold as needed
            client.publish(MQTT_TOPIC, b"Motion Detected!")
            print("Motion Detected! Message Sent.")
            time.sleep(1)  # Avoid spamming the broker

        time.sleep(0.1)


# Run the program
if __name__ == "__main__":
    main()
