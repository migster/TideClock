# TideClock - CircuitPython LED Matrix Tide Display

A CircuitPython-powered tide clock that displays real-time tide data on LED matrices. Features three 8x8 LED matrices showing a 24-hour tide chart with automatic updates and WiFi connectivity.

## Hardware Requirements
- CircuitPython-compatible microcontroller with WiFi (e.g., ESP32, Raspberry Pi Pico W)
- Three 8x8 LED matrices with HT16K33 controllers (I2C addresses: 0x70, 0x71, 0x72)
- I2C connections to the LED matrices
- Internet connection via WiFi

## Setup Instructions

### 1. Install CircuitPython
- Download and flash CircuitPython onto your microcontroller
- Version 8.0+ recommended for best compatibility

### 2. Install Required Libraries
Copy the following libraries to your CIRCUITPY/lib directory:
- `adafruit_requests.mpy`
- `adafruit_connection_manager.mpy`
- `adafruit_ht16k33/` (entire folder for LED matrix control)
- `adafruit_ntp.mpy` (for time synchronization)

### 3. Configure Settings
Create or edit `settings.toml` in the root directory with your configuration:
```toml
# WiFi Configuration
WIFI_SSID = "your_wifi_network"
WIFI_PASSWORD = "your_wifi_password"

# Optional: NOAA Station Configuration  
# Station ID for St. Petersburg, FL (default)
TIDE_STATION = "8726724"

# Update interval in seconds (default: 3600 = 1 hour)
UPDATE_INTERVAL = 3600

# Time Settings
NTP_SERVER = 'time.google.com'
TIMEZONE_OFFSET = -5          # EST = -5, adjust for your location
```

### 4. Hardware Connections
Connect three 8x8 LED matrices to I2C:
- Matrix 1 (hours 0-7): Address 0x70
- Matrix 2 (hours 8-15): Address 0x71  
- Matrix 3 (hours 16-23): Address 0x72

## How It Works

### Data Fetching
- Fetches hourly tide predictions for the current day from NOAA API
- Automatically syncs time with NTP server on startup
- Updates display every hour and refreshes data daily at midnight
- Uses NOAA's free public API (no authentication required)

### LED Matrix Display
- **Three 8x8 matrices** display 24-hour tide data (8 hours per matrix)
- **Height represents tide level** (0-7 scale, bottom to top)
- **Current hour highlighted in yellow**, other hours in red
- **Real-time updates** as hours change
- **Error indication** displays red X pattern on middle matrix

### Console Output
- ASCII art tide chart displayed in serial console
- Raw tide data with timestamps and water levels
- Debugging information for troubleshooting

### Update Schedule
- **Hourly display updates**: LED matrices refresh when hour changes
- **Daily data refresh**: New tide data fetched after midnight
- **Error recovery**: Automatic retry with exponential backoff

## Customization Options

### Change Location
Update the `TIDE_STATION` in `settings.toml` to your desired NOAA station:
```toml
TIDE_STATION = "your_station_id_here"
```
Find station IDs at: https://tidesandcurrents.noaa.gov/

### Time Zone Configuration
Adjust timezone offset in `settings.toml`:
```toml
TIMEZONE_OFFSET = -5  # EST = -5, PST = -8, etc.
```

### Update Frequency
Modify data refresh interval in `settings.toml`:
```toml
UPDATE_INTERVAL = 3600  # seconds (3600 = 1 hour)
```

### Matrix Colors and Patterns
Colors are defined in the code and can be modified:
- `matrix.LED_YELLOW`: Current hour indicator
- `matrix.LED_RED`: Other hours
- Error pattern: Red X on middle matrix

## Project Structure
```
TideClock/
├── code.py              # Main application code
├── settings.toml        # Configuration file (WiFi, station, etc.)
├── requirements.txt     # CircuitPython library dependencies
├── README.md           # This file
└── tests/              # Test and utility scripts
    ├── blinktest.py           # LED matrix test
    ├── matrixtest.py          # Matrix functionality test  
    ├── serial_tide_display.py # Serial console tide display
    └── simple_tide_display bar chart.py # Bar chart version
```

## API Information
Uses the NOAA Tides and Currents API:
- **Base URL**: `https://api.tidesandcurrents.noaa.gov/api/prod/datagetter`
- **Default Station**: 8726724 (St. Petersburg, FL)
- **Data Type**: Hourly tide predictions
- **Datum**: MLLW (Mean Lower Low Water)
- **Format**: JSON
- **No API key required**

## Troubleshooting

### WiFi Connection Issues
- Verify `WIFI_SSID` and `WIFI_PASSWORD` in `settings.toml`
- Check signal strength and network availability
- Some networks may require additional configuration

### Matrix Display Issues
- Verify I2C connections to all three matrices
- Check matrix addresses (0x70, 0x71, 0x72)
- Ensure `adafruit_ht16k33` library is installed
- Test individual matrices with provided test scripts

### API and Time Issues
- Check internet connectivity after WiFi connection
- Verify station ID is valid at NOAA website
- Time sync failures will show in console but won't prevent operation
- API failures trigger error pattern display

### Common Error Messages
- `"Matrix setup failed"`: Check I2C wiring and addresses
- `"Network setup failed"`: Check WiFi credentials
- `"Error fetching tide data"`: Check internet connection and station ID
- `"Time sync failed"`: NTP server issues (continues with system time)

## Data Format
The NOAA API returns tide predictions in this format:
```json
{
  "predictions": [
    {
      "t": "2026-01-17 00:00",
      "v": "1.234"
    }
  ]
}
```
Where:
- `"t"`: Timestamp in local time
- `"v"`: Tide level in feet relative to MLLW (Mean Lower Low Water) datum

## Features
- **Real-time Updates**: Automatic hourly matrix updates and daily data refresh
- **Visual Indicators**: Current hour highlighted in yellow, historical/future hours in red
- **Error Handling**: Graceful failure with visual error indicators and retry logic
- **Time Sync**: NTP time synchronization for accurate hour tracking
- **Console Logging**: Detailed ASCII tide charts and debugging information
- **Configurable**: Easy customization via settings.toml file
- **Modular Design**: Test scripts for debugging individual components

## License
This project is licensed under the GNU General Public License v3.0 - see the [LICENSE.txt](LICENSE.txt) file for details.

This is free software: you are free to change and redistribute it under the terms of the GPL v3. There is NO WARRANTY, to the extent permitted by law.

## Contributing
Test scripts in the `/tests` directory can help with development and debugging:
- Run `blinktest.py` to verify LED matrix functionality
- Use `matrixtest.py` for matrix-specific testing
- `serial_tide_display.py` provides console-only tide display