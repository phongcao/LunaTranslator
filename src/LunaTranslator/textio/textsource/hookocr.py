import functools, gobject
from textio.textsource.textsourcebase import basetext
from textio.textsource.texthook import texthook
from textio.textsource.ocrtext import ocrtext, OCRMultiRegionDispatch


class hookocr(texthook, ocrtext):
    def init(self):
        self._hook_region_text_state = {}
        self._hook_region_ids = set()
        texthook.init(self)
        ocrtext.init(self)

    def start(self, hwnd, pids, gamepath, gameuid, autostart=False):
        self._hook_region_text_state.clear()
        self._hook_region_ids.clear()
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

    def _get_hook_slot_count(self):
        return min(len(self.selectedhook), len(self._get_render_ranges()))

    def _get_hook_ranges(self):
        return self._get_render_ranges()[: self._get_hook_slot_count()]

    def _get_ocr_ranges(self):
        ranges = self._get_render_ranges()[self._get_hook_slot_count() :]
        for region in ranges:
            if region.range_ui.isfocus:
                return [region]
        return ranges

    def _clear_region_translation_async(self, region_ids):
        if not region_ids:
            return
        gobject.base.safeinvokefunction.emit(
            functools.partial(self.clear_region_translation, region_ids)
        )

    def _sync_hook_region_overlay(self, auto=True):
        hook_ranges = self._get_hook_ranges()
        region_ids = {region.region_id for region in hook_ranges}
        stale_region_ids = list(self._hook_region_ids - region_ids)
        if stale_region_ids:
            self._clear_region_translation_async(stale_region_ids)
        self._hook_region_ids = region_ids
        if not hook_ranges:
            return
        payload_regions = []
        blank_region_ids = []
        for order, (region, key) in enumerate(
            zip(hook_ranges, self.selectedhook[: len(hook_ranges)])
        ):
            text = self._hook_region_text_state.get(key)
            if text and text.strip():
                payload_regions.append(region.buildtextdispatch(text, order))
            else:
                blank_region_ids.append(region.region_id)
        if blank_region_ids:
            self._clear_region_translation_async(blank_region_ids)
        if payload_regions:
            basetext.dispatchtext(
                self, OCRMultiRegionDispatch(payload_regions, auto), isFromHook=True
            )

    def edit_selectedhook_remove(self, key):
        texthook.edit_selectedhook_remove(self, key)
        self._hook_region_text_state.pop(key, None)
        self._sync_hook_region_overlay()

    def edit_selectedhook_insert(self, key, idx=-1):
        texthook.edit_selectedhook_insert(self, key, idx)
        self._sync_hook_region_overlay()

    def showhiderangeui(self, b):
        ocrtext.showhiderangeui(self, b)
        self._sync_hook_region_overlay(auto=False)

    def leaveone(self):
        ocrtext.leaveone(self)
        self._sync_hook_region_overlay(auto=False)

    def setrect(self, rect):
        ocrtext.setrect(self, rect)
        self._sync_hook_region_overlay(auto=False)

    def clearrange(self):
        self._hook_region_ids.clear()
        ocrtext.clearrange(self)

    def handle_output(self, hc, hn: bytes, tp, output):
        key = (hc, hn.decode("utf8"), tp)
        if key in self.selectedhook:
            self._hook_region_text_state[key] = output
            mapped_keys = set(self.selectedhook[: self._get_hook_slot_count()])
            if key in mapped_keys:
                self.dispatchtext_multiline_delayed(key, output)
            elif len(self.selectedhook) == 1:
                self.dispatchtext(output)
            else:
                self.dispatchtext_multiline_delayed(key, output)
        gobject.base.hookselectdialog.update_item_new_line.emit(key, output)

    def dispatchtext(self, text):
        if isinstance(text, OCRMultiRegionDispatch):
            return basetext.dispatchtext(self, text, isFromHook=True)
        return texthook.dispatchtext(self, text)

    def dispatchtextlines(self, keyandtexts: list):
        mapped_count = self._get_hook_slot_count()
        if mapped_count == 0:
            return texthook.dispatchtextlines(self, keyandtexts)
        try:
            keyandtexts.sort(key=lambda xx: self.selectedhook.index(xx[0]))
        except:
            pass
        mapped_keys = set(self.selectedhook[:mapped_count])
        fallback = []
        has_mapped_update = False
        for key, text in keyandtexts:
            self._hook_region_text_state[key] = text
            if key in mapped_keys:
                has_mapped_update = True
            else:
                fallback.append((key, text))
        if has_mapped_update:
            self._sync_hook_region_overlay()
        if fallback:
            return texthook.dispatchtextlines(self, fallback)

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
        payload_regions = []
        hook_ranges = self._get_hook_ranges()
        for order, (region, key) in enumerate(
            zip(hook_ranges, self.selectedhook[: len(hook_ranges)])
        ):
            text = self._hook_region_text_state.get(key)
            if text and text.strip():
                payload_regions.append(region.buildtextdispatch(text, order))
        payload = self.getallres(False)
        if payload:
            payload_regions.extend(payload.regions)
        if payload_regions:
            return OCRMultiRegionDispatch(payload_regions, False)
        return texthook.gettextonce(self)