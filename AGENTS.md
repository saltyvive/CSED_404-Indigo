# Project conventions

- Use Conventional Commits for all new commits: `feat: ...`, `fix: ...`, `docs: ...`, `refactor: ...`, `test: ...`, `chore: ...`. An optional scope is allowed, for example `refactor(demo): ...`.
- Refer to the magnetically responsive desk region as **sweet spot (스윗 스팟)** in new documentation, UI, and discussion. Historical raw data and identifiers must remain unchanged.
- `demo/` contains the initial MagAir feasibility prototype, bundled models, analysis tools, tests, and historical experiment documentation. It is not the future controlled training environment.
- Do not create a new training/research implementation directory until the user and team decide its approach. Keep proposed equipment and experiment choices distinct from decisions already made.
- Keep raw measurement data, generated reports, build products, credentials, and the unrelated Android coursework out of Git. Preserve local experiment files during reorganizations.
- Run demo commands from `demo/`. Keep the Xcode project and its source/resource paths portable together.
- Treat hardware used to label training data as separate from inference inputs. Do not imply that Pencil IMU, external angle sensors, or jig coordinates are available to the eventual hardware-free application unless explicitly designed and disclosed.
