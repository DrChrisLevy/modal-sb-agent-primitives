# Blog: Modal agent patterns

The blog post lives in a separate site repository. Each step is a runnable script in `steps/`, and marked code blocks in the site post are copied from those scripts.

## Setup

You need:

- A Modal account, authenticated with `modal setup` (or a profile in `~/.modal.toml`).
- An OpenAI-compatible model endpoint, such as [Modal's Model APIs](https://modal.com/products/model-apis) ([Shared Endpoints](https://modal.com/docs/guide/shared-endpoints)), and a [proxy token](https://modal.com/docs/guide/endpoints#proxy-tokens) for it.

Run everything from the project root, in a shell that has sourced `env.sh`:

```bash
source env.sh
```

`env.sh` loads two variables from `~/.config/modal-learn/secrets.env`, a file outside the repo, so neither is committed:

- `ENDPOINT_URL`: the model endpoint.
- `MODAL_PROXY_TOKEN`: the endpoint token.

`MODEL` is optional. Without it, the outside-loop steps use the first model the endpoint lists; OpenCode defaults to `moonshotai/Kimi-K3.1-Pro`.

Create the named Secret for the credential and Sidecar demos in your active Modal workspace. This command creates or replaces only the demo Secret, using a fake credential:

```bash
uv run modal secret create blog-demo-key BLOG_DEMO_KEY=blog-demo-not-a-real-key --force
```

`run_all.sh` also runs this command so the demo setup is idempotent.

## Run a step

```bash
uv run python blog/steps/s1_minimal.py "Create /workspace/fizzbuzz.py for 1-15, run it, and report the output."
uv run python blog/steps/s2_locked.py "Write and run a small script, then try fetching https://example.com with a short timeout."
uv run python blog/steps/s3_sidecar.py "Fetch http://key-proxy:8080/headers, then try https://example.com; report each result."
uv run python blog/steps/s4_opencode.py "Write fizzbuzz.py for 1..15 and run it"
uv run python blog/steps/s5_tools_sidecar.py "Fix add.py so add(a, b) returns their sum. Test it with Python."
uv run python blog/steps/s6_snapshots.py filesystem
uv run python blog/steps/s6_snapshots.py start snapshot-demo
uv run python blog/steps/s6_snapshots.py resume snapshot-demo
uv run python blog/steps/s6_snapshots.py sidecar
uv run python blog/steps/s6_snapshots.py memory
uv run python blog/steps/s7_building_blocks.py server
uv run python blog/steps/s7_building_blocks.py turn chat-a "Create notes.txt containing 'apples'."
uv run python blog/steps/s7_building_blocks.py turn chat-b "Create notes.txt containing 'bananas'."
uv run python blog/steps/s7_building_blocks.py turn chat-a "What did you put in notes.txt?"
uv run python blog/steps/s7_building_blocks.py turn chat-b "What did you put in notes.txt?"
uv run python blog/steps/s7_building_blocks.py stop chat-a
uv run python blog/steps/s7_building_blocks.py turn chat-a "Read notes.txt and report its contents."
uv run python blog/steps/s7_building_blocks.py cleanup
```

The Sidecar step pre-builds its proxy image and waits for the listener before starting the agent. It uses the same fake named Secret above; stopping the Sandbox also stops its Sidecar.

The OpenCode step installs `@opencode/cli@2.3.0` and ripgrep during the image build (the first build needs internet). Only its trusted Sidecar receives the endpoint token, via an ephemeral `Secret.from_dict`; main has no API key. Model responses are buffered, not streamed token by token.

## Edit the post

- **Prose:** edit the site post directly.
- **Code:** edit the script in `steps/`, then run `uv run python blog/sync.py`. Never edit a marked code block in the site post by hand.
- **Show new code:** wrap it in `# region: name` / `# endregion` in the script. In the site post, add `<!-- snippet: steps/file.py#name -->` above an empty code block, then run `sync.py`.

Both write and `--check` modes need the post's path: set `BLOG_POST_PATH=/path/to/article.md` (for example in your local secrets file) or pass `--post /path/to/article.md` (the CLI option takes precedence). Source paths in snippet markers always resolve relative to this `blog/` directory, not the destination. Sync replaces only marked fence contents; prose, front matter, image links, and unmarked code blocks are left unchanged. `run_all.sh` uses `BLOG_POST_PATH`.

## Check everything

```bash
uv run python blog/sync.py --check          # code blocks match the scripts
uv run python -m unittest discover -s blog  # unit tests
bash blog/run_all.sh                        # sync check, then every step for real on Modal
```

## Diagrams

`diagrams/*_body.html` are the sources. Each compiles to a standalone `.html` and a `.png` screenshot. The site post embeds PNGs copied to the site's `posts/static_blog_imgs/` directory; keep its site image URLs when updating them.
