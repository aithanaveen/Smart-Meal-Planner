# 🥗 Smart Meal Planner: IoT Kitchen Management System

An intelligent, end-to-end IoT solution designed to modernize kitchen management. This system tracks pantry inventory using RFID and load cells, provides a real-time dashboard for inventory management, and allows for automated appliance control.

---

## 🚀 Features

### 🛒 Smart Pantry Tracking
- **RFID Identification**: Automatically identify ingredients as they are placed in the pantry.
- **Load Cell Weighing**: Precision tracking of ingredient quantities by weight.
- **Real-time Synchronization**: Instant updates to the backend database upon sensor changes.

### 📱 Digital Dashboard
- **Inventory Overview**: Visual breakdown of current stock levels and weights.
- **Live Kitchen Feed**: Real-time activity log using Server-Sent Events (SSE).
- **Shopping List**: Automatically generated lists based on low-stock alerts.
- **Mobile Responsive**: Access your kitchen status from any device.

### ⚡ Appliance Control
- **Remote Toggle**: Control kitchen appliances (via Relays or IR) directly from the web interface.
- **Automated Alerts**: Buzzer feedback on the hardware for successful scans or weight thresholds.

---

## 🛠️ Technology Stack

- **Frontend**: HTML5, CSS3 (Vanilla), JavaScript (ES6+)
- **Backend**: Python, Flask, SQLite3
- **Hardware**: ESP32, MFRC522 RFID Reader, HX711 Load Cell, 5V Relay, Buzzer
- **Communication**: REST API, Server-Sent Events (SSE)

---

## 📂 Project Structure

```text
Smart-Meal/
├── backend/            # Flask Server & Database logic
│   ├── app.py          # Main application entry point
│   └── instance/       # SQLite database storage
├── frontend/           # Web Dashboard
│   ├── index.html      # UI Structure
│   └── style.css       # Premium Design System
├── esp32/              # Arduino/C++ Firmware
│   └── smart_pantry.ino# Hardware logic for sensors & controls
└── requirements.txt    # Python dependencies
```

---

## ⚙️ Setup & Installation

### 1. Backend Setup
```bash
# Navigate to the backend directory
cd backend

# Install dependencies
pip install -r ../requirements.txt

# Start the Flask server
python app.py
```

### 2. Frontend Access
Simply open `frontend/index.html` in your browser, or access it via the Flask local server URL (usually `http://127.0.0.1:5000`).

### 3. ESP32 Configuration
1. Open `esp32/smart_pantry.ino` in the Arduino IDE.
2. Install necessary libraries: `MFRC522`, `HX711`.
3. Update your WiFi credentials and Backend IP address in the code.
4. Upload to your ESP32 board.

---

## 📸 Screenshots
*(Add your generated images or screenshots here)*

---

## 🤝 Contributing
Contributions are welcome! Please feel free to submit a Pull Request.

## 📝 License
This project is licensed under the MIT License.