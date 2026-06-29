import os
import sys
import json
import requests
from datetime import datetime

class FoxESSAPI:
    def __init__(self, api_key, sn):
        self.api_key = api_key
        self.sn = sn
        self.base_url = "https://www.foxesscloud.com/api"
    
    def get_soc(self):
        """Get current battery state of charge using just API key"""
        path = "/device/queryDeviceById"
        params = {
            "sn": self.sn,
            "appVersion": "4.0.0",
            "lang": "en",
            "token": self.api_key  # Only require API key
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
    
    def attempt_set_battery_mode(self, mode):
        """
        Try to set battery mode with API key only.
        
        Note: This may fail if FoxESS requires signing.
        If it does, you'll need to:
        1. Use the web portal manually, OR
        2. Use the workarounds in PART 3 below
        """
        path = "/device/setBattery"
        params = {
            "sn": self.sn,
            "batWorkMode": mode,  # "Self-use" or "Scheduler"
            "token": self.api_key
        }
        
        try:
            response = requests.post(
                f"{self.base_url}{path}",
                data=params,
                timeout=10
            )
            response.raise_for_status()
            data = response.json()
            
            if data.get("code") == 0:
                print(f"✓ Mode set to: {mode}")
                return True
            else:
                error_msg = data.get("msg", "Unknown error")
                print(f"✗ Mode change failed: {error_msg}", file=sys.stderr)
                return False
        except Exception as e:
            print(f"✗ Mode change error: {e}", file=sys.stderr)
            return False

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
    """Load state from file to track if we've already switched today"""
    state_file = "foxess_state.json"
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Note: Could not load state file: {e}")
    
    return {"switched_to_self_use": False, "date": None}

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
                state = {"switched_to_self_use": False, "date": today}
                save_state(state)
                print(f"✓ Daily state reset")
                return state
            return state
        else:
            # First run - create state file
            state = {"switched_to_self_use": False, "date": today}
            save_state(state)
            return state
    except Exception as e:
        print(f"Note: Error in daily reset: {e}")
        return {"switched_to_self_use": False, "date": today}

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
    already_switched = state.get("switched_to_self_use", False)
    
    print("\n--- FoxESS Battery Monitor ---")
    
    current_hour = datetime.now().hour
    current_minute = datetime.now().minute
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    
    print(f"Time: {timestamp}")
    print(f"Status: {'Already switched to Self Use' if already_switched else 'Normal monitoring'}")
    
    # Between 6pm-8pm: Monitor and attempt to switch (only if not already switched)
    if 18 <= current_hour < 20:
        print(f"\n⏰ Monitoring window (6pm-8pm)")
        
        if already_switched:
            print("⏭️  Already switched to Self Use today - skipping SOC check")
            print("   (Will switch back to Scheduler at 9pm)")
        else:
            # Get SOC
            soc = fox.get_soc()
            if soc is None:
                print("✗ Failed to retrieve SOC. Check API key and SN.", file=sys.stderr)
                sys.exit(1)
            
            print(f"SOC: {soc}%")
            
            if soc < 40:
                print(f"⚠️  SOC LOW ({soc}%) - Attempting to switch to Self Use...")
                success = fox.attempt_set_battery_mode("Self-use")
                
                if success:
                    # Mark as switched and save state
                    state["switched_to_self_use"] = True
                    save_state(state)
                    
                    message = f"🔋 FoxESS Alert [{timestamp}]\nSOC: {soc}%\n→ Switched to Self Use"
                    send_notification(ntfy_topic, message)
                else:
                    # Mode change failed - send alert anyway so you know
                    message = f"⚠️  FoxESS Alert [{timestamp}]\nSOC: {soc}% (BELOW THRESHOLD)\n❌ Could not auto-switch mode\n→ Manual action may be needed"
                    send_notification(ntfy_topic, message)
            else:
                print(f"✓ SOC healthy ({soc}%) - No action needed")
    
    # At 9pm: Always attempt to switch back to Scheduler (regardless of switched state)
    elif current_hour == 21:
        if 0 <= current_minute < 5:
            print(f"\n⏰ 9pm - Attempting to switch back to Scheduler...")
            success = fox.attempt_set_battery_mode("Scheduler")
            
            if success:
                # Reset the switched flag
                state["switched_to_self_use"] = False
                save_state(state)
                
                message = f"📅 FoxESS Schedule [{timestamp}]\n→ Switched back to Scheduler mode"
                send_notification(ntfy_topic, message)
            else:
                message = f"⚠️  FoxESS Alert [{timestamp}]\n❌ Could not switch to Scheduler\n→ Manual action may be needed"
                send_notification(ntfy_topic, message)
    
    else:
        print(f"Outside monitoring window (hour: {current_hour})")
    
    print("\n--- Complete ---\n")

if __name__ == "__main__":
    main()


