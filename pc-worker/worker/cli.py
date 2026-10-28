"""CLI entry point for the local Worker skeleton."""

import argparse
import json
import time
from pathlib import Path

from . import __version__
from .client import WorkerApiError, read_token, request, save_token
from .search import MODEL_NAME, prepare_embedding, search_library


def emit(status: str, **extra: int) -> None:
    event = {
        "component": "pc-worker",
        "version": __version__,
        "status": status,
        "capabilities": [],
        "remoteConnected": False,
        **extra,
    }
    print(json.dumps(event, ensure_ascii=False), flush=True)


def connected_cycle(server: str, token: str, library: Path) -> None:
    request(server, "/api/v1/pc/heartbeat", token, {})
    claim = request(server, "/api/v1/pc/study/claim", token, {}).get("job")
    if claim is None:
        print(json.dumps({"component": "pc-worker", "status": "connected_idle", "remoteConnected": True,
                          "capabilities": ["local_pdf_search"]}, ensure_ascii=False), flush=True)
        return
    try:
        result = search_library(library, claim["query"], claim["maxResults"])
    except Exception:
        result = {"success": False, "modelName": MODEL_NAME, "elapsedMs": 0,
                  "excerpts": [], "error": "本地 PDF 检索失败；请检查资料目录和文件。"}
    request(server, f"/api/v1/pc/study/{claim['jobId']}/complete", token, result)
    print(json.dumps({"component": "pc-worker", "status": "job_completed" if result["success"] else "job_failed",
                      "jobId": claim["jobId"], "remoteConnected": True, "capabilities": ["local_pdf_search"],
                      "modelName": result["modelName"], "elapsedMs": result["elapsedMs"]}, ensure_ascii=False), flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Dengvis PC Worker local skeleton")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--once", action="store_true", help="print local status and exit (default)")
    mode.add_argument("--run", action="store_true", help="wait locally until interrupted")
    mode.add_argument("--prepare-embedding", action="store_true", help="download the public local embedding model")
    parser.add_argument("--interval-seconds", type=float, default=1.0)
    parser.add_argument("--max-cycles", type=int, default=None)
    parser.add_argument("--server", type=str, default="http://127.0.0.1:8000")
    parser.add_argument("--token-file", type=Path, default=Path.home() / ".dengvis" / "pc-worker-token")
    parser.add_argument("--pair-code", type=str, default=None, help="exchange a one-time code for a PC token")
    parser.add_argument("--library", type=Path, default=None, help="explicitly allowed local PDF directory")
    parser.add_argument("--connect", action="store_true", help="enable outbound heartbeat and job polling")
    args = parser.parse_args(argv)

    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be greater than zero")
    if args.max_cycles is not None and (not args.run or args.max_cycles < 1):
        parser.error("--max-cycles requires --run and a positive number")

    if args.prepare_embedding:
        try:
            cache = prepare_embedding()
        except Exception:
            parser.error("本地语义模型准备失败；请检查网络和磁盘空间。")
        print(json.dumps({"component": "pc-worker", "status": "embedding_ready",
                          "modelName": "BAAI/bge-small-zh-v1.5", "cacheDir": str(cache)},
                         ensure_ascii=False), flush=True)
        return 0

    if args.pair_code:
        try:
            paired = request(args.server, "/api/v1/pc/pair", body={"code": args.pair_code})
            save_token(args.token_file, paired["token"])
        except (WorkerApiError, OSError) as error:
            parser.error(str(error))
        print(json.dumps({"component": "pc-worker", "status": "paired", "deviceId": paired["deviceId"],
                          "tokenFile": str(args.token_file)}, ensure_ascii=False), flush=True)
        return 0

    if args.connect:
        if args.library is None:
            parser.error("--connect requires --library")
        try:
            library = args.library.expanduser().resolve(strict=True)
            if not library.is_dir():
                parser.error("--library must be a directory")
            token = read_token(args.token_file)
            cycles = 0
            while True:
                try:
                    connected_cycle(args.server, token, library)
                except WorkerApiError as error:
                    print(json.dumps({"component": "pc-worker", "status": "disconnected", "message": str(error),
                                      "remoteConnected": False}, ensure_ascii=False), flush=True)
                cycles += 1
                if not args.run or (args.max_cycles is not None and cycles >= args.max_cycles):
                    return 0
                time.sleep(args.interval_seconds)
        except (OSError, WorkerApiError) as error:
            parser.error(str(error))

    emit("idle")
    if not args.run:
        return 0

    cycles = 0
    try:
        while args.max_cycles is None or cycles < args.max_cycles:
            time.sleep(args.interval_seconds)
            cycles += 1
    except KeyboardInterrupt:
        pass
    emit("stopped", cycles=cycles)
    return 0
