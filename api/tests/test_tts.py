from __future__ import annotations

import unittest
from unittest.mock import patch

from app import tts


class TtsTestCase(unittest.TestCase):
    def test_macos_say_uses_aiff_input_before_mp3_encoding(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], failure_message: str) -> None:
            commands.append(command)

        with (
            patch.object(tts, "SAY_BIN", "/usr/bin/say"),
            patch.object(tts, "ESPEAK_BIN", None),
            patch.object(tts, "FFMPEG_BIN", "ffmpeg"),
            patch.object(tts, "run_subprocess", side_effect=fake_run_subprocess),
        ):
            tts.synthesize_speech_sync("test speech")

        self.assertEqual(commands[0][:2], ["/usr/bin/say", "-o"])
        self.assertTrue(commands[0][2].endswith(".aiff"))
        self.assertEqual(commands[0][3], "test speech")
        self.assertEqual(commands[1][0], "ffmpeg")
        self.assertEqual(commands[1][3], commands[0][2])

    def test_espeak_uses_wav_input_before_mp3_encoding(self) -> None:
        commands: list[list[str]] = []

        def fake_run_subprocess(command: list[str], failure_message: str) -> None:
            commands.append(command)

        with (
            patch.object(tts, "SAY_BIN", None),
            patch.object(tts, "ESPEAK_BIN", "espeak"),
            patch.object(tts, "FFMPEG_BIN", "ffmpeg"),
            patch.object(tts, "run_subprocess", side_effect=fake_run_subprocess),
        ):
            tts.synthesize_speech_sync("test speech")

        self.assertEqual(commands[0][:2], ["espeak", "-w"])
        self.assertTrue(commands[0][2].endswith(".wav"))
        self.assertEqual(commands[0][3], "test speech")
        self.assertEqual(commands[1][0], "ffmpeg")
        self.assertEqual(commands[1][3], commands[0][2])


if __name__ == "__main__":
    unittest.main()
