import subprocess
import schedule
import time
from datetime import datetime
import os

# Replace with your actual direct stream URL
STREAM_URL = "https://stream.yammat.fm/radio/8000/yammat.mp3"

# Seconds to record: 8 hours = 28800 seconds
RECORD_DURATION = "28800"
RECORD_DURATION_TEST = "15"

# Name of your rclone remote and folder in Google Drive
RCLONE_REMOTE = "gdrive:Radio recordings"

def record_radio_show():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_recording_{now}.mp3"
    print(f"Starting recording, saving to {output_file}...")
    
    # Record the full show using stream copy
    command = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-t", RECORD_DURATION,
        "-c:a", "libmp3lame",
        "-b:a", "192k",
        output_file
    ]
    
    try:
        subprocess.run(command, check=True)
        print("Recording finished successfully.")
        
        # Use rclone to copy the recording file to Google Drive
        rclone_command = [
            "rclone",
            "copy",
            output_file,
            RCLONE_REMOTE,
            "--progress"
        ]
        print("Uploading recording to Google Drive...")
        subprocess.run(rclone_command, check=True)
        print("Upload finished successfully.")
        
        # Optionally remove the local file after successful upload
        os.remove(output_file)
        print("Local file removed.")
    except subprocess.CalledProcessError as e:
        print("An error occurred during recording or upload:", e)

def test_record_radio_show():
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_test_recording_{now}.mp3"
    print(f"Starting test recording, saving to {output_file}...")
    
    # Record a short 15-second test show, re-encoding to MP3
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
        
        # Use rclone to copy the test recording file to Google Drive
        rclone_command = [
            "rclone",
            "copy",
            output_file,
            RCLONE_REMOTE,
            "--progress"
        ]
        print("Uploading test recording to Google Drive...")
        subprocess.run(rclone_command, check=True)
        print("Upload finished successfully.")
        
        # Optionally remove the local file after successful upload
        # os.remove(output_file)
        # print("Local file removed.")
    except subprocess.CalledProcessError as e:
        print("An error occurred during test recording or upload:", e)

# Schedule recording every Friday at 20:55.
schedule.every().friday.at("20:55").do(record_radio_show)

# Schedule test recording every minute
# schedule.every(1).minutes.do(test_record_radio_show)
#schedule every sunday at 13 26
# schedule.every().sunday.at("13:28").do(record_radio_show)

print("Radio recording scheduler is running...")

# test_record_radio_show()

while True:
    schedule.run_pending()
    time.sleep(30)
