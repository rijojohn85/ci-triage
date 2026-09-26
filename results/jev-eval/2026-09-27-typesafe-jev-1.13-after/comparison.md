# Jev eval comparison

| metric | 2026-09-27-typesafe-jev-1.13 | 2026-09-27-typesafe-jev-1.13-before | 2026-09-27-typesafe-jev-1.13-after |
| --- | --- | --- | --- |
| verdict | FAILED | FAILED | FAILED |
| overall accuracy | 0.297 | 0.536 | 0.674 |
| per-class accuracy: code | 0.300 | 0.600 | 0.600 |
| per-class accuracy: flaky | 0.000 | 0.000 | 0.000 |
| per-class accuracy: infra | 0.167 | 0.306 | 0.806 |
| per-class accuracy: external | 0.111 | 1.000 | 1.000 |
| per-class accuracy: unknown | 0.958 | 0.750 | 0.792 |
| confident-wrong | 19 | 32 | 7 |
| trick pass rate | 6/18 | 9/18 | 9/18 |
| evidence retention | 0/38 | 38/38 | 38/38 |
