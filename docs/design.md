# Volleyball bot: design

Data: 2026-11-12 · Approvato dall'utente
Base di partenza: fork di https://github.com/jeremynata/volleyball-bot

## Perché

Il club cerca campi liberi sul portale prenotazioni di Yokohama
(`https://www.shisetsu.city.yokohama.lg.jp/user/Home`). Controllare a mano
è noioso, e non si sa quando compaiono slot nuovi (prima apertura o
cancellazioni). Il bot controlla al posto dell'utente e lo avvisa su Telegram.
Gli slot non vanno sold out in fretta: l'avviso serve a sapere cosa c'è,
così l'utente decide con calma se prenotare e poi fa il sondaggio al gruppo
WhatsApp (skill `crea-sondaggio`).

Il bot di Jeremy funziona, ma è pesante (Chromium a ogni run, centinaia di
click, 6 palestre, login), rumoroso (notifica ogni 10 minuti anche senza
novità) e sporca la cronologia git (un commit a ogni run).

## Obiettivi

1. Gira da solo su GitHub Actions ogni 10 minuti, dalle 7:00 alle 23:50 ora
   giapponese, senza che il computer dell'utente sia acceso.
   *Deciso dall'utente.*
2. Controlla solo **Kohoku Sports Center** (港北スポーツセンター), **tutti gli
   orari**, sulla vista di default del portale (1 mese). *Deciso dall'utente.*
3. Tutte le impostazioni di filtro stanno in un **file di configurazione**
   facile da modificare a mano. Cambiare palestra o orari non richiede di
   toccare il codice. *Deciso dall'utente.*
4. Avvisi su **Telegram**. *Deciso dall'utente.*
5. **Nessun login e nessun browser**: il bot consulta le disponibilità come
   un visitatore, con semplici richieste HTTP. Niente pausa/ripresa, niente
   credenziali del portale. *Deciso dall'utente dopo la ricognizione.*
6. Più leggero e robusto possibile: run di pochi secondi.

## Non-obiettivi

- Prenotare automaticamente, o fare login sul portale.
- Pausa/ripresa da Telegram (non serve: il bot non usa l'account).
- Inviare messaggi su WhatsApp (l'utente incolla lui i testi).
- Interfaccia web, database, server propri.
- Altri portali oltre a quello di Yokohama.

## Anti-obiettivi (cose che lo renderebbero un fallimento anche se "funziona")

- **Spam**: messaggi quando non è cambiato niente, o 100 alert di errore al
  giorno se il sito è giù.
- **Falsi allarmi**: un errore di lettura (risposta vuota, sito cambiato) che
  fa sembrare tutti gli slot "nuovi" o "spariti".
- **Commit a ogni run** nella cronologia del repo.
- Token visibili nel repo pubblico.
- Carico eccessivo sul sito.

## Vincoli noti

- Il fork di un repo pubblico è pubblico. Segreti in GitHub Secrets:
  solo `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
- L'utente crea lui il bot Telegram con @BotFather e inserisce lui token e
  chat_id nei Secrets; Claude non li maneggia.
- `gh` non è installato sul Mac dell'utente: il fork si fa da web (o si
  installa `gh`).
- Il cron di GitHub Actions è in UTC e a volte ritarda o salta run: va bene.

## Come funziona il sito (ricognizione del 2026-11-12)

Fatta in Chrome con hook su XHR e poi replicata in Python puro (`requests`,
nessun browser, nessun login). Prototipo funzionante: `spike.py` e
`parse_time.py` nello scratchpad della sessione
(`/private/tmp/claude-501/-Users-tobi-Desktop-Personal-Volleyball/91958b5c-efd2-4f85-9e8f-533a36bfc84b/scratchpad/`),
con due pagine orari salvate (`time_0.html`, `time_1.html`) utili come
fixture. Giro completo per Kohoku: ~20 s, 25 celle-giorno candidate → 2 lotti.

Base `https://www.shisetsu.city.yokohama.lg.jp/user/`. I POST sono
`multipart/form-data` con `__RequestVerificationToken` preso dall'HTML della
pagina corrente (anche come header `RequestVerificationToken`) e
`X-Requested-With: XMLHttpRequest`. Lo stato è lato server, legato ai cookie:
serve una `requests.Session`.

1. `GET Home` → cookie + token.
2. `POST Home/SearchByPurpose` con `HomeModel.SelectedPurpose=5`
   (バレーボール 6人制; 9人制=6), `HomeModel.SearchByDateTimeModel.SelectedPurposeCategory=1`,
   `HomeModel.DateFrom=`, `HomeModel.DateTo=`, `HomeModel.SelectedSearchTarget=0`,
   `HomeModel.SearchByDateTimeModel.SelectedPlaceClassCategory=1`,
   `HomeModel.SelectedPurposeCategory=1`, `HomeModel.SelectedPlaceClassCategory=1`,
   `SelectedLanguageCode=0`. Risposta
   `{"Result":"Ok","Information":"./AvailabilityCheckApplySelectFacility"}`.
3. `GET AvailabilityCheckApplySelectFacility` → 22 palestre con
   `SelectFacilities.Facilities[i].{IsChecked,SelectedFacility.Value,SelectedFacility.Text}`.
   Kohoku = codice 11 (ma va cercata per nome, dal config).
   `POST AvailabilityCheckApplySelectFacility/Next` con tutte le righe; per
   quelle scelte `IsChecked=true` seguito da `IsChecked=false` (checkbox
   ASP.NET), per le altre solo `false`.
4. `GET AvailabilityCheckApplySelectDays` → token. Poi
   `POST .../GetAvailability` (solo token) e `POST .../SearchCondition` con
   `SearchCondition.StartDate=<oggi JST>`, `DisplayTerm=4` (1 mese),
   `DisplayCalendar=0`, `TimeZone=0` + le liste
   `DisplayTermList[0..3].Value=1,2,3,4`, `DisplayCalendarList[0..1].Value=0,1`,
   `TimeZoneList[0..3].Value=1,2,3,0`, `WeekList[0..7].Value=1..8`
   (senza le liste: errore E-203-000014). Risposta JSON:
   `[{"Result":"Ok"}, {"Horizontal":[{"Common":{FacilityCode, FacilityName,
   Rows:[{Code, Name, IsDisplayGroup, Cells:[{UseDate, DisplayStatusForUser,
   IsEnabledForUser, ...}]}], Dates:[...]}}]}]`.
   `DisplayStatusForUser` ∈ `some` (▲), `vacant` (○), `full`, `closed`,
   `receptionClosed`. Candidate = `some` o `vacant` con `IsEnabledForUser`.
   Kohoku: 3 righe (第一体育室（全面）, Ａ（半面）, Ｂ（半面）), 30 giorni.
5. `POST AvailabilityCheckApplySelectDays/Next` con: i campi di
   `SearchCondition` del punto 4, **tutte** le celle di tutte le righe
   (`Horizontal[0].Common.Rows[r].Cells[c].IsChecked` true/false +
   `.UseDate`; mandare solo quelle spuntate dà errore E-203-000017),
   `Rows[r].Code`, `Rows[r].IsDisplayGroup` (`true`/`false`),
   `Horizontal[0].Common.FacilityCode`, `token=null`. **Massimo 20 celle
   spuntate per volta.** Per il lotto successivo: nuovo
   `GET .../SelectDays` per il token, poi di nuovo `Next`.
6. `GET AvailabilityCheckApplySelectTime` → l'HTML contiene
   `JSON.parse("{"AvailabilityTime":...}")` (stringa JS da
   decodificare due volte). Dentro: `AvailabilityTime.FacilityList[].Days[]`
   con `UseDate` e `DisplayRows[]` (`ObjectName` = sala) → `DisplayCells[]`
   con `TimeFrom`, `TimeTo` (es. 730.0, 900.0), `Status`, `IsEnabledForUser`.
   **Slot libero = `IsEnabledForUser == true`.** Visti `Status` 0 e 17,
   entrambi mostrati come ○ nel sito; 5, 9, 14 non prenotabili.
   Fasce a Kohoku: 7:30–9:00, 9:00–11:00, 11:00–13:00, 13:00–15:00, …

Altro:
- Non esistono link diretti a uno slot, una palestra o un giorno: tutto è
  legato alla sessione. Il link nei messaggi punta a `.../user/Home`.
- `POST api/Header/GetSiteClosing` (solo token) risponde
  `{"isClosing":false}`: se `true` il sito è in manutenzione e il run va
  saltato senza alert.
- Il bot di Jeremy gira oggi su GitHub Actions: il sito accetta gli IP di
  GitHub.

## Scelte prese da Claude (l'utente può contestarle)

1. **Motore HTTP puro** (`requests` + `beautifulsoup4` o regex), niente
   Playwright. Un client gentile: User-Agent onesto, timeout, nessun retry
   aggressivo.
2. **Notifica solo quando compare almeno uno slot nuovo.** Uno slot è
   identificato da (palestra, sala, data, inizio, fine). Uno slot che sparisce
   e poi ricompare (es. cancellazione) conta di nuovo come nuovo. Gli slot
   spariti non generano messaggi (opzione in config, default off).
   Riepilogo senza novità: opzione in config, default off.
3. **Stato salvato con `actions/cache`** (chiave per run, `restore-keys` per
   prefisso), non con commit. Se lo stato manca (primo run o cache persa), il
   bot salva la situazione attuale e manda **un solo** messaggio "baseline"
   con l'elenco attuale, non una raffica di "nuovi".
4. **Controllo di sanità**: se la risposta del punto 4 non contiene la
   palestra configurata o ha zero righe/celle, il run fallisce e lo stato non
   viene toccato. "Tutto pieno" (celle presenti ma nessuna candidata) è un
   risultato valido.
5. **Alert di errore limitati**: se un run fallisce, messaggio Telegram al
   massimo una volta ogni 6 ore (config); quando torna a funzionare, un
   messaggio "di nuovo OK". In caso di errore si salva come artifact l'ultima
   risposta HTTP ricevuta. Manutenzione del sito (`isClosing`) = run saltato,
   nessun alert.
6. **Formato messaggio** in inglese, così si può inoltrare al gruppo, con
   date esplicite (regola del club), es.
   `Tue 17 Nov 2026 · 7:30–9:00 · Kohoku · Gym 1 (full)`, nomi tradotti con
   le tabelle di Jeremy, titolo tipo `🏐 3 new slots at Kohoku`, e un link
   alla Home del portale. Messaggi oltre 4096 caratteri vanno spezzati.
7. **File di configurazione `config.yaml`** nella radice del repo, con
   commenti:
   - `purpose`: 5 (pallavolo 6人制);
   - `gyms`: nomi giapponesi come appaiono sul sito
     (oggi solo `港北スポーツセンター`);
   - `rules`: lista di filtri; uno slot passa se soddisfa almeno una regola.
     Ogni regola può avere `rooms` (vuoto = tutte), `time_from`/`time_to`
     (vuoto = tutto il giorno), `min_duration_minutes` (0), `weekdays`
     (vuoto = tutti). Oggi: una sola regola vuota = tutto.
   - `notify_gone`, `notify_no_change`: false;
   - `error_alert_every_hours`: 6.
8. Il cron resta `*/10 22-23,0-14 * * *` (UTC), scritto in un posto solo e
   commentato.
9. Codice in Python 3.12, nomi e commenti in inglese, README breve in
   italiano: come creare il bot Telegram e trovare il chat_id, quali Secrets
   inserire, come modificare `config.yaml`, come lanciarlo a mano.
10. Il fork eredita i commit "maj dispos" di Jeremy: restano nella storia
    (riscriverla non vale la pena). Il vecchio codice, il file di storico e
    i secret `LOGIN_*`/`NTFY_URL` non servono più e si tolgono.

## Lasciato al costruttore

- Struttura dei moduli.
- Test: parsing da fixture salvate (JSON del mese, HTML orari), filtri,
  diff tra stati, formattazione messaggi, alert limitati. Nessun test deve
  chiamare il sito vero; un comando a parte per una prova live.
