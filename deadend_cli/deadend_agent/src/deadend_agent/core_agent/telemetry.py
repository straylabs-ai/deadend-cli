# Copyright (C) 2025 Yassine Bargach
# Licensed under the GNU Affero General Public License v3
# See LICENSE file for full license information.

"""OpenTelemetry telemetry setup with multi-backend support.

Supports simultaneous export to:
- Console (for development/debugging)
- OTLP endpoint (for Jaeger, Honeycomb, Grafana, etc.)
- File (JSON logs for local analysis)

Configuration via environment variables:
- OTEL_CONSOLE_ENABLED: Enable console export (default: true)
- OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint URL (optional)
- OTEL_FILE_EXPORT_PATH: Path for file export (optional)
- OTEL_SERVICE_NAME: Service name for traces (default: deadend-agent)
"""

from __future__ import annotations

import os
import json
from pathlib import Path
from typing import Sequence

try:
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider, ReadableSpan
    from opentelemetry.sdk.trace.export import (
        BatchSpanProcessor,
        ConsoleSpanExporter,
        SpanExporter,
        SpanExportResult,
    )
    from opentelemetry.sdk.resources import Resource, SERVICE_NAME
    from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter

    OTEL_AVAILABLE = True
except ImportError:
    OTEL_AVAILABLE = False
    # Fallback no-op implementation
    class NoOpSpan:
        def set_attribute(self, key, value): pass
        def set_status(self, status): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass

    class NoOpTracer:
        def start_as_current_span(self, name, **kwargs):
            return NoOpSpan()


class FileSpanExporter(SpanExporter):
    """Exports spans to JSON files for local analysis."""

    def __init__(self, export_path: str):
        """Initialize file exporter.

        Args:
            export_path: Directory path where span files will be written
        """
        self.export_path = Path(export_path).expanduser()
        self.export_path.mkdir(parents=True, exist_ok=True)

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to JSON file.

        Args:
            spans: Sequence of spans to export

        Returns:
            SpanExportResult indicating success or failure
        """
        try:
            # Group spans by trace_id for better organization
            for span in spans:
                trace_id = format(span.context.trace_id, '032x')
                file_path = self.export_path / f"trace_{trace_id}.jsonl"

                span_data = {
                    "name": span.name,
                    "trace_id": trace_id,
                    "span_id": format(span.context.span_id, '016x'),
                    "parent_id": format(span.parent.span_id, '016x') if span.parent else None,
                    "start_time": span.start_time,
                    "end_time": span.end_time,
                    "duration_ns": span.end_time - span.start_time if span.end_time else None,
                    "attributes": dict(span.attributes) if span.attributes else {},
                    "status": {
                        "status_code": span.status.status_code.name,
                        "description": span.status.description,
                    },
                }

                # Append to file (JSONL format)
                with open(file_path, "a") as f:
                    json.dump(span_data, f)
                    f.write("\n")

            return SpanExportResult.SUCCESS
        except Exception as e:
            print(f"FileSpanExporter error: {e}")
            return SpanExportResult.FAILURE

    def shutdown(self):
        """Shutdown exporter."""
        pass


class MultiSpanExporter(SpanExporter):
    """Sends spans to multiple exporters simultaneously."""

    def __init__(self, exporters: list[SpanExporter]):
        """Initialize multi-exporter.

        Args:
            exporters: List of span exporters to send to
        """
        self.exporters = exporters

    def export(self, spans: Sequence[ReadableSpan]) -> SpanExportResult:
        """Export spans to all configured exporters.

        Args:
            spans: Sequence of spans to export

        Returns:
            SpanExportResult.SUCCESS if at least one exporter succeeds
        """
        results = []
        for exporter in self.exporters:
            try:
                result = exporter.export(spans)
                results.append(result)
            except Exception as e:
                print(f"Exporter {exporter.__class__.__name__} error: {e}")
                results.append(SpanExportResult.FAILURE)

        # Return success if at least one succeeded
        return (
            SpanExportResult.SUCCESS
            if SpanExportResult.SUCCESS in results
            else SpanExportResult.FAILURE
        )

    def shutdown(self):
        """Shutdown all exporters."""
        for exporter in self.exporters:
            try:
                exporter.shutdown()
            except Exception as e:
                print(f"Exporter shutdown error: {e}")


def setup_telemetry() -> trace.Tracer | NoOpTracer:
    """Configure multi-backend OpenTelemetry.

    Reads configuration from environment variables:
    - OTEL_CONSOLE_ENABLED: Enable console export (default: "true")
    - OTEL_EXPORTER_OTLP_ENDPOINT: OTLP endpoint (e.g., http://localhost:4317)
    - OTEL_FILE_EXPORT_PATH: File export path (e.g., ~/.cache/deadend/traces/)
    - OTEL_SERVICE_NAME: Service name (default: "deadend-agent")

    Returns:
        Configured tracer instance, or NoOpTracer if OpenTelemetry unavailable
    """
    if not OTEL_AVAILABLE:
        print("OpenTelemetry not available, using no-op tracer")
        return NoOpTracer()

    exporters = []

    # Console exporter (for development)
    if os.getenv("OTEL_CONSOLE_ENABLED", "true").lower() == "true":
        exporters.append(ConsoleSpanExporter())
        print("OpenTelemetry: Console exporter enabled")

    # OTLP exporter (for production backends)
    if endpoint := os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT"):
        try:
            exporters.append(OTLPSpanExporter(endpoint=endpoint))
            print(f"OpenTelemetry: OTLP exporter enabled (endpoint: {endpoint})")
        except Exception as e:
            print(f"OpenTelemetry: OTLP exporter error: {e}")

    # File exporter (for local analysis)
    if path := os.getenv("OTEL_FILE_EXPORT_PATH"):
        try:
            exporters.append(FileSpanExporter(path))
            print(f"OpenTelemetry: File exporter enabled (path: {path})")
        except Exception as e:
            print(f"OpenTelemetry: File exporter error: {e}")

    if not exporters:
        print("OpenTelemetry: No exporters configured, using no-op tracer")
        return NoOpTracer()

    # Create tracer provider with service name
    service_name = os.getenv("OTEL_SERVICE_NAME", "deadend-agent")
    resource = Resource(attributes={SERVICE_NAME: service_name})
    provider = TracerProvider(resource=resource)

    # Add batch processor with multi-exporter
    if len(exporters) == 1:
        provider.add_span_processor(BatchSpanProcessor(exporters[0]))
    else:
        provider.add_span_processor(BatchSpanProcessor(MultiSpanExporter(exporters)))

    # Set as global provider
    trace.set_tracer_provider(provider)

    # Return tracer
    tracer = trace.get_tracer(__name__)
    print(f"OpenTelemetry: Tracer initialized for service '{service_name}' with {len(exporters)} exporter(s)")
    return tracer


# Global tracer instance
tracer = setup_telemetry()
