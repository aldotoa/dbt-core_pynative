# N.B.
# This will add to the package’s __path__ all subdirectories of directories on sys.path named after the package which effectively combines both modules into a single namespace (dbt.adapters)
# The matching statement is in plugins/postgres/dbt/__init__.py

from enum import Enum
import importlib
from pkgutil import extend_path
import pkgutil
import sys

# Ensure metricflow_semantic_interfaces alias if using dbt_semantic_interfaces
if "metricflow_semantic_interfaces" not in sys.modules:
    try:
        import metricflow_semantic_interfaces  # noqa: F401
    except ImportError:
        try:
            import dbt_semantic_interfaces

            sys.modules["metricflow_semantic_interfaces"] = dbt_semantic_interfaces
            for _, modname, _ in pkgutil.walk_packages(
                dbt_semantic_interfaces.__path__, "dbt_semantic_interfaces."
            ):
                mf_name = modname.replace("dbt_semantic_interfaces", "metricflow_semantic_interfaces", 1)
                try:
                    mod = importlib.import_module(modname)
                    sys.modules[mf_name] = mod
                except Exception:
                    pass
        except ImportError:
            pass



# Ensure EventGroupType on dbt_common.events.base_types
try:
    import dbt_common.events.base_types as _base_types
    if not hasattr(_base_types, "EventGroupType"):
        class EventGroupType(str, Enum):
            PARSE = "parse"
            EXEC = "exec"
        _base_types.EventGroupType = EventGroupType
except Exception:
    pass

try:
    import dbt_common.events.functions as _ev_funcs
    if not hasattr(_ev_funcs, "fire_or_defer_event"):
        def fire_or_defer_event(e, *args, **kwargs):
            return _ev_funcs.fire_event(e)
        _ev_funcs.fire_or_defer_event = fire_or_defer_event
    if not hasattr(_ev_funcs, "fire_deferred_events"):
        def fire_deferred_events(*args, **kwargs):
            pass
        _ev_funcs.fire_deferred_events = fire_deferred_events
except Exception:
    pass

try:
    import dbt_common.helper_types as _ht
    if not hasattr(_ht, "WarnErrorOptionsV2"):
        if hasattr(_ht, "WarnErrorOptions"):
            _ht.WarnErrorOptionsV2 = _ht.WarnErrorOptions
        else:
            class WarnErrorOptionsV2:
                pass
            _ht.WarnErrorOptionsV2 = WarnErrorOptionsV2
except Exception:
    pass

try:
    import dbt_common.invocation as _inv
    if not hasattr(_inv, "get_invocation_started_at"):
        import datetime
        _inv_started_at = datetime.datetime.now(datetime.timezone.utc)
        _inv.get_invocation_started_at = lambda: _inv_started_at
except Exception:
    pass

try:
    import dbt_common.clients._jinja_blocks as _jb
    if not hasattr(_jb, "ExtractWarning"):
        class ExtractWarning:
            pass
        _jb.ExtractWarning = ExtractWarning
except Exception:
    pass

# Fallback for opentelemetry if not installed
if "opentelemetry" not in sys.modules:
    try:
        import opentelemetry  # noqa: F401
    except ImportError:
        import types

        otel = types.ModuleType("opentelemetry")
        trace_mod = types.ModuleType("opentelemetry.trace")
        context_mod = types.ModuleType("opentelemetry.context")
        context_context_mod = types.ModuleType("opentelemetry.context.context")

        class _NoOpSpan:
            def __enter__(self):
                return self

            def __exit__(self, *args):
                pass

            def set_attribute(self, *args, **kwargs):
                pass

            def set_status(self, *args, **kwargs):
                pass

            def record_exception(self, *args, **kwargs):
                pass

        class _NoOpTracer:
            def start_as_current_span(self, *args, **kwargs):
                return _NoOpSpan()

            def start_span(self, *args, **kwargs):
                return _NoOpSpan()

        class StatusCode(str, Enum):
            OK = "OK"
            ERROR = "ERROR"
            UNSET = "UNSET"

        class Context:
            pass

        class Link:
            pass

        class Span:
            pass

        class SpanContext:
            pass

        trace_mod.get_tracer = lambda *args, **kwargs: _NoOpTracer()
        trace_mod.StatusCode = StatusCode
        trace_mod.Link = Link
        trace_mod.Span = Span
        trace_mod.SpanContext = SpanContext
        context_mod.attach = lambda *args, **kwargs: None
        context_mod.detach = lambda *args, **kwargs: None
        context_mod.get_current = lambda *args, **kwargs: {}
        context_mod.Context = Context
        context_context_mod.Context = Context

        otel.trace = trace_mod
        otel.context = context_mod

        sys.modules["opentelemetry"] = otel
        sys.modules["opentelemetry.trace"] = trace_mod
        sys.modules["opentelemetry.context"] = context_mod
        sys.modules["opentelemetry.context.context"] = context_context_mod

__path__ = extend_path(__path__, __name__)
