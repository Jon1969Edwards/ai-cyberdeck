import os
import urllib.request
import tarfile

MODEL_URL = "https://alphacephei.com/vosk/models/vosk-model-small-en-us-0.15.zip"
MODEL_DIR = "vosk-model-small-en-us-0.15"

if os.path.exists(MODEL_DIR):
    print(f"Model already exists at {MODEL_DIR}")
    exit(0)

print("Downloading Vosk small English model (~50MB)...")
zip_path = "vosk-model-small-en-us-0.15.zip"
urllib.request.urlretrieve(MODEL_URL, zip_path)

print("Extracting model...")
import zipfile
with zipfile.ZipFile(zip_path, 'r') as zip_ref:
    zip_ref.extractall(".")

print("Cleaning up...")
os.remove(zip_path)

print(f"Model ready at {MODEL_DIR}")
