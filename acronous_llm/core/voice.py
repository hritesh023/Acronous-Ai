import os
import tempfile
import wave
import io
import struct
import numpy as np

class VoiceEngine:
    def __init__(self, config):
        self.config = config
        self._stt_model = None
        self._stt_loaded = False

    def _ensure_stt(self):
        if self._stt_loaded:
            return
        self._stt_loaded = True
        try:
            import whisper
            self._stt_model = whisper.load_model(self.config.STT_MODEL)
        except Exception:
            self._stt_model = None

    @property
    def stt_model(self):
        self._ensure_stt()
        return self._stt_model

    def _convert_to_wav(self, audio_path, target_sr=16000):
        try:
            from pydub import AudioSegment
            audio = AudioSegment.from_file(audio_path)
            audio = audio.set_frame_rate(target_sr).set_channels(1).set_sample_width(2)
            temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            audio.export(temp.name, format="wav")
            return temp.name
        except Exception:
            try:
                import subprocess
                temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
                subprocess.run([
                    'ffmpeg', '-y', '-i', audio_path,
                    '-ar', str(target_sr), '-ac', '1',
                    '-sample_fmt', 's16', temp.name
                ], check=True, capture_output=True)
                return temp.name
            except Exception:
                return audio_path

    def _preprocess_audio(self, audio_path):
        converted_path = self._convert_to_wav(audio_path)
        try:
            import soundfile as sf
            data, sr = sf.read(converted_path)
            if len(data.shape) > 1:
                data = np.mean(data, axis=1)
            data = data / np.max(np.abs(data) + 1e-10)
            gain = 2.0
            data = np.clip(data * gain, -1.0, 1.0)
            temp = tempfile.NamedTemporaryFile(suffix=".wav", delete=False)
            sf.write(temp.name, data, sr, subtype='PCM_16')
            if converted_path != audio_path:
                os.unlink(converted_path)
            return temp.name
        except Exception:
            return converted_path if converted_path != audio_path else audio_path

    def transcribe(self, audio_path):
        if self.stt_model is None:
            return self._fallback_stt(audio_path)
        try:
            processed = self._preprocess_audio(audio_path)
            result = self.stt_model.transcribe(
                processed,
                language=self.config.LANG,
                temperature=0.0,
                compression_ratio_threshold=2.4,
                logprob_threshold=-1.0,
                no_speech_threshold=0.6,
                condition_on_previous_text=True,
            )
            text = result.get("text", "").strip()
            if processed != audio_path:
                os.unlink(processed)
            return text
        except Exception:
            return ""

    def transcribe_bytes(self, audio_bytes, ext='.wav'):
        with tempfile.NamedTemporaryFile(suffix=ext, delete=False) as f:
            f.write(audio_bytes)
            tmp_path = f.name
        try:
            if os.path.getsize(tmp_path) < 100:
                return ""
            text = self.transcribe(tmp_path)
            return text
        finally:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)

    def _fallback_stt(self, audio_path):
        return ""

    def text_to_speech(self, text, output_path=None):
        if output_path is None:
            output_path = tempfile.NamedTemporaryFile(suffix=".wav", delete=False).name
        try:
            import pyttsx3
            engine = pyttsx3.init()
            engine.save_to_file(text, output_path)
            engine.runAndWait()
            return output_path
        except Exception:
            try:
                import edge_tts
                import asyncio
                async def _tts():
                    communicate = edge_tts.Communicate(text, voice="en-US-JennyNeural")
                    await communicate.save(output_path)
                asyncio.run(_tts())
                return output_path
            except Exception:
                return None

    def list_microphones(self):
        try:
            import sounddevice as sd
            return [d["name"] for d in sd.query_devices() if d["max_input_channels"] > 0]
        except Exception:
            return []
