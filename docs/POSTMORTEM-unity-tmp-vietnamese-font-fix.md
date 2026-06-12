# Post-mortem: Unity TMP "Vietnamese renders as squares" embed font fix

**Date:** 2026-06-12
**Area:** `src/NativeImpl/LunaHook/.../engines/mono/monocommon.hpp` (experimental "Unity TMP Font Fix")
**Test subject:** Unity House v0.10.4 — Unity 2021.3.40f1, IL2CPP, TextMeshPro 3.0.6
**Outcome:** Feature is **not achievable** by runtime glyph generation in this class of build. Left as a safe detection-only no-op. The viable path (pre-baked AssetBundle font) is documented at the end.

---

## TL;DR of the technical conclusion

When an embedded translation contains glyphs the game's baked TMP atlas lacks (e.g. Vietnamese diacritics → tofu squares), you cannot generate them at runtime in a shipped IL2CPP build, because of **three independent walls**:

1. **Read-only baked atlas.** Baked TMP atlas `Texture2D`s are not readable in player builds. TMP's own `ClearAtlasTextures` refuses to reset them — the "make readable" branch is `#if UNITY_EDITOR` only; in a player build it logs a warning and `return`s. So an existing asset can never gain new glyphs at runtime.
2. **`TMP_FontAsset.CreateFontAsset` is a stripped stub.** It is the only API that builds a *fresh, writable* atlas, but because the game loads fonts from bundles and never calls it, IL2CPP stripped it to a stub. Invoking it via `il2cpp_runtime_invoke` jumps into an invalid pointer → hard AV.
3. **The embed hook runs on a worker thread, not Unity's main thread.** Texture upload / glyph rasterization must happen on the main/render thread. (Proven — see below.)

The robust fix the mature tools use (XUnity.AutoTranslator) is to ship a **pre-baked** Vietnamese `TMP_FontAsset` (atlas already populated → zero runtime rasterization) in an AssetBundle and register it as a global fallback. That artifact does not exist in this repo yet.

---

## 1. Why this took so long and burned a lot of tokens

The investigation worked, but it was **sequential trial-and-error against a black box**, and each wrong turn cost a full build + manual game launch + crash + log read cycle. Specific causes:

### a. We started from a solution, not from a model of the system
The first hours (prior session + start of this one) tried to *make a thing work* (create a font, patch `sourceFontFile`, add fallbacks) before establishing the **basic facts**: which TMP APIs survived stripping, whether the embed runs on the main thread, and whether atlases are writable. Those three facts alone determine feasibility, and we didn't measure them up front.

### b. One root cause masqueraded as many different crashes
Every heavy-allocation managed call (`CreateFontAsset`, then `TryAddCharacters`) crashed at the *first allocation that triggered a GC*, because the hook thread wasn't GC-registered. We treated each as a new mystery (shader null? GC lifetime? stub method?) and chased each separately. It was **one bug** (unattached thread) wearing several costumes. We only saw that after fixing the thread attach made `TryAddCharacters` suddenly "work" (return cleanly), which retroactively explained the earlier `CreateFontAsset` crash too.

### c. No native debugger → we were blind
There was no `cdb`/WinDbg available, and Unity's crash dump only resolves *exported* symbols (`BrotliDecoderIsFinished`, `WriteZStream` — useless). So every "where did it crash" question had to be answered by **bisecting with `fflog` print statements and rebuilding**, instead of reading one stack trace. A single working stack trace would have collapsed several iterations into one.

### d. The verify loop was slow and human-gated
Each hypothesis required: edit → `cmake --build` (tens of seconds) → deploy DLL → user manually launches translator + game → reproduce the crashing line → read `lunahook_fontfix.log`. The human-in-the-loop game launch (correctly — injecting into a game is the user's call) meant long round-trips, so the cost of a *wrong guess* was very high. That's exactly the regime where you want fewer, higher-information experiments.

### e. We discovered constraints one at a time instead of enumerating them
Wall #1 (read-only atlas), #2 (stub `CreateFontAsset`), #3 (worker thread) were each found *after* an approach that depended on the opposite assumption failed. They could all have been checked cheaply and in parallel *before* writing any font-creation code.

---

## 2. What to do differently next time (a fast playbook)

When asked to manipulate a managed runtime (Unity/IL2CPP, Mono, .NET, JVM…) from a native hook, **spend the first iteration measuring the environment, not building the feature.** Concretely:

### Build a one-shot "capability probe" before any feature code
A single instrumented pass that logs, on the first hooked call:

- **Thread identity.** Log `GetCurrentThreadId()` and compare against the known main-thread id (capture it at a guaranteed-main-thread point, e.g. the first frame, or note whether a GC-allocating call crashes — if a trivial managed *allocation* crashes with "GC collect on unknown thread", you are NOT on the GC/main thread). **Decide thread-safety strategy before writing managed calls.**
- **API survival.** For every managed method/field the plan needs, resolve it and log the pointer. For IL2CPP, also `grep` the method-name strings in `global-metadata.dat` first (cheap, no game launch) — absence means stripped. *Resolving non-null is necessary but not sufficient: a found method can still be a stub.*
- **Writability / state invariants.** For TMP specifically: is the atlas `Texture2D.isReadable`? What is `atlasPopulationMode`? These decide whether runtime glyph addition is even possible.

### Read the managed source for the exact API you're about to call — first, not after the crash
`CreateFontAsset` and `ClearAtlasTextures` both had the answer sitting in plain TMP source (`#if UNITY_EDITOR ... return;`, `FontEngine.LoadFontFace != Success`). Ten minutes reading `TMP_FontAsset.cs` / `FontEngine.bindings.cs` up front would have pre-empted at least three build-test-crash cycles. The Unity C# reference and `needle-mirror`/`Unity-Technologies` GitHub mirrors are fetchable.

### Treat "what's the failure mode of this exact call?" as a literature question
Each Unity API has a documented/observable failure contract (returns error enum vs. throws managed exception vs. native AV). Knowing that `LoadFontFace` *returns* `Invalid_File` (graceful) but `CreateFontAsset` *crashes* on a stub tells you where to put guards.

### Get a real stack trace early, or make one possible
If no debugger is installed, either (a) install one once (`cdb` from the Windows SDK / `procdump`), or (b) instrument with enough fine-grained logging that the *last line before silence* uniquely identifies the failing call. We eventually did (b); doing it from line one would have been faster. One symbolic stack beats ten print-bisections.

### Enumerate kill criteria before investing
For "generate glyphs at runtime", the feasibility predicate was: *writable atlas* AND *a font-asset factory that works* AND *main-thread execution*. Write that predicate down first; the moment any conjunct is provably false, stop and switch strategy (here: pre-baked bundle) instead of iterating on a doomed approach.

### Batch the cheap, offline checks
Metadata greps, reading managed source, and computing enum values (`GlyphRenderMode.SDFAA = 0x1045`) need no game launch. Front-load all of them in parallel so the expensive game-launch round-trips are spent only on things that genuinely require runtime observation.

### Heuristic: in a stripped IL2CPP build, assume the "convenience/editor" APIs are gone
Runtime asset *construction* paths (`CreateFontAsset`, `CreateDynamicFontFromOSFont`, file/byte font loaders) are commonly stripped because shipped games load pre-built assets. Assume they're absent until proven present; design around *loading* pre-built assets, not *building* them.

---

## 2b. How to prompt differently next time (for the human side)

Most of the fix is on the assistant side (measure before building). But a few prompt-level
levers reliably prevent the "start solutioning → rabbit hole" failure mode:

1. **Ask for a feasibility check before a fix.** Highest-leverage change. Instead of
   *"Fix the Vietnamese squares,"* say: *"Before writing any fix, tell me whether this is even
   achievable and what it depends on. List the unknowns you'd verify first and how you'd verify
   each cheaply."* This reframes the first move from "write code" to "build a model of the system."

2. **Ask for the kill criteria up front.** *"What must be true for this approach to work? If any
   of those is false, stop and tell me instead of iterating."* Forces the feasibility predicate to
   be written down — here it was *writable atlas AND a working font factory AND main-thread
   execution*, and each was cheaply falsifiable on day one.

3. **Name the cost of a wrong guess.** *"Each test requires me to manually launch the game, so it's
   expensive. Prefer fewer, higher-information experiments over trial-and-error. Front-load anything
   checkable offline."* When the loop is known to be slow/human-gated, batch the cheap checks
   (metadata greps, reading source) instead of burning round-trips on guesses.

4. **Ask me to read the exact API's source/docs first.** *"Before calling any Unity/TMP API, read
   its actual source and tell me its failure mode."* The `#if UNITY_EDITOR ... return;` that caused
   the final crash was in plain TMP source.

5. **Use the verb that matches intent.** Imperatives ("fix it", "it crashes again") pull toward
   action. If you want understanding, say **"diagnose" / "investigate" / "explain why"** and expect
   findings + a stop, not an immediate patch.

6. **For black-box runtimes, ask for a probe first.** *"Start with a read-only capability probe:
   what threads, what APIs exist/are stripped, what state invariants hold. Don't mutate anything
   until we've seen that."*

**Reusable template to paste for this class of problem:**

> Goal: [X]. **Before proposing a fix**, (1) tell me if it's feasible and what it depends on,
> (2) list what you must verify and how you'd verify each *cheaply/offline*, (3) note your kill
> criteria. Testing is expensive — I have to [launch the game / deploy / …] manually — so prefer
> few high-information experiments. Only start building once we agree the approach can actually work.

**Caveat:** even with perfect prompting, some iteration here was unavoidable — a few facts (the
worker-thread, the stub method) could only be learned by running. Good prompting wouldn't have
eliminated those, but it would have front-loaded the cheap discoveries and surfaced the "this is a
wall" conclusion in ~2–3 iterations instead of a dozen.

## 3. Next steps

### Recommended: ship a pre-baked Vietnamese TMP font and register it as a fallback
This sidesteps all three walls — a pre-baked atlas needs no rasterization, no writable texture, and registration (`List.Add`) is light enough to run from the worker thread (verified: our `fallbackFontAssets` add returned `ok=1`).

1. **Author the asset (in Unity Editor, one-time):**
   - Pick a font with full Vietnamese coverage (Noto Sans / Arial Unicode / Be Vietnam Pro).
   - Create a `TMP_FontAsset` with **Static** atlas population and a baked atlas covering Latin + Latin-Extended-Additional (Vietnamese) ranges. Static + pre-baked = no runtime FontEngine needed.
   - Match the shader to what desktop builds ship (`TextMeshPro/Distance Field`, and confirm the Mobile variant isn't required).
   - `BuildAssetBundles` targeting Standalone; produce e.g. `vi_tmp_sdf.bundle`. Keep TMP version compatible with common targets (TMP 3.x / Unity 2021–2022).

2. **Ship it** under `src/files/LunaHook/` (or a dedicated `fonts/` dir) so it deploys with the hook.

3. **Wire up loading (native, in `monocommon.hpp`):**
   - `AssetBundle.LoadFromFile(path)` → `bundle.LoadAllAssets()` / `LoadAsset(name, typeof(TMP_FontAsset))`. *Note:* the legacy disabled `hook_GetTextElement` here reported `LoadAllAssets` crashing — prefer the typed `LoadAsset` / `LoadAllAssets(Type)` overload, and do the load once, guarded, ideally confirmed to be on a safe thread.
   - Register the loaded asset into `TMP_Settings.fallbackFontAssets` (global) — already proven to work from the embed thread.
   - Do **not** call `TryAddCharacters` or mutate any baked asset. TMP samples the pre-baked atlas at render time; no rasterization path is touched.

4. **Validate** with the capability-probe mindset: log the bundle load result, the asset pointer, and the `List.Add` result; then confirm visually.

### If a per-language bundle is undesirable
- Consider generating the bundle build as part of CI from a checked-in font + a tiny Unity project, so contributors don't hand-bake it.
- Alternatively scope the feature to engines/builds where `CreateFontAsset` is *not* stripped (detectable via the capability probe) and only enable runtime generation there.

### Housekeeping for the current code
- The experimental toggle (`experimental_unity_tmp_font_fix`) is **off by default** — keep it that way.
- Current `monocommon.hpp` `TMPFallbackFont` is detection-only and safe. Before merging, remove the now-dead helpers (`createFont`, `createFontAsset`, `loadFaceResult`, `ensureTMPShader`, `clearFontAssetData`, `makeDynamic`, `newobject`, `pin`, `hasNativePtr`) and the verbose `fflog` file sink, or keep a single gated diagnostic.
- Keep the capability-probe code (thread id, API resolution, `isReadable`, glyph coverage via `FontEngine.GetGlyphIndex`) — it's the reusable asset from this whole exercise.

---

## Appendix: concrete facts captured (so we never re-derive them)

- **Embed thread is a worker thread, not main.** Proven: before `il2cpp_thread_attach`, a GC-triggering managed call crashed with "collect on unknown thread" — impossible on the always-registered main thread. Fix for *simple* calls: attach once per thread (`il2cpp_thread_attach(il2cpp_domain_get())`, idempotent, never detach). This does **not** make texture/GPU work safe.
- **`il2cpp_runtime_invoke` arg convention:** reference-type args are passed as the object pointer **directly** in the `params[]` array; value-type args as a **pointer to the value**. (The disabled `hook_GetTextElement` using `&stringptr` is in an `if(0)` block and is not a correct reference.)
- **`FontEngine.LoadFontFace(Font, int)` returns `FontEngineError`** (0 = Success, 4 = `Invalid_File`). An OS-name `new Font("Arial")` returns `Invalid_File` (no embedded byte data). The game's own baked `sourceFontFile` returns Success.
- **`GlyphRenderMode.SDFAA = 0x1045`** (`RASTER_MODE_NO_HINTING|8BIT|SDFAA|1X`).
- **Coverage test:** after `LoadFontFace`, `FontEngine.GetGlyphIndex(codepoint)` returns 0 if the face lacks the glyph. Unity House dialogue font `BakbakOneRegular`: `'a'`=present, all Vietnamese codepoints (U+1EA1/1EBF/1ECF/1EEF)=0. `LiberationSans`/`Roboto` (also loaded): present.
- **Stripped in this build:** `CreateFontAsset` (stub/crashes), `CreateDynamicFontFromOSFont`, `Internal_CreateFontFromPath`, `LoadFontFace(string)`, `LoadFontFace(byte[])`. **Survived:** `Internal_CreateFont`, `LoadFontFace(Font,int)`, `TryAddCharacters`, `set_atlasPopulationMode`, `ClearFontAssetData`, `get_sourceFontFile`, `Resources.FindObjectsOfTypeAll`, `TMP_Settings.get_fallbackFontAssets`. (Cheap to recheck per game: `grep -a -o <name> global-metadata.dat`.)
- **TMP `ClearAtlasTextures`** early-returns in player builds when `texture.isReadable == false` (the readable-fix is editor-only), leaving the asset half-cleared → render-time crash. This is the wall behind the final crash.
