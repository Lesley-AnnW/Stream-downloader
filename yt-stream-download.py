import yt_dlp
import datetime
import os
import threading
import logging
import sys
import shutil
import json
import time  

from constants import CONFIG_FILE, DEFAULT_SEGMENT_DURATION, DEFAULT_OUTPUT_DIR, DEFAULT_LOG_FILE

shutdown_event = threading.Event()

def setup_logging(log_file=None):
    """Sets up logging to console and optionally to a log file."""
    for handler in logging.root.handlers[:]:
        logging.root.removeHandler(handler)

    log_format = '%(asctime)s - %(threadName)s - %(levelname)s - %(message)s'
    formatter = logging.Formatter(log_format)

    handlers = [logging.StreamHandler(sys.stdout)]

    if log_file:
        try:
            file_handler = logging.FileHandler(log_file, mode='a')
            file_handler.setFormatter(formatter)
            handlers.append(file_handler)
        except Exception as e:
            print(f"Failed to set up log file handler for {log_file}: {e}", file=sys.stderr)
            print("Continuing with console logging only.", file=sys.stderr)
            logging.info("Continuing with console logging only.")
            log_file = None

    logging.basicConfig(level=logging.INFO, format=log_format, handlers=handlers)

    if log_file:
        logging.info(f'Logging to file: {log_file}')
    else:
        logging.info('Logging to console only.')



def load_configuration(config_path):
    '''Loads configuration from JSON file and validates it.'''
    try:
        with open(config_path, 'r') as f:
            config = json.load(f)

        if 'streams' not in config or not isinstance(config['streams'], list):
            raise ValueError("Config missing 'streams' list or 'streams' is not a list.")

        if 'output_dir' not in config:
            logging.warning(f"'output_dir' not found in config, using default: {DEFAULT_OUTPUT_DIR}")
            config['output_dir'] = DEFAULT_OUTPUT_DIR
        if 'segment_duration' not in config:
             logging.warning(f"'segment_duration' not found in config, using default: {DEFAULT_SEGMENT_DURATION}")
             config['segment_duration'] = DEFAULT_SEGMENT_DURATION
        if 'log_file' not in config:
             logging.warning(f"'log_file' not found in config, using default: {DEFAULT_LOG_FILE}")
             config['log_file'] = DEFAULT_LOG_FILE
        if 'schedule_enabled' not in config:
             logging.warning(f"'schedule_enabled' not found in config, defaulting to False.")
             config['schedule_enabled'] = False

        return config
    except FileNotFoundError:
        logging.error(f"Configuration file not found: {config_path}")
        sys.exit(1)
    except json.JSONDecodeError as e:
        logging.error(f"Error decoding JSON from configuration file {config_path}: {e}")
        sys.exit(1)
    except ValueError as e:
        logging.error(f"Invalid configuration in {config_path}: {e}")
        sys.exit(1)
    except Exception as e:
        logging.error(f"An unexpected error occurred while loading configuration: {e}")
        sys.exit(1)

def get_start_time_from_user():
    '''
    Prompts user for start time as HH:MM or 'start now'.
    Returns a tuple (hour, minute) or None if 'start now'.
    '''
    while True:
        user_input = input(
            "Enter start time for recording (HH:MM, 24-hour format) "
            "or type 'start now' to begin immediately: "
        ).strip().lower()

        if user_input == 'start now':
            return None

        try:
            parts = user_input.split(':')
            if len(parts) != 2:
                raise ValueError("Input must contain exactly one colon.")

            hour = int(parts[0])
            minute = int(parts[1])

            if not (0 <= hour <= 23 and 0 <= minute <= 59):
                raise ValueError("Hour must be between 00-23 and Minute between 00-59.")

            return hour, minute
        except ValueError as e:
            print(f"Invalid format or value: {e}. Please enter time as HH:MM (e.g., 09:30 or 17:45), or type 'start now'.")
        except Exception as e:
             print(f"An unexpected error occurred: {e}. Please try again.")


def cleanup_part_files(directory):
    '''Removes leftover yt-dlp/ffmpeg partial files (.part) in the specified directory.'''
    logging.debug(f"Checking for leftover '.part' files in {directory}")
    removed_count = 0
    for fname in os.listdir(directory):
        if fname.endswith('.part'):
            file_path = os.path.join(directory, fname)
            try:
                os.remove(file_path)
                logging.info(f'Removed leftover .part file: {fname}')
                removed_count += 1
            except OSError as e:
                logging.warning(f'Could not remove .part file {file_path}: {e}')
            except Exception as e:
                 logging.warning(f'Unexpected error removing .part file {file_path}: {e}')
    if removed_count == 0:
        logging.debug("No leftover '.part' files found.")

def download_segment(stream_url, stream_name, quality, output_dir, segment_duration_sec):
    '''Downloads a single segment for a given stream.'''
    thread_name = threading.current_thread().name
    now = datetime.datetime.now()
    timestamp = now.strftime('%Y-%m-%d_%H-%M-%S')

    output_template = os.path.join(
        output_dir,
        f'{stream_name}_{timestamp}.%(ext)s'
    )
    ydl_opts = {
        'format': quality,
        'outtmpl': output_template,
        'external_downloader': 'ffmpeg',
        'external_downloader_args': ['-y', '-t', str(segment_duration_sec)],
        'quiet': True,
        'noprogress': True,
        'verbose': False,
        'postprocessors': [{ 
            'key': 'FFmpegVideoConvertor',
            'preferedformat': 'mp4', 
        }],
    }

    try:
        if shutdown_event.is_set():
            logging.info(f'[{thread_name}] Shutdown signalled before starting download for {stream_name}. Aborting segment.')
            return

        logging.info(f'[{thread_name}] Starting download segment for "{stream_name}" (URL: {stream_url[:30]}...)')

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])

        if shutdown_event.is_set():
             logging.info(f'[{thread_name}] Shutdown signalled during/after download for {stream_name}. Segment likely saved.')

        logging.info(f'[{thread_name}] Successfully downloaded segment for "{stream_name}"')

    except yt_dlp.utils.DownloadError as e:
        logging.error(f'[{thread_name}] Download failed for "{stream_name}": {e}')
        
    except Exception as e:
        logging.exception(f'[{thread_name}] An unexpected error occurred during download for "{stream_name}": {e}')


def start_downloads(config):
    '''Initializes and manages the download threads.'''
    output_dir = config.get('output_dir')
    segment_duration = config.get('segment_duration')
    streams = config.get('streams', [])

    if not streams:
        logging.warning('No streams configured in the "streams" list. Nothing to download.')
        return

    logging.info(f'Starting download process for {len(streams)} configured streams...')
    active_threads = []
    for stream_config in streams:
        if not isinstance(stream_config, dict) or not all(k in stream_config for k in ('url', 'stream_name', 'quality')):
            logging.warning(f'Skipping invalid stream entry: {stream_config}. Must be a dict with "url", "stream_name", and "quality".')
            continue

        thread = threading.Thread(
            target=download_segment,
            args=(
                stream_config['url'],
                stream_config['stream_name'],
                stream_config['quality'],
                output_dir,
                segment_duration,
            ),
            name=f'Thread-{stream_config["stream_name"][:15]}'
        )
        thread.start()
        active_threads.append(thread)

    if not active_threads:
        logging.warning('No valid streams found to start download threads.')
        return

    logging.info(f'{len(active_threads)} download threads started.')

    try:
        while any(t.is_alive() for t in active_threads):
            time.sleep(1)

        logging.info('All download threads appear to have completed their tasks.')

    except KeyboardInterrupt:
        logging.warning('Ctrl+C detected. Signaling download threads to shut down gracefully...')
        shutdown_event.set()
        logging.info('Shutdown signal sent to all threads.')

    finally:
        logging.info('Waiting for all download threads to finish completely...')
        for thread in active_threads:
            thread.join()
            logging.debug(f'Thread {thread.name} has finished.')
        logging.info('All download threads have finished execution.')


def handle_scheduling(schedule_enabled, get_start_time_func, stop_event):
    '''
    Handles user scheduling: prompts for time if enabled, waits if necessary.
    Returns True if it's time to execute downloads now, False if scheduling
    was cancelled or resulted in no execution needed now.
    '''
    if not schedule_enabled:
        logging.info("Scheduling is disabled. Starting downloads immediately.")
        return True 

    logging.info("Scheduling is enabled.")
    start_time_tuple = get_start_time_func()

    if start_time_tuple is None:
        logging.info("User chose 'start now'. Starting downloads immediately.")
        return True

    start_hour, start_minute = start_time_tuple
    logging.info(f"Scheduled start time requested: {start_hour:02d}:{start_minute:02d}")

    try:
        now = datetime.datetime.now()
        target_time = now.replace(hour=start_hour, minute=start_minute, second=0, microsecond=0)

        if target_time <= now:
            logging.info(f"Target time {start_hour:02d}:{start_minute:02d} has already passed for today. Scheduling for the same time tomorrow.")
            target_time += datetime.timedelta(days=1)
        else:
            logging.info(f"Scheduled start time set for today at {start_hour:02d}:{start_minute:02d}.")

        wait_seconds = (target_time - now).total_seconds()

        if wait_seconds > 0:
            logging.info(f"Waiting for {wait_seconds:.2f} seconds (until {target_time}). Press Ctrl+C to cancel wait and exit.")
            interrupted = stop_event.wait(timeout=wait_seconds)

            if interrupted:
                logging.warning("Wait interrupted by shutdown signal (e.g., Ctrl+C). Exiting schedule wait.")
                return False 
            else:
                logging.info("Scheduled time reached. Proceeding with downloads.")
                return True 
        else:
             logging.info("Scheduled time is effectively now. Starting downloads immediately.")
             return True

    except (ValueError, TypeError) as e:
        logging.error(f"Invalid schedule time configuration encountered: {e}. Running immediately as fallback.")
        return True 
    except Exception as e:
         logging.error(f"An unexpected error occurred during scheduling wait: {e}. Running immediately as fallback.")
         return True


def main():
    """
    Main function: Sets up environment, handles scheduling, and starts downloads.
    """
    config = load_configuration(CONFIG_FILE)

    setup_logging(config.get('log_file')) 

    logging.info("Checking for ffmpeg...")
    if shutil.which('ffmpeg') is None:
        logging.error("ffmpeg not found in system PATH. yt-dlp requires ffmpeg for downloading and processing streams.")
        logging.error("Please install ffmpeg and ensure it's accessible in your PATH environment variable.")
        sys.exit(1)
    else:
        logging.info("ffmpeg found successfully.")

    output_dir = config.get('output_dir') 
    try:
        os.makedirs(output_dir, exist_ok=True)
        logging.info(f'Output directory set to: "{output_dir}"')
        cleanup_part_files(output_dir)
    except OSError as e:
        logging.error(f'Could not create or access output directory "{output_dir}": {e}')
        sys.exit(1)
    except Exception as e:
         logging.error(f'An unexpected error occurred during output directory setup: {e}')
         sys.exit(1)


    schedule_enabled = config.get('schedule_enabled', False) 
    should_execute_now = handle_scheduling(schedule_enabled, get_start_time_from_user, shutdown_event)

    if should_execute_now:
        start_downloads(config)
    else:
        logging.info("Downloads were not started due to scheduling cancellation or configuration.")

    logging.info('Script finished execution.')

if __name__ == '__main__':
    main()
    