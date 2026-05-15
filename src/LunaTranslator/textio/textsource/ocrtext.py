import time, copy, uuid, threading
from myutils.config import globalconfig
from myutils.utils import checkmd5reloadmodule
import NativeUtils, windows
from gui.rangeselect import rangeadjust
from myutils.wrapper import threader
from myutils.ocrutil import imageCut, ocr_run, ocr_init
import time, gobject
from qtsymbols import *
from myutils.keycode import vkcode_map
from textio.textsource.textsourcebase import basetext
from ocrengines.baseocrclass import OCRResultParsed
from CVUtils import cvMat
from traceback import print_exc


class OCRRegionDispatch:
    def __init__(
        self,
        region_id: str,
        rect,
        result: OCRResultParsed,
        order: int,
        text: str = None,
        isocrtranslate: bool = None,
        vertical: bool = None,
    ):
        self.region_id = region_id
        self.rect = rect
        self.result = result
        self.order = order
        self.text = result.textonly if result else (text or "")
        if isocrtranslate is None:
            isocrtranslate = bool(result and result.result.isocrtranslate)
        if vertical is None:
            vertical = bool(result and result.result.vertical)
        self.isocrtranslate = bool(isocrtranslate)
        self.vertical = bool(vertical)


class OCRMultiRegionDispatch:
    def __init__(self, regions: "list[OCRRegionDispatch]", auto: bool):
        self.regions = regions
        self.auto = auto
        self.signature = uuid.uuid4().hex
        self.isocrtranslate = bool(regions and regions[0].isocrtranslate)

    def __bool__(self):
        return bool(self.regions)

    @property
    def text(self):
        return "\n".join(region.text for region in self.regions if region.text)


def _capture_image(*a):
    img = imageCut(*a)
    succ = True
    if a[0]:
        succ, img = img
    else:
        succ = False
    return succ, img


def _ocr_capture_overlay_suppressed(suppressed: bool):
    textsource = getattr(gobject.base, "textsource", None)
    if not textsource or not hasattr(textsource, "ranges"):
        return
    for region in textsource.ranges:
        try:
            region.range_ui.setcapturesuppressed(suppressed)
        except:
            print_exc()


def _ocr_ui_invoke_sync(callback, *argc):
    done = threading.Event()

    def __():
        try:
            callback(*argc)
        finally:
            done.set()

    gobject.base.safeinvokefunction.emit(__)
    done.wait(1)


def imageCutEx(*a, suppress_overlay_on_fallback=True):
    region_render = globalconfig.get("ocr_region_render", True)
    succ, img = _capture_image(*a)
    if region_render and suppress_overlay_on_fallback and (not succ):
        _ocr_ui_invoke_sync(_ocr_capture_overlay_suppressed, True)
        try:
            succ, img = _capture_image(*a)
        finally:
            _ocr_ui_invoke_sync(_ocr_capture_overlay_suppressed, False)
    if img.isNull():
        return img
    if not succ:
        rectX = QRect(a[1], a[2], a[3] - a[1], a[4] - a[2])
        rect2 = windows.GetWindowRect(gobject.base.translation_ui.winid)
        rect = QRect(rect2[0], rect2[1], rect2[2] - rect2[0], rect2[3] - rect2[1])
        if rectX.intersected(rect):
            rect.translate(-a[1], -a[2])
            painter = QPainter(img)
            painter.setBrush(Qt.GlobalColor.white)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.drawRect(rect)
            painter.end()

    if globalconfig.get("use_ocr_preprocess", False):
        try:
            img = checkmd5reloadmodule(
                gobject.getconfig("ocr_preprocess.py"), "ocr_preprocess"
            ).Process(img)
        except:
            print_exc()
    return img


class rangemanger:
    def __init__(self, ref: "ocrtext", ranges: "list[rangemanger]"):
        self.ref = ref
        self.region_id = uuid.uuid4().hex
        self.range_ui = rangeadjust(gobject.base.settin_ui, ranges)
        self.range_ui.setsourcetextvisiblegetter(self._currentsourcetextvisible)
        self.savelastimg: cvMat = None
        self.savelastrecimg: cvMat = None
        self.lastocrtime: float = 0
        self.savelasttext: str = None
        self.last_detected_has_text = False

    def __del__(self):
        self.range_ui.closesignal.emit()

    def _currentsourcetextvisible(self):
        return self.last_detected_has_text

    def _updatesourcetextstate(self, text: str):
        self.last_detected_has_text = bool(text and text.strip())

    def builddispatch(self, result: OCRResultParsed, order: int):
        return OCRRegionDispatch(self.region_id, self.range_ui.getrect(), result, order)

    def buildtextdispatch(self, text: str, order: int):
        return OCRRegionDispatch(
            self.region_id,
            self.range_ui.getrect(),
            None,
            order,
            text=text,
        )

    def getresmanual(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return
        imgr = imageCutEx(self.ref.hwnd, rect[0][0], rect[0][1], rect[1][0], rect[1][1])
        if imgr.isNull():
            return
        result = ocr_run(imgr)
        self.savelastimg = cvMat.fromQImage(imgr)
        self.savelastrecimg = self.savelastimg
        self.lastocrtime = time.time()
        self.savelasttext = result.textonly
        self._updatesourcetextstate(result.textonly)
        return result

    def getresauto(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return
        ok = True
        if globalconfig["ocr_auto_method_v2"] == "analysis":
            imgr = imageCutEx(
                self.ref.hwnd,
                rect[0][0],
                rect[0][1],
                rect[1][0],
                rect[1][1],
                suppress_overlay_on_fallback=False,
            )
            imgr1 = cvMat.fromQImage(imgr)

            image_score = imgr1.MSSIM(self.savelastimg)

            gobject.base.thresholdsett1.emit(str(image_score))
            self.savelastimg = imgr1

            if image_score > globalconfig["ocr_stable_sim_v2"]:

                image_score2 = imgr1.MSSIM(self.savelastrecimg)

                gobject.base.thresholdsett2.emit(str(image_score2))
                if image_score2 > globalconfig["ocr_diff_sim_v2"]:
                    ok = False
                else:
                    self.savelastrecimg = imgr1
            else:
                ok = False
        elif globalconfig["ocr_auto_method_v2"] == "period":
            if time.time() - self.lastocrtime > globalconfig["ocr_interval"]:
                ok = True
            else:
                ok = False
        if ok == False:
            return
        if globalconfig["ocr_auto_method_v2"] != "analysis":
            imgr = imageCutEx(
                self.ref.hwnd, rect[0][0], rect[0][1], rect[1][0], rect[1][1]
            )
        else:
            imgr = imageCutEx(
                self.ref.hwnd, rect[0][0], rect[0][1], rect[1][0], rect[1][1]
            )
        result = ocr_run(imgr)
        t = result.textonly
        self.lastocrtime = time.time()
        self._updatesourcetextstate(t)
        sim = NativeUtils.distance(self.savelasttext, t)
        self.savelasttext = t
        if sim < globalconfig["ocr_text_diff"]:
            return
        self.savelasttext = t
        return result

    def waitforstable(self):
        rect = self.range_ui.getrect()
        if rect is None:
            return False
        imgr = imageCutEx(
            self.ref.hwnd,
            rect[0][0],
            rect[0][1],
            rect[1][0],
            rect[1][1],
            suppress_overlay_on_fallback=False,
        )
        imgr1 = cvMat.fromQImage(imgr)
        image_score = imgr1.MSSIM(self.savelastimg)

        gobject.base.thresholdsett1.emit(str(float(image_score)))
        self.savelastimg = imgr1
        return image_score > globalconfig["ocr_stable_sim2_v2"]


class ocrtext(basetext):
    def hwndChanged(self, hwnd):
        self.hwnd = hwnd

    def init(self):
        self.hwnd = None
        self._pause_state = False
        threader(ocr_init)()
        self.ranges: "list[rangemanger]" = []
        self.gettextthread()

    def clearrange(self):
        self.clear_region_translation()
        for region in self.ranges:
            region.range_ui.closesignal.emit()
        self.ranges.clear()
        globalconfig["ocrregions"].clear()

    def leaveone(self):
        for region in self.ranges[:-1]:
            region.range_ui.closesignal.emit()
        self.ranges = self.ranges[-1:]
        if self.ranges:
            self.ranges[0].range_ui.isfocus = False

    def newrangeadjustor(self):
        if len(self.ranges) == 0 or globalconfig["multiregion"]:
            self.ranges.append(rangemanger(self, self.ranges))

    def starttrace(self, pos):
        for _r in self.ranges:
            _r.range_ui.starttrace(pos)

    def traceoffset(self, curr):
        for _r in self.ranges:
            _r.range_ui.traceoffsetsignal.emit(curr)

    def setrect(self, rect):
        self.ranges[-1].range_ui.setrect(rect)

    def setstyle(self):
        [_.range_ui.setstyle() for _ in self.ranges]

    def showhiderangeui(self, b):
        if b and len(self.ranges) == 0:
            for region in globalconfig["ocrregions"]:
                if region:
                    self.newrangeadjustor()
                    self.setrect(region)
            return
        for _ in self.ranges:
            windows.MouseTrans.unset(_.range_ui.winId())

            if b:
                _r = _.range_ui.getrect()
                if _r:
                    _.range_ui.setrect(_r)
                _.range_ui.setrangevisible(True)
            else:
                _.range_ui.setrangevisible(False)

    def isregionrender(self):
        return globalconfig.get("ocr_region_render", True) and any(
            bool(r.range_ui.getrect()) for r in self.ranges
        )

    def _getrangemanger(self, region_id: str):
        for region in self.ranges:
            if region.region_id == region_id:
                return region

    def begin_region_translation_cycle(self, cycle_id: str, region_ids: "list[str]"):
        for region_id in region_ids:
            region = self._getrangemanger(region_id)
            if region:
                region.range_ui.begintranslationcycle(cycle_id)

    def update_region_translation(
        self,
        region_id: str,
        cycle_id: str,
        engine: str,
        name: str,
        text: str,
        color: str,
    ):
        region = self._getrangemanger(region_id)
        if region:
            region.range_ui.updatetranslation(cycle_id, engine, name, text, color)

    def clear_region_translation(self, region_ids: "list[str]" = None):
        if region_ids is None:
            region_ids = [region.region_id for region in self.ranges]
        for region_id in region_ids:
            region = self._getrangemanger(region_id)
            if region:
                region.range_ui.cleartranslation()

    @threader
    def gettextthread(self):
        laststate = tuple((0 for _ in range(len(globalconfig["ocr_trigger_events"]))))
        lastevents = copy.deepcopy(globalconfig["ocr_trigger_events"])
        while not self.ending:
            if self._pause_state:
                time.sleep(0.1)
                continue
            if not self.isautorunning:
                time.sleep(0.1)
                continue
            rs = self.getuseranges()
            if not rs:
                time.sleep(0.1)
                continue
            if globalconfig["ocr_auto_method_v2"] == "trigger":
                triggered = False
                this = tuple(
                    (
                        windows.GetAsyncKeyState(vkcode_map[line["vkey"]])
                        for line in globalconfig["ocr_trigger_events"]
                    )
                )
                if lastevents != globalconfig["ocr_trigger_events"]:
                    laststate = this
                    lastevents = copy.deepcopy(globalconfig["ocr_trigger_events"])
                    continue
                for _, line in enumerate(globalconfig["ocr_trigger_events"]):
                    event = line["event"]
                    press = this[_]
                    if ((event == 0) and (laststate[_] == 0) and press) or (
                        (event == 1) and laststate[_] and (press == 0)
                    ):
                        triggered = True
                        break
                laststate = this
                if triggered:
                    if self.hwnd:
                        for _ in range(2):
                            # 切换前台窗口
                            p1 = windows.GetWindowThreadProcessId(self.hwnd)
                            p2 = windows.GetWindowThreadProcessId(
                                windows.GetForegroundWindow()
                            )
                            triggered = p1 == p2
                            if triggered:
                                break
                            time.sleep(0.1)

                if triggered:

                    t1 = time.time()
                    while (not self.ending) and (
                        globalconfig["ocr_auto_method_v2"] == "trigger"
                    ):
                        time.sleep(0.1)
                        if time.time() - t1 >= globalconfig["ocr_trigger_delay"]:
                            break
                    while (not self.ending) and (
                        globalconfig["ocr_auto_method_v2"] == "trigger"
                    ):
                        if self.waitforstablex():
                            break
                        time.sleep(0.1)
                    t = self.getallres(False)
                    if t:
                        self.dispatchtext(t)
                time.sleep(0.01)
            else:
                laststate = tuple(
                    (0 for _ in range(len(globalconfig["ocr_trigger_events"])))
                )
                t = self.getallres(True)
                if t:
                    self.dispatchtext(t)
                time.sleep(0.1)

    def waitforstablex(self):
        for range_ui in self.getuseranges():
            if not range_ui.waitforstable():
                return False
        return True

    def getuseranges(self):
        for r in self.ranges:
            if r.range_ui.isfocus:
                return [r]
        return self.ranges

    def getallres(self, auto):
        __text: "list[OCRResultParsed]" = []
        __regions: "list[OCRRegionDispatch]" = []
        for r in self.getuseranges():

            if auto:
                _ = r.getresauto()
            else:
                _ = r.getresmanual()
            if _ is None:
                continue
            if _.error:
                _.displayerror()
                return
            __text.append(_)
            __regions.append(r.builddispatch(_, len(__regions)))
        if not __text:
            return
        if self.isregionrender():
            return OCRMultiRegionDispatch(__regions, auto)
        text = "\n".join(_.textonly for _ in __text)
        if __text[0].result.isocrtranslate:
            gobject.base.displayinfomessage(text, "<notrans>")
        else:
            return text

    def gettextonce(self):
        return self.getallres(False)

    def pause_recognition(self):
        self._pause_state = True

    def resume_recognition(self):
        self._pause_state = False

    def end(self):
        self.clear_region_translation()
        globalconfig["ocrregions"] = [_.range_ui.getrect() for _ in self.ranges]
        self.ranges.clear()
