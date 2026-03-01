import requests
import sys

# Usage: python test_stt_api.py path/to/audio.wav
if len(sys.argv) != 2:
    print("Usage: python test_stt_api.py path/to/audio.wav")
    sys.exit(1)

wav_path = sys.argv[1]
url = "http://localhost:8080/api/speech-to-text"

with open(wav_path, "rb") as f:
    files = {"audio": f}
    response = requests.post(url, files=files)

print("Status:", response.status_code)
print("Response:", response.json())
