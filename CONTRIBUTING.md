# Contributing

Contributions to the engine, tests, documentation, and original examples are
welcome.

## Content boundary

Do not submit extracted game databases, copyrighted dialogue, art, audio,
player saves, private journals, or credentials. Regression fixtures must use
original synthetic content created for this repository.

## Development

```sh
python3 -m pip install -e .
python3 -m unittest discover -s tests -v
python3 -m compileall -q src tests examples
git diff --check
```

Keep changes focused. New condition predicates or userscript verbs should carry
a small synthetic regression demonstrating their state semantics.
