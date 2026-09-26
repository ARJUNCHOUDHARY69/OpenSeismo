# ==============================================================================
# Project: OpenSeismo - Decentralized Edge-AI Earthquake Detection
# Copyright (c) 2026 OpenSeismo Project (FOSSEE Hackathon Submission)
# 
# This software is released under the MIT License.
# The hardware designs are released under the CC BY-SA 4.0 License.
# ==============================================================================
import time
import struct
import json
import socket
import threading
import serial
import subprocess
import board
import busio
import spidev  # ADDED FOR LORA
from smbus2 import SMBus
import adafruit_ahtx0
import adafruit_bmp280
import adafruit_adxl34x

# ==========================================
# SECURE NETWORK CONFIGURATION
# ==========================================
WINDOWS_PC_TAILSCALE_IP = "YOUR_TAILSCALE_IP"
PORT = 9999

TARGET_HZ = 50.0
LOOP_INTERVAL = 1.0 / TARGET_HZ
SLOW_SENSOR_INTERVAL = 10.0
MPU_ADDR = 0x68

global_gps_data = None
sms_queue = []  # Queue for emergency SMS messages
system_telemetry_queue = [] # Queue for DB system events

def connect_to_windows():
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(5)
    try:
        sock.connect((WINDOWS_PC_TAILSCALE_IP, PORT))
        print(f"🔒 Connected securely to Windows PC!")
        return sock
    except Exception:
        return None

def send_payload(sock, payload, packet_name):
    """Sends payload to DB. If it fails, prints error and tries to reconnect."""
    if not sock:
        print(f"⚠️ [DB] Offline! Cannot send {packet_name}. Attempting Tailscale reconnect...")
        return connect_to_windows()
    try:
        sock.sendall(payload.encode('utf-8'))
        # Only print success for slow/important packets so we don't spam the terminal with 1-second fast batches
        if packet_name != "Fast Seismic Batch":
            print(f"📤 [DB] Successfully sent {packet_name} to Windows!")
        return sock
    except Exception as e:
        print(f"❌ [DB] Connection dropped while sending {packet_name}! Error: {e}")
        return connect_to_windows()

# ==========================================
# LORA MESH NETWORK (RAW SPIDEV)
# ==========================================
class RawLoRa:
    def __init__(self, bus=0, device=0):
        self.spi = spidev.SpiDev()
        self.spi.open(bus, device)
        self.spi.max_speed_hz = 500000
        self.spi.mode = 0

    def write_register(self, reg, val):
        self.spi.xfer2([reg | 0x80, val])

    def read_register(self, reg):
        return self.spi.xfer2([reg & 0x7F, 0x00])[1]

    def setup(self):
        self.write_register(0x01, 0x80 | 0x00) # Sleep
        time.sleep(0.1)
        self.write_register(0x01, 0x80 | 0x01) # Standby
        time.sleep(0.1)
        self.write_register(0x06, 0x6C); self.write_register(0x07, 0x40); self.write_register(0x08, 0x00) # 433 MHz
        self.write_register(0x09, 0x8F) # Max Power
        self.write_register(0x39, 0x12); self.write_register(0x20, 0x00); self.write_register(0x21, 0x08)
        self.write_register(0x1D, 0x72) # BW 125, CR 4/5
        self.write_register(0x1E, 0xC4) # SF 12, CRC ON
        self.write_register(0x26, 0x0C) # LDRO ON, AGC ON
        
        # PERMANENTLY LOCK INTO RX CONTINUOUS (Receiver Only!)
        self.write_register(0x01, 0x80 | 0x05)

    def receive_packet(self):
        # CRITICAL: Always ensure we are in RX Continuous (0x05). 
        # If the radio drops to standby due to noise/glitch, this kicks it back!
        if (self.read_register(0x01) & 0x07) != 0x05:
            self.write_register(0x01, 0x80 | 0x05)

        # Check RX_DONE flag (bit 6)
        if self.read_register(0x12) & 0x40:
            self.write_register(0x12, 0xFF) # Clear all IRQ flags
            rx_bytes = self.read_register(0x13)
            self.write_register(0x0D, self.read_register(0x10))
            resp = self.spi.xfer2([0x00] + [0x00] * rx_bytes)
            self.last_rssi = self.read_register(0x1A) - 164
            
            return bytes(resp[1:]).decode('utf-8', errors='ignore')
        return None

# ==========================================
# ON-DEMAND MODEM THREAD (GPS + SMS)
# ==========================================
modem_lock = threading.Lock()

def modem_worker():
    global global_gps_data
    print("🛰️📱 Starting On-Demand Modem Thread (Open/Close safely)...")

    # 1. INITIALIZE (Runs Once)
    def run_initial_setup(ser):
        ser.setDTR(False)
        ser.setRTS(False)
        
        def init_cmd(cmd, delay=1.0, wait_ok=False):
            ser.write(cmd.encode('utf-8') + b'\r\n')
            time.sleep(delay)
            resp = ser.read_all().decode('utf-8', errors='ignore').strip()
            if wait_ok:
                for _ in range(20):
                    if "OK" in resp or "ERROR" in resp: break
                    time.sleep(1.0)
                    resp += ser.read_all().decode('utf-8', errors='ignore').strip()
            return resp

        print("📡 Initializing GPS & SMS...")
        init_cmd("AT+QGPS=1", delay=1.0)
        init_cmd("AT+CMGF=1", delay=1.0)
        init_cmd('AT+CSCS="GSM"', delay=1.0)
        
        print("📡 Pre-configuring 4G Data Connection... (Please wait ~40 seconds)")
        init_cmd("AT+QNETDEVCTL=0", delay=2.0)
        init_cmd("AT+COPS=0", delay=15.0, wait_ok=True)
        init_cmd("AT+CGACT=1,1", delay=5.0, wait_ok=True)
        init_cmd("AT+CGPADDR=1", delay=2.0) # Runs silently
        init_cmd("AT+QNETDEVCTL=1,1,1", delay=5.0, wait_ok=True)
        
        print("⏳ Letting modem settle before starting main loops...")
        time.sleep(10.0)
        print("✅ Modem Initialized & 4G Ready. Port closed.")

    try:
        with serial.Serial('/dev/ttyUSB0', 115200, timeout=2) as ser:
            run_initial_setup(ser)
    except Exception as e:
        if "Device or resource busy" in str(e):
            print("⚠️ Port /dev/ttyUSB0 is busy! Auto-killing the ghost process...")
            try:
                subprocess.run(["sudo", "fuser", "-k", "/dev/ttyUSB0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                time.sleep(2)
                with serial.Serial('/dev/ttyUSB0', 115200, timeout=2) as ser:
                    run_initial_setup(ser)
            except Exception as inner_e:
                print(f"⚠️ Retry Startup Error: {inner_e}")
        else:
            print(f"⚠️ Modem Startup Error: {e}")

    # Set to CURRENT TIME so it waits a full 30 seconds BEFORE polling GPS for the first time!
    last_gps_check = time.time()
    last_ping_check = 0
    last_fallback_attempt = 0

    while True:
        current_time = time.time()
        
        # --- 0. AUTO-FALLBACK WATCHDOG (Every 10 seconds) ---
        if current_time - last_ping_check >= 10.0:
            # Ping Google DNS. -c 1 (one packet), -W 2 (2 seconds timeout)
            ping_ok = (subprocess.run(["ping", "-c", "1", "-W", "2", "8.8.8.8"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0)
            
            if not ping_ok:
                # If ping fails, try to dial 4G every 60 seconds
                if current_time - last_fallback_attempt > 60.0:
                    print("⚠️ [NETWORK] Internet Drop Detected! Fast 4G Fallback Initiated...")
                    last_fallback_attempt = current_time
                    try:
                        print("📡 Running DHCP client on usb0... (Waiting 5s for IP)")
                        subprocess.run(["sudo", "dhclient", "-v", "usb0"], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                        time.sleep(5.0) # Let the routing tables update
                        print("✅ Fast Cellular Fallback Complete! Tailscale will auto-reconnect.")
                        
                        global system_telemetry_queue
                        system_telemetry_queue.append({"t_epoch": round(time.time(), 2), "event": "4G_FALLBACK_TRIGGERED"})
                    except Exception as e:
                        print(f"⚠️ Cellular Fallback Error: {e}")
            last_ping_check = time.time()

        # --- 1. SMS DISPATCHER (High Priority & Lightning Fast) ---
        if len(sms_queue) > 0:
            msg = sms_queue.pop(0)
            print(f"📱 Dialing SMS Alert to Airtel...")
            with modem_lock:
                try:
                    with serial.Serial('/dev/ttyUSB0', 115200, timeout=1) as ser:
                        ser.setDTR(False)
                        ser.setRTS(False)

                        def send_fast(cmd):
                            ser.write(cmd.encode('utf-8') + b'\r\n')
                            time.sleep(0.1) # Lightning fast 100ms pause

                        # 0. WAKEUP & SETUP (Fast execution)
                        send_fast("AT")
                        ser.read_all() # Clear buffer

                        send_fast("AT+CMGF=1")
                        send_fast('AT+CSCS="GSM"')
                        send_fast('AT+CPMS="SM","SM","SM"')
                        ser.read_all() # Clear setup responses

                        # 1. DIAL
                        ser.write(b'AT+CMGS="+910000000000"\r\n')

                        # 2. DYNAMIC PROMPT WAIT (Moves instantly when ready)
                        prompt_ready = False
                        for _ in range(20): # Wait up to 2 seconds max
                            if ser.in_waiting:
                                if '>' in ser.read(ser.in_waiting).decode('utf-8', errors='ignore'):
                                    prompt_ready = True
                                    break
                            time.sleep(0.1)

                        if prompt_ready:
                            print("✉️ Prompt ready! Injecting payload...")
                            ser.write(msg.encode('utf-8'))
                            time.sleep(0.1) # Tiny buffer
                            ser.write(b'\x1A')

                            # 3. DYNAMIC DELIVERY CONFIRMATION
                            success = False
                            for _ in range(600): # Wait up to 60s for cell network
                                if ser.in_waiting:
                                    final_resp = ser.readline().decode('utf-8', errors='ignore').strip()
                                    if "OK" in final_resp or "+CMGS:" in final_resp:
                                        success = True
                                        break
                                    if "ERROR" in final_resp:
                                        print(f"⚠️ Network Error: {final_resp}")
                                        break
                                time.sleep(0.1)

                            if success:
                                print("✅ SMS Dispatched Fast!")
                            else:
                                print("⚠️ SMS Failed delivery.")
                        else:
                            print("⚠️ Modem refused prompt.")

                except Exception as e:
                    print(f"⚠️ SMS Serial Error: {e}")

        # --- 2. GPS POLLER (Every 30 seconds) ---
        if current_time - last_gps_check >= 30.0:
            with modem_lock:
                try:
                    with serial.Serial('/dev/ttyUSB0', 115200, timeout=1) as ser:
                        ser.setDTR(False)
                        ser.setRTS(False)
                        ser.write(b'AT+QGPSLOC=0\r\n')
                        lines = ser.readlines()

                        for line_bytes in lines:
                            try:
                                line = line_bytes.decode('utf-8', errors='ignore').strip()

                                if "516" in line:
                                    print("⏳ GPS searching for satellites... (No lock yet)")

                                elif line.startswith('+QGPSLOC:'):
                                    parts = line.split('+QGPSLOC: ')[1].split(',')
                                    if len(parts) >= 11:
                                        lat_raw, lon_raw = parts[1], parts[2]
                                        alt = float(parts[4]) if parts[4] else 0.0
                                        sats = int(parts[10]) if parts[10] else 0

                                        lat_deg = float(lat_raw[:2]); lat_min = float(lat_raw[2:-1])
                                        lat = lat_deg + (lat_min / 60.0)
                                        if lat_raw.endswith('S'): lat = -lat

                                        lon_deg = float(lon_raw[:3]); lon_min = float(lon_raw[3:-1])
                                        lon = lon_deg + (lon_min / 60.0)
                                        if lon_raw.endswith('W'): lon = -lon

                                        global_gps_data = {"lat": round(lat, 6), "lon": round(lon, 6), "alt": alt, "sats": sats}
                            except Exception:
                                pass
                except Exception as e:
                    print(f"⚠️ GPS Read Error: {e}")

            last_gps_check = time.time()

        time.sleep(0.1) # Fast loop!

# ==========================================
# STA/LTA SEISMIC TRIGGER ALGORITHM
# ==========================================
class STALTATrigger:
    def __init__(self, sta_len=25, lta_len=500, threshold=2.0):
        self.sta_len = sta_len
        self.lta_len = lta_len
        self.threshold = threshold
        self.history = []

    def update(self, energy: float):
        self.history.append(energy)
        if len(self.history) > self.lta_len:
            self.history.pop(0)
        if len(self.history) < self.lta_len:
            return False, None
        sta = sum(self.history[-self.sta_len:]) / self.sta_len
        lta = sum(self.history) / self.lta_len
        ratio = (sta / lta) if lta > 1e-5 else 1.0
        return ratio >= self.threshold, ratio

# ==========================================
# LORA MESH WORKER THREAD (RECEIVER ONLY)
# ==========================================
trigger_mesh_alert = False # Left for future, but unused in RX-only
global_buzzer_stop_time = 0 
mesh_telemetry_queue = [] # Queue for DB ingester

def lora_worker(lora, buzzer):
    global sms_queue, global_buzzer_stop_time, mesh_telemetry_queue
    print("📡 Starting LoRa Mesh Background Thread (STRICTLY RX MODE)...")
    last_lora_sms = 0

    while True:
        try:
            current_time = time.time()

            # --- Listen for Incoming Packets from ESP8266 ---
            packet = lora.receive_packet()
            if packet:
                rssi = getattr(lora, 'last_rssi', 'N/A')
                try:
                    data = json.loads(packet)
                    node_id = data.get("node", "UNKNOWN")
                    ratio = float(data.get("ratio", 0.0))
                    sta_val = float(data.get("sta", 0.0))
                    lta_val = float(data.get("lta", 0.0))
                    uptime = int(data.get("uptime", 0))
                    mag = float(data.get("mag", 0.0))

                    # ROUTINE TELEMETRY (Logs exact STA/LTA from ESP for DB)
                    if data.get("type") == "health":
                        print(f"📡 [LORA MESH] TELEMETRY | Node: {node_id} | Status: SAFE | STA/LTA: {ratio:.2f} | Uptime: {uptime}s | Signal: {rssi} dBm")
                        # Push to queue for Windows DB
                        mesh_telemetry_queue.append({
                            "t_epoch": round(current_time, 2), 
                            "node": node_id, 
                            "status": "SAFE", 
                            "ratio": ratio, 
                            "sta": sta_val,
                            "lta": lta_val,
                            "uptime": uptime,
                            "rssi": rssi
                        })

                    # EMERGENCY ALERT FROM ESP8266
                    elif data.get("type") == "alert" or data.get("alert") == 1:
                        print(f"\n🔥🔥🔥 [LORA MESH] EARTHQUAKE ALERT FROM {node_id} | Mag: {mag:.1f} | Signal: {rssi} dBm 🔥🔥🔥\n")
                        
                        # Push alert to queue for Windows DB
                        mesh_telemetry_queue.append({
                            "t_epoch": round(current_time, 2), 
                            "node": node_id, 
                            "status": "UNSAFE", 
                            "ratio": ratio, 
                            "mag": mag,
                            "rssi": rssi
                        })

                        # Sound Pi buzzer immediately
                        if buzzer:
                            buzzer.play(880)
                            global_buzzer_stop_time = current_time + 6.0 

                        # Queue SMS
                        if current_time - last_lora_sms > 60.0:
                            # Grab base station location if available
                            global global_gps_data
                            if global_gps_data is not None:
                                loc = f"{global_gps_data['lat']},{global_gps_data['lon']}"
                                map_link = f"Base: https://www.google.com/maps?q={loc}"
                            else:
                                map_link = "Base: GPS Acquiring..."

                            sms_text = (
                                f"🚨 SEISMIC ALERT (REMOTE MESH) 🚨\n"
                                f"Node: {node_id}\n"
                                f"Magnitude: {mag:.1f} (Ratio: {ratio:.2f})\n"
                                f"Signal: {rssi} dBm\n"
                                f"{map_link}\n"
                                f"TAKE COVER NOW!"
                            )
                            sms_queue.append(sms_text)
                            last_lora_sms = current_time

                except json.JSONDecodeError:
                    print(f"⚠️ [LORA] Corrupted packet received: {packet}")
                except Exception as inner_e:
                    print(f"⚠️ [LORA] Data parsing error: {inner_e}")

        except Exception as e:
            print(f"🚨 [LORA] CRITICAL THREAD CRASH PREVENTED: {e}")
            time.sleep(1)

        time.sleep(0.01) # Fast polling loop

def main():
    global trigger_mesh_alert, global_buzzer_stop_time
    print("Initializing Direct Socket Sensor Node with STA/LTA Edge Trigger & MESH NETWORK...")

    # Start combined Modem Thread (GPS + SMS)
    modem_thread = threading.Thread(target=modem_worker, daemon=True)
    modem_thread.start()

    try:
        from gpiozero import TonalBuzzer
        buzzer = TonalBuzzer(18)
        buzzer.play(440)
        time.sleep(1)
        buzzer.stop()
    except Exception:
        buzzer = None

    # START LORA RADIO IN BACKGROUND
    lora = RawLoRa()
    try:
        lora.setup()
        print("✅ LoRa Mesh Radio Initialized.")
        lora_thread = threading.Thread(target=lora_worker, args=(lora, buzzer), daemon=True)
        lora_thread.start()
    except Exception as e:
        print(f"⚠️ LoRa Error: {e}")

    try: bus = SMBus(1); bus.write_byte_data(MPU_ADDR, 0x6B, 0)
    except Exception as e:
        print(f"⚠️ MPU6050 Init Error: {e}")
        bus = None
    try: i2c = busio.I2C(board.SCL, board.SDA)
    except: i2c = None
    try: adxl = adafruit_adxl34x.ADXL345(i2c, address=0x53)
    except: adxl = None
    try: aht = adafruit_ahtx0.AHTx0(i2c)
    except: aht = None

    bmp = None
    if i2c:
        for addr in (0x77, 0x76):
            try: bmp = adafruit_bmp280.Adafruit_BMP280_I2C(i2c, address=addr); break
            except: pass

    fast_batch = []
    trigger = STALTATrigger()

    next_loop_time = time.perf_counter()
    last_slow_read_time = 0
    last_batch_send_time = time.time()
    last_gps_send_time = 0
    last_sms_time = 0 # Track SMS to prevent spam
    last_mesh_ping = 0
    loop_count = 0
    alarm_end_time = 0

    sock = connect_to_windows()

    print("🚀 System Live! Capturing data, checking Mesh, and calculating STA/LTA...")

    try:
        while True:
            loop_count += 1
            current_time = time.time()

            # (LoRa Mesh logic is now handled in the dedicated lora_worker thread!)

            if current_time - last_slow_read_time >= SLOW_SENSOR_INTERVAL:
                t_val = None
                env_data = {"t_epoch": round(current_time, 2), "t": 0.0, "h": 0.0, "p": 0.0}
                if aht:
                    try: t_val = aht.temperature; env_data["h"] = round(aht.relative_humidity, 1)
                    except: pass
                if bmp:
                    try:
                        env_data["t"] = round(bmp.temperature if t_val is None else t_val, 1)
                        env_data["p"] = round(bmp.pressure, 1)
                    except: pass

                payload = json.dumps({"type": "slow", "data": env_data}, separators=(',', ':')) + "\n"
                sock = send_payload(sock, payload, "Weather Data")

                last_slow_read_time = current_time

            mx, my, mz, ax, ay, az = 0.0, 0.0, 0.0, 0.0, 0.0, 0.0
            is_event = 0

            if bus:
                try:
                    raw = bus.read_i2c_block_data(MPU_ADDR, 0x3B, 14)
                    u = struct.unpack(">7h", bytes(raw))
                    mx, my, mz = round(u[0]/16384.0*9.8, 2), round(u[1]/16384.0*9.8, 2), round(u[2]/16384.0*9.8, 2)

                    magnitude = (mx**2 + my**2 + mz**2)**0.5
                    dynamic_energy = abs(magnitude - 9.8)

                    is_triggered, current_ratio = trigger.update(dynamic_energy)

                    if loop_count % 50 == 0 and current_ratio is not None:
                        status = "🟢 NORMAL" if current_ratio < trigger.threshold else "🔴 SHAKING"
                        print(f"📈 Seismic Engine | STA/LTA Ratio: {current_ratio:.2f} / {trigger.threshold} | {status}")

                    if is_triggered:
                        is_event = 1
                        global_buzzer_stop_time = current_time + 7.0

                        # --- LOCAL TRIGGER EMERGENCY MESH & SMS ---
                        if current_time - last_sms_time > 60.0:
                            if global_gps_data is not None:
                                loc_details = f"Map: https://www.google.com/maps?q={global_gps_data['lat']},{global_gps_data['lon']}"
                            else:
                                loc_details = "Location: Acquiring..."

                            sms_text = f"CRITICAL ALERT (MASTER PI)\nSTA/LTA Ratio: {current_ratio:.2f}\n{loc_details}"
                            sms_queue.append(sms_text)
                            last_sms_time = current_time

                            # Blast warning to the ESP8266 Community Node safely via thread flag!
                            trigger_mesh_alert = True

                        if buzzer: buzzer.play(440)
                    else:
                        if current_time >= global_buzzer_stop_time and global_buzzer_stop_time > 0:
                            if buzzer: buzzer.stop()
                            global_buzzer_stop_time = 0
                        elif global_buzzer_stop_time > current_time:
                            is_event = 1

                except Exception as e:
                    if loop_count % 50 == 0:
                        print(f"⚠️ MPU6050 Read Error: {e}")
            if adxl:
                try:
                    ax_, ay_, az_ = adxl.acceleration
                    ax, ay, az = round(ax_, 2), round(ay_, 2), round(az_, 2)
                except: pass

            fast_batch.append({"t": round(current_time, 2), "mx": mx, "my": my, "mz": mz, "ax": ax, "ay": ay, "az": az, "e": is_event})

            if current_time - last_batch_send_time >= 1.0:
                payload = json.dumps({"type": "fast", "data": fast_batch}, separators=(',', ':')) + "\n"
                sock = send_payload(sock, payload, "Fast Seismic Batch")
                fast_batch.clear()
                last_batch_send_time = current_time

            # --- FLUSH LORA MESH TELEMETRY TO WINDOWS DB ---
            if len(mesh_telemetry_queue) > 0:
                mesh_batch = mesh_telemetry_queue.copy()
                mesh_telemetry_queue.clear()
                payload = json.dumps({"type": "mesh", "data": mesh_batch}, separators=(',', ':')) + "\n"
                sock = send_payload(sock, payload, "LoRa Mesh Telemetry")

            # --- FLUSH SYSTEM TELEMETRY TO WINDOWS DB ---
            if len(system_telemetry_queue) > 0:
                sys_batch = system_telemetry_queue.copy()
                system_telemetry_queue.clear()
                payload = json.dumps({"type": "sys_event", "data": sys_batch}, separators=(',', ':')) + "\n"
                sock = send_payload(sock, payload, "System Event Alert")

            if current_time - last_gps_send_time >= 30.0:
                if global_gps_data is not None:
                    gps_payload = global_gps_data.copy()
                    gps_payload["t_epoch"] = round(current_time, 2)
                    payload = json.dumps({"type": "gps", "data": gps_payload}, separators=(',', ':')) + "\n"
                    sock = send_payload(sock, payload, "GPS Location Data")

                last_gps_send_time = current_time

            next_loop_time += LOOP_INTERVAL
            sleep_time = next_loop_time - time.perf_counter()
            if sleep_time > 0: time.sleep(sleep_time)
            else: next_loop_time = time.perf_counter()

    except KeyboardInterrupt:
        pass
    finally:
        if sock: sock.close()
        if bus: bus.close()

if __name__ == '__main__':
    main()
