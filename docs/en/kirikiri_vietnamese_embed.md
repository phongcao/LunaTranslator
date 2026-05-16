# KiriKiri Vietnamese Embed Debugging Notes

Last updated: 2026-05-15

This note summarizes the final working approach used to support Vietnamese embedded text in LOVELYxCATION's KiriKiri textbox path, the ideas that did not work, and the debugging inputs that were most useful.

Scope note:
- The automatic Vietnamese font and charset resolution is generic embedded-text support and can remain enabled normally.
- The KiriKiri textbox render-replacement path described below should be treated as a KiriKiri-specific compatibility tweak, not as a generic rule for all engines or all target languages.
- As of this revision, that textbox path is behind the experimental embed setting `experimental_kirikiri_textbox` with the English UI label `Experimental KiriKiri textbox compatibility`.
- This experimental path was validated mainly against LOVELYxCATION and should be enabled per game when needed.

## 1. Current Working Method

The final solution is a pipeline, not a single fix.

### A. Vietnamese font and charset are resolved automatically

- `src/LunaTranslator/textio/textsource/texthook.py` resolves an automatic embedded font family and charset for Vietnamese.
- The relevant pieces are:
  - `EMBED_AUTO_CHARSET_BY_LANGUAGE["vi"] = 163`
  - `EMBED_AUTO_FONT_FAMILIES_BY_LANGUAGE["vi"] = ["Tahoma", "Arial", "Segoe UI", "Times New Roman"]`
  - `resolve_embed_font_family()`
  - `resolve_embed_charset()`
  - `set_settings_ex()`
- Those settings are sent through `Luna_SettingsEx()` and stored in shared memory by `src/NativeImpl/LunaHook/LunaHost/LunaHostDll.cpp`.

This means the injected hook can render Vietnamese with a compatible font and charset even when the game itself is using a Japanese font.

### B. The native GDI font-switch path now reuses fonts correctly

- `src/NativeImpl/LunaHook/LunaHook/hijackfuns.cc` applies the shared-memory font family and charset through the GDI hook layer.
- The important class is `DCFontSwitcher`.
- A critical bug was fixed there: the font-switch path must reuse cached `HFONT` objects instead of creating a new font on nearly every `GetGlyphOutlineW` / `TextOutW` / related hook call.
- Before that fix, the game eventually hit repeated:
  - `Polygon drawing failed/HR=887602FA`
  - followed by a KiriKiri canvas draw exception.

This was the real crash fix.

### C. Long translations are not written back into the original engine buffer

- The KiriKiri path in `src/NativeImpl/LunaHook/LunaHook/engine32/KiriKiri.cpp` caches `original -> translated` pairs.
- Instead of forcing long translated text back into engine-sized buffers, it performs render-time replacement.
- This avoids cutoff and avoids overwriting destinations that were allocated for the original Japanese text length.

This is the core structural reason the current approach works better than earlier attempts.

### D. Render-time replacement uses two levels

#### Direct full-string replacement

- If the `DrawText` path exposes a full `ttstr`, the hook replaces the whole rendered string directly.

#### Glyph fallback queue

- Some KiriKiri textbox frames only expose single-character `ttstr` arguments during rendering.
- In that case, the hook uses a glyph fallback queue:
  - `queueKiriKiriGlyphLine()` prepares translated rows.
  - `consumeKiriKiriGlyphLine()` emits those rows at render time.
- The queue only emits a later translated row when the native glyph stream really starts a new row.

This is why row counting and row synchronization matter so much in this engine.

### E. Row packing is based on the native row budget, not only sentence count

- `estimateKiriKiriNativeRowBudget()` estimates how many rows the original Japanese line is likely to occupy.
- `queueKiriKiriGlyphLine()` then balances the Vietnamese translation into that many rows.
- Same-line multi-sentence Japanese text can be joined and repacked instead of blindly split sentence-by-sentence.

This fixed the earlier cases where the translation expected 2 or 3 rows but the engine only ever rendered 1 or 2 native rows.

### F. Separator handling in the glyph queue is now synchronized

- The glyph fallback queue must not skip a separator from the pending original if the engine is actually drawing that separator as the current glyph.
- A bug here caused mixed Vietnamese + Japanese lines in the textbox.
- The fix was to keep the queue aligned when a full-width space like `　` is rendered as its own glyph.

This fixed the later "dirty mixed line" issue after the crash itself was already solved.

## 2. Issues and Failed Attempts

The final result came after several wrong turns and partial fixes.

### A. Directly pushing long translations into original buffers

This caused cutoff and was fundamentally unsafe.

Reason:
- The game's destination buffer can be sized for the original Japanese text.
- A longer Vietnamese translation can overflow, truncate, or destabilize the render path.

Conclusion:
- The correct approach is render-time replacement, not bounded write-back.

### B. Blind newline insertion and naive wrapping

At different points, wrapping the Vietnamese translation with explicit line breaks looked promising, but it often failed in the textbox path.

Observed problems:
- only the first line rendered correctly
- later lines were not emitted
- or later rows overlapped

Reason:
- In this KiriKiri path, later rows only appear when the engine itself starts a new row in the glyph stream.

### C. Splitting every sentence at punctuation

This caused overlap in same-line multi-sentence text.

Reason:
- Japanese sentence boundaries on `。` did not always correspond to a real layout break.
- When the hook treated same-line punctuation as a row break, the next translated segment could render with the original x-offset and collide with the previous one.

Conclusion:
- Same-line punctuation continuations must often stay in one combined replacement and then be rebalanced by row budget.

### D. Letting sentence count decide the number of translated rows

This caused missing trailing rows.

Example failure mode:
- a translation was packed into 2 or 3 rows
- but the native textbox only ever started 1 or 2 actual rows
- so the last translated row was never emitted

Conclusion:
- row budget must be inferred from the original rendered width and native behavior, not only from translation structure.

### E. Accent-stripping "canvas-safe" fallback

One attempted workaround replaced Vietnamese accented characters on later rows with ASCII equivalents.

Why it was rejected:
- it visibly degraded the Vietnamese text
- it did not actually solve the crash
- later evidence showed the crash was not limited to later rows anyway

Conclusion:
- do not use accent stripping as the solution here.

### F. Over-focusing on secondary rows as the crash source

This turned out to be too narrow.

What the later logs showed:
- repeated polygon failures started before the final popup
- the final exception could happen on a first-row glyph as well

Conclusion:
- the crash was not a "second-row-only" problem.

### G. Suspecting the Python font/charset bridge was not applied

This was a reasonable hypothesis, but it was only partially right.

What was true:
- Vietnamese absolutely needed a compatible font and charset.

What was false:
- the bridge itself was not the missing piece anymore.

Render-time logging later proved that the KiriKiri hook was already seeing:
- `font_family=Tahoma`
- `font_charset_enabled=1`
- `font_charset=163`

So the remaining crash was elsewhere.

### H. The real crash cause: leaking GDI fonts in the font-switch path

The actual native crash fix came from `DCFontSwitcher`.

Problem:
- it was effectively missing the cache in the hot render path
- new fonts were being created again and again
- KiriKiri eventually started reporting polygon drawing failures and then crashed on canvas draw

Conclusion:
- font switching was necessary, but font reuse was just as important.

## 3. What Was Most Useful For Finding the Right Solution

Several debugging tools and habits were consistently valuable.

### A. Native embed logs

The most useful logs were the KiriKiri embed logs in:

- `C:\Games\LovelyXCation\LunaHookDebug\kirikiri_embed_*.log`

The most useful log entries were:

- `drawtext.fallback_probe`
- `drawtext.sequence_start`
- `drawtext.sequence_row_start`
- `drawtext.sequence_replace`
- `drawtext.sequence_skip`
- `drawtext.sequence_drop`
- `drawtext.sequence_done`

These revealed:
- whether the path had a full-string `ttstr` or only a 1-character glyph
- where row transitions actually happened
- whether the queue lost synchronization
- whether a row was never emitted because the native row never started
- whether a separator glyph like `　` caused the queue to drop

Adding render-time font logging was especially important because it proved the active font and charset inside the failing hook path.

### B. KiriKiri console log

The second critical log was:

- `C:\Games\LovelyXCation\savedata\krkr.console.log`

This told us:
- the exact script page around the failure
- the `override.tjs(456)` draw call involved in the popup
- the repeated `Polygon drawing failed/HR=887602FA` warnings before the final exception

This separated real engine canvas failures from simple translation-layout mistakes.

### C. Screenshots from actual game output

The screenshots were essential.

They exposed issues that logs alone did not fully explain:
- overlap
- lines missing from the textbox
- over-aggressive sanitization that removed Vietnamese diacritics
- mixed Vietnamese and Japanese on the same line
- visual confirmation that the crash was finally gone

In several cases, the screenshot was the fastest way to identify whether the latest patch improved the real user-facing result.

### D. Tight rebuild and redeploy loop

Every native hypothesis had to be validated by:

1. editing the hook
2. rebuilding `LunaHook32.dll`
3. redeploying it to `src/files/LunaHook/LunaHook32.dll`
4. reproducing the same scene
5. comparing the new logs and screenshot to the previous run

Because this was an injected native hook problem, reasoning without a quick rebuild/test cycle was not enough.

### E. Looking for the smallest discriminating signal

The most effective investigations were usually the smallest ones.

Examples:
- checking whether a failing path exposed full strings or only 1-character glyphs
- checking whether a native new-row event actually occurred
- checking the exact `drawtext.sequence_drop` line when a mixed textbox appeared
- checking the render-time font family and charset instead of assuming they were or were not applied

These small checks were more useful than broad exploration.

## Practical Takeaways

- Separate the generic fix from the engine-specific fix: Vietnamese font/charset fallback is generic embed support, while the textbox render-replacement and glyph-queue logic should stay KiriKiri-specific.
- For now, treat the textbox workaround as experimental and validated mainly on LOVELYxCATION rather than as a proven default for every KiriKiri title.
- Vietnamese support in KiriKiri embed mode needs both a compatible font/charset and a safe render-time replacement strategy.
- Do not treat sentence punctuation as a layout break unless the original text really implies a visual break.
- Do not assume the engine will honor however many translated rows look reasonable; measure against native row behavior.
- Do not use accent stripping as a long-term fix.
- In this engine, repeated polygon-drawing failures are a strong signal to inspect the font-switch and GDI hook path.
- Mixed translated/Japanese lines can come from queue desynchronization on separators, not only from translation quality or font issues.