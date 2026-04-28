"""
test_gnai_models.py
逐一測試 GNAI OAuth2 模型是否可連線，自動輸出可用清單。
用法：python test_gnai_models.py "<Bearer_Token>"
      或直接執行後貼上 token
"""

import sys
import json
import re
import urllib.request
import urllib.error
import time

GNAI_BASE_URL = "https://gnai.intel.com/api/providers/openai/v1/chat/completions"
TIMEOUT_SEC = 20

# 注意：此清單需與 models.js 的 OAUTH2_MODELS 保持同步
OAUTH2_MODELS = [
    'gpt-4o',
    'gpt-4.1',
    'gpt-5-mini',
    'gpt-5-nano',
    'gpt-5.1',
    'gpt-5.2',
    'gpt-5.4',
    'gpt-5.4-mini',
    'gpt-5.4-nano',
    'o3',
    'o3-mini',
    'o4-mini',
]


def is_reasoning_model(model: str) -> bool:
    return bool(re.match(r'^o\d', model, re.IGNORECASE) or re.match(r'^gpt-5', model, re.IGNORECASE))


def build_payload(model: str) -> dict:
    base = {"model": model, "messages": [{"role": "user", "content": "hi"}]}
    if is_reasoning_model(model):
        base["max_completion_tokens"] = 5
    else:
        base["max_tokens"] = 5
        base["temperature"] = 0
    return base


def test_model(token: str, model: str) -> tuple[bool, str]:
    body = json.dumps(build_payload(model)).encode()
    req = urllib.request.Request(
        GNAI_BASE_URL,
        data=body,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=TIMEOUT_SEC) as resp:
            resp.read()
            return True, "OK"
    except urllib.error.HTTPError as e:
        body_txt = e.read().decode(errors="replace")[:200]
        return False, f"HTTP {e.code}: {body_txt}"
    except urllib.error.URLError as e:
        return False, f"連線失敗: {e.reason}"
    except Exception as e:
        return False, str(e)


def main():
    if len(sys.argv) >= 2:
        token = sys.argv[1].strip()
    else:
        token = input("請貼上 OAuth2 Bearer Token：").strip()

    if not token:
        print("未提供 token，結束。")
        sys.exit(1)

    print(f"\n共 {len(OAUTH2_MODELS)} 個模型，逐一測試中...\n")
    print(f"{'模型':<28} {'狀態'}")
    print("-" * 60)

    ok_models = []
    fail_models = []

    for model in OAUTH2_MODELS:
        success, msg = test_model(token, model)
        status = "✅ 可用" if success else f"❌ {msg}"
        print(f"{model:<28} {status}")
        if success:
            ok_models.append(model)
        else:
            fail_models.append(model)
        time.sleep(0.5)

    print("\n" + "=" * 60)
    print(f"可用模型 {len(ok_models)}/{len(OAUTH2_MODELS)} 個：")
    for m in ok_models:
        print(f"  '{m}',")
    print()

    if fail_models:
        print(f"無法連線（建議從 sidepanel.js 移除）：")
        for m in fail_models:
            print(f"  {m}")


if __name__ == "__main__":
    main()
