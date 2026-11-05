#include <OneWire.h>
#include <DallasTemperature.h>

// =====================================
// PIN CONFIGURATION
// =====================================

// DS18B20 Temperature Sensor (needs 4.7k pull-up from DATA to 5V)
#define ONE_WIRE_BUS A1

// Turbidity Sensor
#define TURBIDITY_PIN A0

// HC-SR04 Ultrasonic Sensor (VCC=5V, GND=GND)
#define TRIG_PIN 2
#define ECHO_PIN 3

// =====================================
// TEMPERATURE SENSOR
// =====================================

OneWire oneWire(ONE_WIRE_BUS);
DallasTemperature sensors(&oneWire);

float Celsius = 0;

// =====================================
// TURBIDITY SENSOR
// =====================================

int sensorValue = 0;
int turbidity = 0;

// =====================================
// ULTRASONIC SENSOR
// =====================================

// Distance from sensor face to tank BOTTOM (cm). Include mount height.
const float TANK_HEIGHT = 30.0;
float waterDistance = 0;
float waterLevel = 0;
float waterLevelPercentage = 0;

void setup() {
  Serial.begin(9600);
  sensors.begin();
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  digitalWrite(TRIG_PIN, LOW);
  delay(500);
}

float getDistance() {
  digitalWrite(TRIG_PIN, LOW);
  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH);
  delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);

  // 30ms timeout ≈ ~5m; 0 means no echo
  long duration = pulseIn(ECHO_PIN, HIGH, 30000);
  if (duration == 0) {
    return -1;
  }
  return duration * 0.0343 / 2.0;
}

void loop() {
  bool tempConnected = false;
  bool levelValid = false;
  const char* waterStatus = "UNKNOWN";

  // --- Temperature (DS18B20) ---
  sensors.requestTemperatures();
  Celsius = sensors.getTempCByIndex(0);

  if (Celsius != DEVICE_DISCONNECTED_C &&
      Celsius >= -55 && Celsius <= 125) {
    tempConnected = true;
  }

  // --- Turbidity ---
  // Typical analog modules: higher ADC ≈ clearer water.
  // Dirtiness index 0–100 across the full ADC range (so clear water is not stuck at 0).
  sensorValue = analogRead(TURBIDITY_PIN);
  turbidity = map(sensorValue, 0, 1023, 100, 0);
  turbidity = constrain(turbidity, 0, 100);

  if (turbidity < 20) {
    waterStatus = "CLEAR";
  } else if (turbidity < 50) {
    waterStatus = "CLOUDY";
  } else {
    waterStatus = "DIRTY";
  }

  // --- Water level (HC-SR04) ---
  waterDistance = getDistance();
  // Accept echoes a bit beyond tank height so mount offset still shows up
  if (waterDistance > 0 && waterDistance <= (TANK_HEIGHT + 20.0)) {
    waterLevel = TANK_HEIGHT - waterDistance;
    if (waterLevel < 0) waterLevel = 0;
    if (waterLevel > TANK_HEIGHT) waterLevel = TANK_HEIGHT;
    waterLevelPercentage = (waterLevel / TANK_HEIGHT) * 100.0;
    levelValid = true;
  }

  // One JSON object per line for the Node serial bridge
  Serial.print("{");
  Serial.print("\"temperatureC\":");
  if (tempConnected) Serial.print(Celsius, 2);
  else Serial.print("null");
  Serial.print(",\"tempConnected\":");
  Serial.print(tempConnected ? "true" : "false");
  Serial.print(",\"turbidityRaw\":");
  Serial.print(sensorValue);
  Serial.print(",\"turbidity\":");
  Serial.print(turbidity);
  Serial.print(",\"waterStatus\":\"");
  Serial.print(waterStatus);
  Serial.print("\",\"distanceCm\":");
  // Always report distance when an echo was received (helps wiring debug)
  if (waterDistance > 0) Serial.print(waterDistance, 2);
  else Serial.print("null");
  Serial.print(",\"waterLevelCm\":");
  if (levelValid) Serial.print(waterLevel, 2);
  else Serial.print("null");
  Serial.print(",\"waterLevelPct\":");
  if (levelValid) Serial.print(waterLevelPercentage, 1);
  else Serial.print("null");
  Serial.print(",\"tankHeightCm\":");
  Serial.print(TANK_HEIGHT, 1);
  Serial.print(",\"levelValid\":");
  Serial.print(levelValid ? "true" : "false");
  Serial.println("}");

  delay(1000);
}
