# Doctor GenAI Simulation

- Doctor app:  http://localhost:8003/
- Admin portal: http://localhost:8003/admin   (password = ADMIN_PASSWORD in .env)

## Run
    pip install -r requirements.txt
    uvicorn main:app --reload

## Database
New Supabase project: run `schema.sql` once in SQL Editor (full schema for the whole project).
Existing database from an older version: run `migrate_v3.sql` once instead (nothing is dropped).
The doctor registration is now the Demographic Form (code, age, gender, degree, specialty, years since MBBS,
designation, patient setting, AI questions). Every question is optional; a skipped one is stored as NULL.

## Admin portal
Overview (Busy vs Quiet, per-scenario and per-page stats), Doctors, Sessions (with full
event log per session), Activity log (filter/search everything), Records, and CSV export of
events / sessions / doctors / records for analysis.

## Docker (port 8003)
    cp .env.example .env      # then fill in SUPABASE_URL, SUPABASE_KEY, ADMIN_PASSWORD
    docker compose up -d --build

- Doctor app:   http://localhost:8003/
- Admin portal: http://localhost:8003/admin

Logs: `docker compose logs -f` | Stop: `docker compose down` | Update: `git pull && docker compose up -d --build`

Without compose:

    docker build -t doctor-sim .
    docker run -d --name doctor-sim -p 8003:8003 --env-file .env --restart unless-stopped doctor-sim

The `.env` file is not baked into the image (see `.dockerignore`); it is passed at runtime.

## Case data (v2)
All case content lives in `static/cases.json` (generated from the case-set PDF) and `static/followup.json`.
To refresh after editing the PDF: `python parse_cases.py path/to/case_set.pdf` (needs `pip install pdfplumber`).
Optional media: `static/videos/A.mp4 … H.mp4`, `static/audio/A.mp3 … H.mp3` (falls back to a computer voice).
Run `migrate_v2.sql` once in Supabase to store the transcript and treatment plan with each record.

## Look and feel (v7)
- Hospital palette: teal (primary), soft clinical blue-grey surfaces, red kept only for warnings.
- Background photos: add `static/images/hospital-bg.jpg` (desktop) and optionally `hospital-bg-mobile.jpg` (phone). See `static/images/README.txt`.
- Floating prescription button (bottom right on every GenAI page): shows the patient summary and everything added to the prescription, lets the doctor remove items, approve, view the sheet, and download it as a PDF (generated in the browser, no extra libraries).

## Diagnosis & Plan (v9)
The old Diagnosis and Recommendations pages are now one page, **Diagnosis & Plan**, with six steps:
Assessment (incl. must-not-miss) → Diagnosis → Medicines → Tests → Advice & follow-up → Review.
- Tick an AI suggestion to add it to the treatment plan; once ticked, its wording can be edited in place (with "Restore original wording").
- Or write your own diagnosis, reasoning, medicine, test or advice in the "Your own" box. Ticks and own entries work independently or together.
- Own items can be edited, un-ticked (kept as a draft) or deleted. "Add all" / "Clear" act on the AI suggestions of that group only.
- Diagnosis is a new prescription section (on-screen sheet, floating cart, PDF and saved record).
- New logged events: `dx_step`, `add_all_ai`, `clear_ai`, `restore_original`, `delete_own`. The page name in the log is `dxrec`
  (older sessions keep `dx` and `recs`).
