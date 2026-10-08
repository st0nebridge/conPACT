# Settings

Open the settings window from the **Settings** link on any toast, or from the
conPACT folder:

```bash
python tools/settings.py
```

The same command changes them without the window:

```bash
python tools/settings.py show
python tools/settings.py set min_context_tokens 150k lead_seconds 600
python tools/settings.py reset idle_seconds
python tools/settings.py reset              # everything back to defaults
```

In the window the settings are on four tabs: **Idle toast** (the toast itself,
when it comes, how long **Silence** lasts and how long a result stays up),
**Session size** (which sessions it comes for), **Early toast**, and **Agent**
(compactions an agent queues). Ctrl+Tab and Ctrl+Shift+Tab move between them.
If a value is refused, its tab is marked and brought forward.

## Every setting

| Setting | Default | Allowed | What it does |
|---|---|---|---|
| `idle_toast` | on | on, off | The idle toast. Off is the file `idle-notify.off`, so with no request pending a turn end starts no Python. |
| `min_context_fill` | 50 | 1 to 100 percent | The toast only comes for sessions at least this full, **wherever the app reports a context window**. ChatGPT Desktop does. A fraction travels between apps in a way a token count does not. |
| `min_context_tokens` | 100,000 | 1 to 10,000,000 | The same minimum where the app reports no window to take a fraction of, which today means Claude Code. |
| `lead_seconds` | 300 | 10 to 86,400 | How long before the cache expires the toast comes (never before 60% of the cache's lifetime). |
| `idle_seconds` | off | 10 to 86,400, or off | An **extra, earlier** toast this long after the last reply. Dismissing it does not stop the one above. |
| `early_toast_seconds` | 120 | 10 to 86,400 | How long that early toast waits for an answer before it closes itself. |
| `mute_seconds` | 86,400 | 60 to 604,800 | How long **Silence** silences a session for, or until the session is used again, whichever comes first. |
| `closure_min_context_tokens` | off | 1 to 10,000,000, or off | A compaction an agent queues without a minimum runs only if the context is at least this large. Off: it always runs. An agent's own minimum wins. |
| `guard_spin_off_sessions` | on | on, off | Refuse a compaction queued by a session working in a `.claude/worktrees/...` checkout. Those are merged and archived rather than resumed, so the summary is never read. Off lets one compact itself anyway. |
| `result_seconds` | 8 | 1 to 600 | How long the toast shows the finished compaction before it closes. |

## How values are read

- Numbers may be typed as `150000`, `150,000`, `150 000` or `150k`.
- `off`, or an empty field in the window, switches off a setting that may be
  off.
- Every value is checked before anything is saved. If one is refused, nothing
  changes.
- Values are kept in `~/.conpact/settings.json`, which holds only the
  ones you changed. A value in that file that is out of range is ignored.
- New values apply from the next turn end.
