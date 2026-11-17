# Toolkit motion revision — 2026-11-17

Reference: https://www.pinterest.com/pin/968273988657956593/

The exact 15-second reference video was retrieved from its public metadata and inspected at 0.1-second transition intervals. Its applicable motion language is an ink/red/cream palette, thin registration marks, an establishing red point and orbit, masked type reveals, rapidly expanding circles, staggered geometric compositions, card depth, and stepped closing wipes. Its branding, media and source code are not application assets.

## Shared visual direction

Keep the established tool interface, Stop display font, Chinese/English typography, ALPHA 1.0, private0516 and existing AI/license text. Use the app orange #ff4b23, cream #f8f7f2 and a warm ink #171a15 for motion covers. Build geometry in CSS/canvas or QPainter. Reference grids/registration marks should be faint, with no fabricated work/performance counters, no audiovisual soundtrack and no long showreel inside a utility.

## Startup: about 1,400 ms

1. 0–320 ms: an ink cover with a faint crosshair/registration marks. One orange point settles into the center and a thin arc/line establishes the composition.
2. 280–650 ms: orange point expands into a circular color wipe; simple toolkit bars/geometric pieces align. Title reveals through a horizontal mask rather than an overall fade. Author/version are small, readable secondary text.
3. 600–980 ms: brief, stable title composition; subtle orbit/geometric counter-motion supplies the beat, then a cream card/aperture expands to reveal the actual workspace.
4. 940–1,400 ms: reveal the workspace in shallow staggered bands/groups, with about 12–18 px displacement and scale roughly .985→1. No entire live widget tree opacity effect. Remove the cover completely and unlock input once, then allow the first-run About dialog.

The exact stage boundaries may move by ±80 ms to suit each renderer, but both applications should visibly belong to the same family. The transition must finish while hidden as well as visible.

## Shutdown: about 650 ms

1. Capture/freeze the current appearance once; content retreats subtly for 100–140 ms.
2. Six alternating stepped ink bands wipe across the content, staggered approximately 30–40 ms, with the closing cover fully opaque by about 430 ms.
3. Orange mark/point contracts to a small point and disappears. Final cover/window fade occupies only the final 80–100 ms, then the existing native close action runs exactly once.

Closing during startup cancels startup work and never flashes the main interface or opens About afterwards. Busy close retains existing cancel/finish behavior. A bridge-close error must restore the usable main UI. Repeated close requests must be harmless.

## Working UI motion

- Page changes: 240–300 ms directional card/strip reveal, a short offset and slight depth scale; settle cleanly. Rapid switching cancels the old transition.
- Dialogs: 260–300 ms masked/card lift reveal; 180–220 ms reverse collapse. Correct keyboard focus/inert/modal state throughout.
- Capsule selectors/primary buttons: 160–220 ms restrained geometric sweep or accent shift and icon motion, preserving button behavior and keyboard support.
- Logs: roughly 220–260 ms baseline reveal/short vertical movement, only for the newest few entries. Keep bounded queues, batched insertion, automatic following and manual scroll anchors.
- Progress/counts: continuous, monotonic-looking visual interpolation with unchanged exact numeric state; no simulated throughput values.
- Decoration/preview: no continuous work when minimized, hidden, unfocused, covered or intentionally static. Retain the existing 60fps ceiling and geometry caching.

## Motion preference

The user explicitly requested removal of the locked reduced-motion switch. Mesh must not reintroduce it or inherit a stored/system reduced-motion lock. Texture should also show the redesigned startup/shutdown by default; retain explicit constructor/test-environment overrides but remove the Windows automatic reduction fallback. Do not modify Windows settings.

## Validation

Validate startup, first/second launch About sequencing, interrupted startup, double close, rapid tabs/dialogs, error restoration, busy cancel, both languages, bounded log bursts/manual scroll, idle timer suspension and real native shutdown. Use the existing isolated native WebView2 smoke and native Windows Qt smoke against synchronized portable files. Keep original engine tests and verify the final package/source manifests. Generate short previews or time-sliced screenshots of the actual implementation when practical.

Ownership: Mesh implementation is ui.html; Texture implementation is UI-only Python modules and their tests. Conversion engines and assets are outside this motion revision. The primary agent owns runtime synchronization, host adjustments if required, final regression and packaging.
