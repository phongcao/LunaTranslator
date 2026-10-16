import os, importlib
from myutils.config import globalconfig, _TR
from qtsymbols import *
from myutils.commonbase import ArgsEmptyExc
from myutils.hwnd import safepixmap
from myutils.utils import stringfyerror
from traceback import print_exc
import threading, gobject, NativeUtils, windows
from ocrengines.baseocrclass import baseocr, OCRResultParsed


def imageCut(hwnd, rect: QRect, curr=-1) -> QImage:
    succ, pix = NativeUtils.GdiCropImage(
        rect.x(), rect.y(), rect.right(), rect.bottom(), hwnd, curr
    )
    pix = safepixmap(pix).toImage()
    if hwnd:
        return succ, pix
    return pix


def windowCaptureCut(hwnd, rect: QRect) -> QImage:
    """WGC（Windows Graphics Capture）截取绑定窗口自身的画面并裁剪到选区
    （屏幕物理坐标）。与 GDI 不同，DirectX/UE 等游戏也能拿到当前画面，
    且不含遮挡在其上的其他窗口。失败返回空 QImage。"""
    data = NativeUtils.WinRT.capture_window(hwnd)
    if not data:
        return QImage()
    bounds = windows.GetExtendedFrameBounds(hwnd) or windows.GetWindowRect(hwnd)
    if not bounds:
        return QImage()
    img = QImage.fromData(data)
    if img.isNull():
        return img
    if img.format() == QImage.Format.Format_ARGB32:
        # 交换链的 alpha 通道常无意义（可能全 0），窗口截图按不透明处理
        img.reinterpretAsFormat(QImage.Format.Format_RGB32)
    crop = rect.translated(-bounds[0], -bounds[1])
    if not crop.intersects(img.rect()):
        return QImage()
    # 选区超出窗口的部分由 copy 以 0 填充，尺寸保持与选区一致
    return img.copy(crop)


_nowuseocrx = None
_nowuseocr = None
_ocrengine: baseocr = None
_initlock = threading.Lock()


def ocr_end():
    global _ocrengine, _nowuseocr, _nowuseocrx
    with _initlock:
        _nowuseocr = None
        _nowuseocrx = None
        _ocrengine = None


def ocr_init():
    with _initlock:
        __ocr_init()


def __ocr_init():
    global _nowuseocr, _ocrengine, _nowuseocrx
    use = None
    for k in globalconfig["ocr"]:
        if globalconfig["ocr"][k]["use"] == True and os.path.exists(
            ("LunaTranslator/ocrengines/" + k + ".py")
        ):
            use = k
            break
    _nowuseocrx = use
    if use is None:
        raise Exception(_TR("未选择OCR引擎"))
    if _nowuseocr == use:
        return
    _ocrengine = None
    _nowuseocr = None
    aclass = importlib.import_module("ocrengines." + use).OCR
    _ocrengine = aclass(use)
    _nowuseocr = use


def ocr_run(qimage: QImage):
    gobject.base.setimage.emit(qimage)
    if (qimage is None) or qimage.isNull() or (qimage.bits() is None):
        return OCRResultParsed()
    global _nowuseocrx, _ocrengine
    thisocrtype = _nowuseocrx
    try:
        ocr_init()
        thisocrtype: str = _ocrengine.typename
        res = _ocrengine._private_ocr(qimage)
        gobject.base.setresult.emit(res)
        return res
    except Exception as e:
        if isinstance(e, ArgsEmptyExc):
            msg = str(e)
        else:
            print_exc()
            msg = stringfyerror(e)
        return OCRResultParsed(error=msg, engine=thisocrtype)
