# Volleyball Bot Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Riscrivere il fork di `jeremynata/volleyball-bot` come bot HTTP leggero (niente browser, niente login) che ogni 10 minuti legge le disponibilità di Kohoku sul portale di Yokohama e avvisa su Telegram solo per gli slot nuovi.

**Architecture:** Pacchetto Python `bot/` con moduli piccoli: config (YAML), portal (client HTTP + parsing), slots (modello + filtri), state (JSON + diff), messages (testo inglese), telegram (invio), main (orchestrazione). GitHub Actions lo lancia via cron e conserva `state.json` con `actions/cache`.

**Tech Stack:** Python 3.12 su Actions (codice compatibile 3.9 per i test sul Mac: `from __future__ import annotations`), `requests`, `beautifulsoup4`, `PyYAML`, `pytest`. Telegram Bot API (`sendMessage`).

**Spec:** `/Users/tobi/Desktop/Personal/Volleyball/docs/superpowers/specs/2026-11-12-volleyball-bot-design.md` (va copiato nel repo in Task 1 come `docs/design.md`). La sezione "Come funziona il sito" è la fonte di verità per ogni campo HTTP.

## Global Constraints

- Nessun login sul portale e nessun browser/Playwright. Dipendenze runtime solo: `requests`, `beautifulsoup4`, `PyYAML`.
- Segreti solo da env: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`. Mai stampati nei log.
- Base URL: `https://www.shisetsu.city.yokohama.lg.jp/user/`. Link nei messaggi: `https://www.shisetsu.city.yokohama.lg.jp/user/Home`.
- "Oggi" = data nel fuso `Asia/Tokyo` (UTC+9), mai la data del runner.
- Massimo 20 celle-giorno spuntate per `SelectDays/Next`.
- Slot libero = cella oraria con `IsEnabledForUser == true`.
- Chiave slot = `(gym, room, date, start, end)`; `start`/`end` come `"7:30"`, `"13:00"`; `date` ISO `"2026-11-30"`; `gym`/`room` in giapponese come dal sito.
- Messaggi in inglese, date sempre esplicite: `Mon 30 Nov 2026 · 7:30–9:00 · Kohoku · Gym 1 B (half)`.
- Testo Telegram ≤ 4096 caratteri per messaggio (spezzare).
- Nessun test chiama il sito o Telegram veri.
- Nessun commit dal workflow; stato solo in `actions/cache`.
- Cron: `*/10 22-23,0-14 * * *` (UTC = 7:00–23:50 JST).

## Review Focus

1. **Data di partenza nel fuso sbagliato**: tra le 0:00 e le 9:00 JST il runner (UTC) è ancora "ieri" → `StartDate` deve essere la data JST. Test in Task 3 (`test_start_date_is_jst`).
2. **Risposta del portale con errore o senza la palestra** (`Result: Error`, palestra non nella lista, zero righe) → il run fallisce con `PortalError`, lo stato non cambia, nessun "GONE"/"NEW" falso. Test in Task 3 e Task 6.
3. **Confini dei lotti** (0, 20, 21 candidate) → 0 richieste orari, 1 lotto, 2 lotti. Test in Task 3 (`test_batches`).
4. **`state.json` mancante o corrotto** → un solo messaggio baseline, nessuna eccezione. Test in Task 4 e Task 6.
5. **Invio Telegram fallito** (rete, 401, 429) → il run fallisce e lo stato slot NON viene salvato, così gli slot nuovi verranno notificati al run dopo. Test in Task 6.

---

### Task 0: Preparazione (manuale, la fa l'utente con Claude)

Nessun codice. Claude guida, l'utente esegue i passaggi che toccano i suoi account.

- [ ] **Step 1:** L'utente fa il fork su github.com di `jeremynata/volleyball-bot` (pulsante Fork) sul proprio account.
- [ ] **Step 2:** L'utente crea il bot con @BotFather su Telegram, scrive un messaggio al bot, e ricava il `chat_id` (README, Task 7, spiega come). Inserisce `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID` in Settings → Secrets and variables → Actions del fork. Rimuove `LOGIN_ID`, `LOGIN_PWD`, `NTFY_URL` se presenti.
- [ ] **Step 3:** L'utente abilita Actions sul fork (i fork le hanno disabilitate di default) ma **disabilita il workflow `Scan volley`** finché il Task 7 non è pushato, per non far girare il vecchio bot senza segreti.
- [ ] **Step 4:** Claude clona il fork in `/Users/tobi/Desktop/Personal/Volleyball/volleyball-bot` e crea il branch `rewrite`. Verifica: `git -C volleyball-bot status` mostra `On branch rewrite`.

### Task 1: Scheletro, config e fixture

**Files:**
- Delete: `get_info.py`, `analyse_dispo.py`, `get_and_analyze.py`, `notify.py`, `dispos_interessantes_passes.json`
- Create: `bot/__init__.py`, `bot/config.py`, `config.yaml`, `requirements.txt` (sovrascrive), `requirements-dev.txt`, `.gitignore` (sovrascrive), `docs/design.md`, `tests/__init__.py`, `tests/fixtures/{month.json,time_page.html,facility_page.html,days_page.html}`, `tests/test_config.py`
- Fixture: copiare da `/Users/tobi/Desktop/Personal/Volleyball/docs/superpowers/fixtures/`.

**Interfaces:**
- Produces:
  - `@dataclass(frozen=True) class Rule: rooms: tuple[str, ...] = (); time_from: str | None = None; time_to: str | None = None; min_duration_minutes: int = 0; weekdays: tuple[str, ...] = ()` (weekdays come `"Mon"`…`"Sun"`)
  - `@dataclass(frozen=True) class Config: purpose: int; gyms: tuple[str, ...]; rules: tuple[Rule, ...]; notify_gone: bool; notify_no_change: bool; error_alert_every_hours: int`
  - `load_config(path: str | Path) -> Config`; solleva `ValueError` con messaggio chiaro se `gyms` vuoto, `rules` mancante, orario non `H:MM`, weekday sconosciuto.

- [ ] **Step 1: Write the failing tests** in `tests/test_config.py`:
  - `test_repo_config_loads`: `load_config("config.yaml")` → `purpose == 5`, `gyms == ("港北スポーツセンター",)`, `rules == (Rule(),)`, `notify_gone is False`, `notify_no_change is False`, `error_alert_every_hours == 6`.
  - `test_rule_fields_parsed`: YAML con una regola `{rooms: [第一体育室（全面）], time_from: "19:00", min_duration_minutes: 120, weekdays: [Sat, Sun]}` → `Rule(("第一体育室（全面）",), "19:00", None, 120, ("Sat","Sun"))`.
  - `test_empty_gyms_rejected`, `test_bad_time_rejected` (`time_from: "7pm"`), `test_bad_weekday_rejected` (`weekdays: [Sabato]`) → `pytest.raises(ValueError)`.
- [ ] **Step 2:** `python -m pytest tests/test_config.py -v` → FAIL (`ModuleNotFoundError: bot`).
- [ ] **Step 3: Implement** `bot/config.py` e scrivi `config.yaml` con commenti in italiano per ogni campo (cosa fa, valori ammessi, esempio di regola serale commentato). `requirements.txt`: `requests`, `beautifulsoup4`, `PyYAML`. `requirements-dev.txt`: `-r requirements.txt` + `pytest`. `.gitignore`: `state.json`, `debug/`, `__pycache__/`, `.venv/`.
- [ ] **Step 4:** `python -m pytest -v` → PASS.
- [ ] **Step 5: Commit** `chore: replace Playwright bot with config skeleton and fixtures`.

### Task 2: Modello slot e filtri

**Files:**
- Create: `bot/slots.py`, `tests/test_slots.py`

**Interfaces:**
- Consumes: `Rule` (Task 1).
- Produces:
  - `@dataclass(frozen=True, order=True) class Slot: date: str; start: str; gym: str; room: str; end: str` — ordine dei campi scelto perché `sorted()` dia data → ora → palestra → sala. `key` property → `(gym, room, date, start, end)`. `to_dict()` / `Slot.from_dict(d)`.
  - `minutes(hhmm: str) -> int`, `hhmm(value: float | int) -> str` (`730.0 → "7:30"`, `1300 → "13:00"`).
  - `matches(slot: Slot, rule: Rule) -> bool`; `apply_rules(slots: Iterable[Slot], rules: Sequence[Rule]) -> list[Slot]` (slot passa se soddisfa almeno una regola; risultato ordinato, senza duplicati).

- [ ] **Step 1: Write the failing tests:**
  - `test_hhmm`: `hhmm(730.0) == "7:30"`, `hhmm(1300) == "13:00"`, `hhmm(900.0) == "9:00"`.
  - `test_empty_rule_matches_everything`: `matches(Slot("2026-11-30","7:30","港北スポーツセンター","第一体育室Ｂ（半面）","9:00"), Rule())` is True.
  - `test_time_window`: con `Rule(time_from="19:00")` lo slot 7:30–9:00 non passa, uno 19:00–21:00 passa; con `Rule(time_to="13:00")` 11:00–13:00 passa, 13:00–15:00 no (`time_to` limita la **fine**).
  - `test_min_duration`: `Rule(min_duration_minutes=120)` scarta 7:30–9:00 (90 min), tiene 9:00–11:00.
  - `test_weekdays_and_rooms`: 2026-11-30 è lunedì → `Rule(weekdays=("Sat",))` False, `("Mon",)` True; `Rule(rooms=("第一体育室（全面）",))` scarta la sala B.
  - `test_apply_rules_union_dedup_sorted`: due regole che matchano lo stesso slot → compare una volta; output ordinato per data poi ora.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `bot/slots.py`. Weekday da `datetime.date.fromisoformat(slot.date).strftime("%a")` non va bene (dipende dal locale): usa una tupla `("Mon",…,"Sun")[d.weekday()]`.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat: slot model and config rules`.

### Task 3: Client del portale

**Files:**
- Create: `bot/portal.py`, `tests/test_portal.py`

**Interfaces:**
- Consumes: `Slot`, `hhmm` (Task 2).
- Produces:
  - `class PortalError(Exception)`, `class SiteClosed(Exception)`.
  - Funzioni pure (testate su fixture):
    - `parse_token(html: str) -> str` (valore di `input[name=__RequestVerificationToken]`; `PortalError` se manca).
    - `facility_fields(html: str, gyms: Sequence[str]) -> list[tuple[str, str]]` — tutte le righe `SelectFacilities.Facilities[i]`, `IsChecked` `true`+`false` per le palestre scelte (match per nome esatto dopo `strip()`), solo `false` per le altre; `PortalError` se una palestra configurata non c'è.
    - `search_condition_fields(start: date) -> list[tuple[str, str]]` — esattamente i campi del punto 4 della spec (`DisplayTerm=4`, liste incluse).
    - `parse_month(payload: list) -> list[MonthFacility]` con `@dataclass class MonthFacility: index: int; code: int; name: str; rows: list[dict]` (righe grezze del JSON); `PortalError` se `payload[0]["Result"] != "Ok"` o se nessuna riga/cella.
    - `candidate_cells(fac: MonthFacility) -> list[tuple[int, int]]` — `(row_idx, cell_idx)` con `DisplayStatusForUser in ("some","vacant")` e `IsEnabledForUser`.
    - `batches(cells: list[tuple[int,int]], size: int = 20) -> list[list[tuple[int,int]]]`.
    - `days_next_fields(start: date, fac: MonthFacility, picked: set[tuple[int,int]]) -> list[tuple[str, str]]` — punto 5 della spec: condizione + **tutte** le celle con `IsChecked` `true`/`false` e `UseDate`, `Rows[r].Code`, `Rows[r].IsDisplayGroup`, `FacilityCode`, `("token","null")`. Prefisso `Horizontal[{fac.index}].Common`.
    - `parse_time_page(html: str) -> list[Slot]` — estrae `JSON.parse("{"AvailabilityTime…")`, decodifica due volte, una `Slot` per ogni cella con `IsEnabledForUser`; gym = `FacilityList[].Common.Name`, room = `DisplayRows[].ObjectName`, date = `UseDate[:10]`. `PortalError` se il blocco manca.
    - `today_jst(now: datetime | None = None) -> date`.
  - `fetch_slots(purpose: int, gyms: Sequence[str], *, session: requests.Session | None = None, now: datetime | None = None) -> list[Slot]` — il flusso completo dei punti 1–6 della spec; prima del punto 2 chiama `api/Header/GetSiteClosing` e solleva `SiteClosed` se `isClosing` è true. Ogni POST: multipart (`files=[(k,(None,v))]`), token nel body e header `RequestVerificationToken`, `X-Requested-With: XMLHttpRequest`, timeout 30 s. Una risposta JSON `{"Result":"Error",...}` a qualunque passo → `PortalError` con l'endpoint e il codice (es. `E-203-000017`). Salva l'ultima risposta in `debug/last_response.txt` prima di sollevare.

- [ ] **Step 1: Write the failing tests** (fixture in `tests/fixtures/`):
  - `test_parse_token_days_page`: token non vuoto da `days_page.html`.
  - `test_facility_fields_kohoku`: da `facility_page.html` con `["港北スポーツセンター"]` → contiene `("SelectFacilities.Facilities[10].IsChecked","true")` seguito da `(...[10].IsChecked,"false")`, `(...[10].SelectedFacility.Value,"11")`; nessun altro indice ha `"true"`. Con `["Nonexistent"]` → `PortalError`.
  - `test_month_candidates`: `parse_month(json.load(month.json))` → 1 facility, `code == 11`, 3 righe; `len(candidate_cells(f)) == 25`.
  - `test_month_error_result`: `parse_month([{"Result":"Error","Information":"E-203-000014"}])` → `PortalError` con `"E-203-000014"` nel messaggio.
  - `test_batches`: `batches([])==[]`; 20 celle → 1 lotto; 21 → lotti da 20 e 1.
  - `test_days_next_fields`: con il facility della fixture e `picked={(0,5)}` → esattamente una riga `IsChecked` `"true"` (`Horizontal[0].Common.Rows[0].Cells[5].IsChecked`), 90 righe `IsChecked` in totale (3×30), contiene `("Horizontal[0].Common.FacilityCode","11")` e `("token","null")`.
  - `test_search_condition_fields`: contiene `("SearchCondition.DisplayTerm","4")`, `("SearchCondition.StartDate","2026-11-12")` per `date(2026,11,12)`, e `("SearchCondition.WeekList[7].Value","8")`.
  - `test_parse_time_page`: da `time_page.html` → 7 slot; il primo ordinato è `Slot("2026-11-30","7:30","港北スポーツセンター","第一体育室Ｂ（半面）","9:00")`; include `Slot("2026-12-09","13:00",…,"15:00")` (Status 17).
  - `test_start_date_is_jst`: `today_jst(datetime(2026,11,12,16,30,tzinfo=timezone.utc)) == date(2026,11,13)`.
  - `test_fetch_slots_site_closed`: sessione finta (classe con `get`/`post` che restituiscono oggetti con `.text`, `.json()`, `.raise_for_status()`) dove `GetSiteClosing` → `{"isClosing":true}` → `SiteClosed`.
  - `test_fetch_slots_happy_path`: sessione finta che serve le fixture in base all'URL (Home e SelectDays → `days_page.html`, SelectFacility → `facility_page.html`, SearchCondition → `month.json`, SelectTime → `time_page.html`, gli altri POST → `{"Result":"Ok","Information":"./..."}`) → `fetch_slots(5, ["港北スポーツセンター"], session=fake, now=...)` restituisce gli slot del parse (deduplicati: due lotti che servono la stessa pagina danno 7 slot, non 14) e la sessione ha ricevuto 2 POST a `AvailabilityCheckApplySelectDays/Next`.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `bot/portal.py`. Parte da `docs/superpowers/fixtures/spike.py` (prototipo funzionante) ma con le funzioni pure sopra. Più palestre = un `Horizontal[i]` per palestra: `fetch_slots` itera su tutte le facility del JSON del mese; i lotti restano per facility.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Live check (non è un test):** `python -c "from bot.portal import fetch_slots; s=fetch_slots(5,['港北スポーツセンター']); print(len(s)); print(*s[:5], sep='\n')"` → stampa un numero >0 (o 0 se è tutto pieno) senza eccezioni, in meno di ~60 s.
- [ ] **Step 6: Commit** `feat: HTTP client for Yokohama facility portal`.

### Task 4: Stato e confronto

**Files:**
- Create: `bot/state.py`, `tests/test_state.py`

**Interfaces:**
- Consumes: `Slot` (Task 2).
- Produces:
  - `@dataclass class State: slots: list[Slot] | None = None; failing: bool = False; last_error_alert: datetime | None = None` (`slots is None` = mai visto nulla → baseline).
  - `load_state(path: str | Path) -> State` — file mancante, vuoto o JSON non valido → `State()` (e un warning su stderr).
  - `save_state(state: State, path: str | Path) -> None` — scrittura atomica (file temporaneo + `os.replace`).
  - `diff(old: Sequence[Slot], new: Sequence[Slot]) -> tuple[list[Slot], list[Slot]]` → `(appeared, gone)`, entrambi ordinati, per `Slot.key`.
  - `should_alert(state: State, now: datetime, every_hours: int) -> bool`.

- [ ] **Step 1: Write the failing tests:** `test_roundtrip` (salva e ricarica 2 slot + `failing=True` + un datetime), `test_missing_file`, `test_corrupt_file` (`"{not json"`) → `State()`, `test_diff` (old `{A,B}`, new `{B,C}` → `([C],[A])`), `test_should_alert` (None → True; 5 h fa con 6 → False; 6 h fa → True).
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `bot/state.py` (datetime in ISO con fuso).
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat: persisted state and diff`.

### Task 5: Messaggi e Telegram

**Files:**
- Create: `bot/messages.py`, `bot/telegram.py`, `tests/test_messages.py`, `tests/test_telegram.py`

**Interfaces:**
- Consumes: `Slot` (Task 2).
- Produces:
  - `PORTAL_URL = "https://www.shisetsu.city.yokohama.lg.jp/user/Home"`
  - `GYMS: dict[str, str]` e `ROOMS: list[tuple[str, str]]` — le tabelle di Jeremy (vedi `notify.py` del repo originale prima di cancellarlo, o la spec): `港北スポーツセンター→Kohoku`, `第一体育室→Gym 1`, `第二体育室→Gym 2`, `体育室→Gym`, `（全面）→" (full)"`, `（半面）→" (half)"`, `Ａ/Ｂ/Ｃ→" A"/" B"/" C"`, più le altre 5 palestre di Jeremy.
  - `slot_line(s: Slot) -> str` → `"Mon 30 Nov 2026 · 7:30–9:00 · Kohoku · Gym 1 B (half)"` (en dash `–` tra gli orari, `·` come separatore; giorno della settimana e mese in inglese senza dipendere dal locale).
  - `new_slots_message(new, gone=()) -> str` — titolo `🏐 {n} new slot(s) at {gym names}`; righe `slot_line`; se `gone`, sezione `Gone ({k})`; in fondo `Book: {PORTAL_URL}`.
  - `baseline_message(slots) -> str` — `🏐 Volleyball bot is running. Currently free ({n}):` + righe (o `No free slots right now.`) + link.
  - `no_change_message(slots) -> str`, `error_message(err: str, run_url: str | None) -> str` (`⚠️ Volleyball bot failed: …`), `recovered_message() -> str` (`✅ Volleyball bot is working again.`).
  - `split_message(text: str, limit: int = 4096) -> list[str]` — spezza solo tra righe.
  - `class TelegramError(Exception)`; `send(text: str, token: str, chat_id: str, *, session=None) -> None` — POST `https://api.telegram.org/bot{token}/sendMessage` con `chat_id`, `text`, `disable_web_page_preview=true`, una chiamata per pezzo di `split_message`; status ≠ 200 o `ok: false` → `TelegramError` **senza** il token nel messaggio.

- [ ] **Step 1: Write the failing tests:**
  - `test_slot_line`: `Slot("2026-11-30","7:30","港北スポーツセンター","第一体育室Ｂ（半面）","9:00")` → `"Mon 30 Nov 2026 · 7:30–9:00 · Kohoku · Gym 1 B (half)"`; sala `第一体育室（全面）` → `"Gym 1 (full)"`; palestra sconosciuta → resta in giapponese.
  - `test_new_slots_message`: 3 slot → prima riga `"🏐 3 new slots at Kohoku"`; 1 slot → `"🏐 1 new slot at Kohoku"`; ultima riga contiene `PORTAL_URL`.
  - `test_baseline_empty`: `baseline_message([])` contiene `"No free slots right now."`.
  - `test_split_message`: 300 righe da 30 caratteri → ogni pezzo ≤ 4096, riunendo i pezzi con `"\n"` si riottiene il testo.
  - `test_send_posts_each_chunk` / `test_send_error_hides_token`: sessione finta; risposta 401 → `TelegramError` il cui `str()` non contiene il token.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** i due moduli.
- [ ] **Step 4:** run → PASS.
- [ ] **Step 5: Commit** `feat: English Telegram messages`.

### Task 6: Orchestrazione e CLI

**Files:**
- Create: `bot/main.py`, `bot/__main__.py`, `tests/test_main.py`

**Interfaces:**
- Consumes: `load_config`, `fetch_slots`, `SiteClosed`, `PortalError`, `apply_rules`, `load_state`/`save_state`/`diff`/`should_alert`, i messaggi, `send`.
- Produces:
  - `run(config: Config, state_path: Path, *, fetch=fetch_slots, notify: Callable[[str], None], now: datetime) -> int` (exit code).
  - `main(argv: list[str] | None = None) -> int` — opzioni `--config config.yaml`, `--state state.json`, `--dry-run` (stampa i messaggi invece di inviarli; non richiede i segreti). Senza `--dry-run` legge `TELEGRAM_BOT_TOKEN`/`TELEGRAM_CHAT_ID` dall'env e fallisce con messaggio chiaro se mancano. `run_url` per gli errori da `GITHUB_SERVER_URL`/`GITHUB_REPOSITORY`/`GITHUB_RUN_ID` se presenti.

Comportamento di `run`, in ordine:
1. `state = load_state(...)`; `slots = apply_rules(fetch(config.purpose, config.gyms, now=now), config.rules)`.
2. `SiteClosed` → stampa "site closed", ritorna 0, stato invariato.
3. Altra eccezione → se `should_alert(...)`: `notify(error_message(...))` e `last_error_alert = now`; `failing = True`; salva **solo** questi campi (slot invariati); ritorna 1. Se anche `notify` fallisce, ritorna 1 senza rilanciare.
4. Successo: costruisci i messaggi — `failing` → `recovered_message()`; `state.slots is None` → `baseline_message(slots)`; altrimenti `diff`: nuovi → `new_slots_message(new, gone if config.notify_gone else ())`; solo spariti e `notify_gone` → stesso messaggio con 0 nuovi; niente e `notify_no_change` → `no_change_message`.
5. Invia tutti i messaggi; se un invio solleva, ritorna 1 **senza salvare** lo stato.
6. Salva `State(slots=slots, failing=False, last_error_alert=None)`; ritorna 0.

- [ ] **Step 1: Write the failing tests** (con `fetch` e `notify` finti, `tmp_path`):
  - `test_first_run_sends_one_baseline`: stato assente, 3 slot → 1 messaggio che inizia con `"🏐 Volleyball bot is running"`, stato salvato con 3 slot.
  - `test_new_slot_notified_once`: stato con `{A}`, fetch `{A,B}` → 1 messaggio con la riga di B e non di A; secondo run identico → 0 messaggi.
  - `test_gone_silent_by_default`: stato `{A,B}`, fetch `{A}` → 0 messaggi, stato `{A}`.
  - `test_portal_error_keeps_state_and_alerts_once`: stato `{A}`; fetch solleva `PortalError` due volte a 10 min di distanza → 1 solo messaggio di errore, exit 1 entrambe le volte, stato slot ancora `{A}`; poi fetch ok con `{A}` → 1 messaggio `recovered`, `failing` False.
  - `test_site_closed_is_silent`: fetch solleva `SiteClosed` → exit 0, 0 messaggi, file stato non modificato.
  - `test_telegram_failure_does_not_save`: stato `{A}`, fetch `{A,B}`, notify solleva `TelegramError` → exit 1, stato ancora `{A}`.
  - `test_corrupt_state_gives_baseline`: file stato `"garbage"` → 1 baseline.
  - `test_dry_run_needs_no_secrets`: `main(["--dry-run", ...])` con fetch patchato e env vuoto → exit 0.
- [ ] **Step 2:** run → FAIL.
- [ ] **Step 3: Implement** `bot/main.py` e `bot/__main__.py` (`raise SystemExit(main())`).
- [ ] **Step 4:** `python -m pytest -v` (tutta la suite) → PASS.
- [ ] **Step 5: Live dry run:** `python -m bot --dry-run --state /tmp/vb_state.json` due volte → la prima stampa il baseline con gli slot di Kohoku, la seconda non stampa messaggi. Poi cancella `/tmp/vb_state.json`.
- [ ] **Step 6: Commit** `feat: run loop with baseline, diff and rate-limited alerts`.

### Task 7: Workflow GitHub Actions e README

**Files:**
- Modify: `.github/workflows/scan.yml` (riscrittura completa)
- Create: `README.md` (sovrascrive), `.github/workflows/test.yml`

**Interfaces:**
- Consumes: `python -m bot` (Task 6).

- [ ] **Step 1: Scrivi `scan.yml`:** nome `Scan volley`; `on: schedule` con il cron dei Global Constraints (commento con la conversione JST) + `workflow_dispatch`; `permissions: contents: read`; `concurrency: scan-volley` senza cancel; job con `timeout-minutes: 5`:
  1. `actions/checkout@v4`
  2. `actions/setup-python@v5` con `python-version: "3.12"` e `cache: pip`
  3. `pip install -r requirements.txt`
  4. `actions/cache/restore@v4` con `path: state.json`, `key: bot-state-${{ github.run_id }}`, `restore-keys: bot-state-`
  5. `python -m bot` con env `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` dai secrets
  6. `actions/cache/save@v4` con `if: always()`, `path: state.json`, `key: bot-state-${{ github.run_id }}` (salta da solo se il file non esiste: aggiungi `hashFiles('state.json') != ''` alla condizione)
  7. `actions/upload-artifact@v4` con `if: failure()`, `path: debug/`, `if-no-files-found: ignore`, `retention-days: 3`
  Nessun passo di commit/push.
- [ ] **Step 2: Scrivi `test.yml`:** su `push` e `pull_request`, Python 3.12, `pip install -r requirements-dev.txt`, `python -m pytest -q`.
- [ ] **Step 3: Verifica sintassi:** `python -c "import yaml,sys; [yaml.safe_load(open(f)) for f in sys.argv[1:]]" .github/workflows/scan.yml .github/workflows/test.yml` → nessun errore.
- [ ] **Step 4: Scrivi `README.md` in italiano** (breve): cosa fa; come creare il bot con @BotFather; come trovare il `chat_id` (scrivere al bot, poi aprire `https://api.telegram.org/bot<TOKEN>/getUpdates` e leggere `message.chat.id`); quali Secrets aggiungere; come modificare `config.yaml` (con un esempio di regola "solo sabato dopo le 13"); come lanciarlo a mano (Actions → Scan volley → Run workflow) e in locale (`python -m bot --dry-run`); come resettare lo stato (Actions → Caches → cancellare `bot-state-*`: al run dopo arriva un nuovo baseline).
- [ ] **Step 5: Commit** `ci: lightweight scan workflow with cached state`.

### Task 8: Messa in funzione (con l'utente)

- [ ] **Step 1:** Push del branch `rewrite`, merge su `main` del fork (dopo la review finale).
- [ ] **Step 2:** L'utente riabilita il workflow `Scan volley` e lo lancia a mano (Run workflow).
- [ ] **Step 3: Verifica:** il run è verde in meno di ~2 minuti; arriva su Telegram il messaggio baseline; il secondo run (a mano o dopo 10 min) è verde e non manda messaggi; in Actions → Caches c'è una voce `bot-state-*`; il workflow `Tests` è verde.
- [ ] **Step 4:** Spostare spec e piano dentro il repo (`docs/`) se non già fatto, e rimuovere `docs/superpowers/fixtures/` dalla cartella del club.
