# jira-stackrank

## Run locally

```bash
poetry config virtualenvs.in-project true
poetry install
cp .env.example .env
poetry run jira-stackrank
poetry run jira-stackrank --apply
```
