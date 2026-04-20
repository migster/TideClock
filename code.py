import wifi
import socketpool
import ssl
import adafruit_requests
import time
import board
from adafruit_ht16k33.matrix import Matrix8x8x2
import os
import rtc
import adafruit_ntp
import gc
import microcontroller
from microcontroller import watchdog as wdt
from watchdog import WatchDogMode

# Load WiFi credentials from settings.toml
WIFI_SSID = os.getenv('WIFI_SSID')
WIFI_PASSWORD = os.getenv('WIFI_PASSWORD')
TIDE_STATION = os.getenv('TIDE_STATION', '8726724')  # Default to St. Petersburg, FL

# Handle TIMEZONE_OFFSET with error checking
try:
    tz_val = os.getenv('TIMEZONE_OFFSET', '-5')  # Default as string
    print(f"TIMEZONE_OFFSET raw value: {tz_val}")
    TIMEZONE_OFFSET = int(float(tz_val))  # Convert via float first to handle decimals
    print(f"TIMEZONE_OFFSET parsed: {TIMEZONE_OFFSET}")
except (ValueError, AttributeError) as e:
    print(f"Error parsing TIMEZONE_OFFSET: {e}")
    TIMEZONE_OFFSET = -5  # Default to EST

# Handle LED_BRIGHTNESS with error checking
try:
    brightness_str = os.getenv('LED_BRIGHTNESS', '1.0')
    LED_BRIGHTNESS = float(brightness_str)
    LED_BRIGHTNESS = max(0.0, min(1.0, LED_BRIGHTNESS))  # Clamp to valid range
    print(f"LED_BRIGHTNESS loaded: {LED_BRIGHTNESS}")
except (ValueError, TypeError) as e:
    print(f"Error parsing LED_BRIGHTNESS, using default: {e}")
    LED_BRIGHTNESS = 1.0

try:
    NTP_SERVER = os.getenv('NTP_SERVER', 'time.google.com')
except Exception as e:
    print(f"Error with NTP_SERVER: {e}")
    NTP_SERVER = 'time.google.com'

# US DST auto-adjust: when enabled, TIMEZONE_OFFSET is treated as
# standard-time offset and +1 is added during DST (2nd Sun Mar - 1st Sun Nov).
DST_AUTO = os.getenv('DST_AUTO', '1') == '1'


def is_us_dst(t):
    """Return True if US DST is active for the given localtime struct.

    US DST: 2nd Sunday of March through 1st Sunday of November.
    tm_wday: 0=Mon ... 6=Sun.
    """
    month, mday, wday = t.tm_mon, t.tm_mday, t.tm_wday
    if month < 3 or month > 11:
        return False
    if 3 < month < 11:
        return True
    days_since_sunday = (wday + 1) % 7
    last_sunday_mday = mday - days_since_sunday
    if month == 3:
        # DST starts on the 2nd Sunday (mday 8-14)
        return last_sunday_mday >= 8
    # November: DST ends on the 1st Sunday (mday 1-7)
    return last_sunday_mday < 1

# Serial "display mirror": set DISPLAY_DUMP="0" in settings.toml to silence.
DISPLAY_DUMP = os.getenv('DISPLAY_DUMP', '1') == '1'

# NOAA API endpoint
API_URL = "https://api.tidesandcurrents.noaa.gov/api/prod/datagetter"

# 3x5 pixel font for digits 0-9 and colon/slash
# Each character is 3 columns wide, 5 rows tall, stored as column bitmasks (LSB = top row)
FONT_3X5 = {
    '0': (0x1F, 0x11, 0x1F),
    '1': (0x00, 0x1F, 0x00),
    '2': (0x1D, 0x15, 0x17),
    '3': (0x15, 0x15, 0x1F),
    '4': (0x07, 0x04, 0x1F),
    '5': (0x17, 0x15, 0x1D),
    '6': (0x1F, 0x15, 0x1D),
    '7': (0x01, 0x01, 0x1F),
    '8': (0x1F, 0x15, 0x1F),
    '9': (0x17, 0x15, 0x1F),
    '/': (0x18, 0x04, 0x03),
    ':': (0x00, 0x0A, 0x00),
}

class SimpleTideDisplay:
    def __init__(self):
        self.pool = None          # Socket pool for NTP re-sync
        self.last_ntp_sync = None # Track last NTP sync date
        self._wdt_feed_warned = False  # One-shot log guard for WDT feed errors
        self.setup_watchdog()
        self.setup_matrices()
        self.setup_network()
        
    def setup_watchdog(self):
        """Initialize watchdog timer to auto-reboot on hangs"""
        try:
            wdt.timeout = 60  # Reboot if not fed within 60 seconds
            wdt.mode = WatchDogMode.RESET
            print("Watchdog timer enabled (60s timeout)")
        except Exception as e:
            print(f"Watchdog setup failed: {e}")
        
    def setup_matrices(self):
        """Initialize the LED matrices"""
        try:
            print("Setting up LED matrices...")
            i2c = board.I2C()
            
            # Initialize the three 8x8 matrices with brightness parameter
            self.matrix1 = Matrix8x8x2(i2c, address=0x70, brightness=LED_BRIGHTNESS)  # First 8 hours (left)
            self.matrix2 = Matrix8x8x2(i2c, address=0x71, brightness=LED_BRIGHTNESS)  # Middle 8 hours (center) 
            self.matrix3 = Matrix8x8x2(i2c, address=0x72, brightness=LED_BRIGHTNESS)  # Last 8 hours (right)
            
            print(f"LED brightness set to {LED_BRIGHTNESS:.2f}")
            
            # Clear all matrices
            self.clear_matrices()
            
            # Stage 1: matrices alive — light corner pixel on each matrix
            self.matrix1[0, 0] = self.matrix1.LED_GREEN
            self.matrix2[0, 0] = self.matrix2.LED_GREEN
            self.matrix3[0, 0] = self.matrix3.LED_GREEN
            print("LED matrices initialized successfully")
            self.dump_display("boot: matrices alive")
            
        except Exception as e:
            print(f"Matrix setup failed: {e}")
            self.matrix1 = None
            self.matrix2 = None
            self.matrix3 = None
        
    def setup_network(self):
        """Initialize WiFi connection and requests session"""
        try:
            has_matrices = self.matrix1 and self.matrix2 and self.matrix3
            
            # Stage 2: WiFi connecting — yellow spinner on matrix2
            if has_matrices:
                self.matrix1[0, 0] = self.matrix1.LED_GREEN   # Stage 1 done
                self.matrix2[0, 0] = self.matrix2.LED_YELLOW  # WiFi in progress
                self.dump_display("boot: wifi connecting")

            print("Connecting to WiFi...")
            wifi.radio.connect(WIFI_SSID, WIFI_PASSWORD)
            print(f"Connected to {WIFI_SSID}")
            
            # Stage 2 done — WiFi connected
            if has_matrices:
                self.matrix2[0, 0] = self.matrix2.LED_GREEN
                self.dump_display("boot: wifi connected")

            self.pool = socketpool.SocketPool(wifi.radio)
            self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())
            
            # Stage 3: NTP syncing — yellow on matrix3
            if has_matrices:
                self.matrix3[0, 0] = self.matrix3.LED_YELLOW
                self.dump_display("boot: ntp syncing")

            print("Syncing NTP...")
            self.sync_time(self.pool)
            self.last_ntp_sync = time.localtime().tm_mday
            
            # Stage 3 done — all green
            if has_matrices:
                self.matrix3[0, 0] = self.matrix3.LED_GREEN
                self.dump_display("boot: all stages green")

            time.sleep(1)  # Brief pause so you can see all-green
            
            # Show date/time on matrices to confirm sync
            self.show_boot_info()
            
            gc.collect()
            print(f"Free memory after setup: {gc.mem_free()} bytes")
            
        except Exception as e:
            print(f"Network setup failed: {e}")
            # Show red on whichever stage failed
            if self.matrix1 and self.matrix2 and self.matrix3:
                for m in [self.matrix1, self.matrix2, self.matrix3]:
                    if m[0, 0] != m.LED_GREEN:
                        m[0, 0] = m.LED_RED
                self.dump_display("boot: setup error")
            
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
                self.pool = socketpool.SocketPool(wifi.radio)
                self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())

                print(f"WiFi reconnected successfully to {WIFI_SSID}")
                return True
                
            except Exception as e:
                print(f"WiFi reconnection attempt {attempt + 1} failed: {e}")
                if attempt < max_attempts - 1:
                    wait = 5 * (attempt + 1)
                    for _ in range(wait):
                        self.feed_watchdog()
                        time.sleep(1)
                    
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
                self.pool = socketpool.SocketPool(wifi.radio)
                self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())
                
            return True
            
        except Exception as e:
            print(f"Network connectivity test failed: {e}")
            return False
            
    def sync_time(self, pool):
        """Sync local time with NTP server, auto-adjusting for US DST if enabled."""
        try:
            print(f"Syncing time with {NTP_SERVER}...")
            # First sync at standard-time offset so we have a valid date to test DST against
            ntp = adafruit_ntp.NTP(pool, server=NTP_SERVER, tz_offset=TIMEZONE_OFFSET)
            rtc.RTC().datetime = ntp.datetime

            if DST_AUTO and is_us_dst(time.localtime()):
                effective_offset = TIMEZONE_OFFSET + 1
                print(f"DST active — re-syncing with offset {effective_offset}")
                ntp = adafruit_ntp.NTP(pool, server=NTP_SERVER, tz_offset=effective_offset)
                rtc.RTC().datetime = ntp.datetime

            current_time = time.localtime()
            print(f"Local time set to: {current_time.tm_year}-{current_time.tm_mon:02d}-{current_time.tm_mday:02d} "
                  f"{current_time.tm_hour:02d}:{current_time.tm_min:02d}:{current_time.tm_sec:02d}")

        except Exception as e:
            print(f"Time sync failed: {e}")
            print("Continuing with system time...")

    def feed_watchdog(self):
        """Feed the watchdog timer to prevent reboot"""
        try:
            wdt.feed()
        except Exception as e:
            if not self._wdt_feed_warned:
                print(f"Watchdog feed failed (further errors suppressed): {e}")
                self._wdt_feed_warned = True

    def maybe_resync_ntp(self):
        """Re-sync NTP daily at 3 AM to prevent clock drift"""
        current_time = time.localtime()
        if current_time.tm_hour == 3 and self.last_ntp_sync != current_time.tm_mday:
            print("Daily NTP re-sync triggered...")
            try:
                if not self.check_wifi_connection():
                    self.reconnect_wifi()
                if self.pool is None:
                    self.pool = socketpool.SocketPool(wifi.radio)
                self.sync_time(self.pool)
                self.last_ntp_sync = current_time.tm_mday
                print("NTP re-sync complete")
            except Exception as e:
                print(f"NTP re-sync failed: {e}")

    def dump_display(self, label=""):
        """Print a colored 24x8 snapshot of all three matrices to serial."""
        if not DISPLAY_DUMP:
            return
        if not (self.matrix1 and self.matrix2 and self.matrix3):
            return
        try:
            t = time.localtime()
            ts = f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}"
            print(f"--- dump[{ts}] {label} ---")
            RESET = "\x1b[0m"
            # 0=OFF 1=RED 2=GREEN 3=YELLOW (HT16K33 Matrix8x8x2 values)
            colors = {0: "\x1b[38;5;238m", 1: "\x1b[91m",
                      2: "\x1b[92m", 3: "\x1b[93m"}
            # Iterate y from 7 down to 0 so the dump matches physical display
            # orientation (matrix row 0 is at the bottom of the real panel).
            for y in range(7, -1, -1):
                row = ""
                for mi, m in enumerate((self.matrix1, self.matrix2, self.matrix3)):
                    if mi:
                        row += RESET + "|"
                    for x in range(8):
                        try:
                            c = m[x, y]
                        except Exception:
                            c = 0
                        row += colors.get(c, "") + "\u2588\u2588"
                print(row + RESET)
        except Exception as e:
            print(f"dump_display error: {e}")

    def _draw_char(self, matrix, char, x_offset, y_offset, color):
        """Draw a single 3x5 character on a matrix at the given offset"""
        cols = FONT_3X5.get(char)
        if not cols:
            return
        for cx, col_bits in enumerate(cols):
            for ry in range(5):
                if col_bits & (1 << ry):
                    px = x_offset + cx
                    py = y_offset + (4 - ry)  # Flip vertically so top row draws at higher Y
                    if 0 <= px < 8 and 0 <= py < 8:
                        matrix[px, py] = color

    def _draw_string(self, matrix, text, y_offset, color):
        """Draw a short string centered on an 8x8 matrix"""
        # Each char is 3px wide + 1px gap
        total_width = len(text) * 4 - 1
        x_start = max(0, (8 - total_width) // 2)
        for i, ch in enumerate(text):
            self._draw_char(matrix, ch, x_start + i * 4, y_offset, color)

    def show_boot_info(self):
        """Show date then time across all 3 matrices on boot"""
        if not (self.matrix1 and self.matrix2 and self.matrix3):
            print("Cannot show boot info - matrices not available")
            return

        current_time = time.localtime()
        month_str = f"{current_time.tm_mon:02d}"
        day_str = f"{current_time.tm_mday:02d}"
        hour_str = f"{current_time.tm_hour:02d}"
        min_str = f"{current_time.tm_min:02d}"

        # --- Phase 1: Date across all 3 matrices (MM / DD) ---
        self.clear_matrices()
        # Matrix 1: month (MM) in green, centered
        self._draw_string(self.matrix1, month_str, 1, self.matrix1.LED_GREEN)
        # Matrix 2: slash in green, centered
        self._draw_string(self.matrix2, "/", 1, self.matrix2.LED_GREEN)
        # Matrix 3: day (DD) in green, centered
        self._draw_string(self.matrix3, day_str, 1, self.matrix3.LED_GREEN)

        print(f"Boot display: {month_str} / {day_str}")
        self.dump_display(f"boot: date {month_str}/{day_str}")
        print("Showing date for 3 seconds...")
        time.sleep(3)

        # --- Phase 2: Time across all 3 matrices (HH : MM) ---
        self.clear_matrices()
        # Matrix 1: hours (HH) in green, centered
        self._draw_string(self.matrix1, hour_str, 1, self.matrix1.LED_GREEN)
        # Matrix 2: colon in green, centered
        self._draw_string(self.matrix2, ":", 1, self.matrix2.LED_GREEN)
        # Matrix 3: minutes (MM) in green, centered
        self._draw_string(self.matrix3, min_str, 1, self.matrix3.LED_GREEN)

        print(f"Boot display: {hour_str} : {min_str}")
        self.dump_display(f"boot: time {hour_str}:{min_str}")
        print("Showing time for 3 seconds...")
        time.sleep(3)

        self.clear_matrices()
        self.dump_display("boot: cleared")
        print("Boot sequence complete, loading tide data...")
            
    def show_api_status(self, status):
        """Show API fetch status on matrix1 corner pixel.
        'fetching' = yellow, 'ok' = green, 'fail' = red, 'clear' = off"""
        if not self.matrix1:
            return
        if status == 'fetching':
            self.matrix1[7, 7] = self.matrix1.LED_YELLOW
        elif status == 'ok':
            self.matrix1[7, 7] = self.matrix1.LED_GREEN
        elif status == 'fail':
            self.matrix1[7, 7] = self.matrix1.LED_RED
        elif status == 'clear':
            self.matrix1[7, 7] = 0
        self.dump_display(f"api status: {status}")

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
                    self.pool = socketpool.SocketPool(wifi.radio)
                    self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())
                
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
                
                try:
                    if response.status_code == 200:
                        data = response.json()
                        print("Tide data received successfully")
                        return self.parse_tide_data(data)
                    else:
                        raise Exception(f"API request failed with status: {response.status_code}, Response: {response.text}")
                finally:
                    response.close()
                    gc.collect()
                    print(f"Free memory after fetch: {gc.mem_free()} bytes")
                    
            except Exception as e:
                last_error = e
                print(f"Attempt {attempt + 1} failed: {e}")
                
                # On socket errors, try to recreate the session
                if "socket" in str(e).lower():
                    print("Socket error detected, recreating session...")
                    try:
                        self.pool = socketpool.SocketPool(wifi.radio)
                        self.requests = adafruit_requests.Session(self.pool, ssl.create_default_context())
                    except Exception as session_error:
                        print(f"Session recreation failed: {session_error}")
                
                if attempt < max_retries - 1:
                    # Exponential backoff: 30s, 60s, 120s
                    wait_time = 30 * (2 ** attempt)
                    print(f"Waiting {wait_time} seconds before retry...")
                    for _ in range(wait_time // 10):
                        self.feed_watchdog()
                        time.sleep(10)
                    
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
        self.dump_display(f"tide chart (current hour {current_hour:02d})")
    
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
        self.dump_display("error X pattern")
        
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
        self.dump_display("safe mode border")
    
    def display_on_matrices_stale(self, tide_data):
        """Display tide data with stale indicator (green dots instead of red)"""
        if not tide_data or not (self.matrix1 and self.matrix2 and self.matrix3):
            return
            
        normalized_data = self.normalize_tide_levels(tide_data)
        current_time = time.localtime()
        current_hour = current_time.tm_hour
        
        self.clear_matrices()
        
        matrices = [self.matrix1, self.matrix2, self.matrix3]
        
        for matrix_idx, matrix in enumerate(matrices):
            start_hour = matrix_idx * 8
            matrix_data = normalized_data[start_hour:start_hour + 8]
            
            for hour_offset, (time_str, level) in enumerate(matrix_data):
                if hour_offset >= 8:
                    break
                actual_hour = start_hour + hour_offset
                # Use green for all points to indicate stale/yesterday's data
                if actual_hour == current_hour:
                    matrix[hour_offset, level] = matrix.LED_YELLOW
                else:
                    matrix[hour_offset, level] = matrix.LED_GREEN

        print("Stale tide data displayed on LED matrices (green = yesterday's data)")
        self.dump_display(f"stale tide (current hour {current_hour:02d})")
    
    def run_continuous(self):
        """Run the tide display continuously (updates every hour)"""
        print("Starting Tide Clock (Continuous Mode)...")
        
        last_hour = -1       # Track the last hour we displayed
        last_date = None     # Track the last date we fetched data for
        tide_data = None     # Store current tide data
        consecutive_failures = 0  # Track consecutive API failures
        max_failures = 5     # Enter safe mode after this many failures
        in_safe_mode = False # Flag for safe mode operation
        data_is_stale = False  # Flag for stale (yesterday's) data
        
        while True:
            try:
                # Feed watchdog at the start of each loop
                self.feed_watchdog()
                
                current_time = time.localtime()
                current_hour = current_time.tm_hour
                current_date = (current_time.tm_year, current_time.tm_mon, current_time.tm_mday)
                
                # Daily NTP re-sync at 3 AM
                self.maybe_resync_ntp()
                
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
                    
                    self.show_api_status('fetching')
                    new_tide_data = self.fetch_tide_data()
                    # Show result on LED
                    self.show_api_status('ok' if new_tide_data else 'fail')
                    if new_tide_data:
                        tide_data = new_tide_data
                        last_date = current_date
                        consecutive_failures = 0  # Reset failure count
                        in_safe_mode = False      # Exit safe mode
                        data_is_stale = False     # Fresh data
                        # Force immediate redraw so the user isn't stuck looking at
                        # a stale-green or safe-mode border until the hour ticks.
                        last_hour = -1

                        # Display on serial console when we get new data
                        self.display_ascii_chart(tide_data)
                        print("Tide data will refresh again after midnight...")
                    else:
                        consecutive_failures += 1
                        print(f"Failed to get tide data (failure #{consecutive_failures})")
                        
                        # Mark data as stale if we had data from a previous day
                        if tide_data is not None and last_date is not None and current_date != last_date:
                            data_is_stale = True
                            print("Warning: displaying stale data from previous day")
                        
                        # Enter safe mode after too many failures
                        if consecutive_failures >= max_failures and not in_safe_mode:
                            print(f"Entering safe mode after {consecutive_failures} consecutive failures")
                            in_safe_mode = True
                            self.show_safe_mode_on_matrices()
                        elif data_is_stale and tide_data is not None:
                            # Show yesterday's data in green as a stale indicator
                            self.display_on_matrices_stale(tide_data)
                            last_hour = current_hour
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
                        # Feed watchdog during long retry waits
                        for _ in range(retry_delay // 10):
                            self.feed_watchdog()
                            time.sleep(10)
                        continue
                
                # Check if the hour has changed and we have tide data
                if current_hour != last_hour and tide_data is not None:
                    print(f"Hour changed from {last_hour} to {current_hour}, updating matrix display...")
                    if data_is_stale:
                        self.display_on_matrices_stale(tide_data)
                    else:
                        self.display_on_matrices(tide_data)
                    last_hour = current_hour
                
                # In safe mode, show different pattern periodically
                if in_safe_mode:
                    self.show_safe_mode_on_matrices()
                
                # Sleep for 30 seconds before checking again
                # Feed watchdog and collect garbage during sleep
                gc.collect()
                for _ in range(3):
                    self.feed_watchdog()
                    time.sleep(10)
                
            except Exception as e:
                print(f"Error in main loop: {e}")
                consecutive_failures += 1
                self.show_error_on_matrices()
                
                # Progressive error recovery delays
                error_delay = min(300 * consecutive_failures, 1800)  # Max 30 minutes
                print(f"Waiting {error_delay // 60} minutes before retry...")
                # Feed watchdog during long error waits
                for _ in range(error_delay // 10):
                    self.feed_watchdog()
                    time.sleep(10)
    
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
                try:
                    hour = time_str.split(' ')[1].split(':')[0]
                except (IndexError, AttributeError):
                    hour = "??"
                hour_line += f"{hour:>2}"
            else:
                hour_line += "  "
        print(hour_line)
        
        date_label = "Unknown"
        if normalized_data:
            try:
                date_label = normalized_data[0][0].split(' ')[0]
            except (IndexError, AttributeError):
                pass
        print(f"\nDate: {date_label}")
        print(f"Location: Station {TIDE_STATION}")
        print(f"Units: Feet above MLLW")
        print("="*60)
        
        # Print raw data for reference
        print("\nRAW TIDE DATA:")
        for time_str, level in tide_data[:24]:
            print(f"{time_str}: {level:.2f} ft")
    
    def run_once(self):
        """Run the tide display once (for testing)"""
        print("Starting Tide Clock (Single Run)...")
        
        self.show_api_status('fetching')
        tide_data = self.fetch_tide_data()
        if tide_data:
            self.show_api_status('ok')
            # Display on both serial console and LED matrices
            self.display_ascii_chart(tide_data)
            self.display_on_matrices(tide_data)
        else:
            self.show_api_status('fail')
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