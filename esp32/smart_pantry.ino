#include <SPI.h>
#include <MFRC522.h>
#include <HX711.h>
#include <WiFi.h>
#include <HTTPClient.h>
#include <WebServer.h>
#include <ArduinoJson.h>

// ============================================================
//  PIN DEFINITIONS
// ============================================================
#define SS_PIN           5    // RC522 SDA/SS
#define RST_PIN          22   // RC522 RST
#define DOUT_PIN         16   // HX711 Data Out
#define CLK_PIN          17   // HX711 Clock
#define IR_LED_PIN       4    // IR LED (via NPN transistor)
#define BUZZER_PIN       2    // Buzzer (Beeps on scan/startup)

// SPI Pins
#define SCK_PIN          18
#define MISO_PIN         19
#define MOSI_PIN         23

// ============================================================
//  CALIBRATION
// ============================================================
#define CALIBRATION_FACTOR  2280.0f   // Adjust for your load cell

// ============================================================
//  WIFI & SERVER CONFIGURATION
// ============================================================
const char* ssid      = "JioFiber-u8pNk";
const char* password  = "uiqu7phoolahDab3";
const char* postURL   = "http://192.168.29.22:5000/update-weight";
const char* signalURL = "http://192.168.29.22:5000/cooking-signal";

// ============================================================
//  RFID → INGREDIENT MAP
// ============================================================
struct TagMap {
  const char* uid;
  const char* ingredient;
};

TagMap tags[] = {
  { "A1B2C3D4", "Rice"      },
  { "B2C3D4E5", "Milk"      },
  { "C3D4E5F6", "Flour"     },
  { "D4E5F6A1", "Sugar"     },
  { "E5F6A1B2", "Olive Oil" },
  { "F6A1B2C3", "Butter"    },
};
const int TAG_COUNT = sizeof(tags) / sizeof(tags[0]);

// ============================================================
//  OBJECT INSTANCES
// ============================================================
MFRC522 rfid(SS_PIN, RST_PIN);
HX711   scale;
WebServer debugServer(80);

// ============================================================
//  GLOBALS
// ============================================================
String lastScannedUID = "None";
String lastIngredient = "None";
float  lastWeight     = 0.0;
bool   wifiConnected  = false;

// Timing
unsigned long lastSignalCheck  = 0;
const unsigned long SIGNAL_INTERVAL = 5000;   // 5 seconds
const unsigned long WIFI_RETRY_MS   = 10000;  // 10 seconds between reconnect attempts
unsigned long lastWifiRetry = 0;

// ============================================================
//  HELPERS & FEEDBACK
// ============================================================

void beep(int ms) {
  digitalWrite(BUZZER_PIN, HIGH);
  delay(ms);
  digitalWrite(BUZZER_PIN, LOW);
}

void startupMelody() {
  beep(100); delay(50);
  beep(100); delay(50);
  beep(200);
}

String uidToString(MFRC522::Uid uid) {
  String result = "";
  for (byte i = 0; i < uid.size; i++) {
    if (uid.uidByte[i] < 0x10) result += "0";
    result += String(uid.uidByte[i], HEX);
  }
  result.toUpperCase();
  return result;
}

const char* lookupIngredient(const String& uid) {
  for (int i = 0; i < TAG_COUNT; i++) {
    if (uid.equals(tags[i].uid)) return tags[i].ingredient;
  }
  return nullptr;
}

// ============================================================
//  WEB SERVER (DEBUG OUTPUT)
// ============================================================

void handleRoot() {
  String html = "<!DOCTYPE html><html><head><meta http-equiv='refresh' content='3'>";
  html += "<style>body{font-family:sans-serif; text-align:center; background:#f4f4f9; padding:20px;}";
  html += ".card{background:white; padding:20px; border-radius:10px; box-shadow:0 2px 10px rgba(0,0,0,0.1); display:inline-block;}";
  html += "h1{color:#2c3e50;} .val{font-size:1.5em; font-weight:bold; color:#e67e22;}</style></head><body>";
  html += "<h1>Smart Pantry ESP32 Debug</h1>";
  html += "<div class='card'>";
  html += "<h3>WiFi Status: <span style='color:" + String(wifiConnected ? "green" : "red") + "'>" + (wifiConnected ? "Connected" : "Disconnected") + "</span></h3>";
  html += "<p><b>IP Address:</b> " + WiFi.localIP().toString() + "</p>";
  html += "<hr>";
  html += "<p><b>Last RFID Scanned:</b> <br><span class='val'>" + lastScannedUID + "</span></p>";
  html += "<p><b>Identified As:</b> <br><span class='val'>" + lastIngredient + "</span></p>";
  html += "<p><b>Last Weight:</b> <br><span class='val'>" + String(lastWeight, 1) + "g</span></p>";
  html += "</div></body></html>";
  debugServer.send(200, "text/html", html);
}

// ============================================================
//  WIFI MANAGEMENT
// ============================================================

void connectWiFi() {
  Serial.print("[WiFi] Connecting to ");
  Serial.println(ssid);
  WiFi.mode(WIFI_STA);
  WiFi.begin(ssid, password);
  
  // Non-blocking wait for initial connection (15s)
  unsigned long t = millis();
  while (WiFi.status() != WL_CONNECTED && millis() - t < 15000) {
    delay(500);
    Serial.print(".");
  }

  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    Serial.println("\n[WiFi] Connected! IP: " + WiFi.localIP().toString());
    beep(500); // Single long beep for success
  } else {
    wifiConnected = false;
    Serial.println("\n[WiFi] Initial connection failed.");
  }
}

bool ensureWiFi() {
  if (WiFi.status() == WL_CONNECTED) {
    wifiConnected = true;
    return true;
  }
  
  wifiConnected = false;
  unsigned long now = millis();
  if (now - lastWifiRetry < WIFI_RETRY_MS) return false;
  lastWifiRetry = now;

  Serial.println("[WiFi] Reconnecting...");
  WiFi.begin(ssid, password);
  return false;
}

// ============================================================
//  HTTP TASKS
// ============================================================

void postWeightToServer(const String& rfidUid, const char* ingredient, float weight) {
  if (!ensureWiFi()) return;

  StaticJsonDocument<200> doc;
  doc["rfid_uid"]   = rfidUid;
  doc["ingredient"] = ingredient;
  doc["weight"]     = (int)weight;

  String jsonPayload;
  serializeJson(doc, jsonPayload);

  HTTPClient http;
  http.begin(postURL);
  http.addHeader("Content-Type", "application/json");
  http.setTimeout(5000);

  int httpCode = http.POST(jsonPayload);
  if (httpCode == 200) {
    Serial.println("[HTTP] Weight updated successfully.");
  } else {
    Serial.printf("[HTTP] POST failed, code: %d\n", httpCode);
  }
  http.end();
}

void checkCookingSignal() {
  if (!ensureWiFi()) return;

  HTTPClient http;
  http.begin(signalURL);
  http.setTimeout(4000);
  int httpCode = http.GET();

  if (httpCode == 200) {
    String payload = http.getString();
    DynamicJsonDocument doc(512);
    deserializeJson(doc, payload);

    if (doc["pending"] | false) {
      const char* recipe = doc["recipe"] | "Recipe";
      JsonArray steps = doc["steps"].as<JsonArray>();
      
      Serial.println("[Signal] Received cooking signal: " + String(recipe));
      beep(100); delay(50); beep(100); // Double beep for signal
      
      for (JsonVariant v : steps) {
        Serial.println("[IR] Firing signal for: " + v.as<String>());
        digitalWrite(IR_LED_PIN, HIGH);
        delay(1000);
        digitalWrite(IR_LED_PIN, LOW);
        delay(500);
      }
    }
  }
  http.end();
}

// ============================================================
//  CORE LOGIC
// ============================================================

void handleRFIDScan() {
  if (!rfid.PICC_IsNewCardPresent()) return;
  if (!rfid.PICC_ReadCardSerial())   return;

  // 🔊 Instant beep on detection to confirm hardware is working!
  beep(150);

  String uidStr = uidToString(rfid.uid);
  lastScannedUID = uidStr;
  
  const char* ingredient = lookupIngredient(uidStr);
  lastIngredient = (ingredient != nullptr) ? ingredient : "Unknown Tag";

  Serial.println("[RFID] Scanned: " + uidStr + " (" + lastIngredient + ")");

  // Scale read
  delay(1000);
  float weight = 0.0f;
  if (scale.is_ready()) {
    weight = scale.get_units(5);
    if (weight < 0) weight = 0.0f;
  }
  lastWeight = weight;
  Serial.printf("[Scale] Weight: %.1fg\n", weight);

  if (ingredient != nullptr) {
    postWeightToServer(uidStr, ingredient, weight);
  }

  rfid.PICC_HaltA();
  rfid.PCD_StopCrypto1();
  delay(2000); // Prevent spamming
}

// ============================================================
//  MAIN
// ============================================================

void setup() {
  Serial.begin(115200);
  pinMode(BUZZER_PIN, OUTPUT);
  pinMode(IR_LED_PIN, OUTPUT);
  digitalWrite(BUZZER_PIN, LOW);
  digitalWrite(IR_LED_PIN, LOW);

  // Initial feedback: Confirm buzzer works!
  startupMelody();
  Serial.println("\n[System] Starting...");

  // RFID Setup with explicit SPI pins
  SPI.begin(SCK_PIN, MISO_PIN, MOSI_PIN, SS_PIN);
  rfid.PCD_Init();
  Serial.println("[RFID] Initialized");

  // Scale Setup
  scale.begin(DOUT_PIN, CLK_PIN);
  scale.set_scale(CALIBRATION_FACTOR);
  scale.tare();
  Serial.println("[Scale] Initialized and Tared");

  // WiFi Setup
  connectWiFi();

  // Debug Web Server
  debugServer.on("/", handleRoot);
  debugServer.begin();
  Serial.println("[System] Debug server started at port 80");
  
  Serial.println("[System] Setup complete.");
}

void loop() {
  debugServer.handleClient();
  handleRFIDScan();

  unsigned long now = millis();
  if (now - lastSignalCheck >= SIGNAL_INTERVAL) {
    lastSignalCheck = now;
    checkCookingSignal();
  }
  
  ensureWiFi(); // Background check
  delay(10);
}
