import requests
import base64

import os

api_key = os.getenv("GOOGLE_TTS_API_KEY", "") or os.getenv("GEMINI_API_KEY", "")
ssml = '<speak><prosody rate="1.15" pitch="+1st">दो अलग-अलग साइज़ के पाइप को जोड़ना <emphasis level="strong">बच्चों का खेल</emphasis> नहीं है!</prosody><break time="200ms"/><prosody rate="1.0" pitch="-1st">पहले बड़े पाइप पर टेप लपेटकर मार्किंग कर लो।</prosody></speak>'

for v in ["hi-IN-Chirp3-HD-Orus", "hi-IN-Neural2-B"]:
    url = f"https://texttospeech.googleapis.com/v1/text:synthesize?key={api_key}"
    payload = {
        "input": {"ssml": ssml},
        "voice": {"languageCode": "hi-IN", "name": v},
        "audioConfig": {"audioEncoding": "MP3"}
    }
    resp = requests.post(url, json=payload)
    if resp.status_code == 200:
        data = base64.b64decode(resp.json()["audioContent"])
        print(f"{v}: SSML SUCCESS! ({len(data)} bytes)")
        with open(f"output/test_ssml_{v}.mp3", "wb") as f:
            f.write(data)
    else:
        print(f"{v}: SSML ERROR ({resp.status_code}): {resp.text[:250]}")
