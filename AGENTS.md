# Project conventions

- Use Conventional Commits for all new commits: `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`, `test: ...`, `chore: ...`. An optional scope is allowed, for example `refactor(demo): ...`.
- Refer to the magnetically responsive desk region as **sweet spot (스윗 스팟)** in new documentation, UI, and discussion. Historical raw data and identifiers must remain unchanged.
- `demo/` contains the initial MagAir feasibility prototype, bundled models, analysis tools, tests, and historical experiment documentation. It is not the future controlled training environment.
- `research/` is the active apparatus-based collection and modeling workspace, authorized on 2026-11-23. It starts with the 21×13 printed grid and fixture pose/height labels. Keep future model choices and collection conditions distinct from decisions already made.
- User authorized raw measurement publication to this GitHub repository on 2026-11-24. Preserve byte-exact, immutable session ZIPs and a SHA-256 inventory under `datasets/`. Working `data/` copies remain ignored. Keep generated reports, build products, credentials, and unrelated Android coursework out of Git. Preserve local experiment files during reorganizations.
- Run archived demo commands from `demo/` and active collection/modeling commands from `research/`. Each Xcode project must remain portable with its own sources/resources. Preserve the active research app identity and its on-device data; the archived demo has a separate bundle identifier.
- Treat hardware used to label training data as separate from inference inputs. Do not imply that Pencil IMU, external angle sensors, or jig coordinates are available to the eventual hardware-free application unless explicitly designed and disclosed.
