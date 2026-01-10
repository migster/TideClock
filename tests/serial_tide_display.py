# This is simple test of the API that displays a tide bar chart in the console.
# Good for troubleshooting network or API issues without needing a display.

import wifi
import socketpool
import ssl
import adafruit_requests
import json
import time

# Wi-Fi credentials - UPDATE THESE!
WIFI_SSID = "Your_WiFi_Network"
WIFI_PASSWORD = "Your_WiFi_Password"

# NOAA API endpoint
API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

class SimpleTideDisplay:
    def __init__(self):
        self.setup_network()
        
    def setup_network(self):
        """Initialize WiFi connection and requests session"""
        try:
            print("Connecting to WiFi...")
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
            print(f"Connected to {WIFI_SSID}")
            
            pool = socketpool.SocketPool(wifi.radio)
            self.requests = adafruit_requests.Session(pool, ssl.create_default_context())
            
        except Exception as e:
            print(f"Network setup failed: {e}")
            
    def fetch_tide_data(self):
        """Fetch tide data from NOAA API"""
        try:
            # Get current date in YYYYMMDD format
            current_time = time.localtime()
            date_str = f"{current_time.tm_year:04d}{current_time.tm_mon:02d}{current_time.tm_mday:02d}"
            
            # Build API URL with parameters
            params = {
                "begin_date": date_str,
                "end_date": date_str,
                "station": "8726724",  # St. Petersburg, FL station
                "product": "predictions",
                "datum": "MLLW",
                "time_zone": "lst",
                "interval": "h",
                "units": "english",
                "format": "json"
            }
            
            # Construct URL with parameters
            url_with_params = API_URL + "?" + "&".join([f"{k}={v}" for k, v in params.items()])
            
            print("Fetching tide data...")
            print(f"URL: {url_with_params}")
            
            response = self.requests.get(url_with_params)
            
            if response.status_code == 200:
                data = response.json()
                print("Tide data received successfully")
                return self.parse_tide_data(data)
            else:
                print(f"API request failed with status: {response.status_code}")
                print(f"Response: {response.text}")
                return None
                
        except Exception as e:
            print(f"Error fetching tide data: {e}")
            return None
    
    def parse_tide_data(self, data):
        """Parse tide data and extract hourly predictions"""
        try:
            predictions = data.get('predictions', [])
            if not predictions:
                print("No tide predictions found in response")
                return None
            
            tide_levels = []
            for prediction in predictions:
                # Extract tide level (water height in feet)
                level = float(prediction.get('v', 0))
                time_str = prediction.get('t', '')
                tide_levels.append((time_str, level))
            
            print(f"Parsed {len(tide_levels)} tide level readings")
            return tide_levels
            
        except Exception as e:
            print(f"Error parsing tide data: {e}")
            return None
    
    def normalize_tide_levels(self, tide_levels):
        """Normalize tide levels to chart height (0-7)"""
        if not tide_levels:
            return []
        
        # Extract just the numeric values for normalization
        values = [level for _, level in tide_levels]
        
        min_level = min(values)
        max_level = max(values)
        level_range = max_level - min_level
        
        if level_range == 0:
            # All levels are the same
            return [(time_str, 4) for time_str, _ in tide_levels]  # Middle of chart
        
        normalized = []
        for time_str, level in tide_levels:
            # Normalize to 0-7 range
            norm_level = int(((level - min_level) / level_range) * 7)
            # Clamp to valid range
            norm_level = max(0, min(7, norm_level))
            normalized.append((time_str, norm_level))
        
        return normalized
    
    def display_ascii_chart(self, tide_data):
        """Display tide chart as ASCII art in console"""
        if not tide_data:
            print("No tide data to display")
            return
        
        normalized_data = self.normalize_tide_levels(tide_data)
        
        print("\n" + "="*60)
        print("24-HOUR TIDE CHART")
        print("="*60)
        
        # Print the chart (8 rows, inverted so high tide is at top)
        for row in range(7, -1, -1):
            line = f"{row} |"
            for time_str, level in normalized_data[:24]:  # Limit to 24 hours
                if level >= row:
                    line += "██"  # Unicode block character
                else:
                    line += "  "
            print(line)
        
        # Print bottom border
        print("  +" + "─" * (len(normalized_data[:24]) * 2))
        
        # Print hour labels (every 4 hours)
        hour_line = "   "
        for i, (time_str, _) in enumerate(normalized_data[:24]):
            if i % 4 == 0:
                hour = time_str.split(' ')[1].split(':')[0]  # Extract hour
                hour_line += f"{hour:>2}" + "  " * 3
            else:
                hour_line += "  "
        print(hour_line)
        
        print(f"\nDate: {normalized_data[0][0].split(' ')[0] if normalized_data else 'Unknown'}")
        print(f"Location: St. Petersburg, FL (Station 8726724)")
        print(f"Units: Feet above MLLW")
        print("="*60)
        
        # Print raw data for reference
        print("\nRAW TIDE DATA:")
        for i, (time_str, level) in enumerate(tide_data[:24]):
            original_level = [level for _, level in tide_data][i]
            print(f"{time_str}: {original_level:.2f} ft")
    
    def run_once(self):
        """Run the tide display once (for testing)"""
        print("Starting Tide Clock (Single Run)...")
        
        tide_data = self.fetch_tide_data()
        if tide_data:
            self.display_ascii_chart(tide_data)
        else:
            print("Failed to get tide data")

def main():
    """Entry point for simple version"""
    # Check WiFi credentials
    if WIFI_SSID == "your_wifi_network":
        print("ERROR: Please update WiFi credentials in the code!")
        print("Edit WIFI_SSID and WIFI_PASSWORD variables")
        return
    
    tide_display = SimpleTideDisplay()
    tide_display.run_once()

if __name__ == "__main__":
    main()