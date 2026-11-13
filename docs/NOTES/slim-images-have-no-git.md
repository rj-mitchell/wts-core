**Three of the four sites' Docker images have no `git`, so a `git+https` dependency can't be installed in them.**

Where Countries Stand, Where Councils Stand and Where Landlords Stand build on `python:3.12.15-slim` and install only
`ca-certificates`. Only Where MPs Stand's image installs `git`. `uv` shells out to `git` for a git dependency. This is
why the sites take the package as a wheel from a tagged release (ADR 0006). Check a site's Dockerfile before
assuming a tool is in its image.
