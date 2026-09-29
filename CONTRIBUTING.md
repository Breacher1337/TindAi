# Contributing to TindAI

This repository is maintained by GrouPals for CCSFEN1L (Introduction to Software Engineering) under Ms. Elsie V. Isip.

---

## Team Roster

- Project Leader: Sapla, Elaijah Angelo A.
- Team Members:
  - Aseoche, Andre Joab L.
  - Ojastro, Raven Marielle O.
  - Pastrana, Aljean Kervy
  - Ventura, Kristine Cate B.

---

## Development Standards

1. Task-Driven Workflow:
   - All contributions must correspond to an active GitHub Issue.
   - Reference the Issue ID in branch names and pull request summaries.
2. Branch Isolation:
   - Do not push directly to the `main` branch.
   - Develop within dedicated task branches using the convention: `task/<issue-id>-<slug>`.
3. Peer Verification:
   - Every pull request requires review and passing automated tests prior to merging into `main`.
4. Commit Syntax:
   - Use Conventional Commits formatting: `type(scope): imperative action [FR-XX]`.
   - Examples:
     - `feat(catalog): add 17 missing FMCG pantry items [FR-02]`
     - `docs(srs): refine non-functional latency benchmarks [NFR-01]`
     - `test(pos): add functional assertions for cash checkout [FR-01]`

---

## Directory Organization

```
TindAI/
├── docs/                   # System specifications, SRS, ERD, and wireframes
├── seeds/                  # Seed datasets (catalog, receipts, test vectors)
├── tests/                  # Test matrices and verification documentation
├── backend/                # Django Ninja API service
├── frontend/               # React Vite client
├── CONTRIBUTING.md
└── README.md
```
