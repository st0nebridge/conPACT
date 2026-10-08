# ChatGPT Desktop update failure with the conPACT `CODEX_CLI_PATH` sidecar

Date: 2026-10-07

Platform: Intel Mac (`x86_64`), macOS 26.7

Status: Recovered; the latest ChatGPT Desktop is running without the conPACT sidecar override. The findings below identify two conPACT behaviors that need investigation.

## Executive summary

After ChatGPT Desktop updated from `26.917.71314` to `26.930.41038`, the app stopped at “Organization settings could not be loaded.” The conPACT sidecar was still supplying `CODEX_CLI_PATH`, but the updated ChatGPT bundle had moved its Codex executable from the old flat resource path to a nested `codex-cli` bundle.

The installed conPACT resolver did not recognize that new layout. It selected the Codex executable from an older backup copy of ChatGPT instead, pairing an updated desktop shell with an older Codex app-server. Removing the persistent sidecar installation was not sufficient because the override remained in the active macOS GUI bootstrap environment. Finder and Dock launches inherited that stale value and the desktop app wrote it back into generated configuration.

The working recovery was:

1. Uninstall the conPACT sidecar.
2. Remove generated `CODEX_CLI_PATH` entries.
3. Explicitly clear `CODEX_CLI_PATH` from `gui/<uid>`.
4. Install the current official Intel build.
5. Relaunch through Finder and verify that the app selected its bundled nested Codex executable.

After those steps, ChatGPT Desktop `26.1002.52244` reached its home surface, account lookup succeeded, the startup log reported success, and no organization-settings error appeared. The process remained running during verification.

## Confidence and limits

The packaging change, incorrect executable selection, lingering GUI environment value, and successful clean startup are directly observed. The conclusion that the stale or mismatched Codex app-server produced the generic organization-settings screen is a strongly supported working diagnosis, not a captured internal OpenAI error trace.

No screenshot or Accessibility-tree capture was available: macOS screen capture failed and the test process did not have Accessibility permission. The final UI assessment is therefore based on the user’s observation plus process and application-log evidence.

## Environment and versions

| Item | Value |
| --- | --- |
| Architecture | Intel `x86_64` |
| macOS | 26.7 |
| First failing ChatGPT build | `26.930.41038` |
| Previously working ChatGPT build | `26.917.71314` (bundle build `10954`) |
| Final installed ChatGPT build | `26.1002.52244` (bundle build `13536`) |
| conPACT checkout | `$HOME/git/conPACT` |
| Sidecar launcher | `$HOME/git/conPACT/src/sidecar/codex_sidecar` |

## Findings

### F1 — ChatGPT changed the bundled Codex layout

The previously working build exposed Codex at:

```text
/Applications/ChatGPT.app/Contents/Resources/codex
```

The failing and current builds no longer contain that flat path. Their Codex resources are nested under:

```text
/Applications/ChatGPT.app/Contents/Resources/codex-cli/bin/codex
/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex
```

The sidecar’s installed resolver searched for the old `Contents/Resources/codex` layout. Because it could not find that path in the updated active application, it selected the old flat executable from a backup ChatGPT bundle.

This created a version-skew risk: the current desktop shell launched an app-server from an older ChatGPT release. A stale flat-path marker can also fail before organization settings are read if the target no longer exists.

### F2 — Uninstall did not clear the active GUI bootstrap environment

Before cleanup, conPACT reported the sidecar as installed and the desktop process launched with:

```text
CODEX_CLI_PATH=$HOME/git/conPACT/src/sidecar/codex_sidecar
```

The normal uninstall removed the LaunchAgent and marker. A plain `launchctl getenv CODEX_CLI_PATH` then appeared unset, but inspection of the actual GUI bootstrap domain showed the value was still present:

```text
launchctl print gui/501
    CODEX_CLI_PATH => $HOME/git/conPACT/src/sidecar/codex_sidecar
```

The corresponding `user/501` domain did not contain it. This indicates that an uninstall invoked outside the graphical login bootstrap can clear the caller’s environment while leaving Finder’s environment unchanged.

The value was cleared successfully with the equivalent of:

```bash
launchctl asuser "$(id -u)" launchctl unsetenv CODEX_CLI_PATH
```

Verification must inspect `launchctl print gui/<uid>` rather than relying only on `launchctl getenv` from the invoking process.

### F3 — Backup application bundles can be selected as live dependencies

Two known-good old bundles existed during diagnosis. When the active updated bundle no longer matched the old flat-path search, the resolver selected an executable from a backup application instead of refusing the override or finding the active bundle’s nested executable.

An application backup is useful for recovery, but it should not silently become the runtime dependency of the current application. Modification-time ordering is also ambiguous when multiple copies have identical versions or timestamps.

### F4 — Generated configuration can reintroduce a stale override

`CODEX_CLI_PATH` also appeared in:

```text
$HOME/.codex/config.toml
$HOME/.codex/plugins/cache/.../.mcp.json
```

Removing these entries while leaving the GUI bootstrap environment dirty was temporary: a Finder-launched ChatGPT process inherited the stale value and generated configuration containing it again.

Cleanup therefore needs a defined order:

1. Remove or disable the persistent installer source.
2. Clear the GUI bootstrap environment.
3. Remove or regenerate derived configuration and plugin-cache entries.
4. Relaunch and inspect the new process environment.

### F5 — The final current build starts correctly without the override

The final Finder-launched process used:

```text
/Applications/ChatGPT.app/Contents/Resources/codex-cli/CodexCLI.app/Contents/MacOS/codex
```

Observed final state:

- ChatGPT Desktop version `26.1002.52244` installed.
- `CODEX_CLI_PATH` absent from the ChatGPT process.
- `CODEX_CLI_PATH` absent from `gui/501`.
- conPACT sidecar status: not installed.
- Account lookup succeeded.
- Application startup reported success.
- Initial surface was `home` and became visible according to the app log.
- No organization-settings error appeared in the fresh log.
- The process remained alive through the verification interval and later checks.

The relevant fresh log was:

```text
$HOME/Library/Logs/com.openai.codex/2026/10/07/codex-desktop-00000000-0000-4000-8000-0000000000b1-16068-t0-i1-222338-0.log
```

## Evidence summary

| Check | Observed result |
| --- | --- |
| Inspect old app bundle | Flat `Contents/Resources/codex` exists in `26.917.71314` |
| Inspect new app bundles | Flat path absent; nested `codex-cli` executable exists in `26.930.41038` and `26.1002.52244` |
| Inspect sidecar status before uninstall | Installed, marker present, shim running, selected old backup bundle |
| Run sidecar uninstall | LaunchAgent and marker reported removed |
| Inspect user bootstrap | No `CODEX_CLI_PATH` entry |
| Inspect GUI bootstrap | Stale sidecar path still present until explicitly cleared |
| Relaunch before GUI cleanup | New process continued to use the conPACT sidecar |
| Relaunch after GUI cleanup | New process used current app’s nested bundled executable |
| Inspect fresh startup log | Account lookup and app startup succeeded; home surface visible; no organization-settings message |

One direct launch with a sanitized environment briefly worked and then disappeared because the command harness terminated its background descendant. There was no crash report and the application log ended abruptly. That run should not be classified as an application crash; it was superseded by the persistent Finder-launch test.

## Package provenance and verification limits

The final Intel package came from the URL published in OpenAI’s live update feed:

```text
https://persistent.oaistatic.com/codex-app-prod/ChatGPT-darwin-x64-26.1002.52244.zip
```

Downloaded SHA-256:

```text
3642492f4de31e615db56efd77cbe48d6cd781448cca08cdaf4c7949d67ac5f6
```

That checksum matched the Homebrew cask, and the application carried a stapled notarization ticket. Local `codesign` verification was not usable on this machine: both ChatGPT and Safari returned trust/signature errors, including `CSSMERR_TP_NOT_TRUSTED`. Authenticity evidence is therefore the exact official update-feed URL, matching published checksum, and stapled notarization ticket—not a successful local signature-chain verification.

OpenAI’s documented desktop update controls are described at <https://learn.chatgpt.com/docs/enterprise/manage-app-updates>.

## Recommended conPACT changes

1. Resolve Codex from the active ChatGPT bundle first and support both the legacy flat path and the current nested signed-bundle path.
2. Do not select a sibling or backup ChatGPT bundle merely because its old flat executable is discoverable. If the active bundle cannot be resolved compatibly, fail open by leaving the override disabled and report the reason.
3. Make macOS install and uninstall explicitly target the active GUI bootstrap domain. Verify the result using `launchctl print gui/<uid>`.
4. Have `status` report persistent LaunchAgent state, caller-domain state, and GUI-domain state separately so a discrepancy is visible.
5. On uninstall, scrub or regenerate derived `CODEX_CLI_PATH` entries in managed configuration, or report every remaining location precisely.
6. Record both the selected ChatGPT bundle version and selected Codex executable in diagnostics. Warn when they come from different bundles.
7. Preserve rollback bundles, but exclude clearly named backup locations from automatic runtime discovery.

## Suggested regression coverage

- Current app has only the nested layout and an older backup app has the flat layout: select the current nested executable.
- Marker references a removed flat path while the same app contains a nested executable: fall back within the same app.
- Uninstall runs from a non-GUI bootstrap context: clear and verify the GUI-domain variable.
- User and GUI bootstrap domains disagree: `status` reports the discrepancy.
- ChatGPT updates from flat to nested layout while the sidecar is installed: recover without selecting an unrelated application bundle.
- No compatible executable exists in the active app: disable the override and provide an actionable diagnostic.

## Reproduction outline

1. Install a ChatGPT build whose Codex executable is at the legacy flat path.
2. Install the conPACT sidecar so the GUI environment receives `CODEX_CLI_PATH`.
3. Keep a copy of the old ChatGPT bundle in `/Applications` or another scanned location.
4. Replace the active application with a build that only has the nested `codex-cli` layout.
5. Launch ChatGPT through Finder.
6. Inspect the desktop process environment, conPACT selection diagnostics, and the spawned Codex executable.
7. Run uninstall from a terminal or agent context outside the GUI bootstrap.
8. Compare `launchctl print user/<uid>` with `launchctl print gui/<uid>` and relaunch through Finder.

Expected faulty behavior: the resolver selects the old backup executable and/or Finder continues to inject the sidecar after uninstall.

Expected corrected behavior: the active application’s nested executable is selected, or the override is disabled safely; uninstall removes the GUI-domain value and verifies it.

## Recovery and rollback assets retained

The current application is installed at:

```text
/Applications/ChatGPT.app
```

Known-good rollback copies were retained at:

```text
/Applications/ChatGPT-sept-24-working.app
$HOME/Applications/ChatGPT Rollback Backups/ChatGPT-26.917.71314-pre-26.1002.52244.app
```

The initially failing `26.930.41038` bundle was also preserved for comparison at:

```text
$HOME/Applications/ChatGPT Rollback Backups/ChatGPT-26.930.41038-broken.app
```

Do not remove these bundles until the resolver and GUI-bootstrap cleanup changes have regression coverage and have been exercised against an update transition.

## Non-blocking observations

The latest logs also contained unrelated warnings about an unavailable remote SSH host, denied access to some threads, stale experimental feature keys, and an MCP pipe warning during contaminated runs. None prevented the final clean startup, and none currently explains the organization-settings failure.
