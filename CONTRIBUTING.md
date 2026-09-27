# Contributing

Contributions are welcome.

Please preserve the project's core architecture:

- V6 remains the factual data plane;
- Canonical V12 remains the decision authority;
- no duplicate production scorer or optimizer;
- public/private boundaries remain intact;
- missing evidence is never silently fabricated.

Before submitting a pull request:

1. branch from current `main`;
2. keep the change bounded;
3. add or update tests;
4. run the relevant test scope;
5. update affected documentation.

Default local regression command:

```bash
python -m pytest -q
```

Performance improvements must not weaken correctness, search coverage, privacy, or validation.

Do not claim production success from branch-only evidence.
