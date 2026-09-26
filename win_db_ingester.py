# ==============================================================================
# Project: OpenSeismo - Decentralized Edge-AI Earthquake Detection
# Copyright (c) 2026 OpenSeismo Project (FOSSEE Hackathon Submission)
# 
# This software is released under the MIT License.
# The hardware designs are released under the CC BY-SA 4.0 License.
# ==============================================================================
import sys
import json
import socket
import threading
import pymysql

# Force UTF-8 for Windows console to fix emoji printing errors
if sys.stdout and hasattr(sys.stdout, 'reconfigure'):
    sys.stdout.reconfigure(encoding='utf-8')


# ==========================================
# SUPER EASY DATABASE SETUP
# ==========================================
DB_PASS = "YOUR_DB_PASSWORD"  
DB_PORT = 3307    

print("⚙️ Checking Database...")
try:
    conn = pymysql.connect(host="localhost", port=DB_PORT, user="root", password=DB_PASS, autocommit=True)
    cursor = conn.cursor()
    
    cursor.execute("CREATE DATABASE IF NOT EXISTS openseismopi;")
    cursor.execute("USE openseismopi;")
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS seismic_data (
        id BIGINT AUTO_INCREMENT PRIMARY KEY,
        timestamp_epoch DOUBLE, mpu_x FLOAT, mpu_y FLOAT, mpu_z FLOAT, adxl_x FLOAT, adxl_y FLOAT, adxl_z FLOAT,
        is_event TINYINT(1) DEFAULT 0
    );""")
    
    try: cursor.execute("ALTER TABLE seismic_data ADD COLUMN is_event TINYINT(1) DEFAULT 0;")
    except: pass
    
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS env_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp_epoch DOUBLE, temperature FLOAT, humidity FLOAT, pressure FLOAT
    );""")
    
    # ADVANCED GPS TABLE (WITH ALL DETAILS)
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS gps_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp_epoch DOUBLE, 
        latitude FLOAT(10, 6), 
        longitude FLOAT(10, 6), 
        altitude FLOAT, 
        satellites INT,
        hdop FLOAT,
        fix_type INT,
        course FLOAT,
        speed_kmh FLOAT,
        time_utc VARCHAR(20),
        date_utc VARCHAR(20)
    );""")
    
    # If the table was already created in the previous step, these ALTERs will add the new columns!
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN hdop FLOAT;")
    except: pass
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN fix_type INT;")
    except: pass
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN course FLOAT;")
    except: pass
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN speed_kmh FLOAT;")
    except: pass
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN time_utc VARCHAR(20);")
    except: pass
    try: cursor.execute("ALTER TABLE gps_data ADD COLUMN date_utc VARCHAR(20);")
    except: pass

    # LORA MESH TABLE
    cursor.execute("""
    CREATE TABLE IF NOT EXISTS mesh_data (
        id INT AUTO_INCREMENT PRIMARY KEY,
        timestamp_epoch DOUBLE, 
        node_id VARCHAR(50),
        status VARCHAR(20),
        sta_lta_ratio FLOAT,
        sta FLOAT,
        lta FLOAT,
        uptime_s INT,
        rssi INT,
        mag FLOAT
    );""")
    
    print("✅ MariaDB is Ready! Tables created automatically.")
except Exception as e:
    print(f"❌ Could not connect to MariaDB. Did you install it? Error: {e}")
    exit(1)


# ==========================================
# DIRECT SECURE RECEIVER (NO MQTT NEEDED)
# ==========================================
HOST = '0.0.0.0'
PORT = 9999

def handle_client(client_socket):
    buffer = ""
    while True:
        try:
            data = client_socket.recv(4096).decode('utf-8')
            if not data: break
            
            buffer += data
            while '\n' in buffer:
                line, buffer = buffer.split('\n', 1)
                payload = json.loads(line)
                
                if payload.get("type") == "fast":
                    sql = "INSERT INTO seismic_data (timestamp_epoch, mpu_x, mpu_y, mpu_z, adxl_x, adxl_y, adxl_z, is_event) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)"
                    records = []
                    event_triggered = False
                    for d in payload["data"]:
                        is_event = d.get("e", 0)
                        if is_event == 1:
                            event_triggered = True
                        records.append((d["t"], d["mx"], d["my"], d["mz"], d["ax"], d["ay"], d["az"], is_event))
                    
                    cursor.executemany(sql, records)
                    print(f"📦 Saved {len(records)} fast seismic records.")
                    
                    if event_triggered:
                        print("🚨 EARTHQUAKE ALERT RECEIVED FROM PI! 🚨")
                        try:
                            import winsound
                            winsound.Beep(1000, 1000)
                        except: pass
                        
                elif payload.get("type") == "slow":
                    d = payload["data"]
                    sql = "INSERT INTO env_data (timestamp_epoch, temperature, humidity, pressure) VALUES (%s, %s, %s, %s)"
                    cursor.execute(sql, (d["t_epoch"], d["t"], d["h"], d["p"]))
                    print(f"🌦️ Saved environmental weather record.")
                    
                # ADVANCED GPS LOGIC
                elif payload.get("type") == "gps":
                    d = payload["data"]
                    sql = """INSERT INTO gps_data 
                             (timestamp_epoch, latitude, longitude, altitude, satellites, hdop, fix_type, course, speed_kmh, time_utc, date_utc) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    cursor.execute(sql, (
                        d["t_epoch"], d["lat"], d["lon"], d["alt"], d["sats"],
                        d.get("hdop"), d.get("fix"), d.get("course"), d.get("speed"),
                        d.get("utc_time"), d.get("utc_date")
                    ))
                    print(f"🛰️ Saved GPS: {d['lat']}, {d['lon']} | Sats: {d['sats']} | Speed: {d.get('speed')} km/h | Time: {d.get('utc_time')}")
                    
                # GPS STATUS LOGGING
                elif payload.get("type") == "gps_status":
                    if payload.get("status") == "searching":
                        print("⏳ Pi is actively searching for GPS satellites (No lock yet)...")
                        
                # SYSTEM EVENT LOGGING
                elif payload.get("type") == "sys_event":
                    for d in payload["data"]:
                        event = d.get("event")
                        if event == "4G_FALLBACK_TRIGGERED":
                            print(f"🚨🚨 [SYSTEM ALERT] RASPBERRY PI LOST WI-FI! Auto-Fallback to 4G Cellular Successful. 🚨🚨")
                        else:
                            print(f"🔧 [SYSTEM EVENT] {event}")
                        
                # LORA MESH TELEMETRY
                elif payload.get("type") == "mesh":
                    sql = """INSERT INTO mesh_data 
                             (timestamp_epoch, node_id, status, sta_lta_ratio, sta, lta, uptime_s, rssi, mag) 
                             VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)"""
                    records = []
                    for d in payload["data"]:
                        records.append((
                            d.get("t_epoch"), 
                            d.get("node"), 
                            d.get("status"), 
                            d.get("ratio"),
                            d.get("sta", 0.0), 
                            d.get("lta", 0.0), 
                            d.get("uptime", 0),
                            d.get("rssi", 0), 
                            d.get("mag", 0.0)
                        ))
                    if records:
                        cursor.executemany(sql, records)
                        for d in payload["data"]:
                            node = d.get("node", "UNKNOWN")
                            ratio = d.get("ratio", 0.0)
                            rssi = d.get("rssi", 0)
                            mag = d.get("mag", 0.0)
                            
                            if d.get("status") == "UNSAFE":
                                print(f"🔥🔥🔥 [DB] SAVED EMERGENCY LORA MESH ALERT | Node: {node} | Mag: {mag:.1f} | Signal: {rssi} dBm 🔥🔥🔥")
                            else:
                                print(f"📡 [DB] Saved LoRa Mesh Telemetry | Node: {node} | STA/LTA: {ratio:.2f} | Signal: {rssi} dBm")
                    
        except Exception as e:
            print(f"⚠️ Network drop or Error: {e}")
            break
    client_socket.close()

# Start Server
server = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
server.bind((HOST, PORT))
server.listen(5)
print(f"🚀 Windows Server is LIVE! Listening for Raspberry Pi on port {PORT}...")

while True:
    client_sock, addr = server.accept()
    print(f"🔒 Secure Connection Established with Pi at {addr[0]}")
    threading.Thread(target=handle_client, args=(client_sock,)).start()
