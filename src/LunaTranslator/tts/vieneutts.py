from tts.basettsclass import TTSbase, SpeechParam
import io
import json
import os
import re
import wave
from difflib import SequenceMatcher

_RE_SPEECH_TOKEN = re.compile(r"<\|speech_(\d+)\|>")
_RE_NAME_PREFIX = re.compile(r"^[^:：]{1,20}[：:]\s*")
# Match a standalone name line: short, no sentence punctuation
_RE_NAME_LINE = re.compile(r"^[^\n,.!?;:。、！？；：…「」『』()\(\)]{1,20}\n")

# Local cache for downloaded HuggingFace files
_CACHE_DIR = os.path.join(os.path.expanduser("~"), ".cache", "vieneutts")


def _hf_download(repo_id, filename):
    """Download a file from HuggingFace using urllib (avoids huggingface_hub
    which conflicts with LunaTranslator's requests.py shadow)."""
    cache_repo_dir = os.path.join(_CACHE_DIR, repo_id.replace("/", "--"))
    local_path = os.path.join(cache_repo_dir, filename)
    if os.path.isfile(local_path):
        return local_path

    # Also check the standard huggingface_hub cache
    hf_cache = os.path.join(
        os.path.expanduser("~"), ".cache", "huggingface", "hub",
        "models--" + repo_id.replace("/", "--"), "snapshots",
    )
    if os.path.isdir(hf_cache):
        for snap in os.listdir(hf_cache):
            candidate = os.path.join(hf_cache, snap, filename)
            if os.path.isfile(candidate):
                return candidate

    # Download from HuggingFace
    import urllib.request

    url = "https://huggingface.co/{}/resolve/main/{}".format(repo_id, filename)
    os.makedirs(cache_repo_dir, exist_ok=True)
    urllib.request.urlretrieve(url, local_path)
    return local_path


class TTS(TTSbase):
    arg_support_pitch = False

    def getvoicelist(self):
        """Load voice presets from HuggingFace and return voice list."""
        model_type = self.config.get("model_type", "standard").lower()
        self._voice_data = {}

        try:
            voice_repo = self.config.get("voice_repo", "")
            if not voice_repo:
                voice_repo = (
                    "pnnbao-ump/VieNeu-TTS-v2"
                    if model_type == "standard"
                    else "pnnbao-ump/VieNeu-TTS-v2-Turbo-GGUF"
                )

            voices_path = _hf_download(voice_repo, "voices.json")
            with open(voices_path, "r", encoding="utf-8") as f:
                voices_data = json.load(f)

            presets = voices_data.get("presets", {})
            ids = []
            names = []

            if model_type == "standard":
                for name, data in presets.items():
                    codes = data.get("codes", [])
                    if codes and isinstance(codes[0], int):
                        self._voice_data[name] = data
                        ids.append(name)
                        names.append(data.get("description", name))
            else:
                import numpy as np

                for name, data in presets.items():
                    codes = data.get("codes", [])
                    if codes and isinstance(codes[0], float):
                        emb = np.array(codes, dtype=np.float32)
                        if emb.shape[0] == 128:
                            self._voice_data[name] = emb[np.newaxis, :]
                            ids.append(name)
                            names.append(name)

            if ids:
                return ids, names
        except Exception:
            pass

        return [""], ["Default"]

    def init(self):
        """Load the VieNeu ONNX codec for speech token decoding."""
        import numpy as np
        import onnxruntime

        self._np = np
        self._onnx_session = None
        self._turbo_model = None

        model_type = self.config.get("model_type", "standard").lower()

        if model_type == "standard":
            codec_repo = self.config.get(
                "codec_repo", "neuphonic/neucodec-onnx-decoder-int8"
            )
            onnx_path = _hf_download(codec_repo, "model.onnx")
            so = onnxruntime.SessionOptions()
            so.graph_optimization_level = (
                onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
            )
            self._onnx_session = onnxruntime.InferenceSession(
                onnx_path,
                sess_options=so,
                providers=["CPUExecutionProvider"],
            )
        else:
            codec_repo = self.config.get("codec_repo", "pnnbao-ump/VieNeu-Codec")
            decoder_path = _hf_download(codec_repo, "vieneu_decoder.onnx")
            encoder_path = _hf_download(codec_repo, "vieneu_encoder.onnx")
            so = onnxruntime.SessionOptions()
            so.graph_optimization_level = (
                onnxruntime.GraphOptimizationLevel.ORT_ENABLE_ALL
            )
            self._turbo_decoder = onnxruntime.InferenceSession(
                decoder_path,
                sess_options=so,
                providers=["CPUExecutionProvider"],
            )
            self._turbo_encoder = onnxruntime.InferenceSession(
                encoder_path,
                sess_options=so,
                providers=["CPUExecutionProvider"],
            )

    _SAMPLE_RATE = 24000
    # Streaming constants (matching VieNeuGGUFTTS reference server)
    _HOP_LENGTH = 480           # samples per speech token frame
    _CHUNK_TOKENS = 25          # tokens per decode chunk
    _LOOKFORWARD = 10           # extra future tokens for context
    _LOOKBACK = 100             # context tokens before current chunk
    _OVERLAP_FRAMES = 1         # overlap frames for crossfade
    _STRIDE_SAMPLES = _CHUNK_TOKENS * _HOP_LENGTH  # 12000

    _last_spoken_text = ""

    def speak(self, content, voice, param: SpeechParam):
        # Strip character name prefix (e.g. "Person A: ..." or "Name\nDialog")
        content = _RE_NAME_PREFIX.sub("", content)
        if "\n" in content:
            m = _RE_NAME_LINE.match(content)
            if m and len(m.group(0)) < len(content) / 3:
                content = content[m.end():]
        if not content.strip():
            return b""

        # Fuzzy match: skip if too similar to last spoken text
        similarity_threshold = self.config.get("similarity_threshold", 0.85)
        if self._last_spoken_text and content.strip() != self._last_spoken_text:
            ratio = SequenceMatcher(
                None, self._last_spoken_text, content.strip()
            ).ratio()
            if ratio >= similarity_threshold:
                return b""
        self._last_spoken_text = content.strip()

        np = self._np
        model_type = self.config.get("model_type", "standard").lower()

        # Map speed from -10~10 to 0.25~4.0
        if param.speed > 0:
            speed = 1.0 + 3.0 * param.speed / 10
        else:
            speed = 1.0 + 0.75 * param.speed / 10

        # Build the LLM prompt
        prompt = self._build_prompt(content, voice)

        # Call LM Studio /v1/completions with streaming
        lm_url = self.config.get("lm_studio_url", "http://127.0.0.1:1234")
        lm_model = self.config.get("lm_studio_model", "")

        if model_type == "standard":
            payload = {
                "prompt": prompt,
                "max_tokens": 2048,
                "temperature": 1.0,
                "top_k": 50,
                "stop": ["<|SPEECH_GENERATION_END|>"],
                "stream": True,
            }
        else:
            payload = {
                "prompt": prompt,
                "max_tokens": 2048,
                "temperature": 0.4,
                "top_k": 50,
                "top_p": 0.95,
                "min_p": 0.05,
                "repeat_penalty": 1.15,
                "stop": ["<|SPEECH_GENERATION_END|>"],
                "stream": True,
            }

        if lm_model:
            payload["model"] = lm_model

        response = self.proxysession.post(
            "{}/v1/completions".format(lm_url),
            json=payload,
            timeout=300,
            stream=True,
        )

        return self._stream_decode(response, voice, model_type, speed)

    def _stream_decode(self, response, voice, model_type, speed):
        """Stream-decode speech tokens with overlap-add crossfading."""
        import json as json_mod

        np = self._np

        # WAV header with max size (streaming — actual length unknown)
        wav_header = self._wav_header(0x7FFFFFFF)
        first_chunk = True

        # Seed token cache with reference codes for decoder context
        ref_codes = []
        if model_type == "standard":
            voice_name = voice
            if not voice_name or voice_name not in self._voice_data:
                voice_name = self.voicelist[0] if self.voicelist else None
            if voice_name and voice_name in self._voice_data:
                ref_codes = self._voice_data[voice_name].get("codes", [])

        token_cache = list(ref_codes)
        n_decoded_tokens = len(ref_codes)
        n_decoded_samples = 0
        audio_cache = []
        text_buffer = ""

        for line in response.iter_lines():
            if isinstance(line, bytes):
                line = line.decode("utf-8", errors="replace")
            if not line.startswith("data: "):
                continue
            data_str = line[6:]
            if data_str.strip() == "[DONE]":
                break

            try:
                chunk_data = json_mod.loads(data_str)
                token_text = chunk_data["choices"][0].get("text", "")
            except (ValueError, KeyError, IndexError):
                continue
            if not token_text:
                continue

            text_buffer += token_text
            matches = list(_RE_SPEECH_TOKEN.finditer(text_buffer))
            if not matches:
                continue

            for m in matches:
                token_cache.append(int(m.group(1)))
            text_buffer = text_buffer[matches[-1].end():]

            # Decode when enough tokens accumulated
            pending = len(token_cache) - n_decoded_tokens
            if pending >= self._CHUNK_TOKENS + self._LOOKFORWARD:
                # Slice with lookback + overlap context
                tok_start = max(
                    n_decoded_tokens - self._LOOKBACK - self._OVERLAP_FRAMES, 0
                )
                tok_end = min(
                    n_decoded_tokens + self._CHUNK_TOKENS
                    + self._LOOKFORWARD + self._OVERLAP_FRAMES,
                    len(token_cache),
                )

                # Decode this range
                curr_ids = token_cache[tok_start:tok_end]
                recon = self._run_codec(curr_ids, voice, model_type)

                # Extract the chunk portion with overlap margins
                sample_start = (
                    (n_decoded_tokens - tok_start) * self._HOP_LENGTH
                )
                sample_end = sample_start + (
                    self._CHUNK_TOKENS + 2 * self._OVERLAP_FRAMES
                ) * self._HOP_LENGTH
                recon = recon[sample_start:sample_end]
                audio_cache.append(recon)

                # Overlap-add across all cached frames
                processed = self._linear_overlap_add(
                    audio_cache, self._STRIDE_SAMPLES
                )
                new_end = len(audio_cache) * self._STRIDE_SAMPLES
                new_audio = processed[n_decoded_samples:new_end]
                n_decoded_samples = new_end
                n_decoded_tokens += self._CHUNK_TOKENS

                if speed != 1.0:
                    new_audio = self._time_stretch(new_audio, speed)

                pcm = self._float_to_pcm16(new_audio)
                if first_chunk:
                    yield wav_header + pcm
                    first_chunk = False
                else:
                    yield pcm

        # Flush remaining tokens
        remaining = len(token_cache) - n_decoded_tokens
        if remaining > 0:
            tok_start = max(
                len(token_cache)
                - (self._LOOKBACK + self._OVERLAP_FRAMES + remaining),
                0,
            )
            sample_start = (
                (len(token_cache) - tok_start - remaining - self._OVERLAP_FRAMES)
                * self._HOP_LENGTH
            )
            curr_ids = token_cache[tok_start:]
            recon = self._run_codec(curr_ids, voice, model_type)
            recon = recon[sample_start:]
            audio_cache.append(recon)

            processed = self._linear_overlap_add(
                audio_cache, self._STRIDE_SAMPLES
            )
            final_audio = processed[n_decoded_samples:]

            if speed != 1.0:
                final_audio = self._time_stretch(final_audio, speed)

            pcm = self._float_to_pcm16(final_audio)
            if first_chunk:
                yield wav_header + pcm
            else:
                yield pcm

    def _linear_overlap_add(self, frames, stride):
        """Overlap-add with triangular windowing (from VieNeuGGUFTTS server)."""
        np = self._np
        if not frames:
            return np.array([], dtype=np.float32)

        dtype = frames[0].dtype
        total_size = 0
        for i, frame in enumerate(frames):
            frame_end = stride * i + frame.shape[-1]
            total_size = max(total_size, frame_end)

        out = np.zeros(total_size, dtype=dtype)
        sum_weight = np.zeros(total_size, dtype=dtype)

        offset = 0
        for frame in frames:
            fl = frame.shape[-1]
            t = np.linspace(0, 1, fl + 2, dtype=dtype)[1:-1]
            weight = np.abs(0.5 - (t - 0.5))
            out[offset : offset + fl] += weight * frame
            sum_weight[offset : offset + fl] += weight
            offset += stride

        safe = np.where(sum_weight > 0, sum_weight, 1.0)
        return out / safe

    def _run_codec(self, speech_ids, voice, model_type):
        """Run the ONNX codec on a list of speech token IDs."""
        np = self._np
        codes = np.array(speech_ids, dtype=np.int32)[np.newaxis, np.newaxis, :]
        if model_type == "standard":
            return (
                self._onnx_session.run(None, {"codes": codes})[0]
                .astype(np.float32)[0, 0, :]
            )
        else:
            inputs = {"codes": codes}
            voice_emb = self._voice_data.get(voice) if voice else None
            if voice_emb is not None:
                inputs["speaker_embedding"] = voice_emb
            return (
                self._turbo_decoder.run(None, inputs)[0]
                .astype(np.float32)[0, 0, :]
            )

    def _time_stretch(self, audio, speed):
        np = self._np
        n = len(audio)
        if n < 2:
            return audio
        target_len = max(1, int(round(n / speed)))
        return np.interp(
            np.linspace(0, n - 1, target_len),
            np.arange(n),
            audio,
        ).astype(np.float32)

    def _float_to_pcm16(self, audio):
        np = self._np
        audio = np.clip(audio, -1.0, 1.0)
        return (audio * 32767).clip(-32768, 32767).astype(np.int16).tobytes()

    def _wav_header(self, data_size):
        """WAV header for the given PCM data size in bytes."""
        sample_rate = self._SAMPLE_RATE
        bits = 16
        ch = 1
        byte_rate = sample_rate * ch * bits // 8
        block_align = ch * bits // 8
        riff_size = data_size + 36
        h = io.BytesIO()
        h.write(b"RIFF")
        h.write(riff_size.to_bytes(4, "little"))
        h.write(b"WAVE")
        h.write(b"fmt ")
        h.write((16).to_bytes(4, "little"))
        h.write((1).to_bytes(2, "little"))
        h.write(ch.to_bytes(2, "little"))
        h.write(sample_rate.to_bytes(4, "little"))
        h.write(byte_rate.to_bytes(4, "little"))
        h.write(block_align.to_bytes(2, "little"))
        h.write(bits.to_bytes(2, "little"))
        h.write(b"data")
        h.write(data_size.to_bytes(4, "little"))
        return h.getvalue()

    def _build_prompt(self, text, voice):
        model_type = self.config.get("model_type", "standard").lower()

        if model_type == "standard":
            from vieneu_utils.phonemize_text import phonemize_with_dict

            voice_name = voice
            if not voice_name or voice_name not in self._voice_data:
                voice_name = self.voicelist[0] if self.voicelist else None
            if not voice_name or voice_name not in self._voice_data:
                raise Exception("No voice preset available")

            vdata = self._voice_data[voice_name]
            ref_codes = vdata["codes"]
            ref_text = vdata.get("text", "")

            ref_phonemes = phonemize_with_dict(ref_text)
            target_phonemes = phonemize_with_dict(text)
            codes_str = "".join(
                "<|speech_{}|>".format(idx) for idx in ref_codes
            )

            use_chat = self.config.get("use_chat_format", "false").lower() in (
                "true",
                "1",
                "yes",
            )

            if use_chat:
                return (
                    "user: Convert the text to speech:"
                    "<|TEXT_PROMPT_START|>{} {}<|TEXT_PROMPT_END|>\n"
                    "assistant:<|SPEECH_GENERATION_START|>{}"
                ).format(ref_phonemes, target_phonemes, codes_str)
            else:
                return (
                    "<|TEXT_PROMPT_START|>{} {}"
                    "<|TEXT_PROMPT_END|><|SPEECH_GENERATION_START|>{}"
                ).format(ref_phonemes, target_phonemes, codes_str)
        else:
            from vieneu_utils.phonemize_text import phonemize_text

            phonemes = phonemize_text(text)
            return (
                "<|speaker_16|>"
                "<|TEXT_PROMPT_START|>{}<|TEXT_PROMPT_END|>"
                "<|SPEECH_GENERATION_START|>"
            ).format(phonemes)
