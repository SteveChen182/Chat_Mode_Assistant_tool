import json
import logging
import os
import warnings

import certifi
import requests
from urllib3.exceptions import InsecureRequestWarning

logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

DEFAULT_API_KEY = "pak_ZSzDDU-sbWB_y_oBYD4jg3xnPoAcNTTkaEvXxCgibuM"
REQUEST_URL = "https://expertgpt.intel.com/v1/quota"
CONNECT_TIMEOUT = float(os.getenv("QUOTA_CONNECT_TIMEOUT", "5"))
READ_TIMEOUT = float(os.getenv("QUOTA_READ_TIMEOUT", "30"))

def _resolve_api_key():
    env_key = os.getenv("EXPERTGPT_API_KEY")
    if env_key:
        return env_key
    logging.warning(
        "Using embedded API key; consider setting EXPERTGPT_API_KEY in the environment"
    )
    return DEFAULT_API_KEY


def _get_ssl_verify():
    skip_ssl = os.getenv("EXPERTGPT_SKIP_SSL_VERIFY")
    if skip_ssl and skip_ssl.lower() in {"1", "true", "yes"}:
        warnings.warn(
            "SSL verification is disabled. This is unsafe unless you trust the network.",
            InsecureRequestWarning,
        )
        return False

    return os.getenv("EXPERTGPT_SSL_CERT_PATH") or certifi.where()


def test_quota_endpoint(api_key):
    """Test the /v1/quota endpoint with an existing API key"""

    if not api_key:
        print("❌ No personal API key found in database")
        print("Please generate one from your profile page first")
        return False

    print(f"API Key: {api_key[:15]}...")
    print()

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    print("🔍 Testing /v1/quota endpoint...")
    print(f"URL: {REQUEST_URL}")
    print()

    verify = _get_ssl_verify()
    timeout = (CONNECT_TIMEOUT, READ_TIMEOUT)

    try:
        with requests.Session() as session:
            response = session.get(
                REQUEST_URL,
                headers=headers,
                timeout=timeout,
                verify=verify,
            )

        print(f"Status Code: {response.status_code}")
        print()

        if response.status_code == 200:
            quota_data = response.json()
            print("✅ SUCCESS! Quota endpoint is working perfectly!")
            print()
            print("📊 QUOTA SUMMARY:")
            print("=" * 50)

            summary = quota_data.get("quota_summary", {})
            daily_usage = summary.get("daily_usage", 0)
            daily_limit = summary.get("daily_limit", 0)
            daily_remaining = summary.get("daily_remaining", 0)
            print(f"📧 User: {quota_data.get('user', 'N/A')}")
            print(f"📈 Daily Usage: {daily_usage} calls")
            print(f"🎯 Daily Limit: {daily_limit} calls")
            print(f"⚡ Daily Remaining: {daily_remaining} calls")
            print(f"🔄 Reset Time: {summary.get('reset_time', 'N/A')}")
            print(f"🧮 Remaining Budget: {daily_remaining}/{daily_limit} calls today")
            print()

            print("🤖 MODEL QUOTAS:")
            print("=" * 50)
            model_quotas = quota_data.get("model_quotas", {})
            total_model_remaining = 0

            for model, quota_info in model_quotas.items():
                quota_type = quota_info.get("quota_type", "unknown")
                used = quota_info.get("used", 0)
                limit = quota_info.get("limit", 0)
                remaining = quota_info.get("remaining", 0)
                total_model_remaining += remaining
                expires = quota_info.get("expires_at")

                # Status indicators
                if remaining > limit * 0.7:
                    status_icon = "🟢"
                elif remaining > limit * 0.3:
                    status_icon = "🟡"
                elif remaining > 0:
                    status_icon = "🟠"
                else:
                    status_icon = "🔴"

                custom_icon = " 🔥" if quota_type == "custom" else ""

                print(f"{status_icon} {model}{custom_icon}")
                print(f"   📊 Used: {used}/{limit} calls ({quota_type})")
                print(f"   ⚡ Remaining: {remaining} calls")
                if expires:
                    print(f"   ⏰ Expires: {expires}")
                print()

            print(f"🎁 Custom Quotas Active: {quota_data.get('custom_quotas_count', 0)}")
            print(f"🧮 模型剩餘總計: {total_model_remaining} calls")
            print(f"🕐 Last Updated: {quota_data.get('last_updated', 'N/A')}")
            print("\n" + "=" * 60)
            print("🐚 EXAMPLE CURL COMMAND:")
            print("=" * 60)
            print(
                f"""curl -X GET \
  "https://expertgpt.intel.com/v1/quota" \
  -H "Authorization: Bearer {api_key}" \
  -H "Content-Type: application/json"""
            )

            return True

        print("❌ ERROR! Quota endpoint failed.")
        print(f"Status: {response.status_code}")
        try:
            error_data = response.json()
            print(f"Error Response: {json.dumps(error_data, indent=2)}")
        except ValueError:
            print(f"Raw Response: {response.text}")
        return False

    except requests.exceptions.Timeout as timeout_err:
        print("❌ TIMEOUT ERROR!")
        print("The quota endpoint did not respond within the allotted time.")
        print("Consider increasing QUOTA_READ_TIMEOUT (secs) or verifying network access.")
        logging.debug("Timeout details: %s", timeout_err)
        return False

    except requests.exceptions.SSLError as ssl_err:
        print("❌ SSL ERROR!")
        print("Unable to establish a secure connection to the quota endpoint.")
        print("Verify the certificate (EXPERTGPT_SSL_CERT_PATH) or disable verification intentionally.")
        logging.debug("SSL details: %s", ssl_err)
        return False

    except requests.exceptions.ConnectionError:
        print("❌ CONNECTION ERROR!")
        print("Check if you can access: https://expertgpt.intel.com")
        return False

    except Exception as e:
        print(f"❌ UNEXPECTED ERROR: {e}")
        import traceback

        print(traceback.format_exc())
        return False

if __name__ == "__main__":
    print("🚀 TESTING /v1/quota ENDPOINT")
    print("=" * 60)
    
    api_key = _resolve_api_key()
    success = test_quota_endpoint(api_key)
    
    if success:
        print("\n" + "=" * 60)
        print("🎉 TEST COMPLETED SUCCESSFULLY!")
        print("The /v1/quota endpoint is working correctly.")
        print("\n📋 WHAT THIS ENDPOINT PROVIDES:")
        print("• Daily usage and remaining calls")
        print("• Per-model quota information")
        print("• Custom quota details (if any)")
        print("• Quota reset times")
        print("• API-compatible format")
    else:
        print("\n" + "=" * 60)
        print("❌ TEST FAILED!")
        print("Check the error messages above.")
