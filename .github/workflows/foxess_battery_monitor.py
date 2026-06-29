import os
import sys
import json
import hmac
import hashlib
import requests
from datetime import datetime
from urllib.parse import urlencode
import pytz

class FoxESSAPI:
    def __init__(self, api_key, sn, secret):
        self.api_key = api_key
        self.sn = sn
        self.secret = secret
        self.base_url = "https://www.foxesscloud.com/api"
    
    def _sign_request(self, path, params):
        """Generate HMAC-MD5 signature for FoxESS API"""
        string_to_sign = path + urlencode(sorted(params.items()))
        signature = hmac.new(
            self.secret.encode(),
            string_to_sign.encode(),
            hashlib.md5
        ).hexdigest()
        return signature
    
    def get_soc(self):
        """Get current battery state of charge"""
        path = "/device/queryDeviceById"
        params = {
            "sn": self.sn,
            "appVersion": "4.0.0",
            "lang": "en"
        }
        params["sign"] = self._sign_request(path, params)
        params["token"] = self.api_key
        
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
                raise Exception(f"API error: {data.get('msg')}")
        except Exception as e:
            print(f"✗ Error getting SOC: {e}", file=sys.stderr)
            return None
    
    def set_battery_mode(self, mode):
        """
        Set battery mode
        mode: "Self-use" or "Scheduler"
        """
        path = "/device/setBattery"
        params = {
            "sn": self.sn,
            "batHighestCap": 100,
            "batLowestCap": 20,
            "batChargePower": 3000,
            "batDischargePower": 3000,
            "batWorkMode": mode
        }
        params["sign"] = self._sign_request(path, params)
        params["token"] = self.api_key
        
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
                raise Exception(f"API error: {data.get('msg')}")
        except Exception as e:
            print(f"✗ Error setting mode: {e}", file=sys.stderr)
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
    """Load state from file"""
    state_file = "foxess_state.json"
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
    except Exception as e:
        print(f"Note: Could not load state: {e}")
    
    return {"switched_to_self_use": False, "date": None}

def save_state(state):
    """Save state to file"""
    state_file = "foxess_state.json"
    try:
        with open(state_file, 'w') as f:
            json.dump(state, f)
        print(f"✓ State saved")
    except Exception as e:
        print(f"Note: Could not save state: {e}")

def reset_daily_state():
    """Reset state if new day"""
    state_file = "foxess_state.json"
    today = datetime.now().strftime("%Y-%m-%d")
    
    try:
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                state = json.load(f)
            
            if state.get("date") != today:
                state = {"switched_to_self_use": False, "date": today}
                save_state(state)
                print(f"✓ Daily state reset")
                return state
            return state
        else:
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
    secret = os.environ.get("FOXESS_SECRET")
    ntfy_topic = os.environ.get("NTFY_TOPIC")
    
    if not all([api_key, sn, secret, ntfy_topic]):
        print("✗ Missing required environment variables", file=sys.stderr)
        sys.exit(1)
    
    # Initialize
    fox = FoxESSAPI(api_key, sn, secret)
    
    # Load state
    state = reset_daily_state()
    already_switched = state.get("switched_to_self_use", False)
    
    # Get Sydney time
    sydney_tz = pytz.timezone('Australia/Sydney')
    now = datetime.now(sydney_tz)
    current_hour = now.hour
    current_minute = now.minute
    timestamp = now.strftime("%Y-%m-%d %H:%M:%S")
    
    print("\n--- FoxESS Battery Monitor ---")
    print(f"Time: {timestamp}")
    print(f"Status: {'Already switched to Self Use' if already_switched else 'Normal monitoring'}")
    
    # Between 6pm-8pm: Monitor and switch if needed
    if 18 <= current_hour < 21:
        print(f"\n⏰ Monitoring window (6pm-8pm)")
        
        if already_switched:
            print("⏭️  Already switched to Self Use today - skipping SOC check")
            print("   (Will switch back to Scheduler at 9pm)")
        else:
            # Get SOC
            soc = fox.get_soc()
            if soc is None:
                print("✗ Failed to retrieve SOC", file=sys.stderr)
                sys.exit(1)
            
            print(f"SOC: {soc}%")
            
            if soc < 60:
                print(f"⚠️  SOC LOW ({soc}%) - Attempting to switch to Self Use...")
                success = fox.set_battery_mode("Self-use")
                
                if success:
                    state["switched_to_self_use"] = True
                    save_state(state)
                    message = f"🔋 FoxESS Alert [{timestamp}]\nSOC: {soc}%\n→ Switched to Self Use mode"
                    send_notification(ntfy_topic, message)
                else:
                    message = f"⚠️  FoxESS Alert [{timestamp}]\nSOC: {soc}% (BELOW THRESHOLD)\n❌ Could not auto-switch\n→ Manual action needed"
                    send_notification(ntfy_topic, message)
            else:
                print(f"✓ SOC healthy ({soc}%) - No action needed")
    
    # At 9pm: Always switch back to Scheduler
    elif current_hour == 21:
        if 0 <= current_minute < 5:
            print(f"\n⏰ 9pm - Attempting to switch back to Scheduler...")
            success = fox.set_battery_mode("Scheduler")
            
            if success:
                state["switched_to_self_use"] = False
                save_state(state)
                message = f"📅 FoxESS Schedule [{timestamp}]\n→ Switched back to Scheduler mode"
                send_notification(ntfy_topic, message)
            else:
                message = f"⚠️  FoxESS Alert [{timestamp}]\n❌ Could not switch to Scheduler\n→ Manual action needed"
                send_notification(ntfy_topic, message)
    
    else:
        print(f"Outside monitoring window (hour: {current_hour})")
    
    print("\n--- Complete ---\n")

if __name__ == "__main__":
    main()
