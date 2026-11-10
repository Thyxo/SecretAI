# SecretAI – testguide

## 1. Start appen
Dobbeltklik på **`start_hidden.vbs`** i mappen `Documents\GitHub\SecretAI`.
Efter et par sekunder åbner SecretAI-vinduet.

## 2. Log ind på DeepSeek (kun første gang)
1. Klik på den blå knap **«Åbn login-vindue»**.
2. Der åbner et Chrome-vindue med DeepSeek. Log ind, og klar «verify you are human», hvis den kommer.
3. Gå tilbage til SecretAI-vinduet, og klik **«Jeg er logget ind»**.
   Chrome-vinduet lukker, og nu kører Chrome usynligt.
4. Øverst i vinduet skal der stå **«Klar – tryk Ctrl + Alt + Space»** med en grøn prik.

## 3. Test i vinduet
1. Skriv fx `Hvornår lukker Tivoli i aften?` i feltet under **«Prøv det her»**.
2. Klik **«Send»**.
3. Svaret skrives live i boksen. Bagefter står der **«✓ I clipboardet»**.

## 4. Test hotkey
1. Åbn **Notesblok**, og klik inde i den.
2. Tryk **Ctrl + Alt + Space**. Prikken nederst til højre bliver **rød**.
3. Skriv fx `Hvad koster en tur i Den Blå Planet?`. Prøv også æ, ø og å.
   Teksten må **ikke** dukke op i Notesblok.
4. Tryk **Ctrl + Alt + Space** igen. Prikken bliver **orange**.
5. Når prikken bliver **grøn**, så tryk **Ctrl + V** i Notesblok. Svaret indsættes.

`Esc` under optagelse annullerer.

## 5. Skift taster (valgfrit)
1. Find kortet **«Taster»** til venstre i vinduet.
2. Klik på knappen ud for **«Start optagelse»** eller **«Send prompt»**. Den bliver blå og viser «Tryk tasterne …».
3. Hold fx **Ctrl + Shift** nede, og tryk en tast. Så er den nye kombination gemt.
   `Esc` annullerer. **«Nulstil»** går tilbage til Ctrl + Alt + Space.

## 6. Luk appen
Klik **«Afslut»** nederst i vinduet. Du kan også højreklikke på den lille prik i proceslinjen nederst til højre (evt. under pilen ^) og vælge **«Afslut»**.
Lukker du vinduet med **X**, kører appen videre i baggrunden.

## Hvis noget fejler
Skriv, hvilket trin der gik galt. Så tjekker Claude `secretai.log` og `bridge.log`.

| Prik | Betyder |
|---|---|
| Rød | Optager din prompt |
| Orange | DeepSeek tænker |
| Grøn | Svaret ligger i clipboardet |
| Lilla | Fejl |
