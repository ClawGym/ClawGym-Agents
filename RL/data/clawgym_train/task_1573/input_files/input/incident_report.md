Project: Arduino Uno R3 + DHT11 + SG90 micro servo + one pushbutton + one external LED

Summary symptoms
- The Uno randomly resets (bootloader LED flashes and sketch restarts) whenever the micro servo moves, especially at direction changes.
- DHT11 readings turn to garbage (nan, 0.0, or spikes) at the same times the servo twitches.
- Serial Monitor sometimes shows gibberish characters; occasionally uploads fail unless we close the Serial Monitor.

Power and wiring (current state)
- Power source: USB from laptop only (no external supply).
- Servo (SG90): 
  - Orange (signal) → D9
  - Red (Vcc) → Arduino 5V pin
  - Brown (GND) → Arduino GND
  - Note: No external power for the servo; powered straight off the Uno 5V pin.
- DHT11 (blue PCB module) on breadboard:
  - Vcc → 5V
  - GND → GND
  - Data → D2
  - Wires are ~30–40 cm female–male jumpers from Uno to breadboard.
  - No 0.1uF decoupling capacitor across Vcc/GND near the sensor module.
- Button:
  - One leg → D0 (pin 0)
  - Other leg → 5V
  - No resistor to ground; relying on code INPUT, so pin is effectively floating when open.
- LED (external on breadboard):
  - Anode → D1 (pin 1 / TX)
  - Cathode → GND
  - No series resistor used (direct drive from the pin).
- Grounds: Only the Uno’s GND is used. We did a quick test with a 4×AA holder for the servo, but we didn’t tie grounds together, and the servo didn’t respond correctly (jittered).

Observed behavior and notes
- With the servo connected to 5V on the Uno, moving the servo triggers resets (brown-out suspected).
- If we unplug the servo’s red wire (power), the DHT11 reads stable values with the same code and wiring otherwise.
- DHT11 values sometimes show “nan” or big jumps exactly when the servo moves.
- Serial Monitor baud mismatch occurred a couple of times: code uses 115200 but we sometimes had the monitor at 9600. Also noticed using pins 0 and 1 for the button and LED affects Serial output.
- Upload issues: sometimes “port busy” unless we close Serial Monitor first.

Software notes
- The current sketch:
  - Uses delay() in loops for servo sweeping and a 2-second delay between DHT reads.
  - Uses String for building print messages.
  - Uses pins 0 and 1 for the button and LED (conflicts with Serial RX/TX).
  - Reads the button as INPUT (not INPUT_PULLUP), so input is floating/spurious.

Assumptions/constraints
- We need non-blocking code: periodic DHT11 reads without delay(), and a servo move routine that doesn’t block other tasks.
- The button should be debounced and not left floating; prefer INPUT_PULLUP to eliminate external resistor for now.
- Keep Serial prints light to avoid timing interference.

Suspected root causes
- Brown-out resets due to servo current spikes on the Uno’s 5V rail (USB power only).
- Floating input on D0 causing unpredictable triggers.
- Pin conflicts with RX/TX (pins 0/1) used as GPIO interfering with Serial.
- Lack of decoupling near the DHT11 and long sensor leads causing noise coupling from the servo.

Requested deliverables (for reference)
- A corrected non-blocking sketch that avoids pins 0/1 for GPIO, uses millis()-based timing, uses INPUT_PULLUP for the button (with debounce), avoids String, and keeps Serial prints minimal.
- Concrete wiring remediation plan including external servo power (5–6V) with common ground, decoupling caps, LED current-limiting resistor, shorter sensor leads, and note that pins 0/1 are reserved for Serial.
- Troubleshooting report with root causes and step-by-step tests (ground checks, pullups, decoupling, pin usage, baud rate, and closing Serial Monitor before upload).

Environment
- Board: Arduino Uno R3
- Servo: SG90 micro (3-wire)
- Sensor: DHT11 module (with onboard pull-up for data)
- Tools: Arduino IDE 2.x on Windows; Serial Monitor used frequently