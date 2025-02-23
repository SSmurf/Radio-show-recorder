import subprocess
import schedule
import time
from datetime import datetime
import os

STREAM_URL = "https://stream.yammat.fm/radio/8000/yammat.mp3"

RECORD_DURATION = "28800" # 8 hours
RECORD_DURATION_TEST = "15" # 15 seconds

RCLONE_REMOTE = "gdrive:Radio recordings"

def record_radio_show(duration=RECORD_DURATION):
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_recording_{now}.mp3"
    print(f"Starting recording, saving to {output_file}...")
    
    # Record the full show using stream copy
    command = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-t", duration,
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
        # os.remove(output_file)
        # print("Local file removed.")
    except subprocess.CalledProcessError as e:
        print("An error occurred during recording or upload:", e)

def test_record_radio_show(duration=RECORD_DURATION_TEST):
    now = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    output_file = f"yammat_test_recording_{now}.mp3"
    print(f"Starting test recording, saving to {output_file}...")
    
    # Record a short 15-second test show, re-encoding to MP3
    command = [
        "ffmpeg",
        "-i", STREAM_URL,
        "-t", duration,
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

def upload_test_file():
    test_file = "test.mp3"
    rclone_command = [
        "rclone",
        "copy",
        test_file,
        "gdrive:Radio recordings",
        "--progress"
    ]

    start_time = time.time()
    print("Uploading test file to Google Drive...")
    subprocess.run(rclone_command, check=True)
    end_time = time.time()
    print("Upload finished successfully.")

    elapsed_time = end_time - start_time
    print(f"Elapsed time: {elapsed_time:.2f} seconds")

# upload_test_file()


# Schedule recording every Friday at 20:55.
schedule.every().friday.at("20:55").do(record_radio_show)

# Schedule test recording every minute
# schedule.every(5).minutes.do(test_record_radio_show)
#schedule every sunday at 13 26
# schedule.every().sunday.at("13:28").do(record_radio_show)
#schedule for every day at 18:00 and every sunday at 19:00 each for 30 minutes
schedule.every().day.at("18:07").do(record_radio_show("1800"))
schedule.every().sunday.at("19:00").do(record_radio_show("1800"))


print("Radio recording scheduler is running...")

time.sleep(60)
test_record_radio_show()


while True:
    schedule.run_pending()
    time.sleep(30)
