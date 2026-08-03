from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from prep_watchdeck.application.service_plan import SubscriptionPlan
from prep_watchdeck.application.ws_shards import WsShardIngestResult
from prep_watchdeck.domain.service_models import BootstrapResult, ServiceDiagnostics


class ServiceStore(Protocol):
    def initialize(self) -> None:
        """Create service tables if needed."""

    def diagnostics(self) -> ServiceDiagnostics:
        """Return local service store diagnostics."""


@dataclass(frozen=True)
class ServiceRunResult:
    bootstrap: BootstrapResult
    subscription: SubscriptionPlan
    stream: WsShardIngestResult


def run_service_once(store: ServiceStore) -> ServiceDiagnostics:
    store.initialize()
    return store.diagnostics()


def run_service_doctor(store: ServiceStore) -> ServiceDiagnostics:
    store.initialize()
    return store.diagnostics()
