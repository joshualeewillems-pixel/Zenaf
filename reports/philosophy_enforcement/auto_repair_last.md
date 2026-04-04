# Auto-repair run

- UTC: `2026-04-04T02:12:20.385348+00:00`
- Repo: `C:\Users\philc\OneDrive\Desktop\Atria`
- Outcome: **`dry_run`**
- Confirmed violations (before → after): **0 → 0**

## Summary

- Repairable candidate (first in priority): `None`
- Chosen for apply (repairable + handler): `None`
- Handler registered for chosen: False

## Findings by checker (confirmed count)


## Notes

Phase 0: all checkers default to `repairable: false` and no handlers are registered.
Enable repairs by setting `repairable: true` and implementing `repairs.HANDLERS[checker_id]`.

