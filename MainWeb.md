# MainWeb: porting notes

`MainWeb.py` is a stateless, web-ready version of `Main.py` (YouTube playlist URL → private Spotify playlist). It is a **blueprint to port** to the site (hosted on Cloudflare), not a server. Read this first, then translate function by function.

## What the tool does
Paste a YouTube playlist link → read titles via the YouTube Data API → clean titles into artist + song → search Spotify (top 5) and fuzzy-score → create a **private** playlist → show the link plus a match report. No `yt-dlp` anywhere (YouTube blocks it).

## Owner only (non-negotiable)
Several layers, so one failure isn't enough:
1. **Cloudflare Access** (free) in front of the page *and* `/api/*`. Allow only the owner's email. Set the Access session duration long (e.g. 30 days) so no re-login.
2. **Spotify Development Mode allow-list** contains only the owner's account (User Management in the Spotify dashboard).
3. **Owner check in code**: `assert_owner` asks Spotify `/me` and compares to the `OWNER_SPOTIFY_ID` secret. Runs at login, on every token refresh, and `get_access_token` compares the stored user on every request.
4. Input validation (`extract_playlist_id`), 150-song cap, per-IP rate limiting, CORS limited to the site's own origin.

## Staying logged in (sessions)
Log in with Spotify once, then stay logged in for 30 days (`SESSION_TTL`):
- After the callback, `start_session` verifies the owner, stores the Spotify tokens **server-side** (Workers KV, key = random session id, TTL = 30 days) and returns the session id.
- The browser only gets a cookie holding that random id: `HttpOnly; Secure; SameSite=Lax; Path=/; Max-Age=2592000`. Never put Spotify tokens in cookies, `localStorage` or the page.
- Spotify access tokens last 1 hour. `get_access_token` refreshes them server-side using the stored refresh token, so the user never sees it.
- Logout = delete the KV entry and clear the cookie.
- `store` in the code is a dict stand-in. In Workers it is async KV (`get`/`put` with `expirationTtl`), so those functions become `async`.

## Spotify login flow (authorization code + PKCE)
1. `GET /api/login`: `make_pkce()` + random `state`; keep verifier and state in a short-lived (10 min) `HttpOnly` cookie or KV; redirect to `build_login_url(...)`.
2. `GET /callback?code&state`: **reject if state doesn't match**; `exchange_code(...)`, then `start_session(...)`; set the session cookie; redirect to `/`.
3. Redirect URI must be exactly what's registered in the Spotify app (HTTPS on the real domain, e.g. `https://amarildoguga.com/callback`). Only loopback may use `http` (`http://127.0.0.1:8888/callback` is what the CLI uses).
4. Scope: `playlist-modify-private` only.

## Suggested endpoints (all behind Access + session check)
| Endpoint | Does | Uses |
|---|---|---|
| `POST /api/prepare` `{url}` | validate link, return playlist title + videos | `extract_playlist_id`, `fetch_playlist_title`, `fetch_playlist_videos` |
| `POST /api/match` `{videos}` (≤20) | match one chunk; page calls repeatedly and shows a progress bar | `match_videos` |
| `POST /api/create` `{name, uris}` | create playlist, add songs, return link | `dedupe_uris`, `create_playlist`, `add_items` |

**Why chunks:** Workers' free plan limits outbound subrequests per invocation (about 50 at time of writing; verify current limits) and each song costs a Spotify search. 150 songs in one request would fail. Page flow: prepare → match chunks → show the report → owner confirms → create.

**Report:** each result has `status`: `matched` (score ≥ 0.8), `uncertain` (0.6 to 0.8, show for review, pre-untick), `not_found` (< 0.6, no uri). Add only what the owner confirms.

## Secrets (Worker secrets, never in git or page code)
`SPOTIFY_CLIENT_ID`, `SPOTIFY_CLIENT_SECRET`, `YOUTUBE_API_KEY`, `OWNER_SPOTIFY_ID`, `REDIRECT_URI`. The YouTube key should be restricted to "YouTube Data API v3" (an IP/referrer restriction won't work from Workers). Tokens must never be logged.

## Spotify facts learned the hard way
- The app **owner needs Premium**; otherwise every call returns 403 "Active premium subscription required".
- Development Mode: only allow-listed users can log in.
- Create playlist: `POST /v1/me/playlists`. The old `/v1/users/{id}/playlists` returns **403**.
- Add songs: `POST /v1/playlists/{id}/items` (returns **201**), max 100 per call. The old `/tracks` returns **403**.
- Rate limit: HTTP 429 with `Retry-After`; wait that long then retry. Keep ~0.3s between searches.
- Client-credentials tokens can't write playlists; a user login is required.
- Redirect URIs must be HTTPS except loopback IPs; `localhost` is rejected.

## YouTube facts
- Use only the Data API v3 (`playlists`, `playlistItems`, `videos`): ~5 quota units per 150-song playlist of 10,000/day.
- Mix playlists (`list=RD…`) and private playlists can't be read: friendly error.
- Private/deleted videos are silently missing from `videos` results.

## Matching logic (port exactly, then run the tests below)
- `clean_title`: (1) if the description has "Provided to YouTube by …\n\nSong · Artist", use that; (2) cut after `|`; (3) strip bracketed junk words (official, video, audio, lyrics, visualizer, music, mv, hd, 4k, hq, explicit, clip, full, version); (4) strip `feat./ft.`; (5) split on first ` - ` (also – and —) into artist/song; (6) with no separator, the channel name minus " - Topic"/"VEVO" is the artist.
- `similarity`: lowercase, strip non-alphanumerics, `difflib.SequenceMatcher.ratio()` = `2*M/T` (Ratcliff/Obershelp). **JS has no built-in equivalent**: port that algorithm or the scores (and thresholds) will drift. Dice/Levenshtein would need the thresholds re-tuned.
- Score per Spotify result = `0.6*song + 0.4*best artist` (song only if no artist). Best of the top 5. Below 0.6 → not found.

## Test cases (expected output)
| Input title (channel) | Expected (artist, song) |
|---|---|
| `Tinashe - Needs (Official Video)` | Tinashe, Needs |
| `Kehlani - Folded [Official Music Video]` | Kehlani, Folded |
| `Olivia Dean - A Couple Minutes \| A COLORS SHOW` | Olivia Dean, A Couple Minutes |
| `Drake - Search & Rescue (feat. Rihanna) [Lyrics]` | Drake, Search & Rescue |
| `Blinding Lights` (channel `The Weeknd - Topic`) | The Weeknd, Blinding Lights |

Link validation must **reject**: other domains (`evil.com/?list=…`), `javascript:` URLs, `list=RD…`, links without `list=`, ids with odd characters.
Live check: test playlist `PLVRISicIKs9w` (4 videos) → all 4 `matched` at 1.00 (Needs - Tinashe, OUTTA MY MIND - Monsune, Folded - Kehlani, A Couple Minutes - Olivia Dean).
Session checks: no cookie / unknown id / wrong owner / expired session → 401; a non-owner Spotify login → 403.

## Nice-to-have, not required
`MainWeb.py` could later back the CLI too (`Main.py` currently duplicates the matching logic on purpose, to stay simple).
