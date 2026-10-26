HSRP SMART PARKING - REAL-TIME TWO-SLOT PACKAGE
================================================

WHAT IS INCLUDED
- server.py: Flask server, SQLite event log, slot-state API, dashboard-data API, CSV export.
- templates/dashboard.html: professional live dashboard, latest vehicle panel, slot cards, event filters, registered vehicle list.
- templates/register.html: vehicle registration form.
- static/style.css: responsive styling.
- raspberry_pi/slot_sensor_monitor.py: separate sensor monitor for two HC-SR04 sensors.
- This script runs alongside your existing OCR/IR script, so it does not replace your Fast-ALPR pipeline.

IMPORTANT DATABASE NOTE
This server uses D:\HSRP_Parking\vehicles.db. Back up this file before switching servers. The code uses CREATE TABLE IF NOT EXISTS and adds missing event columns, but keep a backup before first run.

INSTALL ON WINDOWS
1. Stop the old Flask server with Ctrl+C.
2. Back up the current project:
   Copy-Item .\server.py .\server.py.backup
   Copy-Item .\vehicles.db .\vehicles.backup.db
   Copy-Item .\templates\dashboard.html .\templates\dashboard.backup.html
3. Copy package server.py to D:\HSRP_Parking\server.py.
4. Copy templates\dashboard.html to D:\HSRP_Parking\templates\dashboard.html.
5. Copy templates\register.html to D:\HSRP_Parking\templates\register.html.
6. Copy static\style.css to D:\HSRP_Parking\static\style.css.
7. Run:
   Set-Location D:\HSRP_Parking
   python server.py
8. Open http://127.0.0.1:5000/dashboard and press Ctrl+F5.

RASPBERRY PI SETUP
1. Copy raspberry_pi/slot_sensor_monitor.py to:
   ~/hsrp_parking/parking/slot_sensor_monitor.py
2. In the script, update HSRP_SERVER_URL if the PC IP has changed. Default is:
   http://10.85.91.237:5000
   Or run it with:
   HSRP_SERVER_URL=http://YOUR_PC_IP:5000 python slot_sensor_monitor.py
3. Activate the existing venv and install requests if needed:
   cd ~/hsrp_parking/parking
   source .venv/bin/activate
   pip install requests
   sudo python slot_sensor_monitor.py
   If lgpio works without sudo in your setup, run without sudo but use the same Python environment.
4. Run this as a separate terminal/process alongside the current OCR script.

WIRING (BCM GPIO)
Slot 1: TRIG GPIO23, ECHO GPIO24.
Slot 2: TRIG GPIO25, ECHO GPIO5.
Grounds must be common. HC-SR04 ECHO is 5 V: use a resistor divider/level shifter so the Raspberry Pi GPIO sees <=3.3 V. Never connect 5 V ECHO directly to Pi GPIO.

CALIBRATION
- Default occupied threshold: 35 cm. Measure the empty-slot distance and the distance to a vehicle in the installed geometry; change HSRP_SLOT_THRESHOLD_CM accordingly.
- The monitor requires three consistent readings before changing state.
- Sensors are read sequentially to reduce cross-talk.
- On a sensor read error, it preserves the last stable occupancy state and reports sensor_error.
- If the sensor is mounted facing downward, calibrate threshold based on floor distance vs vehicle roof distance.

REAL-TIME VEHICLE DETAILS
The dashboard can only show real OCR vehicle details after the OCR process reports the result to Flask using POST /api/vehicle-event with JSON:
{
  "plate": "UP16AB1234",
  "direction": "entry",
  "result": "approved",
  "note": "OCR confidence 0.92",
  "image_filename": "vehicle_capture.jpg"
}
For exit, set direction to "exit". The current OCR script should call this endpoint once it has finalized the plate and decision. This package retains /api/authorize, but you may need to add the POST /api/vehicle-event call in your existing server_test.py after the OCR decision.
If you share your current server_test.py, the exact integration can be inserted without replacing the OCR loop.

CSV EXPORT
Use the Export CSV button. Filters include plate, direction and date. CSV can be opened in Excel.

SECURITY
No-login mode is enabled as requested. Anyone who can reach the Flask server can modify records. Use only on a trusted local network and do not expose port 5000 to the public internet.
