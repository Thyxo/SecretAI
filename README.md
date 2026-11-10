# SecretAI

Tryk en hotkey, skriv din prompt, tryk hotkey igen → svaret fra DeepSeek ligger i dit clipboard.
Kører usynligt i baggrunden (kun Windows).

## Statusvindue
Når du starter programmet, åbner et lille vindue, der viser om alt kører (grønne prikker), om du er logget ind, og som har knapper til login og en testboks. Luk det med X – programmet kører videre. Åbn det igen ved at dobbeltklikke på det grønne tray-ikon nederst til højre. Du kan slå «Vis vindue ved start» fra i vinduet.

## Første gang
1. Installer Python 3 (sæt kryds ved *Add to PATH*) og Google Chrome.
2. Dobbeltklik `setup.bat`.
3. Dobbeltklik `start_hidden.vbs`. Chrome åbner – log ind på DeepSeek, og klar «verify».
4. Tryk **«2 · Jeg er logget ind»** i statusvinduet.
5. Valgfrit: `install_autostart.bat` starter SecretAI automatisk med Windows.

## Daglig brug
| Handling | Hvad sker der |
|---|---|
| `Ctrl+Alt+Space` | Prik bliver **rød**: du optager. Tastetryk går ikke til det aktive program. |
| Skriv prompten | Backspace virker, Enter giver linjeskift, `Esc` annullerer. |
| `Ctrl+Alt+Space` igen | Prik bliver **orange**: AI tænker. |
| Prik bliver **grøn** | Svaret ligger i clipboardet – tryk `Ctrl+V`. |
| Prik bliver **lilla** | Fejl. Se `secretai.log`. Ved login-problemer åbner GUI'en af sig selv. |

Prikken sidder nederst til højre. Slå den fra i tray-ikonet (*Vis prik*), eller sæt `"dot": false` i `config.json`.
Tray-ikonet er også måden at afslutte programmet på (*Afslut*).

## Indstillinger (`config.json`, oprettes automatisk)
- `hotkey`: fx `"ctrl+alt+space"`, `"ctrl+shift+f9"`, `"f9"`
- `dot`: `true` / `false`
- `suppress_keys`: `false` = tastetryk går også til det aktive program under optagelse
- Svar-hastighed: sæt miljøvariablerne `DS_DEEPTHINK=off` og `DS_SEARCH=off` før start for hurtigere svar.

## Begrænsninger
- Dødtaster (´ ` ^ ¨ ~) ignoreres under optagelse. Skriv bogstavet uden accent.
- Kun én prompt ad gangen; hotkey under «tænker» ignoreres.
- Bridgen bruger DeepSeeks hjemmeside via browser-automatisering og kan gå i stykker, hvis siden ændres.
- `ds_server.py` lytter kun på 127.0.0.1.
