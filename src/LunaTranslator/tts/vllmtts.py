from tts.basettsclass import TTSbase, SpeechParam
from myutils.config import _TR
import requests, struct, re, os

# vLLM Manager 运行的两个 TTS 服务器：VieNeu-TTS 读越南语，Qwen3-TTS 读其他语言
VIENEU = "vieneu"
QWEN = "qwen"
AUTO = "auto"
ENGINE_NAMES = {VIENEU: "VieNeu-TTS", QWEN: "Qwen3-TTS"}
NATIVE_RATE = {VIENEU: 48000, QWEN: 24000}

# 与 vLLM Manager 的规则一致：à é ô 等法语也有的字母不能作为判断依据
_vietnamese = re.compile("[ăđĩũơưĂĐĨŨƠƯẠ-ỹ]")


def isvietnamese(text: str):
    return bool(_vietnamese.search(text))


def wavheader(rate: int, datasize: int = None):
    if datasize is None:
        # 流式输出时长度未知，和服务器的流式 wav 一样使用最大值
        riffsize = datasize = 0xFFFFFFFF
    else:
        riffsize = 36 + datasize
    return struct.pack(
        "<4sI4s4sIHHIIHH4sI",
        b"RIFF",
        riffsize,
        b"WAVE",
        b"fmt ",
        16,
        1,
        1,
        rate,
        rate * 2,
        2,
        16,
        b"data",
        datasize,
    )


class TTS(TTSbase):
    arg_support_pitch = False

    def apikey(self):
        key = self.config["SECRET_KEY"].strip()
        if key:
            return key
        return os.environ.get("VLLM_API_KEY", "").strip()

    def baseurl(self, engine):
        return self.config[engine + "_url"].strip().rstrip("/")

    def headers(self):
        key = self.apikey()
        if key:
            return {"Authorization": "Bearer " + key}
        return {}

    def enabled(self, engine):
        return self.config[engine + "_use"]

    def fetchvoices(self, engine):
        try:
            if engine == VIENEU:
                path, parse = "/v1/voices", lambda js: [_["id"] for _ in js["data"]]
            else:
                path = "/v1/audio/voices"
                parse = lambda js: [
                    _
                    for _ in js["voices"] + js.get("uploaded_voices", [])
                    if _ != "default"
                ]
            response = self.proxysession.get(
                self.baseurl(engine) + path, headers=self.headers(), timeout=2
            )
            voices = parse(response.json())
            if voices:
                return voices
        except:
            pass
        # 服务器未启动时使用内置列表
        return self.argstype[engine + "_voice"]["list"]

    def getvoicelist(self):
        # 关闭的服务器不读取声音列表，避免未启动时等待超时
        engines = [_ for _ in (VIENEU, QWEN) if self.enabled(_)]
        internal = [AUTO]
        show = [
            "{} ({})".format(
                _TR("自动"), " / ".join(ENGINE_NAMES[_] for _ in engines) or "-"
            )
        ]
        for engine in engines:
            for voice in self.fetchvoices(engine):
                internal.append("{}|{}".format(engine, voice))
                show.append("{}: {}".format(ENGINE_NAMES[engine], voice))
        return internal, show

    def resolve(self, content: str, voice: str):
        if voice and voice != AUTO:
            engine, _, name = voice.partition("|")
            return engine, name
        if isvietnamese(content):
            return VIENEU, self.config["vieneu_voice"]
        return QWEN, self.config["qwen_voice"]

    def ttscachekey(self, content, voice, param):
        engine, name = self.resolve(content, voice)
        return content, engine, name, param, str(self.config)

    def speak(self, content, voice, param: SpeechParam):
        engine, name = self.resolve(content, voice)
        if not self.enabled(engine):
            # 该服务器已关闭：直接跳过这句，不报错
            return None
        body = {"input": content, "voice": name, "response_format": "pcm"}
        stream = self.config["流式输出"]
        if engine == QWEN:
            if self.config["qwen_language"] != "Auto":
                body["language"] = self.config["qwen_language"]
            if self.config["qwen_instructions"].strip():
                body["instructions"] = self.config["qwen_instructions"].strip()
            if param.speed > 0:
                speed = 1 + 3 * param.speed / 10
            else:
                speed = 1 + 0.75 * param.speed / 10
            if speed != 1:
                # Qwen3-TTS 流式输出时 speed 必须为 1
                body["speed"] = speed
                stream = False
            if stream:
                body["stream_format"] = "audio"
        # VieNeu-TTS 总是流式输出，并且不支持 speed

        url = self.baseurl(engine) + "/v1/audio/speech"
        try:
            response = self.proxysession.post(
                url, headers=self.headers(), json=body, stream=True, timeout=(5, 120)
            )
        except requests.exceptions.RequestException as e:
            raise Exception(
                "{} is not reachable at {} ({}). Start it on the Speech tab of vLLM Manager.".format(
                    ENGINE_NAMES[engine], self.baseurl(engine), e
                )
            )
        if response.status_code != 200:
            raise Exception(
                "{} {}: {}".format(
                    ENGINE_NAMES[engine],
                    response.status_code,
                    self.errormessage(response),
                )
            )
        rate = int(response.headers.get("x-sample-rate", NATIVE_RATE[engine]))
        if stream:
            return self.streampcm(response, rate)
        pcm = response.content
        return wavheader(rate, len(pcm)) + pcm

    def errormessage(self, response: requests.Response):
        try:
            # Qwen3-TTS 的 401 是 {"error": "Unauthorized"}
            error = response.json()["error"]
            if isinstance(error, dict):
                return error.get("message", str(error))
            return str(error)
        except:
            return response.text

    def streampcm(self, response: requests.Response, rate):
        header = wavheader(rate)
        # 第一块数据需要包含 wav 头，播放器用它创建流
        for chunk in response.iter_content(32 * 1024):
            if not chunk:
                continue
            if header:
                chunk = header + chunk
                header = None
            yield chunk
