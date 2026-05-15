Project: PageTurner
Module(s):
- App target: PageTurner (iOS)
- Shared Swift Package: PageTurnerIntents (contains App Intents, entities, queries, and AppShortcutsProvider)
- No App Intents extension target (we plan to add one later)

Target OS and compatibility:
- iOS minimum deployment target: iOS 16
- iOS 17+ features are not gated yet; we have some usages that assume iOS 17 behavior
- Siri and Shortcuts are primary entry points; users are expected to trigger intents via Siri voice (free-form), not only from the Shortcuts UI

Packaging notes:
- All AppIntent types (intents, entities, queries) and AppShortcutsProvider currently live in the Swift Package “PageTurnerIntents” for code sharing with future macOS app
- We do NOT currently mirror these types inside the app bundle target
- Localization for phrases is currently colocated with app Localizable.strings (see LocalizationNotes.md)

Data layer:
- We use SwiftData (@Model) for core objects (e.g., Book). Intents currently fetch @Model instances from a shared container and pass them into helper APIs
- Some operations involve background sync and relatively heavy work (networking and file IO) that can take longer than 30 seconds
- Siri/Shortcuts voice input should allow users to say book names to pick entities (free-form phrases)

Assumptions:
- Siri voice disambiguation should search by book title (free-form), and present recent books first
- We expect intents to be discoverable in Shortcuts without additional setup
- We have not added any @MainActor annotations to perform() methods yet; some methods do open URLs or touch main-thread-only APIs

Known TODOs (pre-review):
- Move shortcut phrases to the correct strings file
- Evaluate whether long-running tasks should open the app
- Revisit entity query types for Siri voice input