import yt_dlp
import datetime
import os
import time
import threading
import logging
import sys
import shutil
import json
import uuid

CONFIG_FILE = 'config.json'

# Setup Logging
logging.basicConfig(level=logging.INFO,
                    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
                    handlers=[logging.StreamHandler(sys.stdout)]) # Log to console

def load_configuration(config_path):
    # Loads configuration from a JSON file
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        # Basic validation
        if 'streams' not in config or not isinstance(config['streams'], list):
            raise ValueError("Config missing 'streams' list.")
        if 'output_dir' not in config:
             raise ValueError("Config missing 'output_dir'.")
        return config
    except FileNotFoundError:
        logging.error(f"Configuration file '{config_path}' not found.")
        sys.exit(1)
    except json.JSONDecodeError:
         logging.error(f"Error decoding JSON from '{config_path}'. Check its format.")
         sys.exit(1)
    except ValueError as e:
         logging.error(f"Invalid configuration: {e}")
         sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred loading configuration: {e}")
        sys.exit(1)

# Optional: Remove old .part files at startup
def cleanup_part_files(directory):
    # Removes leftover yt-dlp/ffmpeg partial files to prevent collision errors
    for fname in os.listdir(directory):
        if fname.endswith('.part'):
            try:
                os.remove(os.path.join(directory, fname))
                logging.info(f"Removed leftover .part file: {fname}")
            except Exception as e:
                logging.warning(f"Could not remove .part file {fname}: {e}")

# Signal threads to stop
shutdown_event = threading.Event()

# Downloads a single segment for a given stream 
def download_segment(stream_url, stream_name, quality, output_dir, segment_duration_sec):
    thread_name = threading.current_thread().name
    now = datetime.datetime.now()
    unique_id = uuid.uuid4().hex[:8]
    timestamp = now.strftime('%Y-%m-%d_%H-%M-%S-%f')
    ydl_opts = {
        'format': quality,
        'outtmpl': os.path.join(
            output_dir, 
            f"{stream_name}_livestream_{timestamp}_{unique_id}_%(id)s.%(ext)s"
        ),
        'noplaylist': True,
        'external_downloader': 'ffmpeg',
        'external_downloader_args': ['-y', '-t', str(segment_duration_sec)],
        'quiet': True,
        'noprogress': True,
        'verbose': False,
        'recode_video': 'mp4'
    }

    try:
        logging.info(f"[{thread_name}] Starting download for '{stream_name}'")
        if shutdown_event.is_set():
            logging.info(f"[{thread_name}] Shutdown signalled before starting download for {stream_name}.")
            return
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])
        if shutdown_event.is_set():
            logging.info(f"[{thread_name}] Shutdown signalled after download for {stream_name}.")
            return
        logging.info(f"[{thread_name}] Successfully downloaded segment for {stream_name}")
    except Exception as e:
        logging.error(f"[{thread_name}] Download failed for {stream_name}: {e}")

    if shutdown_event.is_set():
        logging.info(f"[{thread_name}] Download thread for {stream_name} stopping due to shutdown signal.")
    else:
        logging.info(f"[{thread_name}] Download thread for {stream_name} finished.")

def start_downloads(config):
    output_dir = config['output_dir']
    segment_duration = config.get('segment_duration', 50) # TODO: Default 1 hour 3600

    streams = config.get('streams', [])

    logging.info("Starting download threads...")
    if not streams:
        logging.warning("No streams configured in the 'streams' list. Nothing to download.")
        return # Exit if no streams are defined

    active_threads = []
    for stream in streams:
        # Validate stream entry
        if not isinstance(stream, dict) or not all(k in stream for k in ('url', 'stream_name', 'quality')):
             logging.warning(f"Skipping invalid stream entry: {stream}. Must be a dict with 'url', 'stream_name', and 'quality'.")
             continue

        thread = threading.Thread(
            target=download_segment,
            args=(
                stream['url'],
                stream['stream_name'],
                stream['quality'],
                output_dir,
                segment_duration,
            ),
            # Give threads names for logging
            name=f"Thread-{stream['stream_name'][:10]}" # Truncate long names
        )
        thread.daemon = True
        thread.start()
        active_threads.append(thread)

    if not active_threads:
        logging.warning("No valid streams found to start download threads.")
        return

    # Keep the main thread alive while download threads run
    try:
        while any(t.is_alive() for t in active_threads):
            time.sleep(1)
        logging.info("All download threads have completed their work naturally.")

    except KeyboardInterrupt:
        logging.warning("\nCtrl+C detected! Signaling download threads to shut down gracefully...")
        shutdown_event.set()

    finally:
        logging.info("Waiting for all download threads to complete shutdown...")
        for thread in active_threads:
            thread.join() 
        logging.info("All download threads have finished.")

if __name__ == "__main__":
    config = load_configuration(CONFIG_FILE)
    log_file = config.get("log_file", None)
    if log_file:
         file_handler = logging.FileHandler(log_file)
         file_handler.setFormatter(logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'))
         logging.getLogger().addHandler(file_handler)
         logging.info(f"Logging to file: {log_file}")


    # Checks for ffmpeg
    if shutil.which('ffmpeg') is None:
        logging.error("ffmpeg not found in system PATH. Please install ffmpeg and ensure it's accessible.")
        sys.exit(1)
    else:
        logging.info("ffmpeg found.")

    # Checks if output directory exists
    output_dir = config['output_dir']
    try:
        os.makedirs(output_dir, exist_ok=True) # Prevents error if dir exists
        logging.info(f"Output directory set to: {output_dir}")
    except OSError as e:
        logging.error(f"Could not create output directory '{output_dir}': {e}")
        sys.exit(1)

    # Optional: clean up leftover .part files at startup
    cleanup_part_files(output_dir)

    # Scheduling Logic
    schedule_enabled = config.get('schedule_enabled', False)
    start_hour = config.get('start_hour', None)
    start_minute = config.get('start_minute', 0)

    execute_now = True

    if schedule_enabled and start_hour is not None:
        try:
             start_hour = int(start_hour)
             start_minute = int(start_minute)
             if not (0 <= start_hour <= 23 and 0 <= start_minute <= 59):
                 raise ValueError("Invalid hour or minute specified in config.")

             now = datetime.datetime.now()
             target_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)

             # If target time is in the past for today, schedule it for tomorrow
             if target_time <= now:
                 logging.info(f"Target time {start_hour:02d}:{start_minute:02d} has passed for today. Scheduling for tomorrow.")
                 target_time += datetime.timedelta(days=1)
             else:
                 logging.info(f"Scheduled start time set for today at {start_hour:02d}:{start_minute:02d}.")

             wait_seconds = (target_time - now).total_seconds()

             if wait_seconds > 0:
                 execute_now = False # Don't execute immediately, wait first
                 logging.info(f"Waiting for {wait_seconds:.2f} seconds (until {target_time})... Press Ctrl+C to cancel wait and exit.")
                 try:
                     # Wait using the event, allows immediate exit on Ctrl+C during wait
                     shutdown_event.wait(timeout=wait_seconds)
                     if shutdown_event.is_set(): # Check if wait was interrupted by Ctrl+C
                          logging.warning("Wait cancelled by user (Ctrl+C). Exiting.")
                          sys.exit(0)
                     else:
                          # Wait finished naturally
                          logging.info("Scheduled time reached.")
                          execute_now = True # Set flag to execute after wait
                 except KeyboardInterrupt: # Catch Ctrl+C during the wait itself
                      logging.warning("\nWait cancelled by user (Ctrl+C). Exiting.")
                      sys.exit(0)
             else:
                 # This case means the target time is effectively now
                 logging.info("Scheduled time is now or immediately upcoming.")
                 execute_now = True

        except (ValueError, TypeError) as e:
             logging.error(f"Invalid schedule configuration: {e}. Check 'start_hour' and 'start_minute'. Running immediately.")
             execute_now = True # Fallback to immediate execution on bad config

    else:
        logging.info("Scheduling not enabled or start time not configured. Starting immediately.")
        execute_now = True

    # Starts downloads
    if execute_now:
        start_downloads(config)

    logging.info("Script finished.")