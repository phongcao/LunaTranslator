import time
from traceback import print_exc
from myutils.config import globalconfig
from myutils.wrapper import threader
import threading, types
import NativeUtils


class playonce:
    @threader
    def ___push_data_thread(self, data: "types.GeneratorType[bytes]", volume):
        try:
            for d in data:
                # 停止后仍然读完剩余数据但不再播放：TTSResult 需要完整数据才能缓存，请求也能正常结束
                if self.stopped:
                    continue
                if self.idle:
                    if not self.__start(
                        NativeUtils.bass_stream_handle_create(d, len(d)), volume
                    ):
                        self.stopped = True
                elif not NativeUtils.bass_stream_push_data(self.handle, d, len(d)):
                    self.stopped = True
        finally:
            # 出错时也要结束流，否则 BASS 一直处于 stalled 状态，isplaying 永远为真
            NativeUtils.bass_stream_push_data(self.handle, None, 0)
            self.finished = True

    def __init__(self, fileormem, volume) -> None:
        self.handle = 0
        self.idle = True
        # 没有开始播放就结束了（空数据、创建失败），避免 series_audioplayer 一直等待
        self.finished = False
        self.stopped = False
        self.lock = threading.Lock()
        self.__play(fileormem, volume)

    def __start(self, handle, volume):
        with self.lock:
            if self.stopped:
                NativeUtils.bass_handle_free(handle)
                return False
            self.handle = handle
        if not NativeUtils.bass_handle_play(handle, volume):
            return False
        self.idle = False
        return True

    def stop(self):
        with self.lock:
            self.stopped = True
            _ = self.handle
            self.handle = 0
        NativeUtils.bass_handle_free(_)

    def __del__(self):
        self.stop()

    @property
    def isplaying(self):
        return NativeUtils.bass_handle_isplaying(self.handle)

    @threader
    def __play(self, data: "bytes | str | types.GeneratorType[bytes]", volume):
        if isinstance(data, (bytes, str)):
            handle = NativeUtils.bass_handle_create(
                data, len(data), isinstance(data, bytes)
            )
            if not self.__start(handle, volume):
                self.finished = True
        elif isinstance(data, types.GeneratorType):
            self.___push_data_thread(data, volume)
        else:
            self.finished = True


def bass_code_cast(bs, fr="mp3"):
    # fr没啥用，仅用来给出编码失败时的用来占位的后缀，以少写代码
    to = globalconfig.get("audioformat", "mp3")
    ret = NativeUtils.bass_code_cast(
        bs, to, globalconfig.get("mp3kbps", 64), globalconfig.get("opusbitrate", 10)
    )
    if not ret:
        return bs, fr
    ext = {"mp3": "mp3", "opus": "ogg"}[to]
    return ret, ext


class series_audioplayer:
    def __init__(self, playovercallback=None):
        self.i = 0
        self.playovercallback = playovercallback
        self.lastfile = None
        self.tasks = None
        self.lock = threading.Lock()
        self.lock.acquire()
        self.timestamp = None
        self.lastcontext = None
        self.__dotasks()

    def stop(self):
        self.timestamp = None
        try:
            self.tasks = (None, 0, True)
            self.lock.release()
        except:
            pass

    def play(self, binary, volume=100, force=False, timestamp=None):
        if timestamp and (timestamp != self.timestamp):
            return
        self.timestamp = timestamp
        try:
            self.tasks = (binary, volume, force)
            self.lock.release()
        except:
            pass

    @threader
    def __dotasks(self):
        _playonce = None
        try:
            while True:
                self.lock.acquire()
                task = self.tasks
                self.tasks = None
                if task is None:
                    continue
                binary, volume, force = task
                if _playonce:
                    # 流式播放时推流线程持有 playonce，只靠引用计数无法及时释放，会和下一句重叠
                    _playonce.stop()
                    _playonce = None
                if not binary:
                    continue
                _playonce = playonce(binary, volume)
                while _playonce.idle and not _playonce.finished and not self.tasks:
                    time.sleep(0.1)
                while _playonce.isplaying:
                    time.sleep(0.1)
                    if self.tasks and not (
                        globalconfig.get("ttsnointerrupt", False)
                        and (not self.tasks[-1])
                    ):
                        break
                else:
                    if self.playovercallback:
                        self.playovercallback(force)
        except:
            print_exc()
