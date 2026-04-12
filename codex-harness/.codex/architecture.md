# Architecture — Layered Dependency Rules

## Layer Hierarchy (strict one-way imports)
Types -> Config -> Repository -> Service -> API -> UI

Rule: A layer can ONLY import from layers BELOW it (lower rank).
Violation: Service importing from API -> BLOCKED

## Layer Definitions
| Layer | Rank | Path Pattern | May Import From |
|-------|------|-------------|-----------------|
| Types | 0 | types/, models/, schemas/ | Nothing |
| Config | 1 | config/ | Types |
| Repository | 2 | repository/, db/, persistence/ | Types, Config |
| Service | 3 | service/, domain/ | Types, Config, Repository |
| API | 4 | api/, routes/, handlers/ | Types, Config, Repository, Service |
| UI | 5 | ui/, frontend/, components/ | All above |

## Cross-Cutting Concerns
Logging, auth middleware, telemetry, error handling -> shared utils (lib/, utils/).
All layers may import from lib/utils.

## Enforcement
- Hook `check-architecture.js` runs on every file write
- Pre-commit gate blocks commits with upward imports
- Agents must respect layering when generating new code
