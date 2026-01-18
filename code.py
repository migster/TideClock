import wifi
import socketpool
import ssl
import adafruit_requests
import json
import time
import board
from adafruit_ht16k33.matrix import Matrix8x8x2
import os
import rtc
import adafruit_ntp

# Load WiFi credentials from settings.toml
WIFI_SSID = os.getenv('WIFI_SSID')
WIFI_PASSWORD = os.getenv('WIFI_PASSWORD')
TIDE_STATION = os.getenv('TIDE_STATION', '8726724')  # Default to St. Petersburg, FL

# Handle UPDATE_INTERVAL with error checking
try:
    update_val = os.getenv('UPDATE_INTERVAL', 3600)  # Use integer default
    UPDATE_INTERVAL = int(update_val) if not isinstance(update_val, int) else update_val
except (ValueError, AttributeError) as e:
    print(f"Error parsing UPDATE_INTERVAL: {e}")
    UPDATE_INTERVAL = 3600  # Default to 1 hour

# Handle TIMEZONE_OFFSET with error checking  
try:
    tz_val = os.getenv('TIMEZONE_OFFSET', -5)  # Use integer default
    TIMEZONE_OFFSET = int(tz_val) if not isinstance(tz_val, int) else tz_val
except (ValueError, AttributeError) as e:
    print(f"Error parsing TIMEZONE_OFFSET: {e}")
    TIMEZONE_OFFSET = -5  # Default to EST

try:
    NTP_SERVER = os.getenv('NTP_SERVER', 'time.google.com')
except Exception as e:
    print(f"Error with NTP_SERVER: {e}")
    NTP_SERVER = 'time.google.com'

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
            
            # Sync time with NTP server after WiFi connection
            self.sync_time(pool)
            
        except Exception as e:
            print(f"Network setup failed: {e}")
            
    def check_wifi_connection(self):
        """Check if WiFi is still connected"""
        try:
            return wifi.radio.connected
        except Exception:
            return False
            
    def reconnect_wifi(self, max_attempts=3):
        """Attempt to reconnect WiFi with retry logic"""
        for attempt in range(max_attempts):
            try:
                print(f"WiFi reconnection attempt {attempt + 1}/{max_attempts}...")
                wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
                
                # Recreate the requests session with new socket pool
                pool = socketpool.SocketPool(wifi.radio)
                self.requests = adafruit_requests.Session(pool, ssl.create_default_context())
                
                print(f"WiFi reconnected successfully to {WIFI_SSID}")
                return True
                
            except Exception as e:
                print(f"WiFi reconnection attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    time.sleep(5 * (attempt + 1))  # Exponential backoff: 5s, 10s, 15s
                    
        print("WiFi reconnection failed after all attempts")
        return False
        
    def test_network_connectivity(self):
        """Test basic network connectivity with simple approach"""
        try:
            # Simple test - if we have WiFi and can create a socket pool, we're likely good
            if not self.check_wifi_connection():
                return False
                
            # Try to recreate session if needed
            if not hasattr(self, 'requests') or self.requests is None:
                pool = socketpool.SocketPool(wifi.radio)
                self.requests = adafruit_requests.Session(pool, ssl.create_default_context())
                
            return True
            
        except Exception as e:
            print(f"Network connectivity test failed: {e}")
            return False
            
    def sync_time(self, pool):
        """Sync local time with NTP server"""
        try:
            print(f"Syncing time with {NTP_SERVER}...")
            ntp = adafruit_ntp.NTP(pool, server=NTP_SERVER, tz_offset=TIMEZONE_OFFSET)
            
            # Set the RTC time
            rtc.RTC().datetime = ntp.datetime
            
            current_time = time.localtime()
            print(f"Local time set to: {current_time.tm_year}-{current_time.tm_mon:02d}-{current_time.tm_mday:02d} "
                  f"{current_time.tm_hour:02d}:{current_time.tm_min:02d}:{current_time.tm_sec:02d}")
            
        except Exception as e:
            print(f"Time sync failed: {e}")
            print("Continuing with system time...")
            
    def fetch_tide_data(self, max_retries=3):
        """Fetch tide data from NOAA API with retry logic"""
        last_error = None
        
        for attempt in range(max_retries):
            try:
                # Check WiFi connection first
                if not self.check_wifi_connection():
                    print("WiFi disconnected, attempting to reconnect...")
                    if not self.reconnect_wifi():
                        raise Exception("WiFi reconnection failed")
                
                # Ensure we have a valid requests session
                if not hasattr(self, 'requests') or self.requests is None:
                    print("Creating new requests session...")
                    pool = socketpool.SocketPool(wifi.radio)
                    self.requests = adafruit_requests.Session(pool, ssl.create_default_context())
                
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
                
                # Print current date and time
                current_time = time.localtime()
                print(f"Current time: {current_time.tm_year}-{current_time.tm_mon:02d}-{current_time.tm_mday:02d} "
                      f"{current_time.tm_hour:02d}:{current_time.tm_min:02d}:{current_time.tm_sec:02d}")
                
                print(f"Fetching tide data (attempt {attempt + 1}/{max_retries})...")
                print(f"URL: {url_with_params}")
                
                response = self.requests.get(url_with_params, timeout=30)
                
                if response.status_code == 200:
                    data = response.json()
                    print("Tide data received successfully")
                    return self.parse_tide_data(data)
                else:
                    raise Exception(f"API request failed with status: {response.status_code}, Response: {response.text}")
                    
            except Exception as e:
                last_error = e
                print(f"Attempt {attempt + 1} failed: {e}")
                
                # On socket errors, try to recreate the session
                if "socket" in str(e).lower():
                    print("Socket error detected, recreating session...")
                    try:
                        pool = socketpool.SocketPool(wifi.radio)
                        self.requests = adafruit_requests.Session(pool, ssl.create_default_context())
                    except Exception as session_error:
                        print(f"Session recreation failed: {session_error}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 30s, 60s, 120s
                    wait_time = 30 * (2 ** attempt)
                    print(f"Waiting {wait_time} seconds before retry...")
                    time.sleep(wait_time)
                    
        print(f"All {max_retries} attempts failed. Last error: {last_error}")
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
        
        # Get current hour for highlighting
        current_time = time.localtime()
        current_hour = current_time.tm_hour
        
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
                
                # Calculate the actual hour this represents
                actual_hour = start_hour + hour_offset
                
                # Display single LED point at the tide level for this hour
                # Use yellow for current hour, red for all others
                if actual_hour == current_hour:
                    matrix[matrix_x, level] = matrix.LED_YELLOW  # Current hour in yellow
                    print(f"Current hour ({current_hour}:00) highlighted in yellow on matrix {matrix_idx + 1}")
                else:
                    matrix[matrix_x, level] = matrix.LED_RED     # Other hours in red
        
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
        
    def show_safe_mode_on_matrices(self):
        """Show safe mode pattern for extended failures"""
        if not (self.matrix1 and self.matrix2 and self.matrix3):
            return
            
        # Clear matrices
        self.clear_matrices()
        
        # Show yellow warning pattern on all matrices
        matrices = [self.matrix1, self.matrix2, self.matrix3]
        for matrix in matrices:
            # Show blinking border pattern
            for i in range(8):
                matrix[0, i] = matrix.LED_YELLOW    # Top row
                matrix[7, i] = matrix.LED_YELLOW    # Bottom row
                matrix[i, 0] = matrix.LED_YELLOW    # Left column
                matrix[i, 7] = matrix.LED_YELLOW    # Right column
                
        print("Safe mode pattern displayed on LED matrices")
    
    def run_continuous(self):
        """Run the tide display continuously (updates every hour)"""
        print("Starting Tide Clock (Continuous Mode)...")
        
        last_hour = -1       # Track the last hour we displayed
        last_date = None     # Track the last date we fetched data for
        tide_data = None     # Store current tide data
        consecutive_failures = 0  # Track consecutive API failures
        max_failures = 5     # Enter safe mode after this many failures
        in_safe_mode = False # Flag for safe mode operation
        
        while True:
            try:
                current_time = time.localtime()
                current_hour = current_time.tm_hour
                current_date = (current_time.tm_year, current_time.tm_mon, current_time.tm_mday)
                
                # Check WiFi status periodically
                if not self.check_wifi_connection():
                    print("WiFi connection lost, attempting to reconnect...")
                    if self.reconnect_wifi():
                        consecutive_failures = 0  # Reset failure count on successful reconnect
                    else:
                        consecutive_failures += 1
                
                # Check if we need to fetch new tide data (first boot or new day)
                if tide_data is None or (last_date is not None and current_date != last_date):
                    if last_date is not None:
                        print("New day detected, fetching updated tide data...")
                    else:
                        print("Initial startup, fetching tide data...")
                    
                    new_tide_data = self.fetch_tide_data()
                    if new_tide_data:
                        tide_data = new_tide_data
                        last_date = current_date
                        consecutive_failures = 0  # Reset failure count
                        in_safe_mode = False      # Exit safe mode
                        
                        # Display on serial console when we get new data
                        self.display_ascii_chart(tide_data)
                        print("Tide data will refresh again after midnight...")
                    else:
                        consecutive_failures += 1
                        print(f"Failed to get tide data (failure #{consecutive_failures})")
                        
                        # Enter safe mode after too many failures
                        if consecutive_failures >= max_failures and not in_safe_mode:
                            print(f"Entering safe mode after {consecutive_failures} consecutive failures")
                            in_safe_mode = True
                            self.show_safe_mode_on_matrices()
                        else:
                            self.show_error_on_matrices()
                        
                        # Progressive retry delays based on failure count
                        if consecutive_failures <= 3:
                            retry_delay = 300  # 5 minutes for first few failures
                        elif consecutive_failures <= 6:
                            retry_delay = 900  # 15 minutes for moderate failures
                        else:
                            retry_delay = 1800  # 30 minutes for extended failures
                            
                        print(f"Retrying in {retry_delay // 60} minutes...")
                        time.sleep(retry_delay)
                        continue
                
                # Check if the hour has changed and we have tide data
                if current_hour != last_hour and tide_data is not None:
                    print(f"Hour changed from {last_hour} to {current_hour}, updating matrix display...")
                    self.display_on_matrices(tide_data)
                    last_hour = current_hour
                
                # In safe mode, show different pattern periodically
                if in_safe_mode:
                    self.show_safe_mode_on_matrices()
                
                # Sleep for 30 seconds before checking again
                time.sleep(30)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                consecutive_failures += 1
                self.show_error_on_matrices()
                
                # Progressive error recovery delays
                error_delay = min(300 * consecutive_failures, 1800)  # Max 30 minutes
                print(f"Waiting {error_delay // 60} minutes before retry...")
                time.sleep(error_delay)
    
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
                hour_line += f"{hour:>2}"
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
    
    # Run in continuous mode for clock-like behavior
    tide_display.run_continuous()

if __name__ == "__main__":
    main()