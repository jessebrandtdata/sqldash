"""The smoke test's stand-in for the two paid services (Claude and Jev).

Serves the real page and the real syntax check; the summary, the agreement check and the
capabilities are fakes that spend nothing. Never imported by the app. Usage: fake_server.py [port]
"""
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from sqldash import caps, checker, errors, server  # noqa: E402


def fake_summarize(sql, dialect):
    # Sleep, then answer; "slow" waits longer and "refuse" raises a refusal.
    if "refuse" in sql:
        raise errors.ServiceError("refusal")
    time.sleep(1.5 if "slow" in sql else 0.3)
    return {"text": "It reads t.", "model": "fake-model", "input_tokens": 11, "output_tokens": 7}


def fake_judge(sql, english, dialect):
    # Always answers "differs" after a short wait.
    time.sleep(0.3)
    return {
        "choice": "differs",
        "confidence": 0.87,
        "probabilities": {"agrees": 0.1, "differs": 0.87, "cannot_tell": 0.03},
        "model": "fake-jev",
    }


def fake_capabilities():
    # The real answer for an empty environment with both buttons switched on.
    c = caps.capabilities({})
    c["summary"] = {**c["summary"], "available": True, "missing": None}
    c["judge"] = {**c["judge"], "available": True, "missing": None}
    return c


def main(argv):
    port = int(argv[0]) if argv else 0
    services = server.Services(
        check=checker.check, summarize=fake_summarize, judge=fake_judge, capabilities=fake_capabilities
    )
    srv = server.make_server("127.0.0.1", port, ROOT / "dist", services)
    print(f"sqldash on http://127.0.0.1:{srv.server_address[1]}", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        srv.server_close()


if __name__ == "__main__":
    main(sys.argv[1:])
