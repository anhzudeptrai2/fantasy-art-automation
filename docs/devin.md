# Devin maintenance workflow

1. Someone opens a GitHub issue (bug template).
2. A maintainer reviews it and adds the `devin` label (human gate).
3. `.github/workflows/devin-triage.yml` creates a Devin session and comments the link.
4. Devin analyzes, fixes, adds tests and opens a **pull request** (never pushes to `main`).
5. CI must pass and a human reviews/merges.

## Setup (needs Devin access)
- Create the `devin` label in the repo.
- Add repo secret `DEVIN_API_KEY` (Settings -> Secrets and variables -> Actions).
- Enable branch protection on `main` (require PR + passing CI).
- Check the Devin API endpoint/fields against current Devin docs; the workflow is untested against the live API.
