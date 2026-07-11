# Security

## Content execution boundary

Condition strings are normalized, parsed as Python expressions, and rejected
unless every AST node belongs to the engine's small condition grammar. Calls
may target only named predicates supplied by the engine; attribute access,
imports, lambdas, comprehensions, arbitrary subscripts, and dynamic call
targets are rejected before evaluation.

Userscripts are not passed to a Lua or Python interpreter. The engine extracts
and handles an explicit set of state verbs.

Content projects still control player-facing text, file paths inside profiles,
graph size, and save locations. Treat a content pack like a local application
project: inspect its profiles and provenance before running it, and do not use
the engine as a sandbox for hostile data.

## Reporting

Until a public security contact is configured, do not publish a proof of
concept containing private data. Report the issue privately to the repository
owner and include the smallest synthetic reproduction possible.
