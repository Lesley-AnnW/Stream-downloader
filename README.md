# Stream downloader

In this repository you will find a tool for recording and downloading Youtube livestreams. 
The tool provides a script to download livestreams in timed segments, supporting multiple simultaneous stream downloads at once.

## Overview

The code performs the following steps:
1.  **Loads and configures settings** including:
   - List of livestream URLs and their output parameters.
   - Output directory and log file location.
   - Desired segment duration for each recording.
   - Scheduling preference (start now or at a user-specified time).
2.  **Initializes logging** to both console and a log file for tracking of events and errors.
3.  **Checks for required dependencies**
   1. Verifies that ffmpeg is installed and accessible.
   2. Ensures the output directory exists (creates it if needed).
   3. Cleans up any leftover partial (.part) files from previous interrupted downloads.
4.  **Prompts the user for a scheduled start time**
   - Accepts a time (HH:MM) entered by the user or "start now".
   - Waits until the scheduled time to begin downloads, or starts right away with "start now".
5.  **Starts parallel download threads:**
    * For each configured livestream:
       1. Downloads a segment of the livestream of the specified duration and quality.
       2. Saves the segment to the output directory with a timestamped filename.
       3. Handles download errors and logs their status.
6.  **Monitors all download threads:** 
   1. Waits for all threads to finish downloading their segments.
   2. Handles keyboard interruption (Ctrl+C) gracefully, signaling all threads to stop.
7.  **Finishes execution with a summary log message** 

## Requirements

Python package: 
yt-dlp

   ```bash
      pip install yt-dlp
   ``` 

System dependency:
ffmpeg (must be installed and on your system PATH)

Install ffmpeg:

Linux: sudo apt install ffmpeg
macOS: brew install ffmpeg
Windows: Download and add ffmpeg to PATH (https://ffmpeg.org/download.html)

## Input and output

Input:
Stream URLs and settings as specified in config.json

Output:
Downloaded video segments (e.g., .mp4 files) saved to a local directory
Logs written to console and log file

## How to use 
1.  **Check available download quality** 
   Before adding a stream, you want to see what quality options are available for your chosen livestream URL.
   You can do this using yt-dlp directly in your terminal:
   ```bash
      yt-dlp -F your-livestream-url-here
   ```
   This will output a table of available formats. 
   Choose the format code or selector string you want, and use it in the "quality" field in the config.
2.  **Add your stream to the list in the json file**
3.  **Set your desired duration in seconds**
    Examples: 
    For 1-hour chunks, set "segment_duration": 3600
    For 10-minute chunks, set "segment_duration": 600
    For 30-second chunks, set "segment_duration": 30
4. Optional **Repeat steps 1-3 for additional streams**
5. **Set the output directory in "output_dir"**
6. **Run the downloader**
   ```bash
      python yt-stream-downloader.py
   ```
  You will be prompted:
  'Enter start time for recording (HH:MM, 24-hour format) or type 'start now' to begin immediately:'
  Enter your desired start time (e.g., 20:00 to start at 8 PM), or type start now to begin immediately.
  To schedule recordings for tomorrow, just enter a time that has already passed today; the script will wait until that time tomorrow.
7. **Downloading**
   Wait for your download to finish or use Ctrl+C in the terminal to stop the downloader prematurely.
   When shut down prematurely the script will attempt a graceful shutdown and save any in-progress segments.
