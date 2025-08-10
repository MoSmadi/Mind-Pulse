import os, json, requests
from dotenv import load_dotenv
load_dotenv()

# ----- FILL THESE (or rely on your .env if you call load_dotenv) -----
AZURE_OPENAI_KEY        = os.getenv("AZURE_OPENAI_KEY") 
AZURE_OPENAI_ENDPOINT   = os.getenv("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_DEPLOYMENT = os.getenv("AZURE_OPENAI_DEPLOYMENT")
AZURE_OPENAI_API_VERSION= os.getenv("AZURE_OPENAI_API_VERSION")
# ---------------------------------------------------------------------

url = f"{AZURE_OPENAI_ENDPOINT}/openai/deployments/{AZURE_OPENAI_DEPLOYMENT}/chat/completions?api-version={AZURE_OPENAI_API_VERSION}"
headers = {"Content-Type": "application/json", "api-key": AZURE_OPENAI_KEY}
payload = {
    "messages": [
        {"role":"system","content":"Return the single word: ok"},
        {"role":"user","content":"Say: ok"}
    ],
    "temperature": 0.0,
    "max_tokens": 5
}

print("POST", url)
try:
    r = requests.post(url, headers=headers, data=json.dumps(payload), timeout=60)
    print("Status:", r.status_code)
    if r.status_code != 200:
        print("Body:", r.text[:1000])
    else:
        data = r.json()
        print("Reply:", data["choices"][0]["message"]["content"])
except Exception as e:
    print("Exception:", type(e).__name__, e)
