import os
import sys
import json
import requests
from datetime import datetime
import pytz

class FoxESSAPI:
    def __init__(self, api_key, sn):
        self.api_key = api_key
        self.sn = sn
        self.base_url = "https://www.foxesscloud.com/api"
    
    def get_soc(self):
        """Get current battery state of charge"""
        path = "/device/queryDeviceById"
        params = {
            "sn": self.sn,
            "appVersion": "4.0.0",
            "lang": "en",
            "token": self.api_key
        }
        
        try:
            response = requests.get(
                f"{self.base_url}{path}",
                params=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                soc = data["result"]["soc"]
                print(f"✓ Retrieved SOC: {soc}%")
                return float(soc)
            else:
                error_msg = data.get("msg", "Unknown error")
                print(f"✗ API error: {error_msg}", file=sys.stderr)
                return None
        except Exception as e:
            print(f"✗ Network/connection error: {e}", file=sys.stderr)
            return None

def send_notification(topic_url, message):
    """Send notification via ntfy.sh"""
    try:
        response = requests.post(
            topic_url,
            data=message,
            timeout=10
        )
        response.raise_for_status()
        print(f"📢 Notification sent")
    except Exception as e:
        print(f"✗ Notification failed: {e}", file=sys.stderr)

def load_state():
    """Load state from file to track if we've already alerted today"""
    state_file = "foxess_state.json"
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Note: Could not load state file: {e}")
    
    return {"alerted_today": False, "date": None}

def save_state(state):
    """Save state to file"""
    state_file = "foxess_state.json"
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
        print(f"✓ State saved")
    except Exception as e:
        print(f"Note: Could not save state file: {e}")

def reset_daily_state():
    """Reset state at the start of each day (midnight)"""
    state_file = "foxess_state.json"
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            # If date changed, reset the flag
            if state.get("date") != today:
                state = {"alerted_today": False, "date": today}
                save_state(state)
                print(f"✓ Daily state reset")
                return state
            return state
        else:
            # First run - create state file
            state = {"alerted_today": False, "date": today}
            save_state(state)
            return state
    except Exception as e:
        print(f"Note: Error in daily reset: {e}")
        return {"alerted_today": False, "date": today}

def main():
    # Load from environment
    api_key = os.environ.get("FOXESS_API_KEY")
    sn = os.environ.get("FOXESS_SN")
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    
    if not all([api_key, sn, ntfy_topic]):
        print("✗ Missing required environment variables", file=sys.stderr)
        sys.exit(1)
    
    # Initialize
    fox = FoxESSAPI(api_key, sn)
    
    # Load state and reset if new day
    state = reset_daily_state()
    already_alerted = state.get("alerted_today", False)
    
    # Get Sydney timezone
    sydney_tz = pytz.timezone('Australia/Sydney')
    now = datetime.now(sydney_tz)
    current_hour = now.hour
    current_minute = now.minute
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print("\n--- FoxESS Battery Monitor (Alert-Only Mode) ---")
    print(f"Time: {timestamp}")
    print(f"Status: {'Already alerted today' if already_alerted else 'No alerts yet'}")
    
    # Between 6pm-8pm: Monitor SOC and send alert if low
    if 18 <= current_hour < 20:
        print(f"\n⏰ Monitoring window (6pm-8pm)")
        
        # Get SOC
        soc = fox.get_soc()
        if soc is None:
            print("✗ Failed to retrieve SOC. Check API key and SN.", file=sys.stderr)
            sys.exit(1)
        
        print(f"SOC: {soc}%")
        
        if soc < 60:
            if already_alerted:
                print("⚠️  SOC still low but already alerted today - no duplicate alert")
            else:
                print(f"⚠️  SOC LOW ({soc}%) - Sending alert...")
                message = f"🔋 FoxESS Battery Alert [{timestamp}]\n\nSOC: {soc}%\n\n→ Please switch to Self Use mode in the FoxESS app"
                send_notification(ntfy_topic, message)
                
                # Mark as alerted
                state["alerted_today"] = True
                save_state(state)
        else:
            print(f"✓ SOC healthy ({soc}%) - No alert needed")
    
    # At 9pm: Send reminder to switch back to Scheduler
    elif current_hour == 21:
        if 0 <= current_minute < 5:
            print(f"\n⏰ 9pm - Sending reminder to switch to Scheduler...")
            message = f"📅 FoxESS Scheduler Reminder [{timestamp}]\n\n→ Please switch back to Scheduler mode in the FoxESS app"
            send_notification(ntfy_topic, message)
    
    else:
        print(f"Outside monitoring window (hour: {current_hour})")
    
    print("\n--- Complete ---\n")

if __name__ == "__main__":
    main()
