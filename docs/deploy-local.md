# Local deployment on Windows (Docker Desktop)

xerscope and its local agent on one Windows PC, reachable from that PC only (`127.0.0.1`), with no
route out of the machine. Built and run on the PC; no image is pushed anywhere. The reasons behind
each setting are in [deploy.md §12](deploy.md); this page is the procedure.

Measured so far: the full test suite, `docker compose config` of every file. Not run here: the image
build, the containers, the model on the GPU. The first deployment is the first run of those.

## 1. Folders and files

```
C:\xerscope\
├── Xerscope\                   the repository (git clone), branch deploy-test-llm
│   ├── compose.yaml            the app
│   ├── compose.silo.yaml       no route out; the gate on 127.0.0.1:8501
│   ├── compose.gpu.yaml        the local model, the study, the cascade
│   └── .env                    your settings (step 4), never committed
├── xerscope-data\              XERSCOPE_EXPORTS, read-only in the containers
│   ├── 2026-11-10.xer          the updates of the series, one file each, at the root
│   ├── 2026-11-17.xer
│   ├── projet.xml              a P6 XML export holding the baselines
│   ├── BL-contrat.xer          a baseline as XER: leave it unticked as an update, pick it as the baseline
│   ├── baselines\              optional: baseline files, never read as updates
│   └── *.toml                  optional: your own standards
├── lexicon\                    XERSCOPE_LEXICON_DIR, create the three folders by hand
│   ├── curated\                your trade words (*.toml), read-only in the app
│   ├── generated\              written by lexicon-init
│   └── suggested\              written by the app ("Did you mean" clicks)
└── models\                     XERSCOPE_MODELS, the .gguf files, read-only in the model's container
```

A trade word file, `lexicon\curated\disciplines.toml`:

```toml
[[group]]
words = ["CVC", "clim", "climatisation"]
```

## 2. Machine (once)

1. NVIDIA driver up to date; Docker Desktop with the WSL 2 engine (Settings, General).
2. Give Docker's virtual machine the RAM, `%UserProfile%\.wslconfig` (12 GB kept for Windows):

   ```
   [wsl2]
   memory=52GB
   processors=24
   ```

   then `wsl --shutdown` and start Docker Desktop again.
3. Check the card from Docker:

   ```powershell
   docker run --rm --gpus all nvidia/cuda:12.8.0-base-ubuntu24.04 nvidia-smi
   ```

## 3. Code and model

```powershell
cd C:\xerscope
git clone -b deploy-test-llm https://github.com/Xerscope/Xerscope.git
```

Later updates: `git pull origin deploy-test-llm` in `C:\xerscope\Xerscope`.

Download the model into `C:\xerscope\models` before the first start: its container downloads
nothing. The order and the reasons: [deploy.md §12](deploy.md). Checked on Hugging Face on 26 November
2026 (no official Qwen GGUF of this model; unsloth's is the most downloaded):

| Model | Repository | File | Size |
|---|---|---|---|
| Qwen3.8-27B (main) | `unsloth/Qwen3.8-27B-GGUF` | `Qwen3.8-27B-UD-Q4_K_M.gguf` | 16.6 GB |
| Qwen3.6-35B-A3B (fast second) | `unsloth/Qwen3.6-35B-A3B-GGUF` | the `UD-Q4_K_M` file | 22.1 GB |

In a browser, open
`https://huggingface.co/unsloth/Qwen3.8-27B-GGUF/resolve/main/Qwen3.8-27B-UD-Q4_K_M.gguf` and save it
in `C:\xerscope\models`, or with Hugging Face's command-line tool:

```powershell
pip install -U huggingface_hub
hf download unsloth/Qwen3.8-27B-GGUF Qwen3.8-27B-UD-Q4_K_M.gguf --local-dir C:\xerscope\models
```

Leave out the variants named uncensored, abliterated or MTP: retrained or modified models, and MTP
fails with the agent's JSON schema (llama.cpp issue 30419).

Pin the two images by digest (llama.cpp: a build of b12005 or later):

```powershell
docker buildx imagetools inspect ghcr.io/ggml-org/llama.cpp:server-cuda
docker buildx imagetools inspect alpine/socat:latest
```

## 4. `.env`

In `C:\xerscope\Xerscope\.env` (Notepad: save as "All files", forward slashes, no quotes):

```
XERSCOPE_EXPORTS=C:/xerscope/xerscope-data
XERSCOPE_LEXICON_DIR=C:/xerscope/lexicon
XERSCOPE_GATE_IMAGE=alpine/socat@sha256:<digest>
XERSCOPE_LLM_IMAGE=ghcr.io/ggml-org/llama.cpp:server-cuda@sha256:<digest>
XERSCOPE_MODELS=C:/xerscope/models
XERSCOPE_MODEL_FILE=Qwen3.8-27B-UD-Q4_K_M.gguf
XERSCOPE_LLM_GPU_LAYERS=28
```

`XERSCOPE_LLM_GPU_LAYERS=28` is for Qwen3.8-27B (64 layers of about 0.26 GB) when Windows already
holds about 3 GB of the card; with the screen plugged into the motherboard (the Core Ultra's own
graphics), the card is free and about 36 layers fit. Keep about 1 GB free in `nvidia-smi`: past the
card, the Windows driver may spill into system memory and the model runs, very slowly.

For Qwen3.6-35B-A3B instead: `XERSCOPE_LLM_GPU_LAYERS=99` and `XERSCOPE_LLM_CPU_MOE=24`.
Optional: `XERSCOPE_AGENT_THINKING=low` (a reasoning pass, slower; see deploy.md §12),
`XERSCOPE_AGENT=off` (the model for the study only).

## 5. Start

The app alone, cut off from the network:

```powershell
docker compose -f compose.yaml -f compose.silo.yaml up -d --build
```

The app with the local agent:

```powershell
docker compose -f compose.yaml -f compose.silo.yaml -f compose.gpu.yaml up -d --build
```

Open http://127.0.0.1:8501. The first start builds the image and loads the model (minutes).
The app's image is built here and never looked up on a registry (`pull_policy: build`); an older
checkout printed "pull access denied for xerscope" before building, harmless.

Shorter commands: add `COMPOSE_FILE=compose.yaml;compose.silo.yaml;compose.gpu.yaml` to `.env`
(`;` on Windows), then `docker compose up -d --build`, `docker compose logs -f --tail 50 llm`,
`docker compose ps`, `docker compose down`.

## 6. Check

| What | Command | Expected |
|---|---|---|
| the model loaded | `docker compose -f compose.yaml -f compose.silo.yaml -f compose.gpu.yaml logs llm --tail 20` | "server is listening" |
| room on the card | `nvidia-smi` | 1.5 to 2 GB free; else lower `XERSCOPE_LLM_GPU_LAYERS` (or raise `XERSCOPE_LLM_CPU_MOE`), more free: the other way |
| no route out | `docker network inspect xerscope_silo --format "{{.Internal}}"` | `true` |
| no route out, from the app | `docker compose -f compose.yaml -f compose.silo.yaml exec xerscope /app/.venv/bin/python -c "import socket; socket.create_connection(('1.1.1.1', 443), 3)"` | "Network is unreachable" |
| from another device | `http://<this PC's address>:8501` | no answer |
| the agent | in the Gantt, a question the grammar does not read ("quelles tâches du génie civil traînent ?") | a box "local agent · …" and "How the agent answered" |

## 7. Use

1. Files window: tick the updates of the series, then Done.
2. Baseline window: "Baseline in each file", or a separate file (a P6 XML, or an unticked XER).
3. Gantt, Ask field: the grammar answers at once; what it does not read goes to the agent.

New updates: drop them in `xerscope-data`, reopen the Files window. The lexicon from the exports:

```powershell
docker compose -f compose.yaml -f compose.silo.yaml run --rm lexicon-init
```

## 8. Day to day

| Action | Command (with the `-f` files used to start) |
|---|---|
| stop | `docker compose ... down` |
| update | `git pull origin deploy-test-llm`, then step 5 |
| logs | `docker compose ... logs -f xerscope` |

When something fails: the last 30 lines of `logs llm` and the message the app shows
("Local agent unavailable: …").
