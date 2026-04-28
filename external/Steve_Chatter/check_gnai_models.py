"""
check_gnai_models.py
查詢 GNAI 端點支援的語言模型清單
用法：python check_gnai_models.py "<Bearer_Token>"
      或直接執行後貼上 token
"""

import sys
import json
import urllib.request
import urllib.error

GNAI_MODELS_URL = "https://gnai.intel.com/api/providers/openai/v1/models"


def fetch_models(token: str):
    req = urllib.request.Request(
        GNAI_MODELS_URL,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
            return data
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="replace")
        print(f"HTTP {e.code} 錯誤：{e.reason}")
        print(f"回應內容：{body}")
        sys.exit(1)
    except urllib.error.URLError as e:
        print(f"連線失敗：{e.reason}")
        sys.exit(1)


def main():
    if len(sys.argv) >= 2:
        token = sys.argv[1].strip()
    else:
        token = input("請貼上 OAuth2 Bearer Token：").strip()

    if not token:
        print("未提供 token，結束。")
        sys.exit(1)

    print(f"\n查詢中：{GNAI_MODELS_URL}\n")
    data = fetch_models(token)

    models = data.get("data", [])
    if not models:
        print("回應中沒有 data 欄位，原始內容：")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return

    print(f"共找到 {len(models)} 個模型：\n")
    for m in sorted(models, key=lambda x: x.get("id", "")):
        model_id = m.get("id", "unknown")
        owned_by = m.get("owned_by", "")
        print(f"  {model_id:<40} {owned_by}")


if __name__ == "__main__":
    main()
