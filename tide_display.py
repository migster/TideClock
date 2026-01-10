import wifi
import socketpool
import ssl
import adafruit_requests
import json
import time
import board
from adafruit_ht16k33.matrix import Matrix8x8x2
import os

# Load WiFi credentials from settings.toml
WIFI_SSID = os.getenv('WIFI_SSID')
WIFI_PASSWORD = os.getenv('WIFI_PASSWORD')
TIDE_STATION = os.getenv('TIDE_STATION', '8726724')  # Default to St. Petersburg, FL
UPDATE_INTERVAL = int(os.getenv('UPDATE_INTERVAL', '3600'))  # Default to 1 hour

# NOAA API endpoint
API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

class SimpleTideDisplay:
    def __init__(self):
        self.setup_matrices()
        self.setup_network()
        
    def setup_matrices(self):
        """Initialize the LED matrices"""
        try:
            print("Setting up LED matrices...")
            i2c = board.I2C()
            
            # Initialize the three 8x8 matrices
            self.matrix1 = Matrix8x8x2(i2c, address=0x70)  # First 8 hours (left)
            self.matrix2 = Matrix8x8x2(i2c, address=0x71)  # Middle 8 hours (center) 
            self.matrix3 = Matrix8x8x2(i2c, address=0x72)  # Last 8 hours (right)
            
            # Clear all matrices
            self.clear_matrices()
            print("LED matrices initialized successfully")
            
        except Exception as e:
            print(f"Matrix setup failed: {e}")
            self.matrix1 = None
            self.matrix2 = None
            self.matrix3 = None
        
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
                "station": TIDE_STATION,  # Use configurable station
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
    
    def clear_matrices(self):
        """Clear all LED matrices"""
        if self.matrix1:
            self.matrix1.fill(0)
        if self.matrix2:
            self.matrix2.fill(0)
        if self.matrix3:
            self.matrix3.fill(0)
    
    def display_on_matrices(self, tide_data):
        """Display tide chart on the LED matrices"""
        if not tide_data or not (self.matrix1 and self.matrix2 and self.matrix3):
            print("Cannot display on matrices - data or matrices not available")
            return
            
        normalized_data = self.normalize_tide_levels(tide_data)
        
        # Clear matrices first
        self.clear_matrices()
        
        # Split data into 3 groups of 8 hours each
        matrices = [self.matrix1, self.matrix2, self.matrix3]
        
        for matrix_idx, matrix in enumerate(matrices):
            start_hour = matrix_idx * 8
            end_hour = start_hour + 8
            
            # Get the data for this 8-hour period
            matrix_data = normalized_data[start_hour:end_hour]
            
            for hour_offset, (time_str, level) in enumerate(matrix_data):
                if hour_offset >= 8:  # Safety check
                    break
                    
                # Matrix coordinates: [x, y] where x is hour (0-7), y is tide level (0-7)
                # Matrix1: x=0 is midnight, x=1 is 1AM, etc.
                # Matrix2: x=0 is 8AM, x=1 is 9AM, etc. 
                # Matrix3: x=0 is 4PM, x=1 is 5PM, etc.
                matrix_x = hour_offset  # Direct mapping: 0-7 for each matrix
                
                # Display vertical bar for this hour up to the tide level
                for tide_level_y in range(level + 1):  # 0 up to current level
                    # Choose color based on tide level
                    if level >= 6:
                        matrix[matrix_x, tide_level_y] = matrix.LED_RED     # High tide - Red
                    elif level >= 3:
                        matrix[matrix_x, tide_level_y] = matrix.LED_YELLOW  # Medium tide - Yellow  
                    else:
                        matrix[matrix_x, tide_level_y] = matrix.LED_GREEN   # Low tide - Green
        
        print("Tide data displayed on LED matrices")
    
    def show_error_on_matrices(self):
        """Show error pattern on matrices when data fetch fails"""
        if not (self.matrix1 and self.matrix2 and self.matrix3):
            return
            
        # Clear matrices
        self.clear_matrices()
        
        # Show red X pattern on middle matrix to indicate error
        matrix = self.matrix2
        for i in range(8):
            matrix[i, i] = matrix.LED_RED      # Main diagonal
            matrix[i, 7-i] = matrix.LED_RED    # Counter diagonal
            
        print("Error pattern displayed on LED matrices")
    
    def run_continuous(self):
        """Run the tide display continuously (updates every hour)"""
        print("Starting Tide Clock (Continuous Mode)...")
        
        while True:
            try:
                tide_data = self.fetch_tide_data()
                if tide_data:
                    # Display on both serial console and LED matrices
                    self.display_ascii_chart(tide_data)
                    self.display_on_matrices(tide_data)
                    print("Next update in 1 hour...")
                else:
                    print("Failed to get tide data")
                    self.show_error_on_matrices()
                    print("Retrying in 10 minutes...")
                    time.sleep(600)  # Wait 10 minutes before retry
                    continue
                
                # Wait 1 hour before next update
                time.sleep(UPDATE_INTERVAL)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                self.show_error_on_matrices()
                time.sleep(300)  # Wait 5 minutes before retry
    
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
            # Display on both serial console and LED matrices
            self.display_ascii_chart(tide_data)
            self.display_on_matrices(tide_data)
        else:
            print("Failed to get tide data")
            # Show error pattern on matrices
            self.show_error_on_matrices()

def main():
    """Entry point for simple version"""
    # Check WiFi credentials
    if not WIFI_SSID or not WIFI_PASSWORD:
        print("ERROR: Please update WiFi credentials in settings.toml!")
        print("Add your WIFI_SSID and WIFI_PASSWORD to settings.toml")
        return
    
    tide_display = SimpleTideDisplay()
    
    # Choose mode: run_once() for testing, run_continuous() for production
    tide_display.run_once()  # Change to run_continuous() for continuous updates

if __name__ == "__main__":
    main()