from dotenv import dotenv_values
import httpx

cfg = dotenv_values(".env")
url = cfg["LLM_BASE_URL"].rstrip("/") + "/models"
headers = {"Authorization": f"Bearer {cfg['LLM_API_KEY']}"}
r = httpx.get(url, headers=headers, timeout=30)
print("status", r.status_code)
data = r.json()
items = data.get("data") or data.get("models") or data
if isinstance(items, list):
    for m in items:
        mid = m.get("id") if isinstance(m, dict) else m
        print(mid)
else:
    print(str(data)[:2000])
