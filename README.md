# Chronis HW-1

> **Sensor Processing & Adaptive Capture Simulation Framework**

A modular Python simulation framework that emulates the sensing pipeline of an intelligent wearable device. The project simulates hardware sensors, processes user activity, dynamically adjusts media capture, and enforces architectural constraints through independent software daemons.

---

## Project Overview

Chronis HW-1 models the software stack of a wearable AI device capable of processing sensor data and adapting its capture behavior based on user activity.

The framework includes:

- Mock Hardware Abstraction Layer (HAL)
- Synthetic sensor trace generation
- Motion and posture analysis
- Heart-rate signal quality estimation
- Adaptive capture state machine
- Camera and audio capture daemons
- Worn / Not-Worn detection
- Encryption-first storage pipeline
- Comprehensive automated testing

The project follows a modular architecture where every subsystem communicates only through well-defined interfaces.

---

## Features

### Mock Hardware Abstraction Layer (HAL)

- Simulated I2C sensor interface
- Simulated GPIO interface
- Mock camera frame generation
- Explicit `SensorUnavailable` handling
- No fabricated sensor values

---

### Synthetic Trace Generator

Generates realistic synthetic datasets for four scenarios:

- 💤 Idle / Dormant
- 🌤 Ambient Environment
- 💬 Active Conversation
- 🎉 Multi-Party High Energy

Each trace contains:

- Timestamp
- Accelerometer (XYZ)
- Gyroscope (XYZ)
- Heart Rate
- Audio Energy

---

### Motion Processing Daemon

- Orientation tracking
- Motion classification
- Posture detection
- Gesture energy computation
- Change-point detection
- Double-tap detection

---

### Heart Rate Daemon

- Heart-rate processing
- Signal quality estimation
- Continuous confidence scoring (0–1)

---

### Anchor Gesture Detector

- Detects double-tap gestures
- Creates 30-second annotation windows
- Guaranteed not to modify capture state
- Guaranteed not to trigger camera capture

---

### Camera Daemon

- Mock frame capture
- Timestamp generation
- Encryption handoff before storage
- Enforces encrypted payload interface

---

### Audio Daemon

Supports multiple operating modes:

- 8 kHz Buffer Only
- 8 kHz Saved
- 16 kHz Continuous
- 16 kHz Full Quality
- 48 kHz Lossless

---

### Worn / Not-Worn Detector

Weighted decision using:

- Heart-rate signal quality
- Orientation variance
- Accelerometer activity

Automatically:

- Disables capture when not worn
- Performs gradual wake-up on wear detection
- Logs state transitions

---

### Adaptive Capture State Machine

Implements six capture intensity levels.

| Level | Description |
|--------|-------------|
| L0 | Dormant |
| L1 | Ambient |
| L2 | Passive |
| L3 | Active |
| L4 | Engaged |
| L5 | Peak Activity |

Features:

- Automatic level transitions
- Configurable hysteresis timers
- Stable adaptive capture behavior
- Transition logging

---

## Repository Structure

```text
chronis-hw1/
│
├── tests/
│
├── mock_hal.py
├── trace_generator.py
├── motion_daemon.py
├── heart_rate_daemon.py
├── anchor_gesture.py
├── camera_daemon.py
├── audio_daemon.py
├── worn_detector.py
├── state_machine.py
├── encryption_stub.py
├── interfaces.py
├── run_extended_simulation.py
│
├── README.md
└── requirements.txt
```

---

## Getting Started

### Clone the Repository

```bash
git clone https://github.com/Aditya-Kushwahaa/chronis-hw1.git

cd chronis-hw1
```

### Install Dependencies

```bash
pip install -r requirements.txt
```

---

## Running the Test Suite

```bash
python -m pytest
```

Expected output:

```text
================================================
61 passed
================================================
```

---

## Running the Simulation

```bash
python run_extended_simulation.py
```

The simulation chains all four synthetic scenarios together while validating:

- Motion processing
- Heart-rate processing
- Adaptive capture transitions
- Worn/Not-Worn detection
- Sensor availability handling
- Hysteresis behavior

---

## Architecture

```text
               Synthetic Trace Generator
                          │
                          ▼
                   Mock Hardware HAL
                          │
       ┌──────────────────┼──────────────────┐
       ▼                  ▼                  ▼
 Motion Daemon     Heart Rate Daemon    Audio Daemon
       │                  │
       └────────────┬─────┘
                    ▼
        Worn / Not-Worn Detector
                    │
                    ▼
      Adaptive Capture State Machine
                    │
          ┌─────────┴─────────┐
          ▼                   ▼
   Camera Daemon        Audio Capture
          │                   │
          └─────────┬─────────┘
                    ▼
            Encryption Layer
                    │
                    ▼
             Append-Only Storage
```

---

## Architectural Rules

The framework enforces four global rules throughout the system.

### Rule 1 — Encryption Before Storage

Raw sensor, image, or audio data is never written directly to storage.

---

### Rule 2 — Append-Only Storage

Existing records are never overwritten.

---

### Rule 3 — Explicit Sensor Unavailability

Unavailable sensors always return explicit `SensorUnavailable` values rather than fabricated measurements.

---

### Rule 4 — Strict Module Isolation

Daemons communicate only through defined interfaces and never access each other's internal implementation.

---

## Testing

The project includes automated unit and integration tests covering:

- Mock HAL
- Motion Processing
- Heart Rate Daemon
- Camera Daemon
- Audio Daemon
- Anchor Gesture Detection
- Worn Detector
- Capture State Machine
- Rule Enforcement
- Extended Simulation

### Test Status

✅ **61 / 61 Tests Passed**

---

## Technologies Used

- Python 3.13
- PyTest
- NumPy
- Pandas
- SciPy

---

## Author

**Aditya Kushwaha**

GitHub: https://github.com/Aditya-Kushwahaa

---

## License

This project was developed as part of the **Chronis AI – Hardware Track 1 Internship Assignment** and is intended for educational and evaluation purposes.