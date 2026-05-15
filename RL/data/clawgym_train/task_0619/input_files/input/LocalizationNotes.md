Localization context for App Shortcuts:

- We currently placed the App Shortcuts trigger phrases in the main app’s Localizable.strings file, e.g.:

// Localizable.strings
"Open currently reading" = "Open currently reading";
"Show my reading list" = "Show my reading list";
"Sync my library now" = "Sync my library now";

- We do NOT have AppShortcuts.strings or AppShortcuts.xcstrings in the project.
- We have not added any localized variants that include the special token .applicationName (e.g., "Open Currently Reading in ${applicationName}").

Packaging:
- All App Intents types (intents, entities, queries) and the AppShortcutsProvider live in the Swift Package “PageTurnerIntents”.
- The minimum iOS target is iOS 16.
- We rely on Siri voice input for free-form matching (e.g., user says a book title), but our entity queries and phrases have not been adjusted to support this.

Known issues (for the review to confirm):
- Phrases should live in AppShortcuts.strings, not Localizable.strings.
- Phrases should include \(.applicationName) to be discoverable.
- Because we target iOS 16, having App Intents defined only in a Swift Package may cause discovery/startup issues; we should move or duplicate the definitions into the app bundle (or add an App Intents extension for iOS 17+ if we raise min version).
- Some intent perform() functions may exceed the Siri 30-second timeout; we have not set openAppWhenRun for those cases.