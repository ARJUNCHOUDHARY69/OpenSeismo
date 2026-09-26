# OpenSeismoPi 🌍🚨
> **An Open-Source, Low-Cost Earthquake Early Warning & Detection IoT System**
> Developed for the **FOSSEE Open Hardware Make-A-Thon 2026 (IIT Bombay)**

**OpenSeismoPi** is an affordable, Raspberry Pi-based earthquake early warning system designed to detect tremors and alert communities before disaster strikes. By constantly monitoring sensitive motion and environmental sensors, it identifies the initial signs of an earthquake using a specialized mathematical algorithm. The moment a dangerous tremor is confirmed, the system immediately sounds a local alarm, dispatches emergency SMS text warnings over a 4G LTE cellular network, and seamlessly triggers remote community receiver nodes using long-range LoRa radio. Simultaneously, all live seismic data is securely transmitted to a central computer, where a real-time web dashboard displays the earthquake's waveforms and system status to keep everyone informed and safe.

---

## 🏗️ How It Works (The Physics & Math)
Earthquakes emit multiple types of seismic waves. The two most important for early warning systems are:
1. **P-Waves (Primary Waves):** These travel extremely fast (5-8 km/s) but are compressional and generally cause no structural damage.
2. **S-Waves (Secondary Waves):** These travel slower (3-4 km/s) but are transverse, shear waves that cause severe destruction to buildings and infrastructure.

**OpenSeismoPi** takes advantage of this speed difference. By detecting the harmless P-wave the moment it arrives, the system can issue an emergency alert, providing crucial seconds (or even minutes) of warning time before the destructive S-wave hits.

### The STA/LTA Algorithm
To distinguish between an actual earthquake P-wave and ambient background noise (like a truck driving by or someone dropping a heavy box), the Raspberry Pi runs the **Short-Term Average over Long-Term Average (STA/LTA)** algorithm at a fast 50Hz loop rate. 
- **STA (Short-Term Average):** Reacts instantly to sudden spikes in seismic energy. (Window: 0.5 seconds)
- **LTA (Long-Term Average):** Tracks the steady baseline background noise of the environment. (Window: 10.0 seconds)
- **Trigger:** When the ratio of STA divided by LTA exceeds a critical threshold (≥ 2.0), an earthquake is officially declared.

![STA/LTA Earthquake Trigger Graph](sta_lta_graph.png)
*(Above: A generated plot illustrating how the STA/LTA algorithm filters background noise and cleanly triggers when an earthquake P-Wave arrives.)*

---

## 📡 System Architecture & Communication Stack
OpenSeismoPi is highly modular, featuring a master compute node and remote mesh nodes.

![Communication Stack Architecture](communication_stack_diagram.jpg)

### Four Distinct Protocols:
1. **I2C Bus (400kHz):** Connects the Raspberry Pi to high-precision sensors (MPU6050, BMP280, AHT20).
2. **SPI Bus (10MHz):** Interfaces with the SX1278 LoRa radio for long-range alert transmission.
3. **UART/USB (115200 Baud):** Communicates with the Quectel EC200U 4G LTE Modem using AT commands.
4. **LoRa Wireless (433/868 MHz):** Beams the emergency triggers to remote ESP8266 community nodes up to 5km away.

---

## 🗺️ Network Topology & Zero-Trust Security
![Network Topology](network_topology_diagram.jpg)

Instead of relying solely on local Wi-Fi, the system features **Hardware-Level 4G Auto-Failover**. If an earthquake destroys local fiber-optic lines, the system seamlessly routes telemetry through the cellular modem. 

Furthermore, all telemetry data is transmitted from the Pi to the Windows Database over a **Tailscale WireGuard VPN Tunnel**. This ensures zero-trust encryption, meaning the system can be deployed anywhere in the world without requiring dangerous port-forwards on local routers.

---

## ✅ Pros & Advantages
- **Low Cost & Accessible:** Built entirely from off-the-shelf hobbyist components (Raspberry Pi, MPU6050, ESP8266), making it affordable for developing nations.
- **Redundancy:** Fuses data from two separate accelerometers (MPU6050 + ADXL345) to prevent false positives.
- **Off-Grid Alerting:** If cellular towers collapse, the LoRa mesh network continues to alert nearby community nodes completely off-grid.
- **High-Frequency Sampling:** The Python edge script manages a strict 50Hz (20ms) polling rate for professional-grade wave detection.
- **Plug-and-Play Dashboard:** The backend MariaDB effortlessly powers a live Flask dashboard.

## ❌ Cons & Limitations
- **Sensor Precision:** The MPU6050 and ADXL345 are excellent MEMS sensors but lack the extreme sensitivity of professional broadband seismometers used by geological surveys. They cannot detect micro-quakes from hundreds of miles away.
- **GPS Cold Start Delay:** The Quectel EC200U GPS requires a clear view of the sky and can take 1-3 minutes for a "cold start" satellite lock upon reboot.
- **Single Point of Failure:** While network links are redundant, the entire system relies on the Raspberry Pi maintaining power. An Uninterruptible Power Supply (UPS) is strictly required for real-world deployment.

---

## 🔮 Future Scope
- **AI/Machine Learning:** Replacing the basic STA/LTA algorithm with a pre-trained Edge AI neural network (e.g., TensorFlow Lite) for highly advanced P-wave signature recognition, further reducing false positives.
- **Decentralized LoRa Mesh:** Expanding the ESP8266 community nodes to act as two-way repeaters, allowing the alert signal to hop endlessly across mountain villages.
- **Solar Power:** Upgrading the nodes with MPPT solar charge controllers for permanent, self-sustaining off-grid deployment.

---

## 🚀 Installation & Quick Start

### 1. Master Node Setup (Raspberry Pi 4)
```bash
# Enable I2C and SPI interfaces
sudo raspi-config

# Install required Python libraries
sudo pip3 install pyserial adafruit-blinka smbus2 adafruit-circuitpython-ahtx0 adafruit-circuitpython-bmp280 adafruit-circuitpython-adxl34x --break-system-packages

# Execute the primary daemon
python3 pi_secure_sender.py
```

### 2. Database Server Setup (Windows)
```cmd
# Ensure MariaDB is running on port 3307 and Tailscale VPN is active
# Start the ingestion script
python win_db_ingester.py
```

---

## 📜 License
This project utilizes a dual-license approach to protect both the software and hardware components:
- **Software:** [MIT License](LICENSE)
- **Hardware & Documentation:** Creative Commons Attribution-ShareAlike 4.0 International (CC BY-SA 4.0)

See the `LICENSE` file for full details.
