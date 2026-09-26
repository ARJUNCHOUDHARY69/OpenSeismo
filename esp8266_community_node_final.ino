/* ==============================================================================
 * Project: OpenSeismo - Decentralized Edge-AI Earthquake Detection
 * Copyright (c) 2026 OpenSeismo Project (FOSSEE Hackathon Submission)
 * 
 * This software is released under the MIT License.
 * The hardware designs are released under the CC BY-SA 4.0 License.
 * ============================================================================== */
#include <SPI.h>
#include <LoRa.h>
#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>

// --- PINS ---
#define LORA_SS 5       // D1
#define LORA_DIO0 4     // D2
#define LORA_RST 16     // D0
#define I2C_SDA 0       // D3
#define I2C_SCL 2       // D4
#define BUZZER_PIN 15   // D8

Adafruit_SSD1306 display(128, 64, &Wire, -1);

const int MPU_ADDR = 0x68;
float sta = 0.0;
float lta = 0.1;
float last_ax = 0, last_ay = 0, last_az = 0;

bool alarmActive = false;
unsigned long alarmEndTime = 0;
unsigned long lastMpuRead = 0;
unsigned long lastHealthPing = 0;
unsigned long lastDisplayUpdate = 0;

// UI Variables
unsigned long timeOfLastQuake = 0;
float maxMagnitude = 0.0;
String alarmSource = "";
uint8_t graphData[128] = {0}; // Holds the scrolling seismograph points

void setup() {
  Serial.begin(115200);

  pinMode(BUZZER_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);

  Wire.begin(I2C_SDA, I2C_SCL);

  if(!display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    Serial.println(F("OLED failed to initialize!"));
  } else {
    display.clearDisplay();
    display.setTextColor(WHITE);
    display.setTextSize(1);
    display.setCursor(0, 0);
    display.println("NODE: SLAVE_01");
    display.println("Booting TX Mode...");
    display.display();
  }

  // Wake up MPU6050
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x6B);
  Wire.write(0);
  Wire.endTransmission(true);

  LoRa.setPins(LORA_SS, LORA_RST, LORA_DIO0);
  if (!LoRa.begin(433E6)) {
    Serial.println("Starting LoRa failed!");
    while (1) { yield(); }
  }

  LoRa.setSpreadingFactor(12);
  LoRa.setSignalBandwidth(125E3);
  LoRa.enableCrc(); 

  // ESP IS TRANSMIT ONLY. We just leave it in STANDBY.
  // DO NOT call LoRa.sleep() as it causes oscillator startup failures!

  Serial.println("✅ Node SLAVE_01 Initialized in ONE-WAY TRANSMIT MODE");
  updateNormalDisplay();
}

void loop() {
  unsigned long currentMillis = millis();

  // 1. Check for Local Earthquake (50 times a second)
  if (currentMillis - lastMpuRead >= 20) {
    lastMpuRead = currentMillis;
    checkLocalEarthquake();
  }

  // 2. Handle Display & Alarm Flashing (Updates every 100ms)
  if (currentMillis - lastDisplayUpdate >= 100) {
    lastDisplayUpdate = currentMillis;

    if (alarmActive) {
      if (currentMillis > alarmEndTime) {
        // Time is up, turn off alarm
        alarmActive = false;
        noTone(BUZZER_PIN);
        digitalWrite(BUZZER_PIN, LOW);
        maxMagnitude = 0.0; 
        updateNormalDisplay();
      } else {
        bool flashState = ((currentMillis / 150) % 2 == 0);

        if (flashState) tone(BUZZER_PIN, 2500); 
        else noTone(BUZZER_PIN);

        display.clearDisplay();
        if (flashState) {
          display.fillRect(0, 0, 128, 64, WHITE);
          display.setTextColor(BLACK, WHITE);
        } else {
          display.fillRect(0, 0, 128, 64, BLACK);
          display.setTextColor(WHITE, BLACK);
        }

        display.setTextSize(2);
        display.setCursor(5, 5);
        display.println("EARTHQUAKE");

        display.setTextSize(1);
        display.setCursor(5, 30);
        display.print("MAGNITUDE: ");
        display.print(maxMagnitude, 1); 

        display.setCursor(5, 50);
        display.print("SRC: ");
        display.print(alarmSource);
        display.display();
      }
    } else {
      updateNormalDisplay();
    }
  }

  // 3. Send Health Ping every 5 seconds (Strictly ONE-WAY)
  if (currentMillis - lastHealthPing >= 5000 && !alarmActive) {
    lastHealthPing = currentMillis;
    
    Serial.print("📡 [LORA TX] Sending routine telemetry | STA/LTA: ");
    Serial.println(sta/lta, 2);
    
    LoRa.beginPacket();
    LoRa.print("{\"type\":\"health\", \"node\":\"slave_01\", \"status\":\"SAFE\", \"ratio\":");
    LoRa.print(sta/lta, 2);
    LoRa.print(", \"sta\":");
    LoRa.print(sta, 4);
    LoRa.print(", \"lta\":");
    LoRa.print(lta, 4);
    LoRa.print(", \"uptime\":");
    LoRa.print(millis() / 1000);
    LoRa.print("}");
    LoRa.endPacket();
    
    // NOTE: Removed LoRa.sleep() because going from Sleep -> TX causes
    // oscillator stabilization crashes on some SX1278 modules. 
    // The library automatically leaves the radio in STANDBY after endPacket().
  }
}

// ==========================================
void checkLocalEarthquake() {
  Wire.beginTransmission(MPU_ADDR);
  Wire.write(0x3B);
  Wire.endTransmission(false);
  Wire.requestFrom(MPU_ADDR, 6, true);

  int16_t ax_raw = Wire.read() << 8 | Wire.read();
  int16_t ay_raw = Wire.read() << 8 | Wire.read();
  int16_t az_raw = Wire.read() << 8 | Wire.read();

  float ax = ax_raw / 16384.0;
  float ay = ay_raw / 16384.0;
  float az = az_raw / 16384.0;

  float delta = abs(ax - last_ax) + abs(ay - last_ay) + abs(az - last_az);
  last_ax = ax; last_ay = ay; last_az = az;

  sta = sta * 0.95 + delta * 0.05;
  lta = lta * 0.995 + delta * 0.005;
  if (lta < 0.01) lta = 0.01;

  float ratio = sta / lta;

  // --- UPDATE THE SCROLLING SEISMOGRAPH ARRAY ---
  for (int i = 0; i < 127; i++) {
    graphData[i] = graphData[i+1];
  }
  int plotValue = (int)((ratio - 1.0) * 8.0);
  if (plotValue < 0) plotValue = 0;
  if (plotValue > 31) plotValue = 31;
  graphData[127] = plotValue;

  // --- TRIGGER QUAKE ---
  if (ratio > 1.5 && !alarmActive) {
    maxMagnitude = (ratio - 1.5) * 2.0 + 4.0;
    if (maxMagnitude > 9.9) maxMagnitude = 9.9;

    triggerAlarm("LOCAL MPU6050");

    Serial.println("🚨 [LORA TX] BROADCASTING EMERGENCY ALERT TO PI!");
    LoRa.beginPacket();
    LoRa.print("{\"type\":\"alert\", \"node\":\"slave_01\", \"alert\":1, \"ratio\":");
    LoRa.print(ratio, 2);
    LoRa.print(", \"mag\":");
    LoRa.print(maxMagnitude, 2);
    LoRa.print("}");
    LoRa.endPacket();
  }
}

void triggerAlarm(String source) {
  if (!alarmActive) {
    alarmActive = true;
    alarmSource = source;
    timeOfLastQuake = millis(); 
    alarmEndTime = millis() + 5000; 
  }
}

void updateNormalDisplay() {
  display.clearDisplay();
  display.setTextColor(WHITE, BLACK);
  display.setTextSize(1);

  // Top 32 pixels: Hardcore Text Stats
  display.setCursor(0, 0);
  display.print("NODE: SLAVE_01");
  
  display.setCursor(0, 8);
  display.print("MODE: TX ONLY");

  display.setCursor(0, 16);
  display.print("STA/LTA: ");
  display.print(sta/lta, 2); 

  display.setCursor(0, 24);
  unsigned long safeSeconds = (millis() - timeOfLastQuake) / 1000;
  display.print("Uptime : ");
  display.print(safeSeconds);
  display.print("s Safe");

  // Bottom 32 pixels: LIVE SCROLLING SEISMOGRAPH!
  for (int i = 0; i < 127; i++) {
    display.drawLine(i, 63 - graphData[i], i+1, 63 - graphData[i+1], WHITE);
  }

  display.display();
}
