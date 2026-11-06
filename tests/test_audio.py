from array import array
import math
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import wave

from quizchirp.audio import Audio, PEAK_LIMIT, SOUNDS, VOICES, _vary_note


def encode(samples):
    pcm = array("h", samples)
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm.tobytes()


def decode(data):
    pcm = array("h", data)
    if sys.byteorder != "little":
        pcm.byteswap()
    return pcm


class AudioVariation(unittest.TestCase):
    def test_pitch_and_gain_at_all_extremes(self):
        rate, frequency = 32000, 6000
        source = [round(18000 * math.sin(2 * math.pi * frequency * i / rate))
                  for i in range(3680)]
        for gain_db in (-3.0, 2.0):
            for semitones in (-0.8, 0.8):
                with self.subTest(gain_db=gain_db, semitones=semitones):
                    with patch("quizchirp.audio.random.triangular", side_effect=[gain_db, semitones]):
                        result = decode(_vary_note(encode(source)))
                    speed = 2 ** (semitones / 12)
                    self.assertEqual(len(result), round(len(source) / speed))
                    # Measure zero crossings away from the filter boundaries.
                    crossings = [i for i in range(33, len(result) - 32)
                                 if result[i - 1] <= 0 < result[i]]
                    measured = (len(crossings) - 1) * rate / (crossings[-1] - crossings[0])
                    self.assertAlmostEqual(measured / (frequency * speed), 1, delta=0.001)
                    rms = math.sqrt(sum(x * x for x in result[32:-32]) / len(result[32:-32]))
                    self.assertAlmostEqual(20 * math.log10(rms / (18000 / math.sqrt(2))),
                                           gain_db, delta=0.03)

    def test_real_recordings_remain_audible_without_clipping(self):
        for voice in VOICES:
            with wave.open(str(SOUNDS / f"{voice}.wav")) as src:
                source = decode(src.readframes(src.getnframes()))
            energy = sum(x * x for x in source)
            for gain_db, semitones in ((-3.0, -0.8), (2.0, 0.8)):
                with self.subTest(voice=voice, gain_db=gain_db, semitones=semitones):
                    with patch("quizchirp.audio.random.triangular", side_effect=[gain_db, semitones]):
                        result = decode(_vary_note(encode(source)))
                    self.assertLessEqual(max(abs(x) for x in result), PEAK_LIMIT)
                    ratio = math.sqrt(sum(x * x for x in result) / len(result)
                                      / (energy / len(source)))
                    self.assertGreater(ratio, 0.69)
                    self.assertLess(ratio, 1.28)

    def test_full_scale_input_uses_headroom_without_flattening_peaks(self):
        source = [round(32767 * math.sin(2 * math.pi * i / 13)) for i in range(1000)]
        with patch("quizchirp.audio.random.triangular", side_effect=[2.0, 0.8]):
            result = decode(_vary_note(encode(source)))
        self.assertEqual(max(abs(x) for x in result), PEAK_LIMIT)
        self.assertLess(sum(abs(x) == PEAK_LIMIT for x in result), 10)

    def test_varied_cues_keep_identical_notes_and_fixed_pauses(self):
        audio = Audio(Path("unused-test-settings"))
        for name, count in zip("ABCDEF", range(1, 7)):
            with patch("quizchirp.audio.random.triangular", side_effect=[-3.0, -0.8]) as variation:
                rate, data = audio._cue(name)
            self.assertEqual(variation.call_count, 2)
            frames = round(round(rate * 0.115) / (2 ** (-0.8 / 12)))
            note = data[:2 * frames]
            expected = note
            for gap in (0.065, 0.15, 0.065, 0.15, 0.065)[:count - 1]:
                expected += bytes(2 * int(rate * gap)) + note
            self.assertEqual(data, expected)
        with patch("quizchirp.audio.random.triangular") as variation:
            rate, data = audio._cue("FAIL")
        variation.assert_not_called()
        with wave.open(str(SOUNDS / "FAIL.wav")) as src:
            self.assertEqual((rate, data), (src.getframerate(), src.readframes(src.getnframes())))
