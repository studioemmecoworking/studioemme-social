# Studio Emme, social automatici

Programma che prepara, fa approvare su Telegram e pubblica i post Instagram di Studio Emme.
Gira su GitHub Actions: non serve tenere acceso nessun computer.

## Come funziona

1. Tu carichi foto e video nella cartella `libreria` di Cloudinary.
2. Ogni 15 minuti il programma: legge la libreria (Claude descrive le foto nuove), guarda il calendario in `piano/calendario.json`, e 5 giorni prima di ogni post prepara la bozza (slide + didascalia).
3. Ti arriva su Telegram l'anteprima con i pulsanti **Approva / Modifica / Salta**.
4. Se approvi, il post esce alle 18:30 del giorno previsto. Se premi Modifica, scrivi cosa cambiare e ricevi una nuova bozza.
5. Se manca un materiale (foto o video con codice M1...M16), ti avvisa e ti dice cosa girare.
6. Ogni lunedì mattina ricevi il promemoria dei materiali da raccogliere nelle prossime 4 settimane.

## Nomi dei file in Cloudinary

Il codice all'inizio del nome dice a cosa serve il materiale. Esempio: `M3 tour studio.mp4`, `M13 disponibilità studio 1.jpg`. L'elenco dei codici è in `piano/materiali.json`. Le foto senza codice vanno bene lo stesso: servono per i caroselli generici.

## Segreti da inserire su GitHub

Repository > Settings > Secrets and variables > Actions > New repository secret:

| Nome | Dove si trova |
|---|---|
| ANTHROPIC_API_KEY | console.anthropic.com |
| IG_ACCESS_TOKEN | token Instagram già in uso |
| CLOUDINARY_CLOUD_NAME | `davwtxfu` |
| CLOUDINARY_API_KEY | dashboard Cloudinary > API Keys |
| CLOUDINARY_API_SECRET | dashboard Cloudinary > API Keys |
| TELEGRAM_BOT_TOKEN | BotFather |
| TELEGRAM_CHAT_ID | si ottiene scrivendo `/start` al bot (risponde con il numero) |

I segreti non vanno mai scritti nei file né in chat.

## Primo collaudo

1. Actions > "Ciclo" > Run workflow.
2. Scrivi `/start` al bot Telegram, copia il numero in `TELEGRAM_CHAT_ID`.
3. Rilancia il ciclo: arriva la prima anteprima.

## Comandi Telegram

`/stato` riepilogo dei prossimi post. `/riprova ID` ripete una pubblicazione fallita.

## Note

- Se per 60 giorni il repository non ha attività GitHub spegne i cicli: il commit dello stato e il promemoria settimanale lo evitano.
- Storie: non pubblicabili in automatico (niente link/adesivi via API), restano manuali.
- Test: `python -m pytest -q`.
