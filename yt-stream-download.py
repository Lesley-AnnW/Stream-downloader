import yt_dlp
import datetime
import os
import time
import threading

streams = [
     {
         'url': 'https://www.youtube.com/watch?v=jfKfPfyJRdk&ab_channel=LofiGirl',
         'stream_name': 'Lofi girl stream'
     }
 ]
output_directory = './downloads'
segment_duration = 3600 

if not os.path.exists(output_directory):
    os.makedirs(output_directory)

def download_segment(stream_url, stream_name):
    while True:
        timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
        output_filename = f'{output_directory}/{stream_name}_livestream_{timestamp}.mp4'
        
        ydl_opts = {
            'format': 'bestvideo[height<=480]',
            'outtmpl': output_filename,
            'noplaylist': True,
            'external_downloader': 'ffmpeg',
            'external_downloader_args': ['-t', str(segment_duration)],
        }
        
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            ydl.download([stream_url])
        
        print(f"Downloaded {output_filename}")
        time.sleep(1)  

threads = []
for stream in streams:
    thread = threading.Thread(target=download_segment, args=(stream['url'], stream['stream_name']))
    thread.start()
    threads.append(thread)

for thread in threads:
    thread.join()