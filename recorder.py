import subprocess
import schedule
import time
from datetime import datetime

# Replace with your actual direct stream URL
STREAM_URL = "https://stream.yammat.fm/radio/8000/yammat.mp3"

# Seconds to record: 8 hours = 28800 seconds
RECORD_DURATION = "28800"
RECORD_DURATION_TEST = "15"

def record_radio_show():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_recording_{now}.mp3"
    print(f"Starting recording, saving to {output_file}...")
    
    command = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-t", RECORD_DURATION,
        "-c", "copy",
        output_file
    ]
    
    try:
        subprocess.run(command, check=True)
        print("Recording finished successfully.")
    except subprocess.CalledProcessError as e:
        print("An error occurred during recording:", e)

def test_record_radio_show():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_test_recording_{now}.mp3"
    print(f"Starting test recording, saving to {output_file}...")
    
    command = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-t", RECORD_DURATION_TEST,
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_file
    ]
    
    try:
        subprocess.run(command, check=True)
        print("Test recording finished successfully.")
    except subprocess.CalledProcessError as e:
        print("An error occurred during test recording:", e)

# Schedule recording every Friday at 20:55.
schedule.every().friday.at("20:55").do(record_radio_show)

# Schedule test recording every minute
# schedule.every(1).minutes.do(test_record_radio_show)

print("Radio recording scheduler is running...")

while True:
    schedule.run_pending()
    time.sleep(30)
