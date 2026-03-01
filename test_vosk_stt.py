import sounddevice as sd
import queue
import sys
from vosk import Model, KaldiRecognizer
import json

MODEL_PATH = "vosk-model-small-en-us-0.15"

q = queue.Queue()

def callback(indata, frames, time, status):
    if status:
        print(status, file=sys.stderr)
    q.put(bytes(indata))

def main():
    print("Loading model...")
    model = Model(MODEL_PATH)
    rec = KaldiRecognizer(model, 16000)
    print("Speak into the microphone (Ctrl+C to stop)...")
    with sd.RawInputStream(samplerate=16000, blocksize = 8000, dtype='int16', channels=1, callback=callback):
        while True:
            data = q.get()
            if rec.AcceptWaveform(data):
                result = rec.Result()
                text = json.loads(result).get('text', '')
                if text:
                    print(f"You said: {text}")
            else:
                partial = rec.PartialResult()
                # Optionally print partial results

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\nExiting.")
