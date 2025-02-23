#!/bin/bash
source "/home/ssmurf/PythonProjects/Radio-show-recorder/.venv/bin/activate"  # Activate virtual environment
cd "/home/ssmurf/PythonProjects/Radio-show-recorder"  # Navigate to script directory
/home/ssmurf/PythonProjects/Radio-show-recorder/.venv/bin/python recorder.py >> "/home/ssmurf/PythonProjects/Radio-show-recorder/radio_log.txt" 2>&1 &
