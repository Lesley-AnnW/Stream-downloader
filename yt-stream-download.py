import yt_dlp
import datetime
import os
import threading
import logging
import sys
import shutil
import json
import uuid

CONFIG_FILE = 'config.json'

def setup_logging(log_file=None):
    """
    Sets up logging to console and optionally to a log file.
    """
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)
    handlers = [logging.StreamHandler(sys.stdout)]
    if log_file:
        file_handler = logging.FileHandler(log_file)
        file_handler.setFormatter(logging.Formatter('%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'))
        handlers.append(file_handler)
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
        handlers=handlers
    )
    if log_file:
        logging.info(f"Logging to file: {log_file}")

def load_configuration(config_path):
    """Loads configuration from a JSON file and validates it."""
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)
        if 'streams' not in config or not isinstance(config['streams'], list):
            raise ValueError("Config missing 'streams' list.")
        if 'output_dir' not in config:
            raise ValueError("Config missing 'output_dir'.")
        return config
    except Exception as e:
        logging.error(f"Failed to load configuration: {e}")
        sys.exit(1)

def get_start_time_from_user():
    """Prompt user for HH:MM and return hour, minute as ints."""
    while True:
        user_input = input("Enter start time for recording (HH:MM, 24-hour format): ").strip()
        try:
            parts = user_input.split(":")
            if len(parts) != 2:
                raise ValueError
            hour = int(parts[0])
            minute = int(parts[1])
            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError
            return hour, minute
        except ValueError:
            print("Invalid format. Please enter time as HH:MM (e.g., 09:30 or 17:45).")

def cleanup_part_files(directory):
    """Removes leftover yt-dlp/ffmpeg partial files to prevent collision errors."""
    for fname in os.listdir(directory):
        if fname.endswith('.part'):
            try:
                os.remove(os.path.join(directory, fname))
                logging.info(f"Removed leftover .part file: {fname}")
            except Exception as e:
                logging.warning(f"Could not remove .part file {fname}: {e}")

shutdown_event = threading.Event()

def download_segment(stream_url, stream_name, quality, output_dir, segment_duration_sec):
    """Downloads a single segment for a given stream."""
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
        logging.exception(f"[{thread_name}] Download failed for {stream_name}: {e}")

def start_downloads(config):
    """Initializes and manages the download threads."""
    output_dir = config['output_dir']
    segment_duration = config.get('segment_duration', 3600)
    streams = config.get('streams', [])

    logging.info("Starting download threads...")
    if not streams:
        logging.warning("No streams configured in the 'streams' list. Nothing to download.")
        return

    active_threads = []
    for stream in streams:
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
            name=f"Thread-{stream['stream_name'][:10]}"
        )
        thread.daemon = True
        thread.start()
        active_threads.append(thread)

    if not active_threads:
        logging.warning("No valid streams found to start download threads.")
        return

    try:
        while any(t.is_alive() for t in active_threads):
            threading.Event().wait(1)
        logging.info("All download threads have completed.")
    except KeyboardInterrupt:
        logging.warning("Ctrl+C detected! Signaling download threads to shut down gracefully...")
        shutdown_event.set()
    finally:
        logging.info("Waiting for all download threads to finish...")
        for thread in active_threads:
            thread.join()
        logging.info("All download threads have finished.")

def main():
    config = load_configuration(CONFIG_FILE)
    setup_logging(config.get("log_file"))
    if shutil.which('ffmpeg') is None:
        logging.error("ffmpeg not found in system PATH. Please install ffmpeg and ensure it's accessible.")
        sys.exit(1)
    else:
        logging.info("ffmpeg found.")

    output_dir = config['output_dir']
    try:
        os.makedirs(output_dir, exist_ok=True)
        logging.info(f"Output directory set to: {output_dir}")
    except OSError as e:
        logging.error(f"Could not create output directory '{output_dir}': {e}")
        sys.exit(1)

    cleanup_part_files(output_dir)

    schedule_enabled = config.get('schedule_enabled', False)
    start_hour = None
    start_minute = 0

    if schedule_enabled:
        start_hour, start_minute = get_start_time_from_user()

    execute_now = True

    if schedule_enabled and start_hour is not None:
        try:
            now = datetime.datetime.now()
            target_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)
            if target_time <= now:
                logging.info(f"Target time {start_hour:02d}:{start_minute:02d} has passed for today. Scheduling for tomorrow.")
                target_time += datetime.timedelta(days=1)
            else:
                logging.info(f"Scheduled start time set for today at {start_hour:02d}:{start_minute:02d}.")

            wait_seconds = (target_time - now).total_seconds()

            if wait_seconds > 0:
                execute_now = False
                logging.info(f"Waiting for {wait_seconds:.2f} seconds (until {target_time})... Press Ctrl+C to cancel wait and exit.")
                try:
                    shutdown_event.wait(timeout=wait_seconds)
                    if shutdown_event.is_set():
                        logging.warning("Wait cancelled by user (Ctrl+C). Exiting.")
                        sys.exit(0)
                    else:
                        logging.info("Scheduled time reached.")
                        execute_now = True
                except KeyboardInterrupt:
                    logging.warning("Wait cancelled by user (Ctrl+C). Exiting.")
                    sys.exit(0)
            else:
                logging.info("Scheduled time is now or immediately upcoming.")
                execute_now = True

        except (ValueError, TypeError) as e:
            logging.error(f"Invalid schedule configuration: {e}. Running immediately.")
            execute_now = True

    else:
        logging.info("Scheduling not enabled or start time not configured. Starting immediately.")
        execute_now = True

    if execute_now:
        start_downloads(config)

    logging.info("Script finished.")

if __name__ == "__main__":
    main()