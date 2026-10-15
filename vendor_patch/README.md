# Mesh Converter local pywebview overlay

Patch: `private0516-mesh-bridge-20261007-v1`, against pywebview 6.2.1.
This is a local source patch, not a new upstream release or a security certification.
Original BSD license and copyright notices are retained in LICENSE.pywebview.txt.
The installed upstream .dist-info metadata and licenses are not removed or rewritten;
its RECORD hashes therefore describe upstream files, while manifest.json records both
the upstream hashes and actual local overlay hashes. BUILD_PROVENANCE.json identifies
the overlay separately.

The app binds its own memory-only localhost page before opening a browser. An occupied
127.0.0.1:42001 aborts startup. No fallback to an existing listener is permitted.
The Edge backend pins the initial navigation ID, full URL and WebMessage source,
blocks later navigation/new windows/external resources, and enables the bridge only
after successful trusted navigation. The dispatcher accepts explicit registered
callables; it never traverses API object attributes. Mesh exposes only seven UI methods.

The first launch of this security revision uses webview-secure1, preserving no old
web content or localStorage. Language/About/motion preferences reset once, then persist
normally on subsequent launches. Old profile data is not deleted.

Only static text editing and AST parsing were authorized/performed. Before release,
validate the real WebView2 event properties, CSP/eval compatibility, first/second-launch
preferences, dialogs, all seven UI actions, blocked navigation/messages, and port-conflict
failure under separately authorized runtime testing. Local tampering with source/runtime,
a hostile same-user process and native NIF parsing are not sandboxed by this patch.

Final static compatibility corrections: the synchronous initialized handler rejects
an actual renderer other than Edge Chromium before native window creation, then the
application raises a readable WebView2 requirement error outside the event dispatcher.
The dispatcher accepts the empty callback ID produced by the unchanged upstream
Math.random generator; method names remain restricted and callback indices remain
JSON-encoded. Native close is allowed when idle and the trusted bridge or successful
injection events are not ready, preserving the animation when the UI is ready.
