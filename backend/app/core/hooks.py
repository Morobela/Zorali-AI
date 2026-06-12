"""
Multi-layered hook architecture inspired by PyTorch's nn.Module.
Enables extensibility without modifying core code.
Hooks use weakref to prevent circular-reference memory leaks.
"""
from __future__ import annotations
import weakref
from collections import OrderedDict
from typing import Any, Callable, TypeVar
from uuid import uuid4

T = TypeVar("T")
HookFn = Callable[..., Any]


class _WeakHook:
    """Wraps a hook function with a weak reference to its owner object."""

    def __init__(self, hook_fn: HookFn, owner: Any | None = None):
        self._hook_ref: weakref.ref | None = None
        self._fn = hook_fn
        if owner is not None:
            self._hook_ref = weakref.ref(owner)

    def __call__(self, *args, **kwargs):
        if self._hook_ref is not None and self._hook_ref() is None:
            return None  # owner was garbage-collected
        return self._fn(*args, **kwargs)

    def is_alive(self) -> bool:
        return self._hook_ref is None or self._hook_ref() is not None


class HookRegistry:
    """
    Three-tier hook system: pre-hooks, post-hooks, and always-called hooks.
    Global hooks apply to all components; instance hooks apply to one.
    """

    def __init__(self):
        self._pre_hooks: OrderedDict[str, _WeakHook] = OrderedDict()
        self._post_hooks: OrderedDict[str, _WeakHook] = OrderedDict()
        self._always_hooks: OrderedDict[str, _WeakHook] = OrderedDict()

    def register_pre_hook(self, fn: HookFn, owner: Any | None = None) -> str:
        handle = str(uuid4())
        self._pre_hooks[handle] = _WeakHook(fn, owner)
        return handle

    def register_post_hook(self, fn: HookFn, owner: Any | None = None) -> str:
        handle = str(uuid4())
        self._post_hooks[handle] = _WeakHook(fn, owner)
        return handle

    def register_always_hook(self, fn: HookFn, owner: Any | None = None) -> str:
        """Always-called hooks run even if the main call raises an exception."""
        handle = str(uuid4())
        self._always_hooks[handle] = _WeakHook(fn, owner)
        return handle

    def remove(self, handle: str) -> None:
        self._pre_hooks.pop(handle, None)
        self._post_hooks.pop(handle, None)
        self._always_hooks.pop(handle, None)

    def _prune_dead(self) -> None:
        for store in (self._pre_hooks, self._post_hooks, self._always_hooks):
            dead = [k for k, h in store.items() if not h.is_alive()]
            for k in dead:
                del store[k]

    async def call_with_hooks(self, fn: Callable, *args, **kwargs) -> Any:
        """
        Execute fn wrapped by pre/post hooks.
        Pattern: pre-hooks → fn → post-hooks, always-hooks always run.
        Mirrors PyTorch's _call_impl nested function approach.
        """
        self._prune_dead()
        result = None
        exc_raised = None

        for hook in list(self._pre_hooks.values()):
            hook(*args, **kwargs)

        try:
            import asyncio
            if asyncio.iscoroutinefunction(fn):
                result = await fn(*args, **kwargs)
            else:
                result = fn(*args, **kwargs)
        except Exception as exc:
            exc_raised = exc

        for hook in list(self._post_hooks.values()):
            hook(result, *args, **kwargs)

        for hook in list(self._always_hooks.values()):
            try:
                hook(result, exc_raised, *args, **kwargs)
            except Exception:
                pass

        if exc_raised is not None:
            raise exc_raised
        return result


# Global hook registry — used by the inference pipeline and agent orchestrator
global_hooks = HookRegistry()
