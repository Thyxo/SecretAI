# SecretAI

Tryk en hotkey, skriv din prompt, og tryk hotkey igen. Så ligger svaret fra DeepSeek i dit clipboard.
Kører usynligt i baggrunden (kun Windows).

## Statusvindue
Et liggende, native vindue (PySide6/Qt, følger Windows' lyse/mørke tema) viser:
- om program, bridge og DeepSeek-login kører (grønne prikker),
- **Taster**: klik på «Start optagelse» eller «Send prompt», og tryk den nye kombination. Esc annullerer, og «Nulstil» går tilbage til Ctrl+Alt+Space,
- knapper til login,
- en testboks, hvor svaret skrives live.

Luk vinduet med X, så kører programmet videre. Åbn det igen ved at klikke på tray-ikonet nederst til højre, eller ved at starte SecretAI en gang til. Tray-ikonet skifter farve sammen med prikken.

Browseren bruges kun til login. Til selve svarene kører en usynlig Chrome i baggrunden.

## Første gang
1. Installer Python 3 (sæt kryds ved *Add to PATH*) og Google Chrome.
2. Dobbeltklik `setup.bat`.
3. Dobbeltklik `start_hidden.vbs`. Chrome åbner. Log ind på DeepSeek, og klar «verify».
4. Tryk **«Jeg er logget ind»** i SecretAI-vinduet.
5. Valgfrit: `install_autostart.bat` starter SecretAI automatisk med Windows.

## Daglig brug
| Handling | Hvad sker der |
|---|---|
| `Ctrl+Alt+Space` | Prikken bliver **rød** og pulserer: du optager. Tastetryk går ikke til det aktive program. |
| Skriv prompten | Backspace virker, Enter giver linjeskift, `Esc` annullerer. |
| Send-tasten (standard `Ctrl+Alt+Space` igen) | Prikken bliver **orange**: AI tænker. |
| Prikken bliver **grøn** | Svaret ligger i clipboardet. Tryk `Ctrl+V`. |
| Prikken bliver **lilla** | Fejl. Se `secretai.log`. Ved login-problemer åbner vinduet af sig selv. |

Prikken kan slås fra i vinduet eller i tray-menuen (*Vis prik*). *Afslut* lukker både SecretAI, bridgen og den usynlige Chrome.

## Indstillinger (`config.json`, oprettes automatisk)
- `hotkey` (start) og `hotkey_send` (send): fx `"ctrl+alt+space"`, `"ctrl+shift+f9"`, `"f9"`. De må gerne være ens. Nemmest at ændre i vinduet.
- `dot`: `true` / `false`
- `suppress_keys`: `false` = tastetryk går også til det aktive program under optagelse
- Svar-hastighed: sæt miljøvariablerne `DS_DEEPTHINK=off` og `DS_SEARCH=off` før start for hurtigere svar.
- Afvises den usynlige Chrome af DeepSeek, så sæt `DS_RUN_VISIBLE=1`.

## Begrænsninger
- Dødtaster (´ ` ^ ¨ ~) ignoreres under optagelse. Skriv bogstavet uden accent.
- Kun én prompt ad gangen. Hotkey, mens den «tænker», ignoreres.
- Bridgen bruger DeepSeeks hjemmeside via browser-automatisering og kan gå i stykker, hvis siden ændres.
- `ds_server.py` lytter kun på 127.0.0.1.
