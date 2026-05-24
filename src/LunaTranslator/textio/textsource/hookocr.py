import gobject
from textio.textsource.textsourcebase import basetext
from textio.textsource.texthook import texthook
from textio.textsource.ocrtext import ocrtext, OCRMultiRegionDispatch


class hookocr(texthook, ocrtext):
    def init(self):
        texthook.init(self)
        ocrtext.init(self)

    def start(self, hwnd, pids, gamepath, gameuid, autostart=False):
        self.clear_region_translation()
        return texthook.start(
            self, hwnd, pids, gamepath, gameuid, autostart=autostart
        )

    def hwndChanged(self, hwnd):
        ocrtext.hwndChanged(self, hwnd)
        texthook.hwndChanged(self, hwnd)

    def end(self):
        try:
            ocrtext.end(self)
        finally:
            texthook.end(self)

    def _get_render_ranges(self):
        return [region for region in self.ranges if region.range_ui.getrect()]

    def _get_ocr_ranges(self):
        ranges = self._get_render_ranges()
        for region in ranges:
            if region.range_ui.isfocus:
                return [region]
        return ranges

    def edit_selectedhook_remove(self, key):
        texthook.edit_selectedhook_remove(self, key)

    def edit_selectedhook_insert(self, key, idx=-1):
        texthook.edit_selectedhook_insert(self, key, idx)

    def showhiderangeui(self, b):
        ocrtext.showhiderangeui(self, b)

    def leaveone(self):
        ocrtext.leaveone(self)

    def setrect(self, rect):
        ocrtext.setrect(self, rect)

    def clearrange(self):
        ocrtext.clearrange(self)

    def handle_output(self, hc, hn: bytes, tp, output):
        key = (hc, hn.decode("utf8"), tp)
        if key in self.selectedhook:
            # Only dispatch text (which triggers TTS) for the first hook code
            if self.selectedhook[0] == key:
                if len(self.selectedhook) == 1:
                    self.dispatchtext(output)
                else:
                    self.dispatchtext_multiline_delayed(key, output)
            else:
                self.dispatchtext_multiline_delayed(key, output)
        gobject.base.hookselectdialog.update_item_new_line.emit(key, output)

    def dispatchtext(self, text):
        if isinstance(text, OCRMultiRegionDispatch):
            return basetext.dispatchtext(self, text)
        return texthook.dispatchtext(self, text)

    def dispatchtextlines(self, keyandtexts: list):
        # Only use the first hook code's text for toolbar display and TTS
        try:
            keyandtexts.sort(key=lambda xx: self.selectedhook.index(xx[0]))
        except:
            pass
        if keyandtexts:
            # Dispatch only the first hook code's text to the toolbar
            first_key, first_text = keyandtexts[0]
            texthook.dispatchtextlines(self, [(first_key, first_text)])

    def getallres(self, auto):
        regions = []
        for region in self._get_ocr_ranges():
            if auto:
                result = region.getresauto()
            else:
                result = region.getresmanual()
            if result is None:
                continue
            if result.error:
                result.displayerror()
                return
            regions.append(region.builddispatch(result, len(regions)))
        if not regions:
            return
        return OCRMultiRegionDispatch(regions, auto)

    def gettextonce(self):
        payload = self.getallres(False)
        if payload:
            return payload
        return texthook.gettextonce(self)