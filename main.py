from machine import Pin
import network
import socket
import time
import json
import neopixel

# Configuration
WIFI_SSID = "Haunted"
WIFI_PASSWORD = "lights-camera-action-skeletons"
MQTT_BROKER = "homeassistant.local"
MQTT_PORT = 1883
CLIENT_ID = "gate-controller"
MQTT_USER = "zektor"
MQTT_PASSWORD = "command"
MQTT_TOPIC_UNLOCK = "lock/status"  # Topic for unlock signal
MQTT_TOPIC_CODE = "lock/code"  # Topic to receive code updates

# Button pins
RED_BTN_PIN = 18
GREEN_BTN_PIN = 19
BLUE_BTN_PIN = 5

# LED Configuration
LED_PIN = 12
SEGMENT_LENGTHS = [9, 9, 9, 36]  # Length of each segment
TOTAL_LEDS = sum(SEGMENT_LENGTHS)

# Calculate segment start positions
SEGMENT_STARTS = [0]
for i in range(len(SEGMENT_LENGTHS) - 1):
    SEGMENT_STARTS.append(SEGMENT_STARTS[-1] + SEGMENT_LENGTHS[i])

# Color definitions (RGB format)
COLORS = {
    "red": (255, 0, 0),
    "green": (0, 255, 0),
    "blue": (0, 0, 255),
    "off": (0, 0, 0),
}


def encode_remaining_length(length):
    encoded = bytearray()
    while length > 0:
        digit = length % 128
        length = length // 128
        if length > 0:
            digit |= 0x80
        encoded.append(digit)
    return encoded if encoded else bytearray([0])


class SimpleMQTT:
    def __init__(self, client_id, server, port=1883, user=None, password=None):
        self.client_id = client_id
        self.server = server
        self.port = port
        self.user = user
        self.password = password
        self.sock = None
        self.callback = None

    def set_callback(self, callback):
        self.callback = callback

    def connect(self):
        self.sock = socket.socket()
        addr = socket.getaddrinfo(self.server, self.port)[0][-1]
        self.sock.connect(addr)

        variable_header = bytearray(
            [
                0x00,
                0x04,
                0x4D,
                0x51,
                0x54,
                0x54,
                0x04,
                0x00,
                0x00,
                0x3C,
            ]
        )

        payload = bytearray()

        client_id = self.client_id.encode()
        payload.extend(len(client_id).to_bytes(2, "big"))
        payload.extend(client_id)

        connect_flags = 0x02
        if self.user:
            connect_flags |= 0x80
            user_bytes = self.user.encode()
            payload.extend(len(user_bytes).to_bytes(2, "big"))
            payload.extend(user_bytes)

        if self.password:
            connect_flags |= 0x40
            pass_bytes = self.password.encode()
            payload.extend(len(pass_bytes).to_bytes(2, "big"))
            payload.extend(pass_bytes)

        variable_header[7] = connect_flags
        remaining_length = len(variable_header) + len(payload)
        fixed_header = bytearray([0x10])
        fixed_header.extend(encode_remaining_length(remaining_length))
        packet = fixed_header + variable_header + payload

        self.sock.write(packet)
        resp = self.sock.read(4)
        if not resp or resp[3] != 0:
            raise OSError(f"MQTT Connection failed")

    def subscribe(self, topic):
        packet_id = 1
        topic = topic.encode()

        packet = bytearray(
            [
                0x82,  # SUBSCRIBE packet type
                2 + 2 + len(topic) + 1,  # Remaining length
                0x00,
                packet_id,  # Packet ID
                len(topic) >> 8,
                len(topic) & 0xFF,  # Topic length
            ]
        )
        packet.extend(topic)
        packet.append(0)  # QoS 0

        self.sock.write(packet)
        resp = self.sock.read(5)
        if not resp or resp[0] != 0x90:
            raise OSError("MQTT Subscription failed")

    def check_msg(self):
        try:
            self.sock.setblocking(False)
            header = self.sock.read(1)
            if header is None:
                return

            packet_type = header[0] >> 4
            if packet_type == 3:
                multiplier = 1
                value = 0
                while True:
                    digit = self.sock.read(1)[0]
                    value += (digit & 127) * multiplier
                    if not digit & 128:
                        break
                    multiplier *= 128

                topic_len = int.from_bytes(self.sock.read(2), "big")
                topic = self.sock.read(topic_len).decode()
                message = self.sock.read(value - topic_len - 2).decode()

                if self.callback:
                    self.callback(topic, message)

        except Exception as e:
            pass
        finally:
            self.sock.setblocking(True)

    def publish(self, topic, message):
        topic = topic.encode()
        message = message.encode()
        variable_header = len(topic).to_bytes(2, "big") + topic
        remaining_length = len(variable_header) + len(message)
        fixed_header = bytearray([0x30])
        fixed_header.extend(encode_remaining_length(remaining_length))
        packet = fixed_header + variable_header + message
        try:
            self.sock.write(packet)
        except:
            print("Reconnecting...")
            self.connect()
            self.sock.write(packet)


class LockController:
    def __init__(self):
        self.np = neopixel.NeoPixel(Pin(LED_PIN), TOTAL_LEDS)
        self.red_btn = Pin(RED_BTN_PIN, Pin.IN, Pin.PULL_UP)
        self.green_btn = Pin(GREEN_BTN_PIN, Pin.IN, Pin.PULL_UP)
        self.blue_btn = Pin(BLUE_BTN_PIN, Pin.IN, Pin.PULL_UP)
        self.current_sequence = []
        self.security_code = ["red", "green", "blue"]
        self.last_press_time = 0
        self.debounce_delay = 200
        self.last_red_state = 1
        self.last_green_state = 1
        self.last_blue_state = 1
        self.clear_all()
        self.connect_wifi()
        self.setup_mqtt()

    def connect_wifi(self):
        wlan = network.WLAN(network.STA_IF)
        wlan.active(True)
        if not wlan.isconnected():
            print("Connecting to WiFi...")
            wlan.connect(WIFI_SSID, WIFI_PASSWORD)
            while not wlan.isconnected():
                time.sleep_ms(100)
        print("WiFi connected")

    def setup_mqtt(self):
        print("Connecting to MQTT...")
        self.mqtt = SimpleMQTT(
            "esp32_lock_controller",
            MQTT_BROKER,
            MQTT_PORT,
            user=MQTT_USER,
            password=MQTT_PASSWORD,
        )
        self.mqtt.connect()
        self.mqtt.set_callback(self.mqtt_callback)
        self.mqtt.subscribe(MQTT_TOPIC_CODE)
        print("MQTT Connected and subscribed to code updates")

    def mqtt_callback(self, topic, msg):
        if topic == MQTT_TOPIC_CODE:
            try:
                new_code = json.loads(msg)
                if isinstance(new_code, list) and all(
                    c in ["red", "green", "blue"] for c in new_code
                ):
                    self.security_code = new_code
                    print("New security code set:", self.security_code)
                    self.flash_confirmation()
            except Exception as e:
                print("Error processing new code:", e)

    def clear_all(self):
        for i in range(TOTAL_LEDS):
            self.np[i] = COLORS["off"]
        self.np.write()

    def update_led_display(self):
        for i in range(TOTAL_LEDS - SEGMENT_LENGTHS[-1]):  # Don't clear last segment
            self.np[i] = COLORS["off"]
        for i, color in enumerate(self.current_sequence):
            if i < len(SEGMENT_LENGTHS) - 1:
                start = SEGMENT_STARTS[i]
                length = SEGMENT_LENGTHS[i]
                for j in range(start, start + length):
                    self.np[j] = COLORS[color]
        self.np.write()

    def show_success(self):
        start = SEGMENT_STARTS[-1]
        length = SEGMENT_LENGTHS[-1]
        for i in range(start, start + length):
            self.np[i] = COLORS["green"]
        self.np.write()
        time.sleep(1)
        for i in range(start, start + length):
            self.np[i] = COLORS["off"]
        self.np.write()

    def show_failure(self):
        # Flash red 3 times for failure
        start = SEGMENT_STARTS[-1]
        length = SEGMENT_LENGTHS[-1]

        for _ in range(3):  # Flash 3 times
            # Red on
            for i in range(start, start + length):
                self.np[i] = COLORS["red"]
            self.np.write()
            time.sleep_ms(200)  # On for 200ms

            # Red off
            for i in range(start, start + length):
                self.np[i] = COLORS["off"]
            self.np.write()
            time.sleep_ms(200)  # Off for 200ms

    def flash_confirmation(self):
        for _ in range(2):
            for i in range(TOTAL_LEDS):
                self.np[i] = COLORS["green"]
            self.np.write()
            time.sleep_ms(200)
            self.clear_all()
            time.sleep_ms(200)

    def send_unlock_signal(self):
        try:
            self.mqtt.publish(MQTT_TOPIC_UNLOCK, "UNLOCK")
            print("Unlock signal sent")
        except Exception as e:
            print("Error sending unlock signal:", e)

    def check_sequence(self):
        if len(self.current_sequence) == len(self.security_code):
            if self.current_sequence == self.security_code:
                print("Correct sequence!")
                self.show_success()
                self.send_unlock_signal()
            else:
                print("Incorrect sequence!")
                self.show_failure()
            self.reset_sequence()
            return True
        return False

    def reset_sequence(self):
        self.current_sequence = []
        self.clear_all()

    def check_buttons(self):
        current_time = time.ticks_ms()
        if time.ticks_diff(current_time, self.last_press_time) < self.debounce_delay:
            return

        self.mqtt.check_msg()

        red_state = self.red_btn.value()
        green_state = self.green_btn.value()
        blue_state = self.blue_btn.value()

        button_pressed = False

        if red_state == 0 and self.last_red_state == 1:
            print("Red button pressed")
            self.current_sequence.append("red")
            button_pressed = True
            self.last_press_time = current_time

        elif green_state == 0 and self.last_green_state == 1:
            print("Green button pressed")
            self.current_sequence.append("green")
            button_pressed = True
            self.last_press_time = current_time

        elif blue_state == 0 and self.last_blue_state == 1:
            print("Blue button pressed")
            self.current_sequence.append("blue")
            button_pressed = True
            self.last_press_time = current_time

        self.last_red_state = red_state
        self.last_green_state = green_state
        self.last_blue_state = blue_state

        if button_pressed:
            self.update_led_display()
            if len(self.current_sequence) == len(self.security_code):
                self.check_sequence()

    def run(self):
        print("Starting LED lock controller...")
        print("Waiting for button presses...")
        self.clear_all()
        while True:
            try:
                self.check_buttons()
                time.sleep_ms(50)
            except Exception as e:
                print("Error in main loop:", e)
                time.sleep(1)


try:
    controller = LockController()
    controller.run()
except Exception as e:
    print("Fatal error:", e)
