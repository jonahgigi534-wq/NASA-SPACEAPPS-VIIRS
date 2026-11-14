# Running FireBridge on 3 Claude accounts in parallel

Three people, three laptops, three Claude Code sessions, one repo. **Each person opens only
their own track file and pastes its prompts in order:**

| Track | Who | File |
|---|---|---|
| **A: Data + Science** | the laptop with the NASA data (strongest laptop) | `tracks/TRACK_A_DATA_SCIENCE.md` |
| **B: Backend** | anyone | `tracks/TRACK_B_BACKEND.md` |
| **C: Frontend + Ship** | the person who will present | `tracks/TRACK_C_FRONTEND_SHIP.md` |

Each track file says what you need on your laptop, every prompt to paste (in order), **when** to
run each one, the check to pass before moving on, and the 📣 handoffs to post in team chat.

## Everyone, first 10 minutes
1. Repo owner: GitHub → this repo → **Settings → Collaborators** → add your two teammates.
   They accept the email invite.
2. `git clone https://github.com/jonahgigi534-wq/NASA-SPACEAPPS-VIIRS` then `cd NASA-SPACEAPPS-VIIRS`
3. `claude`, then **Shift+Tab** for plan mode.
4. Open your track file and paste prompt 1. After each prompt passes its check: `/clear`, then
   the next prompt.
5. Before every push: `git pull --rebase origin main` (each prompt already tells Claude to).
6. Make a **shared Google Drive folder** for the app data (too big for GitHub).

## How the tracks fit together
- Tracks only edit their own files (`docs/CONTRACTS.md` §1), so there are no merge conflicts.
- B and C start immediately on fake/sample data in the exact formats in `docs/CONTRACTS.md`.
- Handoffs (Central time): ~4:30 pm A's Texas sample → B · ~6 pm B's API runs → C ·
  ~9 pm A's real data → B, C · ~10 pm A's presets + Methods text → C ·
  Sunday: deploy by 2 pm, video by 6 pm, judge review 8 pm, **submit by 10 pm**.

## If something goes wrong
- **A is late:** B and C keep going on fake data. Ship on A's Texas sample + metrics if needed;
  cut Australia first (CLAUDE.md §8 cut order).
- **A contract needs to change:** post in team chat; the owner updates `docs/CONTRACTS.md` and the
  fake/sample data in the same commit.
- **Push rejected:** `git pull --rebase origin main`, then push. If a conflict is in a file you
  don't own, keep their version (`git checkout --theirs <file>`) and tell the owner.
- **Claude stuck:** recovery prompts are at the bottom of `KICKOFF_PROMPTS.md`.
