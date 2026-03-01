import subprocess
import sys

def speak(text):
    subprocess.run(["espeak-ng", text])

if __name__ == "__main__":
    if len(sys.argv) > 1:
        speak(" ".join(sys.argv[1:]))
    else:
        speak("Hello, this is a test of eSpeak NG on Raspberry Pi.")
