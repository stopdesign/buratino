import curses
import threading
import time

import simpleaudio as sa
from pydub import AudioSegment


class AudioPlayer:
    def __init__(self, file_path):
        self.audio = AudioSegment.from_file(file_path)
        self.current_pos = 0
        self.is_playing = False
        self.stop_flag = False
        self.play_thread = None

    def play_audio(self):
        self.is_playing = True
        while not self.stop_flag:
            # Create a segment starting from the current position
            segment = self.audio[self.current_pos :]
            play_obj = sa.play_buffer(
                segment.raw_data,
                num_channels=segment.channels,
                bytes_per_sample=segment.sample_width,
                sample_rate=segment.frame_rate,
            )
            play_obj.wait_done()  # Wait until playback finishes
            if not self.stop_flag:
                self.is_playing = False
                break

    def start(self):
        if not self.is_playing:
            self.stop_flag = False
            self.play_thread = threading.Thread(target=self.play_audio)
            self.play_thread.start()

    def stop(self):
        self.stop_flag = True
        if self.play_thread:
            self.play_thread.join()

    def pause(self):
        self.stop()
        self.is_playing = False

    def forward(self, seconds=5):
        self.current_pos += seconds * 1000
        if self.current_pos > len(self.audio):
            self.current_pos = len(self.audio)

    def backward(self, seconds=5):
        self.current_pos -= seconds * 1000
        if self.current_pos < 0:
            self.current_pos = 0


def main(stdscr):
    curses.curs_set(0)
    stdscr.nodelay(True)
    stdscr.timeout(100)

    # Replace with your audio file path
    player = AudioPlayer("audio_log/20250117_170724.mp3")

    stdscr.addstr(0, 0, "Audio Player")
    stdscr.addstr(2, 0, "Press 'p' to Play/Pause, 'f' to Forward, 'b' to Backward, 'q' to Quit")

    while True:
        key = stdscr.getch()
        if key == ord("p"):
            if player.is_playing:
                player.pause()
            else:
                player.start()
        elif key == ord("f"):
            player.forward()
        elif key == ord("b"):
            player.backward()
        elif key == ord("q"):
            player.stop()
            break

        # Update display
        stdscr.clear()
        stdscr.addstr(0, 0, "Audio Player")
        stdscr.addstr(2, 0, "Press 'p' to Play/Pause, 'f' to Forward, 'b' to Backward, 'q' to Quit")
        current_time = player.current_pos / 1000
        total_time = len(player.audio) / 1000
        stdscr.addstr(4, 0, f"Current Time: {current_time:.2f}s / {total_time:.2f}s")

        time.sleep(0.1)


curses.wrapper(main)
