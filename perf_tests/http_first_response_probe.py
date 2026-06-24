#!/usr/bin/env python
"""HTTP-only first-response probe for OVERWATCH startup diagnostics."""
from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import json
import math
import pathlib
import ssl
import statistics
import time
import urllib.parse
import uuid


DEFAULT_OUTPUT_DIR = pathlib.Path(__file__).resolve().parent / "results"
DEFAULT_USERS = (1, 3, 6, 9, 12)


def percentile(values: list[float], pct: float) -> float:
    clean = sorted(float(value) for value in values)
    if not clean:
        return 0.0
    rank = math.ceil((pct / 100.0) * len(clean)) - 1
    return clean[max(0, min(rank, len(clean) - 1))]


def perf_url(url: str, *, run_id: str, user_id: int, iteration: int = 1) -> str:
    split = urllib.parse.urlsplit(str(url))
    pairs = [
        (key, value)
        for key, value in urllib.parse.parse_qsl(split.query, keep_blank_values=True)
        if key not in {"overwatch_perf_run_id", "overwatch_perf_user", "overwatch_perf_iteration"}
    ]
    pairs.extend([
        ("overwatch_perf_run_id", run_id),
        ("overwatch_perf_user", str(user_id)),
        ("overwatch_perf_iteration", str(iteration)),
    ])
    return urllib.parse.urlunsplit((
        split.scheme,
        split.netloc,
        split.path or "/",
        urllib.parse.urlencode(pairs),
        split.fragment,
    ))


async def fetch_once(url: str, *, run_id: str, user_id: int, timeout_sec: float) -> dict[str, object]:
    target = perf_url(url, run_id=run_id, user_id=user_id)
    split = urllib.parse.urlsplit(target)
    scheme = split.scheme or "http"
    host = split.hostname or "localhost"
    port = split.port or (443 if scheme == "https" else 80)
    path = urllib.parse.urlunsplit(("", "", split.path or "/", split.query, ""))
    request = (
        f"GET {path} HTTP/1.1\r\n"
        f"Host: {host}\r\n"
        "User-Agent: overwatch-http-first-response-probe\r\n"
        "Connection: close\r\n"
        "\r\n"
    ).encode("ascii")
    started = time.perf_counter()
    connect_ms = 0.0
    first_byte_ms = 0.0
    total_ms = 0.0
    status_code = 0
    bytes_read = 0
    error = ""
    try:
        connect_started = time.perf_counter()
        reader, writer = await asyncio.wait_for(
            asyncio.open_connection(
                host,
                port,
                ssl=ssl.create_default_context() if scheme == "https" else None,
            ),
            timeout=timeout_sec,
        )
        connect_ms = (time.perf_counter() - connect_started) * 1000
        writer.write(request)
        await writer.drain()
        first = await asyncio.wait_for(reader.read(1), timeout=timeout_sec)
        first_byte_ms = (time.perf_counter() - started) * 1000
        rest = await asyncio.wait_for(reader.read(), timeout=timeout_sec)
        raw = first + rest
        bytes_read = len(raw)
        first_line = raw.split(b"\r\n", 1)[0].decode("latin-1", errors="replace")
        parts = first_line.split()
        if len(parts) >= 2 and parts[1].isdigit():
            status_code = int(parts[1])
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
    except Exception as exc:
        error = str(exc).replace("\n", " ")[:300]
    total_ms = (time.perf_counter() - started) * 1000
    return {
        "user_id": user_id,
        "status_code": status_code,
        "ok": 200 <= status_code < 500 and not error,
        "connect_ms": round(connect_ms, 2),
        "time_to_first_byte_ms": round(first_byte_ms, 2),
        "total_ms": round(total_ms, 2),
        "bytes_read": bytes_read,
        "error": error,
    }


async def run_level(url: str, *, run_id: str, users: int, timeout_sec: float) -> dict[str, object]:
    started = time.perf_counter()
    results = await asyncio.gather(*(
        fetch_once(url, run_id=run_id, user_id=user_id, timeout_sec=timeout_sec)
        for user_id in range(1, users + 1)
    ))
    elapsed_sec = time.perf_counter() - started
    return summarize_level(run_id=run_id, users=users, elapsed_sec=elapsed_sec, results=list(results))


def summarize_level(*, run_id: str, users: int, elapsed_sec: float, results: list[dict[str, object]]) -> dict[str, object]:
    ttfb = [float(row.get("time_to_first_byte_ms", 0) or 0) for row in results if row.get("ok")]
    total = [float(row.get("total_ms", 0) or 0) for row in results if row.get("ok")]
    connect = [float(row.get("connect_ms", 0) or 0) for row in results if row.get("ok")]
    return {
        "run_id": run_id,
        "users": users,
        "elapsed_sec": round(elapsed_sec, 3),
        "requests": len(results),
        "ok": sum(1 for row in results if row.get("ok")),
        "errors": sum(1 for row in results if not row.get("ok")),
        "status_codes": {
            str(code): sum(1 for row in results if int(row.get("status_code", 0) or 0) == code)
            for code in sorted({int(row.get("status_code", 0) or 0) for row in results})
        },
        "connect_p95_ms": round(percentile(connect, 95), 2),
        "time_to_first_byte_p50_ms": round(statistics.median(ttfb), 2) if ttfb else 0.0,
        "time_to_first_byte_p95_ms": round(percentile(ttfb, 95), 2),
        "time_to_first_byte_p99_ms": round(percentile(ttfb, 99), 2),
        "total_p95_ms": round(percentile(total, 95), 2),
        "results": results,
    }


async def run_probe(url: str, *, run_id: str, users: list[int], timeout_sec: float) -> dict[str, object]:
    levels = []
    for user_count in users:
        levels.append(
            await run_level(
                url,
                run_id=f"{run_id}_U{user_count:02d}",
                users=user_count,
                timeout_sec=timeout_sec,
            )
        )
    return {
        "run_id": run_id,
        "url": url,
        "created_at": dt.datetime.now(dt.timezone.utc).isoformat(),
        "levels": levels,
    }


def write_reports(payload: dict[str, object], *, output_dir: str | pathlib.Path) -> tuple[pathlib.Path, pathlib.Path]:
    output = pathlib.Path(output_dir)
    output.mkdir(parents=True, exist_ok=True)
    run_id = str(payload["run_id"])
    json_path = output / f"{run_id}_http_first_response.json"
    md_path = output / f"{run_id}_http_first_response.md"
    json_path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    lines = [
        f"# OVERWATCH HTTP First Response Probe {run_id}",
        "",
        f"- URL: `{payload['url']}`",
        "",
        "| Users | Requests | OK | Errors | TTFB p50 ms | TTFB p95 ms | TTFB p99 ms | Total p95 ms | Connect p95 ms |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for row in payload["levels"]:
        lines.append(
            f"| {row['users']} | {row['requests']} | {row['ok']} | {row['errors']} | "
            f"{row['time_to_first_byte_p50_ms']} | {row['time_to_first_byte_p95_ms']} | "
            f"{row['time_to_first_byte_p99_ms']} | {row['total_p95_ms']} | {row['connect_p95_ms']} |"
        )
    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path, md_path


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe HTTP first response without a browser.")
    parser.add_argument("--url", required=True)
    parser.add_argument("--run-id", default=f"HTTP_FIRST_RESPONSE_{uuid.uuid4().hex[:8].upper()}")
    parser.add_argument("--output-dir", default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--users", nargs="*", type=int, default=list(DEFAULT_USERS))
    parser.add_argument("--timeout-sec", type=float, default=30.0)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    payload = asyncio.run(run_probe(args.url, run_id=args.run_id, users=args.users, timeout_sec=args.timeout_sec))
    json_path, md_path = write_reports(payload, output_dir=args.output_dir)
    slowest = max(payload["levels"], key=lambda row: float(row.get("time_to_first_byte_p95_ms", 0) or 0))
    print(json.dumps({
        "run_id": args.run_id,
        "levels": len(payload["levels"]),
        "slowest_users": slowest["users"],
        "slowest_ttfb_p95_ms": slowest["time_to_first_byte_p95_ms"],
        "json_report": str(json_path),
        "markdown_report": str(md_path),
    }, indent=2))
    return 0 if all(int(row.get("errors", 0) or 0) == 0 for row in payload["levels"]) else 2


if __name__ == "__main__":
    raise SystemExit(main())
