"""S8 · PayPal Agent Toolkit, read-only (doc 09; doc 04 §6).

    pip install paypal-agent-toolkit          # in requirements.txt since S8 passed (2026-11-12 UTC)
    python scripts/spike/08_toolkit.py [ORDER_ID]

Builds the toolkit with ONLY the orders.get action enabled, lists the tools it
exposes, and fetches the S4 order (or ORDER_ID). Pass when that order comes back.

The toolkit's Python surface has changed between releases, so this script tries
the documented entry points in turn and records which one worked. Any failure
here means "Ask Pact uses our own read tools" (doc 09 go/no-go), not a blocker.
"""

from __future__ import annotations

import json
import traceback
from typing import Any

import _common as c


def _order_id(a: list[str]) -> str | None:
    if a:
        return a[0]
    st = c.load_state()
    return st.get("s1_order_id") or next(iter((st.get("s5") or {}).values()), {}).get("order_id")


def _build_toolkit(cid: str, secret: str) -> tuple[Any, str]:
    from paypal_agent_toolkit.shared.configuration import Configuration, Context  # type: ignore

    errors = []
    # Framework-neutral core (1.1.0+): no OpenAI Agents / LangChain dependency.
    try:
        from paypal_agent_toolkit.shared.api import PayPalAPI  # type: ignore
        return PayPalAPI(client_id=cid, secret=secret, context=Context(sandbox=True)), "paypal_agent_toolkit.shared.api.PayPalAPI"
    except Exception as e:  # noqa: BLE001
        errors.append(f"shared.api: {e!r}")
    cfg = Configuration(actions={"orders": {"get": True}}, context=Context(sandbox=True))
    for mod, cls in (("paypal_agent_toolkit.openai.toolkit", "PayPalToolkit"),
                     ("paypal_agent_toolkit.langchain.toolkit", "PayPalToolkit"),
                     ("paypal_agent_toolkit.crewai.toolkit", "PayPalToolkit")):
        try:
            module = __import__(mod, fromlist=[cls])
            return getattr(module, cls)(client_id=cid, secret=secret, configuration=cfg), mod
        except Exception as e:  # noqa: BLE001 - recording what failed is the point
            errors.append(f"{mod}: {e!r}")
    raise RuntimeError("; ".join(errors))


def _tool_names(tk: Any) -> list[str]:
    tools = tk.get_tools() if hasattr(tk, "get_tools") else []
    names = []
    for t in tools:
        n = getattr(t, "name", None) or (t.get("function", {}).get("name") if isinstance(t, dict) else None)
        names.append(str(n))
    return names


def _get_order(tk: Any, order_id: str) -> Any:
    api = tk if hasattr(tk, "run") else (getattr(tk, "_paypal_api", None) or getattr(tk, "paypal_api", None))
    if api is None or not hasattr(api, "run"):
        raise RuntimeError("no _paypal_api.run on this toolkit version; call the get-order tool via your agent framework")
    last: Exception | None = None
    for method in ("get_order_details", "get_order", "orders.get", "getOrder"):
        try:
            return api.run(method, {"order_id": order_id})
        except Exception as e:  # noqa: BLE001
            last = e
    raise RuntimeError(f"get order failed: {last!r}")


def main() -> None:
    cid, secret = c.require_credentials()
    try:
        import paypal_agent_toolkit  # type: ignore  # noqa: F401
    except ImportError:
        c.note("S8", "SKIPPED: paypal-agent-toolkit not installed (pip install paypal-agent-toolkit)")
        return
    oid = _order_id(c.args())
    if not oid:
        c.usage("no order id: pass ORDER_ID or run 01/04 first")
    try:
        tk, via = _build_toolkit(cid, secret)
        names = _tool_names(tk)
        c.note("S8", f"toolkit built via {via}; tools exposed (read-only config): {names}")
        res = _get_order(tk, oid)
        text = res if isinstance(res, str) else json.dumps(res)[:500]
        ok = oid in text
        c.note("S8", f"{'PASS' if ok else 'CHECK'} get order {oid} via toolkit: {text[:300]}")
    except Exception as e:  # noqa: BLE001
        c.note("S8", f"FAIL toolkit: {e!r}")
        traceback.print_exc()


if __name__ == "__main__":
    main()
