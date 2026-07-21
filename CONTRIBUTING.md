# Contributing to the Internship List

Thank you for your interest in contributing!

## Finding an Internship to Add
Internships you add meet these requirements. Your internship must:
- be in one of the following categories:
    - software/computer engineering
    - computer/data science
    - product management
    - quant
    - any other tech-related internships
- be located in Canada, or remote.
- not already exist in the internship list.

## Adding an Internship
1) Create a new issue [here](../../issues/new/choose).
2) Select the **New Internship** issue template.
3) Fill in the information about your internship into the form, then hit submit.
> Please make a new submission for each unique position, **even if they are for the same company**.
4) Once your submission has been reviewed, it will be automatically added to the correct README.

## Closing/Archiving an Internship
If a listing is closed, filled, or removed, use the **Close Internship** issue template so we can mark it inactive.

## Automatic README Updates
A script automatically regenerates the README from `.github/scripts/listings.json` whenever a submission is approved, or whenever that file changes directly. You should never hand-edit the table in `README.md` or `OFFSEASON_README.md`, since it gets overwritten.

## Maintainer Notes: Reviewing Submissions
When a "New Internship", "Edit Internship" (via editing an existing new_internship issue), or "Close Internship" issue comes in:
1) Verify it meets the contribution requirements above.
2) Add the `approved` label. This triggers the bot, which parses the form, updates `listings.json`, regenerates the READMEs, commits, pushes, and auto-closes the issue.

**Important:** the issue form fields in `.github/ISSUE_TEMPLATE/new_internship.yaml` and `.github/ISSUE_TEMPLATE/close_internship.yaml` must stay in the exact same order as the `LINES` dictionary in `.github/scripts/contribution_approved.py`. The parser reads answers by line position, not by field name, so reordering, adding, or removing a field in the YAML without updating `LINES` to match will silently corrupt or misassign data.
