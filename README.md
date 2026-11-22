# sqldash

<!-- intro: the maintainer's words -->

## Run

Install deps:
```sh
./deploy-hook
```

Serve:
```sh
./serve [host] [port]
```

Extra Host names to answer to (comma-separated), when served under a name:
```sh
SQLDASH_ALLOWED_HOSTS=box.example ./serve 0.0.0.0
```

Keys, in `~/.config/sqldash/env` (or the file named by `SQLDASH_ENV`):
```sh
ANTHROPIC_API_KEY=...
TYPESAFE_API_KEY=...
```

Gate:
```sh
./check
```
