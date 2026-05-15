# Library App – Search Prototype

We are prototyping a lightweight search module for our library app to improve user experience. The repo includes a small dataset and minimal tests.

## Project layout
- `app/`: search logic and config
- `data/`: book dataset (JSON)
- `tests/`: unit tests

## Running tests
Use:

```
python -m pytest -q
```

## Known issues (please update after fixes)
- The "available only" filter may behave inconsistently. We need to diagnose and fix this before the next demo.

## Collaboration notes
- Keep changes small and focused. We'll summarize fixes to the team after tests pass.
