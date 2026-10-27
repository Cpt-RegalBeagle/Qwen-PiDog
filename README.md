# PiDog AI Stack

A Sunfounder PiDog robot paired with a fully local AI stack. One repo,
two machines, one robot kit: the Pi runs the robot, a second Linux box
runs the LLM / TTS / STT services, and nothing leaves your network.

## Architecture

    Pi robot                          AI server
    python3 main.py                  llama-server  :11434  (LLM, model of your choice)
    XML-RPC daemon :8001             Kokoro TTS    :8880   (speech synthesis)
         |                           OpenWebUI     :8089   (speech-to-text)
         +-------------------------->

Flow: mic -> OpenWebUI STT -> llama-server -> Kokoro TTS -> speaker.
The robot talks to the AI server over plain HTTP; the robot's own
hardware is driven by the Sunfounder SDK through the RPC daemon on :8001.

## Requirements

- Robot: the Sunfounder PiDog kit. The kit installer ships all robot
  dependencies - there is no requirements.txt by design.
- AI server: any Linux with podman and a GPU (AMD ROCm or NVIDIA).
  `ai-stack.sh` autodetects `/dev/kfd` or `/dev/nvidia*`; CPU-only
  works too, just slower.
- Robot host: Python 3 with `requests` and `python-dotenv`.

## Quickstart

### A) AI server

1. Clone this repo and `cd` into it.
2. `./setup.sh` - creates `.env`, `config.py`, `ai-stack.sh` from the
   `*.example` templates (existing files are never overwritten).
3. Edit `.env`:
   - `SERVER_IP` = server IP as seen from the robot
   - `LLAMA_MODEL` = the model your llama-server loads (see Models)
   - `WEBUI_API_KEY` = any non-empty string
4. Put your `.gguf` model file(s) in `MODEL_DIR` (default `~/llama_models`).
5. `./ai-stack.sh`
6. Curl-check the three services:
   ```sh
   curl http://localhost:11434/health   # llama-server
   curl http://localhost:8089/          # OpenWebUI (STT)
   curl http://localhost:8880/          # Kokoro TTS
   ```

### B) Robot

1. Clone the repo onto the Pi (after running the kit installer).
2. `./setup.sh`
3. Edit `.env`: set `SERVER_IP` to the AI server's IP.
4. `python3 pidog_init.py` - run once (hardware init + RPC daemon).
5. `python3 main.py`

## Config reference

### `.env` (created by `setup.sh` from `.env.example`)

| Variable | Meaning |
| --- | --- |
| `SERVER_IP` | AI server IP, as seen from the robot |
| `LLAMA_MODEL` | Model name your llama-server loads (the app reads `LLAMA_MODEL`, not `OLLAMA_MODEL`) |
| `WEBUI_API_KEY` | Key for the OpenWebUI STT endpoint |
| `REMOTE_PI_DOG_PASSWORD` | Robot RPC password (blank if unused) |
| `PIDOG_SSH_PASSWORD` | Robot SSH password (blank if unused) |
| `TAVILY_API_KEY` | Optional web-search key (blank to disable) |
| `CF_TUNNEL_TOKEN_WEBUI` | Optional Cloudflare tunnel token (blank = no tunnel) |
| `TTS_VOICE` | Kokoro voice, default `af_heart` |
| `TTS_MODEL` | TTS backend name, default `kokoro` |
| `LLAMA_TIMEOUT` | LLM request timeout in seconds, default `30` |

### Key `config.py` knobs

| Knob | Purpose |
| --- | --- |
| `PORT_LLAMA` / `PORT_KOKORO` / `PORT_WEBUI` | Service ports (keep in sync with `ai-stack.sh`) |
| `PORT_XMLRPC` | Robot RPC daemon port (8001) |
| `TTS_VOICE` / `TTS_MODEL` | TTS defaults, overridable via `.env` |
| `LLAMA_TIMEOUT` | Per-request timeout, overridable via `.env` |
| `LLM_LOAD_TIMEOUT` | How long to wait for the model to load |
| `SYSTEM_PROMPT` | The robot's persona - customize me |
| `PLAYBACK_*` | TTS playback-end detection tuning |

## Models

Any GGUF your GPU can load:

1. Download a `.gguf` file and put it in `MODEL_DIR`.
2. Set `LLAMA_MODEL` in `.env` to the model name llama-server exposes.
3. Extra llama-server flags (`--models-preset`, `--models-max`,
   `--parallel`, ...) go in `LLM_EXTRA_ARGS` in `ai-stack.sh`.

## Troubleshooting

- Curl the three URLs above; for whichever one fails, run
  `podman logs <container>` (`llama-server`, `open-webui`, `kokoro`).
- Port in use: change the `PORT_*` vars in `ai-stack.sh` (and in
  `config.py` on the robot) or free the port.
- GPU not detected: the script only sees `/dev/kfd` (AMD ROCm) or
  `/dev/nvidia*` (NVIDIA); check your GPU user-group access, or force
  flags via `LLM_GPU_ARGS` / `LLM_GPU_ENV`.
- Model load timeout: raise `LLM_LOAD_TIMEOUT` in `config.py`; large
  models can take a while to load on first use.
