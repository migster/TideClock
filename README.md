# Tide Clock Configuration

## Hardware Requirements
- CircuitPython-compatible microcontroller with WiFi (e.g., ESP32, Raspberry Pi Pico W)
- Display (built-in or connected via I2C/SPI)
- Internet connection

## Setup Instructions

### 1. Install CircuitPython
- Download and flash CircuitPython onto your microcontroller
- Version 8.0+ recommended for best compatibility

### 2. Install Required Libraries
Copy the following libraries to your CIRCUITPY/lib directory:
- adafruit_requests
- adafruit_connection_manager
- adafruit_display_text
- adafruit_bitmap_font

### 3. Configure WiFi
Edit the code.py file and update these variables:
```python
WIFI_SSID = "your_actual_wifi_network_name"
WIFI_PASSWORD = "your_actual_wifi_password"
```

### 4. API Information
The program uses the NOAA Tides and Currents API:
- Station: 8726724 (St. Petersburg, FL)
- To use a different location, find your station ID at: https://tidesandcurrents.noaa.gov/
- Replace the station parameter in the code

## How It Works

### Data Fetching
- Fetches hourly tide predictions for the current day
- Updates every hour automatically
- Uses NOAA's free public API (no authentication required)

### Visualization
- 24-point wide chart (one point per hour)
- 8-point tall chart (representing tide levels)
- Blue bars show tide height for each hour
- Higher bars = higher tide levels
- Lower bars = lower tide levels

### Display Layout
```
Title: "24-Hour Tide Chart"
[Chart visualization - 24x8 grid]
Date: MM/DD/YYYY
```

## Customization Options

### Change Location
Update the station ID in the API parameters:
```python
"station": "your_station_id_here"
```

### Modify Chart Appearance
- `pixel_size`: Size of each chart pixel (default: 8)
- `chart_width`: Number of hours to display (default: 24)
- `chart_height`: Number of tide level gradations (default: 8)
- Colors can be changed in the palette section

### Update Frequency
Change the sleep time in the main loop:
```python
time.sleep(3600)  # 3600 seconds = 1 hour
```

## Troubleshooting

### WiFi Connection Issues
- Verify SSID and password are correct
- Check signal strength
- Some networks may require additional configuration

### API Issues
- Check internet connectivity
- Verify station ID is valid
- NOAA API may have temporary outages

### Display Issues
- Ensure display is properly connected
- Check that display libraries are installed
- Verify display compatibility with your board

## Data Format
The NOAA API returns data in this format:
```json
{
  "predictions": [
    {
      "t": "2026-01-07 00:00",
      "v": "1.234"
    }
  ]
}
```
Where:
- "t" = timestamp
- "v" = tide level in feet (relative to MLLW datum)