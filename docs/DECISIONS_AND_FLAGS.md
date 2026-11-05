# Decisions and attorney flags

Running record of product decisions that changed the original spec, and the points that need legal
review before Project Archive ships to anyone outside the team. Keep this current; it feeds the EULA.

## Decisions (2026-11-04)

| # | Decision | Replaces in spec |
|---|---|---|
| D1 | Project Archive is a Soulseek client for DJs. Search Soulseek in-app; the download goes to quarantine, is checked, then the user chooses **Download to Library** or **Delete**. | 2.2 "conditional" client integration; 3.1 import-first flow |
| D2 | The Soulseek engine is **slskd**, bundled inside our installer and run as a hidden background process. We never implement the Soulseek protocol. | 7.4 adapter stays; 9.2 gate resolved in favour of an existing client |
| D3 | Each install generates its own API key for the engine silently. The user never sees it. | 8.2 / 9.1 "protected local key" |
| D4 | Each install generates its own **Soulseek account** (random human-looking username + strong password) on first launch. The user never creates or sees a Soulseek login. Users with their own Soulseek account can enter it under **Advanced**. | 9.1 "do not collect Soulseek credentials" |
| D5 | Secrets (engine API key, generated Soulseek login, optional own login) live in the OS credential vault (Windows Credential Manager / macOS Keychain); file fallback is user-only readable. The Soulseek password is passed to the engine by environment variable, never written by us to disk. | new |
| D6 | The engine listens for incoming peer connections (Soulseek default port 50300). A one-time plain-language note is shown before the first start; the words "slskd" and "port" are not shown. | 9.1 "no inbound listening socket in MVP" |
| D7 | If the engine can't be reached: silent retry, then one dialog — "Having trouble connecting to the server. [Try again] [Help] [Not now]" — Help opens the FAQ page on the website (`SUPPORT_URL` in the code; page to be created). | 10 "Client unavailable" |
| D8 | Anything a normal user shouldn't need is under an **Advanced** section in Settings: own slskd instance, own Soulseek login, share-a-folder, FFmpeg path. | 6.1 |
| D9 | Sharing a folder back to Soulseek is **opt-in and off by default** (many peers refuse transfers to users who share nothing). | 2.3 "no sharing" (now user-controlled) |
| D10 | Up to 5 tracks are checked at once (Settings); the rest wait in the queue. | 9.1 "max concurrent analyses (default 1)" |
| D11 | Decision buttons are **Download to Library / Download anyway / Delete**. The search-result button is **Check this file**, so it is never confused with the library download. | 3.1 wording box |
| D12 | Store search (Beatport, Bandcamp, Juno, Traxsource, Discogs) stays in the code, unwired, for a later "find it to buy" feature. | — |
| D13 | Paid service: the app will have its own account system and license check on the website. Audio analysis stays fully local; the only thing the app will phone home for is the license. Not built yet. | 1.3 "no account system" (MVP only) |

## ⚑ Attorney flags (for the EULA and privacy policy)

| # | Flag | Why it needs review |
|---|---|---|
| F1 | We bundle and distribute **slskd (AGPL-3.0)** and **FFmpeg (GPL)** inside a paid product. | Source-availability and license-notice obligations for the installer and the website. |
| F2 | We **create Soulseek accounts** for users automatically and store those credentials. | Soulseek's rules and terms of use; what we must disclose to the user about the account acting in their name. |
| F3 | We **charge** for a product that works over the free Soulseek network. | How the service is described and what is actually sold; keep the spec's position that this is not a tool for obtaining unauthorized music. |
| F4 | **Opt-in folder sharing** puts the user in the position of distributing files. | Opt-in wording, default-off, disclaimer. |
| F5 | The app runs an **inbound listener** and **holds credentials** on the user's machine. | Privacy policy: what is stored, where, and that it never leaves the machine. |
| F6 | Our **own account system and license check** (planned). | Standard privacy / data-handling terms for the user data we keep. |

## Not done yet (intentionally)

- Account system, sign-up, subscription, license check (D13).
- Support FAQ page on the website (D7 links to it).
- macOS bundle of the engine (the Windows build bundles it; macOS currently runs from source and can use
  `vendor/slskd/` or an own slskd under Advanced).
- Code signing for the installer.
