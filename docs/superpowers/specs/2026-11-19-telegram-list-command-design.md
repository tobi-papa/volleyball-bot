# Comando /list e lanciatore Cloudflare: design

Data: 2026-11-19 · Repo: `tobi-papa/volleyball-bot` · Design di base: `docs/design.md`

## Perché

Il bot avvisa il gruppo Telegram solo quando compare uno slot nuovo. Dopo
qualche giorno nessuno sa più quali slot sono ancora liberi e quali sono
stati presi. L'utente vuole un comando Telegram che risponda con la **lista
completa delle disponibilità del momento**.

Durante la ricognizione è emerso un secondo problema che blocca il primo:
GitHub lancia il workflow programmato **circa ogni 8 ore** (20 run dal
12 al 19 novembre, intervalli 5,5–10 ore, alcuni alle 2–3 di notte), non
ogni 10 minuti. Un comando letto dal bot "al prossimo run" risponderebbe
dopo ore, e anche gli avvisi delle novità arrivano in ritardo.

## Obiettivi

1. Nel gruppo Telegram, il comando **`/list`** fa arrivare entro ~1–2
   minuti un messaggio con **tutti gli slot liberi adesso** (secondo
   `config.yaml`), letti dal portale in quel momento. *Deciso dall'utente.*
2. Il bot torna a girare **davvero ogni 10 minuti** dalle 7:00 alle 23:50
   JST. *Conseguenza dell'opzione A scelta dall'utente.*
3. Il bot resta su GitHub Actions; nessun server dell'utente da tenere acceso.

## Non-obiettivi

- Spostare lo scraping fuori da GitHub Actions (resta Python, com'è).
- Prenotare, pausa/ripresa, comandi oltre a quelli elencati qui.
- Mandare messaggi in chat diverse da quella configurata.

## Anti-obiettivi

- Chiunque scopra l'URL del Worker riesce a far partire il bot o a scrivere
  nel gruppo.
- `/list` scritto da qualcuno in un'altra chat (il bot è pubblico su
  Telegram) fa partire il bot.
- Token (Telegram, GitHub) visibili nel repo pubblico o nei log.
- Raffiche di run se qualcuno scrive `/list` dieci volte di fila.
- Un `/list` che "si perde" senza nessuna risposta.

## Approcci considerati (scelta dell'utente: A)

- **A. Cloudflare Worker sempre acceso** — riceve i comandi Telegram via
  webhook all'istante e lancia il workflow GitHub via API
  (`workflow_dispatch`); con un Cron Trigger lancia anche la scansione ogni
  10 minuti. Risolve comando e frequenza. Costo: account Cloudflare gratuito,
  un token GitHub salvato nel Worker, un secondo pezzo da mantenere.
- B. Messaggio fisso nel gruppo, aggiornato a ogni run — niente servizi
  nuovi, ma con GitHub a ~8 ore resterebbe vecchio di ore.
- C. Cron esterno (cron-job.org) che lancia il workflow — sistema la
  frequenza, ma `/list` risponderebbe solo al run successivo.

## Architettura

```
Telegram (gruppo) --webhook--> Cloudflare Worker --workflow_dispatch--> GitHub Actions: python -m bot
Cloudflare Cron (ogni 10 min) ---------^                                     |
                                                                             v
                                                              Telegram sendMessage (gruppo)
```

### 1. Cloudflare Worker (`worker/` nel repo)

- JavaScript (ES modules), deploy con `wrangler` (Node 24 è già sul Mac;
  `wrangler` via `npx`). Piano gratuito.
- **Cron Trigger** `*/10 22-23,0-14 * * *` (UTC = 7:00–23:50 JST) →
  `POST https://api.github.com/repos/tobi-papa/volleyball-bot/actions/workflows/scan.yml/dispatches`
  con `{"ref":"main","inputs":{"mode":"scan"}}`.
- **Webhook Telegram** su `POST /telegram`:
  - accetta la richiesta solo se l'header
    `X-Telegram-Bot-Api-Secret-Token` è uguale al segreto `WEBHOOK_SECRET`
    (impostato con `setWebhook`); altrimenti 403 e nient'altro;
  - considera solo messaggi con `chat.id == ALLOWED_CHAT_ID` (l'ID del
    gruppo) e testo `/list` o `/list@<nome_del_bot>` (anche con spazi o
    testo dopo); tutto il resto → 200 senza fare nulla (Telegram non deve
    riprovare);
  - per `/list` valido: lancia `workflow_dispatch` con `mode: list` e
    risponde subito nel gruppo con `⏳ Checking the portal, the full list
    arrives in about a minute.`;
  - **cooldown**: se un `/list` è stato lanciato da meno di 3 minuti,
    risponde `⏳ A list is already on its way.` e non lancia un altro run.
    Il timestamp sta in **Workers KV** (gratuito) o, se si vuole evitare
    KV, si legge l'ultimo run `mode=list` dall'API GitHub (scelta del
    costruttore, vedi sotto);
  - se la chiamata a GitHub fallisce: risponde
    `⚠️ Could not start the check (GitHub error <status>).`;
  - `/help` (o `/start`) → breve testo con i comandi.
- **GET /** → `ok` (per verificare il deploy). Nessun altro endpoint.
- Segreti del Worker (`wrangler secret put`): `TELEGRAM_BOT_TOKEN`,
  `GITHUB_TOKEN`, `WEBHOOK_SECRET`, `ALLOWED_CHAT_ID`. `ALLOWED_CHAT_ID` è
  lo **stesso valore del secret GitHub `TELEGRAM_CHAT_ID`**, cioè il gruppo
  Telegram in cui il bot posta già dal 2026-11-12 (scelta dell'utente: solo
  il gruppo). Sta tra i segreti, non in `wrangler.toml`, perché il repo è
  pubblico; l'utente lo incolla nel terminale (i secret GitHub non si possono
  rileggere). Variabili non segrete in `wrangler.toml`: `GITHUB_REPO`,
  `BOT_USERNAME`.
- Se Telegram trasforma il gruppo in supergruppo, l'ID cambia (nuovo
  `-100…`): il Worker, ricevendo un update con `migrate_to_chat_id` dal
  vecchio ID, lo scrive nel log; README spiega di aggiornare entrambi i
  segreti.
- `GITHUB_TOKEN` = **fine-grained personal access token** dell'utente,
  solo sul repo `tobi-papa/volleyball-bot`, permesso **Actions: Read and
  write** e nient'altro, scadenza 1 anno (l'utente lo crea; README spiega
  come e come rinnovarlo).

### 2. Workflow `scan.yml`

- `workflow_dispatch` con input `mode` (`scan` | `list`, default `scan`),
  passato al bot come `python -m bot --mode <mode>`.
- Il `schedule` di GitHub **resta** come riserva (se il Worker si ferma, il
  bot continua almeno ogni ~8 ore). Doppioni innocui: lo stato evita
  avvisi ripetuti.
- `concurrency`: i run `list` non devono essere cancellati da run `scan` in
  coda (GitHub tiene un solo run "pending" per gruppo). Gruppo
  `scan-volley-${{ inputs.mode || 'scan' }}`; vedi rischio stato sotto.

### 3. Bot Python (`--mode list`)

- `--mode scan` = comportamento attuale, invariato.
- `--mode list`:
  1. legge il portale come sempre e applica le regole;
  2. manda **sempre** un messaggio con la lista completa (anche se vuota),
     raggruppata per giorno, con l'ora di lettura in JST:
     ```
     📋 Free now at Kohoku (29) · checked 14:05 JST

     Tue 17 Nov 2026
       7:30–9:00 · Gym 1 (full)
       7:30–9:00 · Gym 1 A (half)
     Fri 20 Nov 2026
       7:30–9:00 · Gym 1 A (half)
     …
     Taken since the last /list (3):
       Wed 25 Nov 2026 · 9:00–11:00 · Gym 1 A (half)
       …

     Book: https://www.shisetsu.city.yokohama.lg.jp/user/Home
     ```
     Gli slot che **non erano nella lista del `/list` precedente** sono
     marcati `🆕` (stesso riferimento della sezione "Taken"); al primo
     `/list` nessuna marcatura.
  3. la sezione "Taken since the last /list" confronta con la lista
     mandata dal `/list` precedente (`last_listed`); al primo `/list` non
     c'è. `last_listed` vive in un **file e una chiave di cache separati**
     (`list_state.json`, chiave `bot-list-<run_id>`), così un run `scan`
     concorrente non può cancellarlo;
  4. aggiorna lo stato come una scansione (gli slot nuovi sono già nella
     lista: niente messaggio "new slots" separato);
  5. errori: manda subito `⚠️ Could not read the portal: <errore>` (niente
     limite di 6 ore e niente soglia di 2 errori: l'ha chiesto qualcuno);
     manutenzione del portale → `🔧 The portal is in maintenance, try
     again later.`; in entrambi i casi lo stato degli slot non cambia.

## Vincoli

- Telegram: un bot ha **o** webhook **o** `getUpdates`; il bot attuale non
  usa `getUpdates`, quindi il webhook non rompe nulla. Dopo `setWebhook` il
  link `getUpdates` del README non funziona più (va scritto nel README).
- Nei gruppi, con privacy mode attivo, i bot ricevono comunque i comandi
  `/...`: non serve renderlo admin.
- Cloudflare free: 100k richieste/giorno, Cron Trigger inclusi; KV free
  1k scritture/giorno (ampiamente sufficiente).
- GitHub API `workflow_dispatch`: risposta 204, nessun ID del run.
- Repo pubblico: nessun segreto nel codice del Worker né in
  `wrangler.toml`.

## Scelte prese da Claude (contestabili)

1. Comando `/list` (più `/help`); testi in inglese come gli altri messaggi.
2. Risposta immediata "⏳…" dal Worker, così chi scrive sa che è partito.
3. Cooldown 3 minuti tra due `/list`.
4. Sezione "Taken since the last /list" e marcatura `🆕`, entrambe rispetto
   al `/list` precedente, per rispondere al "quali sono andati sold out".
7. `ALLOWED_CHAT_ID` come segreto del Worker, non in `wrangler.toml`.
8. `last_listed` in uno stato separato da quello delle scansioni.
5. Il cron di GitHub resta come riserva.
6. Codice del Worker in JavaScript semplice, senza framework, con test
   (`node --test` o vitest) su: verifica segreto, filtro chat, parsing
   comando, cooldown, chiamata GitHub (fetch finto).

## Rischi

- **Stato concorrente**: un run `list` e un run `scan` contemporanei
  salvano due cache diverse; vince la più recente. Effetto peggiore: un
  avviso "new slot" duplicato. Accettato.
- **Token GitHub scaduto**: il Worker risponde con l'errore di GitHub al
  `/list` e il cron smette; il cron di GitHub fa da riserva. README spiega
  il rinnovo.

## Passi manuali dell'utente

1. Account Cloudflare gratuito; `npx wrangler login` (browser).
2. Token GitHub fine-grained come sopra.
3. Claude fa deploy del Worker, imposta i segreti (l'utente incolla i
   valori nel terminale, non in chat) e chiama `setWebhook`.

## Lasciato al costruttore

- KV oppure API GitHub per il cooldown.
- Struttura dei file in `worker/`, framework di test JS.
- Formato esatto del raggruppamento per giorno (purché come l'esempio).
