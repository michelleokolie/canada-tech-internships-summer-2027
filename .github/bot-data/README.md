# Internship bot

Runs Mondays and Thursdays (and on demand from the Actions tab), finds new internships on
Ashby, Greenhouse and Lever, and opens a PR that adds them to `.github/scripts/listings.json`.
The PR also contains the rebuilt READMEs. Summer roles go to README.md, Fall/Winter/Spring
roles go to OFFSEASON_README.md. Nothing lands without you merging the PR.

## One-time setup
1. Add a Brave Search API key as the repo secret `BRAVE_API_KEY`.
2. Settings, Actions, General: Workflow permissions = "Read and write permissions", and tick
   "Allow GitHub Actions to create and approve pull requests".
3. Actions tab, "Find internships", Run workflow. You can pick `qwen2.5:7b` there to try the bigger model.

## Files
- `queries.txt`: Brave searches, one per line. Add more.
- `companies.txt`: boards to check as `ashby:slug`, `greenhouse:token`, `lever:slug`. Add by hand or let discovery fill it.
- `company_names.json`: display names. Edit a value to fix a name for good.
- `seen.json`: every posting already judged, so rejects never come back.

## Local use
    python .github/scripts/find_internships.py --dry-run    # preview, writes nothing
    python .github/scripts/find_internships.py --no-llm     # keyword rules only
