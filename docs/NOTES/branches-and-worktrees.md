**One branch per step per repository, each in its own git worktree under `/home/user/wt/`.**

The brief wants one small pull request per repository per step. So: `claude/gallant-cerf-xxy2ge` (the ports, in each
site's main checkout; the design, here), `claude/wts-1-library-versions` (Where MPs Stand), `claude/wts-1b-why-not-a-chatbot`,
`claude/wts-1c-toolchain`. Workers on different steps never share a checkout. Editing a pull request's body with
`gh api` appends a footer through the proxy; use the GitHub MCP tool for bodies. Merging a change to the charity
repository's `publish-hub.yml` publishes the hub, so that file is left alone.
